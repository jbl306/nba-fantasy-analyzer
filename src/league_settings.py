"""Yahoo Fantasy league settings reader and budget / limit tracker.

Reads league rules from the Yahoo Fantasy API and tracks:
  - FAAB budget remaining (regular season $300, playoffs $100)
  - Weekly transaction count vs limit (3/week, resets Mondays)
  - Playoff schedule awareness
  - Other league-specific settings (roster positions, waiver type, etc.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import config
from src.yahoo_fantasy import create_yahoo_query


# ---------------------------------------------------------------------------
# Yahoo API: league settings
# ---------------------------------------------------------------------------

def fetch_league_settings(query) -> dict[str, Any]:
    """Fetch and parse Yahoo Fantasy league settings.

    Reads both league settings and league metadata to get the fullest
    picture of scoring type, waiver rules, roster positions, weeks, etc.

    Returns:
        Dict of setting_name → value.
    """
    print("  Fetching league settings from Yahoo...")
    data: dict[str, Any] = {}

    # --- League settings object ---
    try:
        settings = query.get_league_settings()
        for attr in (
            "name", "scoring_type", "waiver_type", "waiver_rule",
            "max_adds", "max_teams", "num_teams", "is_finished",
            "start_week", "end_week", "current_week",
            "playoff_start_week", "trade_end_date",
            "roster_positions", "stat_categories",
            "uses_faab", "draft_type",
        ):
            val = getattr(settings, attr, None)
            if val is not None:
                data[attr] = val.decode("utf-8") if isinstance(val, bytes) else val
    except Exception as e:
        print(f"  Warning: could not fetch league settings: {e}")

    # --- League metadata (fills gaps) ---
    try:
        metadata = query.get_league_metadata()
        for attr in (
            "name", "league_key", "season", "current_week",
            "start_week", "end_week", "num_teams",
            "scoring_type", "league_type",
        ):
            val = getattr(metadata, attr, None)
            if val is not None and attr not in data:
                data[attr] = val.decode("utf-8") if isinstance(val, bytes) else val
    except Exception as e:
        print(f"  Warning: could not fetch league metadata: {e}")

    return data


# ---------------------------------------------------------------------------
# Auto-detect league settings from Yahoo API
# ---------------------------------------------------------------------------

def apply_yahoo_settings(settings: dict[str, Any]) -> list[str]:
    """Override config.py defaults with live Yahoo league settings.

    Reads the settings dict returned by :func:`fetch_league_settings` and
    patches ``config`` module attributes at runtime so every downstream
    component uses the *actual* league rules without manual config edits.

    Patches:
      - ``WEEKLY_TRANSACTION_LIMIT`` from ``max_adds``
      - ``FAAB_ENABLED`` from ``uses_faab``
      - ``FAAB_BUDGET_REGULAR_SEASON`` / ``FAAB_BUDGET_PLAYOFFS`` (if FAAB)
      - Stat-category validation (warns if league is not standard 9-cat)

    Args:
        settings: Dict from :func:`fetch_league_settings`.

    Returns:
        List of human-readable messages describing what was auto-detected.
    """
    messages: list[str] = []

    # --- Weekly transaction limit ---
    max_adds = settings.get("max_adds")
    if max_adds is not None:
        try:
            limit = int(max_adds)
            if limit > 0 and limit != config.WEEKLY_TRANSACTION_LIMIT:
                old = config.WEEKLY_TRANSACTION_LIMIT
                config.WEEKLY_TRANSACTION_LIMIT = limit
                messages.append(
                    f"Transaction limit: {old} → {limit}/week (from Yahoo)"
                )
            elif limit > 0:
                messages.append(f"Transaction limit: {limit}/week ✓")
        except (ValueError, TypeError):
            pass

    # --- FAAB detection ---
    uses_faab = settings.get("uses_faab")
    waiver_type = str(settings.get("waiver_type", "")).lower()

    if uses_faab is not None:
        faab_on = str(uses_faab) in ("1", "True", "true", "yes")
    elif "faab" in waiver_type:
        faab_on = True
    else:
        faab_on = None  # can't determine

    if faab_on is not None and faab_on != config.FAAB_ENABLED:
        config.FAAB_ENABLED = faab_on
        messages.append(
            f"FAAB: {'enabled' if faab_on else 'disabled'} (from Yahoo)"
        )
    elif faab_on is not None:
        messages.append(f"FAAB: {'enabled' if faab_on else 'disabled'} ✓")

    # --- Stat categories validation ---
    stat_cats = settings.get("stat_categories")
    if stat_cats and hasattr(stat_cats, "stats"):
        active_ids: set[int] = set()
        for stat_obj in stat_cats.stats:
            stat = stat_obj.stat if hasattr(stat_obj, "stat") else stat_obj
            stat_id = getattr(stat, "stat_id", None)
            enabled = getattr(stat, "enabled", None)
            is_display = getattr(stat, "is_only_display_stat", None)
            if stat_id is not None and str(enabled) == "1" and str(is_display) != "1":
                try:
                    active_ids.add(int(stat_id))
                except (ValueError, TypeError):
                    pass

        expected_ids = set(config.YAHOO_STAT_ID_MAP.keys())
        missing = expected_ids - active_ids
        extra = active_ids - expected_ids
        # Filter extra to only known basketball stat IDs (ignore display stats)
        known_extra = {sid for sid in extra if sid <= 30}

        if missing:
            missing_names = [
                config.STAT_CATEGORIES.get(
                    config.YAHOO_STAT_ID_MAP[sid], {}
                ).get("name", f"ID:{sid}")
                for sid in missing
            ]
            messages.append(
                f"⚠  League missing expected categories: {', '.join(missing_names)}"
            )
        if known_extra:
            messages.append(
                f"ℹ  League has extra scored categories (stat IDs: {known_extra})"
            )
        if not missing and not known_extra:
            messages.append("Stat categories: standard 9-cat ✓")

    # --- Roster positions ---
    positions = settings.get("roster_positions")
    if positions and hasattr(positions, "__iter__"):
        total_active = 0
        bench = 0
        il_slots = 0
        for rp in positions:
            pos_obj = rp.roster_position if hasattr(rp, "roster_position") else rp
            pos = str(getattr(pos_obj, "position", getattr(pos_obj, "abbreviation", ""))).upper()
            cnt = int(getattr(pos_obj, "count", 1) or 1)
            if pos in ("BN", "BENCH"):
                bench += cnt
            elif pos in ("IL", "IL+", "IR", "IR+", "DL", "DL+"):
                il_slots += cnt
            else:
                total_active += cnt
        if total_active:
            messages.append(
                f"Roster: {total_active} active + {bench} bench + {il_slots} IL"
            )

    # --- Num teams ---
    num_teams = settings.get("num_teams")
    if num_teams is not None:
        messages.append(f"Teams: {num_teams}")

    return messages


# ---------------------------------------------------------------------------
# Yahoo API: FAAB balance
# ---------------------------------------------------------------------------

def get_faab_balance(query) -> int | None:
    """Get your team's remaining FAAB balance from Yahoo.

    Tries several yfpy attributes since the object shape varies.

    Returns:
        Remaining FAAB dollars or None if not available.
    """
    try:
        team_data = query.get_team_info(config.YAHOO_TEAM_ID)
        for attr in ("faab_balance", "waiver_budget", "clinched_playoffs"):
            val = getattr(team_data, attr, None)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
    except Exception as e:
        print(f"  Warning: could not fetch FAAB balance from Yahoo: {e}")

    return None


def get_all_faab_balances(query) -> list[dict[str, Any]]:
    """Get FAAB balances for every team in the league.

    Tries ``get_league_teams()`` first (single API call).  If that doesn't
    include ``faab_balance``, falls back to ``get_team_info()`` per team.

    Returns:
        List of dicts with keys: team_id (int), team_name (str),
        faab_balance (int).  Empty list if FAAB data is unavailable.
    """
    balances: list[dict[str, Any]] = []

    try:
        teams = query.get_league_teams()
    except Exception as e:
        print(f"  Warning: could not fetch league teams for FAAB: {e}")
        return balances

    # --- Attempt 1: pull faab_balance directly from team objects ----------
    for team_obj in teams:
        team = team_obj.team if hasattr(team_obj, "team") else team_obj
        team_id = getattr(team, "team_id", None)
        team_name = str(getattr(team, "name", "Unknown"))
        faab = getattr(team, "faab_balance", None)
        if faab is not None and team_id is not None:
            try:
                balances.append({
                    "team_id": int(team_id),
                    "team_name": team_name,
                    "faab_balance": int(faab),
                })
            except (ValueError, TypeError):
                pass

    if balances:
        return balances

    # --- Attempt 2: individual get_team_info calls -----------------------
    print("  Fetching FAAB balances per team (bulk unavailable)...")
    for team_obj in teams:
        team = team_obj.team if hasattr(team_obj, "team") else team_obj
        team_id = getattr(team, "team_id", None)
        if team_id is None:
            continue
        try:
            info = query.get_team_info(int(team_id))
            faab = getattr(info, "faab_balance", None)
            if faab is not None:
                balances.append({
                    "team_id": int(team_id),
                    "team_name": str(getattr(team, "name", "Unknown")),
                    "faab_balance": int(faab),
                })
        except Exception:
            pass

    return balances


# ---------------------------------------------------------------------------
# Transaction counting
# ---------------------------------------------------------------------------

def fetch_game_weeks(query) -> list[dict]:
    """Fetch all fantasy week date ranges from Yahoo.

    Uses ``get_game_weeks_by_game_id`` which returns exact start/end dates
    for every fantasy week, including extended weeks (e.g. All-Star break).

    Returns:
        List of dicts with keys: week (int), start (date), end (date).
        Empty list on failure.
    """
    try:
        game_key = query.get_league_key().split(".")[0]
        raw_weeks = query.get_game_weeks_by_game_id(int(game_key))
        weeks = []
        for gw in raw_weeks:
            w = int(gw.week)
            s = date.fromisoformat(str(gw.start))
            e = date.fromisoformat(str(gw.end))
            weeks.append({"week": w, "start": s, "end": e})
        return weeks
    except Exception as e:
        print(f"  Warning: could not fetch game weeks: {e}")
        return []


def get_current_week_start(
    game_weeks: list[dict] | None = None,
    current_week: int | None = None,
) -> date:
    """Get the start date of the current fantasy week.

    If Yahoo game-week data is available, uses the exact start date (which
    may span 2 calendar weeks during All-Star break).  Otherwise falls back
    to the most recent Monday.

    Args:
        game_weeks: List from :func:`fetch_game_weeks`.
        current_week: Current fantasy week number (from league settings).

    Returns:
        The start date of the current fantasy week.
    """
    today = date.today()

    if game_weeks and current_week is not None:
        for gw in game_weeks:
            if gw["week"] == current_week:
                return gw["start"]

    # Also try matching by date range (covers edge cases)
    if game_weeks:
        for gw in game_weeks:
            if gw["start"] <= today <= gw["end"]:
                return gw["start"]

    # Fallback: most recent Monday
    return today - timedelta(days=today.weekday())


def count_transactions_this_week(
    transactions: list[dict],
    team_id: int | None = None,
    week_start: date | None = None,
) -> int:
    """Count add/drop transactions made by your team this fantasy week.

    The weekly transaction limit resets at the start of each fantasy week.
    Fantasy weeks usually run Monday–Sunday, but extended weeks (e.g. the
    All-Star break) can span two calendar weeks.

    Args:
        transactions: Parsed transaction list from fetch_league_transactions().
        team_id: Your team ID. Defaults to config.YAHOO_TEAM_ID.
        week_start: Start date of the current fantasy week.  When ``None``,
            defaults to the most recent Monday (standard week assumption).

    Returns:
        Number of transactions placed this fantasy week.
    """
    if team_id is None:
        team_id = config.YAHOO_TEAM_ID
    team_suffix = f".t.{team_id}"

    if week_start is None:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

    start_ts = datetime.combine(week_start, datetime.min.time()).timestamp()

    count = 0
    for txn in transactions:
        # Only count our team — match the ".t.{id}" suffix to avoid
        # false positives from team_id appearing in the league number.
        txn_key = str(txn.get("team_key", ""))
        if not txn_key.endswith(team_suffix):
            continue

        ts = txn.get("timestamp", "")
        try:
            txn_ts = float(ts)
            if txn_ts >= start_ts:
                count += 1
        except (ValueError, TypeError):
            # Conservative: if timestamp is unparseable, skip
            pass

    return count


def check_transaction_limit(
    transactions_this_week: int,
    limit: int | None = None,
) -> dict[str, Any]:
    """Check if the weekly transaction limit allows more moves.

    Returns:
        Dict with: used, limit, remaining, at_limit, message.
    """
    if limit is None:
        limit = config.WEEKLY_TRANSACTION_LIMIT

    remaining = max(0, limit - transactions_this_week)
    at_limit = remaining <= 0

    if at_limit:
        msg = (
            f"Weekly transaction limit reached "
            f"({transactions_this_week}/{limit}). Resets Monday."
        )
    elif remaining == 1:
        msg = (
            f"1 transaction remaining this week "
            f"({transactions_this_week}/{limit})"
        )
    else:
        msg = (
            f"{remaining} transactions remaining this week "
            f"({transactions_this_week}/{limit})"
        )

    return {
        "used": transactions_this_week,
        "limit": limit,
        "remaining": remaining,
        "at_limit": at_limit,
        "message": msg,
    }


# ---------------------------------------------------------------------------
# Budget status computation
# ---------------------------------------------------------------------------

def compute_budget_status(
    remaining_budget: int,
    current_week: int | None = None,
    end_week: int | None = None,
    playoff_start_week: int | None = None,
    start_week: int | None = None,
    league_balances: list[int] | None = None,
) -> dict[str, Any]:
    """Compute budget health and a bidding adjustment factor.

    Uses two signals to determine status:

    1. **Pace-based** — compares your remaining budget to what you'd
       *expect* to have left if you spent evenly across the season.
       ``budget_factor = remaining / expected_remaining``.
    2. **League-relative** — ranks your remaining budget against every
       other manager.  If you have more than most opponents, you have
       purchasing-power advantage regardless of pace.

    When league data is available the final status is driven by the
    *better* of the two signals (you should never feel "MODERATE" when
    you're sitting on more FAAB than 75 % of the league).

    The budget_factor tells the FAAB analyzer how to scale suggestions:
      >1.0 → budget flush (can bid above historical norms)
      ~1.0 → on pace
      <1.0 → budget tight (should bid conservatively)

    Returns:
        Dict with: remaining_budget, weeks_remaining, weekly_budget,
        budget_factor, status, is_playoffs, max_single_bid,
        league_rank, league_size, league_percentile.
    """
    # Determine if we're in playoffs
    if current_week is not None and playoff_start_week is not None:
        is_playoffs = current_week >= playoff_start_week
    else:
        is_playoffs = False

    # Determine weeks remaining & total season length
    total_weeks: int | None = None
    if current_week is not None and end_week is not None:
        weeks_remaining = max(1, end_week - current_week + 1)
        if not is_playoffs and playoff_start_week is not None:
            weeks_remaining = max(1, playoff_start_week - current_week)
        # Total season length for pace calculation
        sw = start_week if start_week is not None else 1
        if not is_playoffs and playoff_start_week is not None:
            total_weeks = max(1, playoff_start_week - sw)
        else:
            total_weeks = max(1, end_week - sw + 1)
    else:
        # Estimate from calendar
        today = date.today()
        year = today.year if today.month <= 6 else today.year + 1
        season_start = date(year - 1 if today.month <= 6 else year, 10, 20)
        season_end = date(year, 4, 13)
        days_left = max(1, (season_end - today).days)
        total_days = max(1, (season_end - season_start).days)
        weeks_remaining = max(1, days_left // 7)
        total_weeks = max(1, total_days // 7)

    total_budget = (
        config.FAAB_BUDGET_PLAYOFFS if is_playoffs
        else config.FAAB_BUDGET_REGULAR_SEASON
    )
    weekly_budget = remaining_budget / max(weeks_remaining, 1)

    # ------------------------------------------------------------------
    # Pace-based budget factor: remaining vs expected-remaining
    # ------------------------------------------------------------------
    if total_weeks is not None and total_weeks > weeks_remaining:
        expected_remaining = total_budget * (weeks_remaining / total_weeks)
        pace_factor = remaining_budget / max(expected_remaining, 1)
    else:
        # Season just started or can't compute elapsed → assume on pace
        pace_factor = remaining_budget / max(total_budget, 1)

    pace_factor = max(0.5, min(2.0, pace_factor))

    # ------------------------------------------------------------------
    # League-relative ranking (when available)
    # ------------------------------------------------------------------
    league_rank: int | None = None
    league_size: int | None = None
    league_pctile: float | None = None
    relative_factor: float | None = None

    if league_balances and len(league_balances) >= 2:
        league_size = len(league_balances)
        # Rank 1 = highest balance
        n_above = sum(1 for b in league_balances if b > remaining_budget)
        league_rank = n_above + 1
        # Percentile: 1.0 = best (most remaining), 0.0 = worst
        league_pctile = 1.0 - (n_above / max(league_size - 1, 1))
        # Map percentile to the same 0–2 scale as pace_factor
        relative_factor = 0.5 + league_pctile * 1.5  # 0→0.5, 0.5→1.25, 1.0→2.0

    # ------------------------------------------------------------------
    # Final budget_factor: best of pace and relative signals
    # ------------------------------------------------------------------
    if relative_factor is not None:
        budget_factor = max(pace_factor, relative_factor)
    else:
        budget_factor = pace_factor

    budget_factor = max(0.5, min(2.0, round(budget_factor, 2)))

    # Status label — action-oriented so managers know how to adjust bids
    if budget_factor >= 1.3:
        status = "FLEXIBLE"       # Spending room — can bid aggressively
    elif budget_factor >= 0.9:
        status = "COMFORTABLE"    # On pace — bid at market rate
    elif budget_factor >= 0.6:
        status = "MODERATE"       # Slightly behind — bid selectively
    else:
        status = "CONSERVE"       # Low funds — only bid on must-haves

    return {
        "remaining_budget": remaining_budget,
        "total_budget": total_budget,
        "weeks_remaining": weeks_remaining,
        "weekly_budget": round(weekly_budget, 1),
        "budget_factor": budget_factor,
        "status": status,
        "is_playoffs": is_playoffs,
        "max_single_bid": int(remaining_budget * config.FAAB_MAX_BID_PERCENT),
        "league_rank": league_rank,
        "league_size": league_size,
        "league_percentile": league_pctile,
        "pace_factor": round(pace_factor, 2),
    }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def format_settings_report(
    settings: dict,
    budget_info: dict | None = None,
    txn_limit: dict | None = None,
) -> str:
    """Format league settings, budget, and transaction limit as a report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("  LEAGUE SETTINGS & CONSTRAINTS")
    lines.append("=" * 70)

    if settings:
        name = settings.get("name", "Unknown League")
        scoring = settings.get("scoring_type", "?")
        waiver = settings.get("waiver_type", "?")
        current_wk = settings.get("current_week", "?")
        end_wk = settings.get("end_week", "?")
        playoff_wk = settings.get("playoff_start_week", "?")
        max_adds = settings.get("max_adds", "?")
        uses_faab = settings.get("uses_faab", "?")

        lines.append(f"\n  League:           {name}")
        lines.append(f"  Scoring:          {scoring}")
        lines.append(f"  Waiver type:      {waiver}")
        lines.append(f"  Uses FAAB:        {uses_faab}")
        lines.append(f"  Max season adds:  {max_adds}")
        lines.append(f"  Current week:     {current_wk}")
        lines.append(f"  End week:         {end_wk}")
        lines.append(f"  Playoff starts:   Week {playoff_wk}")



    if budget_info:
        from src.colors import colorize_budget_status
        lines.append(f"\n  {'─' * 40}")
        lines.append(f"  FAAB BUDGET")
        lines.append(f"  {'─' * 40}")
        lines.append(f"  Remaining:        ${budget_info['remaining_budget']}")
        lines.append(f"  Total budget:     ${budget_info['total_budget']}")
        lines.append(f"  Weeks left:       {budget_info['weeks_remaining']}")
        lines.append(f"  Weekly budget:    ${budget_info['weekly_budget']}")
        lines.append(f"  Max single bid:   ${budget_info['max_single_bid']}")
        lines.append(f"  Budget status:    {colorize_budget_status(budget_info['status'])}")
        rank = budget_info.get("league_rank")
        size = budget_info.get("league_size")
        if rank and size:
            lines.append(f"  League FAAB rank: {rank} of {size}")
        if budget_info["is_playoffs"]:
            lines.append(
                f"  ** PLAYOFF MODE ** Budget reset to "
                f"${config.FAAB_BUDGET_PLAYOFFS}"
            )

    if txn_limit:
        lines.append(f"\n  {'─' * 40}")
        lines.append(f"  WEEKLY TRANSACTIONS")
        lines.append(f"  {'─' * 40}")
        lines.append(f"  {txn_limit['message']}")

    return "\n".join(lines)

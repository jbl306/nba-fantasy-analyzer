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
                data[attr] = val
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
                data[attr] = val
    except Exception as e:
        print(f"  Warning: could not fetch league metadata: {e}")

    return data


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
) -> dict[str, Any]:
    """Compute budget health and a bidding adjustment factor.

    The budget_factor tells the FAAB analyzer how to scale suggestions:
      >1.0 → budget flush (can bid above historical norms)
      ~1.0 → on pace
      <1.0 → budget tight (should bid conservatively)

    Returns:
        Dict with: remaining_budget, weeks_remaining, weekly_budget,
        budget_factor, status, is_playoffs, max_single_bid.
    """
    # Determine if we're in playoffs
    if current_week is not None and playoff_start_week is not None:
        is_playoffs = current_week >= playoff_start_week
    else:
        is_playoffs = False

    # Determine weeks remaining
    if current_week is not None and end_week is not None:
        weeks_remaining = max(1, end_week - current_week + 1)
        if not is_playoffs and playoff_start_week is not None:
            weeks_remaining = max(1, playoff_start_week - current_week)
    else:
        # Estimate from calendar
        today = date.today()
        year = today.year if today.month <= 6 else today.year + 1
        season_end = date(year, 4, 13)
        days_left = max(1, (season_end - today).days)
        weeks_remaining = max(1, days_left // 7)

    # Ideal uniform weekly spend
    total_budget = (
        config.FAAB_BUDGET_PLAYOFFS if is_playoffs
        else config.FAAB_BUDGET_REGULAR_SEASON
    )
    ideal_weekly = total_budget / max(weeks_remaining, 1)
    weekly_budget = remaining_budget / max(weeks_remaining, 1)

    # Budget factor: >1 = flush, <1 = tight  (clamped 0.5–2.0)
    budget_factor = weekly_budget / max(ideal_weekly, 1)
    budget_factor = max(0.5, min(2.0, budget_factor))

    # Status label
    if budget_factor >= 1.3:
        status = "FLUSH"
    elif budget_factor >= 0.9:
        status = "HEALTHY"
    elif budget_factor >= 0.6:
        status = "TIGHT"
    else:
        status = "CRITICAL"

    return {
        "remaining_budget": remaining_budget,
        "total_budget": total_budget,
        "weeks_remaining": weeks_remaining,
        "weekly_budget": round(weekly_budget, 1),
        "budget_factor": round(budget_factor, 2),
        "status": status,
        "is_playoffs": is_playoffs,
        "max_single_bid": int(remaining_budget * config.FAAB_MAX_BID_PERCENT),
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

        # Roster positions
        positions = settings.get("roster_positions", None)
        if positions:
            lines.append(f"\n  Roster positions: {positions}")

    if budget_info:
        lines.append(f"\n  {'─' * 40}")
        lines.append(f"  FAAB BUDGET")
        lines.append(f"  {'─' * 40}")
        lines.append(f"  Remaining:        ${budget_info['remaining_budget']}")
        lines.append(f"  Total budget:     ${budget_info['total_budget']}")
        lines.append(f"  Weeks left:       {budget_info['weeks_remaining']}")
        lines.append(f"  Weekly budget:    ${budget_info['weekly_budget']}")
        lines.append(f"  Max single bid:   ${budget_info['max_single_bid']}")
        lines.append(f"  Budget status:    {budget_info['status']}")
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

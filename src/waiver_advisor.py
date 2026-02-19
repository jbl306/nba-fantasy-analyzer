"""Waiver wire recommendation engine.

Combines NBA stats (from Yahoo Fantasy API) with Yahoo Fantasy roster data
(from yfpy) to identify the best available pickups for a 9-category league.

Flow:
  1. Connect to Yahoo Fantasy and fetch ALL team rosters in the league
  2. Build a set of owned player names (unavailable)
  3. Fetch player stats via Yahoo Fantasy API and compute 9-cat z-scores
  4. Filter stats to only players NOT owned in the league
  5. Analyze your roster's strengths/weaknesses
  6. Rank available players with need-weighted scoring
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from tabulate import tabulate

import config
from src.injury_news import (
    build_injury_lookup,
    fetch_injury_report,
    format_injury_note,
    get_player_injury_status,
)
from src.yahoo_stats import (
    build_player_stats_table,
    check_recent_activity,
    compute_hot_pickup_scores,
    compute_recent_game_stats,
)
from src.yahoo_fantasy import (
    create_yahoo_query,
    extract_player_details,
    extract_player_name,
    get_all_team_rosters,
    get_my_team_roster,
    normalize_name,
)


def match_nba_name_to_yahoo(nba_name: str, owned_names: set[str]) -> bool:
    """Check if an NBA player name matches any owned player in Yahoo.

    Args:
        nba_name: Player name from the stats DataFrame (PLAYER_NAME column).
        owned_names: Set of normalized names of all owned players.

    Returns:
        True if the player is owned (unavailable), False if available.
    """
    return normalize_name(nba_name) in owned_names


def match_yahoo_to_nba(yahoo_name: str, nba_df: pd.DataFrame) -> int | None:
    """Match a Yahoo Fantasy player name to the stats DataFrame.

    Args:
        yahoo_name: Player name from Yahoo Fantasy.
        nba_df: DataFrame with PLAYER_NAME column.

    Returns:
        Index in nba_df if matched, else None.
    """
    norm_yahoo = normalize_name(yahoo_name)

    # Exact match first
    for idx, row in nba_df.iterrows():
        if normalize_name(row["PLAYER_NAME"]) == norm_yahoo:
            return idx

    # Partial match (last name + first initial)
    yahoo_parts = norm_yahoo.split()
    if len(yahoo_parts) >= 2:
        yahoo_last = yahoo_parts[-1]
        yahoo_first_initial = yahoo_parts[0][0] if yahoo_parts[0] else ""

        for idx, row in nba_df.iterrows():
            nba_norm = normalize_name(row["PLAYER_NAME"])
            nba_parts = nba_norm.split()
            if len(nba_parts) >= 2:
                nba_last = nba_parts[-1]
                nba_first_initial = nba_parts[0][0] if nba_parts[0] else ""
                if nba_last == yahoo_last and nba_first_initial == yahoo_first_initial:
                    return idx

    return None


def analyze_roster(
    roster_players: list,
    nba_stats: pd.DataFrame,
) -> pd.DataFrame:
    """Analyze your current roster's 9-cat strengths and weaknesses.

    Args:
        roster_players: List of yfpy player objects from your roster.
        nba_stats: Full league stats DataFrame with z-scores.

    Returns:
        DataFrame summarizing your team's category z-scores.
    """
    roster_stats = []

    for player_obj in roster_players:
        details = extract_player_details(player_obj)
        match_idx = match_yahoo_to_nba(details["name"], nba_stats)

        if match_idx is not None:
            row = nba_stats.loc[match_idx]
            player_data = {"name": details["name"], "position": details["position"]}
            for stat_key in config.STAT_CATEGORIES:
                z_col = f"Z_{stat_key}"
                if z_col in row.index:
                    player_data[z_col] = row[z_col]
            player_data["Z_TOTAL"] = row.get("Z_TOTAL", 0)
            roster_stats.append(player_data)
        else:
            print(f"  Could not match roster player: {details['name']}")

    if not roster_stats:
        return pd.DataFrame()

    roster_df = pd.DataFrame(roster_stats)
    return roster_df


def identify_droppable_players(
    roster_df: pd.DataFrame,
    count: int | None = None,
) -> list[str]:
    """Auto-detect the lowest-value players on your roster by Z_TOTAL.

    Uses ``config.AUTO_DETECT_DROPPABLE`` as the feature toggle:
      - True: rank roster by z-score, return the bottom N names.
      - False: return ``config.DROPPABLE_PLAYERS`` as-is.

    Players listed in ``config.UNDDROPPABLE_PLAYERS`` are never included.
    Players listed in ``config.DROPPABLE_PLAYERS`` are always included
    (even in auto mode) as forced entries.

    Args:
        roster_df: DataFrame from ``analyze_roster`` with ``name`` and
            ``Z_TOTAL`` columns.
        count: How many auto-detected droppable players to return.
            Defaults to ``config.AUTO_DROPPABLE_COUNT``.

    Returns:
        List of player names eligible to be dropped, lowest-value first.
    """
    if count is None:
        count = getattr(config, "AUTO_DROPPABLE_COUNT", 3)

    # Normalise the undroppable set for comparison
    undroppable = {
        normalize_name(n)
        for n in getattr(config, "UNDDROPPABLE_PLAYERS", [])
    }

    manual_list = list(config.DROPPABLE_PLAYERS)

    # ---- Feature off: return the manual list only ----
    if not getattr(config, "AUTO_DETECT_DROPPABLE", False):
        return manual_list

    # ---- Feature on: rank by Z_TOTAL ascending (worst first) ----
    if roster_df.empty or "Z_TOTAL" not in roster_df.columns:
        # Can't compute — fall back to manual list
        return manual_list

    # Filter out undroppable players
    eligible = roster_df[
        ~roster_df["name"].apply(lambda n: normalize_name(n) in undroppable)
    ].copy()

    eligible = eligible.sort_values("Z_TOTAL", ascending=True)
    auto_names = eligible.head(count)["name"].tolist()

    # Merge: auto-detected + manual (deduplicated, preserving order)
    seen = set()
    merged: list[str] = []
    for name in auto_names + manual_list:
        norm = normalize_name(name)
        if norm not in seen and norm not in undroppable:
            seen.add(norm)
            merged.append(name)

    return merged


def identify_team_needs(roster_df: pd.DataFrame) -> dict[str, float]:
    """Identify which stat categories your team is weakest in.

    Categories listed in ``config.PUNT_CATEGORIES`` are excluded so they
    don't appear as weaknesses — you're intentionally ignoring them.

    Args:
        roster_df: DataFrame from analyze_roster with z-score columns.

    Returns:
        Dict mapping category names to average team z-scores, sorted weakest first.
    """
    punt_names = {c.upper() for c in config.PUNT_CATEGORIES}
    cat_averages = {}
    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        if cat_info["name"].upper() in punt_names:
            continue
        z_col = f"Z_{stat_key}"
        if z_col in roster_df.columns:
            cat_averages[cat_info["name"]] = roster_df[z_col].mean()

    # Sort by z-score ascending (weakest categories first)
    return dict(sorted(cat_averages.items(), key=lambda x: x[1]))


def compute_roster_strength(team_needs: dict[str, float]) -> dict[str, Any]:
    """Compute an overall roster strength summary from category z-scores.

    Used by FAAB bid logic to adjust aggressiveness based on how strong
    your roster is relative to a neutral baseline.

    Returns:
        Dict with:
          - ``avg_z``: Mean z-score across non-punt categories.
          - ``strong_cats``: Count of categories with z >= 0.3.
          - ``weak_cats``: Count of categories with z <= -0.3.
          - ``label``: Human-readable strength label.
          - ``bid_factor``: Multiplier for FAAB bids (>1 = bid less, <1 = bid more).
    """
    if not team_needs:
        return {
            "avg_z": 0.0, "strong_cats": 0, "weak_cats": 0,
            "label": "Unknown", "bid_factor": 1.0,
        }
    avg_z = sum(team_needs.values()) / len(team_needs)
    strong = sum(1 for z in team_needs.values() if z >= 0.3)
    weak = sum(1 for z in team_needs.values() if z <= -0.3)

    # Map average z-score to a bid adjustment factor.
    # Strong roster → conservative (factor > 1 reduces urgency, so we
    # actually want to *lower* bids when strong → factor < 1 pushes
    # bids down).  Weak roster → aggressive (factor > 1 pushes bids up).
    #
    # We invert: bid_factor = 1.0 - 0.15 * avg_z (clamped 0.7–1.3)
    # avg_z = +0.5 (strong) → factor = 0.925 (bid ~7.5% less)
    # avg_z = -0.5 (weak)   → factor = 1.075 (bid ~7.5% more)
    bid_factor = 1.0 - 0.15 * avg_z
    bid_factor = max(0.7, min(1.3, bid_factor))

    if avg_z >= 0.4:
        label = "Strong roster"
    elif avg_z >= 0.1:
        label = "Solid roster"
    elif avg_z >= -0.2:
        label = "Average roster"
    elif avg_z >= -0.5:
        label = "Below average"
    else:
        label = "Weak roster"

    return {
        "avg_z": round(avg_z, 2),
        "strong_cats": strong,
        "weak_cats": weak,
        "label": label,
        "bid_factor": round(bid_factor, 3),
    }


def compute_roster_impact(
    add_name: str,
    drop_name: str,
    nba_stats: pd.DataFrame,
) -> dict[str, Any] | None:
    """Compute the category-by-category z-score impact of an add/drop.

    Shows what happens to your team's z-scores when you drop one player
    and add another — positive deltas mean the swap improves that category.

    Args:
        add_name: Name of the player being added.
        drop_name: Name of the player being dropped.
        nba_stats: Full NBA stats DataFrame with z-score columns.

    Returns:
        Dict with per-category deltas, net z-total change, and formatted
        summary string.  None if either player can't be matched.
    """
    add_idx = match_yahoo_to_nba(add_name, nba_stats)
    drop_idx = match_yahoo_to_nba(drop_name, nba_stats)

    if add_idx is None or drop_idx is None:
        return None

    add_row = nba_stats.loc[add_idx]
    drop_row = nba_stats.loc[drop_idx]

    punt_names = {c.upper() for c in config.PUNT_CATEGORIES}
    deltas: dict[str, float] = {}
    net_total = 0.0

    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        if cat_info["name"].upper() in punt_names:
            continue
        z_col = f"Z_{stat_key}"
        if z_col in add_row.index and z_col in drop_row.index:
            add_z = float(add_row.get(z_col, 0))
            drop_z = float(drop_row.get(z_col, 0))
            delta = add_z - drop_z
            deltas[cat_info["name"]] = round(delta, 2)
            net_total += delta

    # Build formatted summary
    from src.colors import green, red
    parts: list[str] = []
    for cat_name, delta in deltas.items():
        sign = "+" if delta >= 0 else ""
        val_str = f"{sign}{delta:.1f}"
        if delta >= 0.3:
            parts.append(f"{cat_name} {green(val_str)}")
        elif delta <= -0.3:
            parts.append(f"{cat_name} {red(val_str)}")
        else:
            parts.append(f"{cat_name} {val_str}")

    net_sign = "+" if net_total >= 0 else ""
    net_str = f"{net_sign}{net_total:.1f}"
    if net_total >= 0.5:
        net_str = green(net_str)
    elif net_total <= -0.5:
        net_str = red(net_str)

    summary = ", ".join(parts) + f"  →  net {net_str} z-score"

    return {
        "deltas": deltas,
        "net_total": round(net_total, 2),
        "summary": summary,
        "add_name": add_name,
        "drop_name": drop_name,
    }


def format_team_analysis(roster_df: pd.DataFrame, team_needs: dict) -> str:
    """Format team analysis as a readable string with color-coded assessments."""
    from src.colors import (
        cyan, green, yellow, red, bold, colorize_assessment, colorize_z_score,
    )

    lines = []
    lines.append(cyan("=" * 70))
    lines.append(cyan("YOUR TEAM CATEGORY ANALYSIS"))
    lines.append(cyan("=" * 70))

    # Show punt info if configured
    if config.PUNT_CATEGORIES:
        lines.append(f"\n  Punt mode: {', '.join(config.PUNT_CATEGORIES)}")
        lines.append("  (excluded from Z_TOTAL, needs analysis, and recommendations)")

    # Show category averages
    lines.append(f"\n{'Category':<12} {'Team Avg Z':>12} {'Assessment':>15}")
    lines.append("-" * 42)

    for cat_name, z_avg in team_needs.items():
        if z_avg >= 0.5:
            assessment = "STRONG"
        elif z_avg >= 0:
            assessment = "Average"
        elif z_avg >= -0.5:
            assessment = "Below Avg"
        else:
            assessment = "WEAK"
        z_str = colorize_z_score(z_avg, f"{z_avg:>12.2f}")
        colored_assessment = colorize_assessment(assessment)
        lines.append(f"{cat_name:<12} {z_str} {colored_assessment:>15}")

    # Identify punt candidates and strengths
    strengths = [c for c, z in team_needs.items() if z >= 0.3]
    weaknesses = [c for c, z in team_needs.items() if z <= -0.3]

    if strengths:
        lines.append(f"\n{green('Strengths')}: {', '.join(strengths)}")
    if weaknesses:
        lines.append(f"{red('Weaknesses')}: {', '.join(weaknesses)}")
        lines.append(f"  -> Target waiver pickups strong in: {', '.join(weaknesses)}")

    return "\n".join(lines)


def score_available_players(
    available_stats: pd.DataFrame,
    team_needs: dict[str, float] | None = None,
    recent_activity: dict[int, dict] | None = None,
    injury_lookup: dict[str, dict] | None = None,
    schedule_game_counts: dict[str, int] | None = None,
    avg_games_per_week: float = 3.5,
    schedule_analysis: dict | None = None,
    hot_pickup_scores: dict[int, dict] | None = None,
    trending_data: dict[str, dict] | None = None,
    player_news: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """Score and rank available players directly from the NBA stats DataFrame.

    This function works with the pre-filtered DataFrame of unowned players
    (already removed from the league via roster checks). It applies:
      - 9-cat z-score value
      - Need-weighted boost for team weaknesses
      - Availability rate discount (season-long GP rate)
      - Recent activity penalty for players not playing lately
      - Injury report penalty from Basketball-Reference data
      - Schedule multiplier for upcoming game count (more games = higher value)
      - **Hot-pickup boost** for recent breakout performance (last N games)
      - **Player news multiplier** for role/performance signals (ESPN blurbs)
      - **Trending boost** for players with spiking ownership across Yahoo

    When *schedule_analysis* is provided (multi-week), the schedule multiplier
    uses week-decay weighting (current week counts more than future weeks).

    Args:
        available_stats: DataFrame of NBA stats for unowned players (with z-scores).
        team_needs: Optional dict of category weaknesses from identify_team_needs.
        recent_activity: Optional dict from check_recent_activity for top candidates.
        injury_lookup: Optional dict from build_injury_lookup for injury status overrides.
        schedule_game_counts: Optional {team_abbr: games} for the upcoming week.
        avg_games_per_week: League avg games/week for schedule multiplier baseline.
        schedule_analysis: Optional full schedule analysis dict from
            :func:`build_schedule_analysis`.  Enables multi-week decay weighting.
        hot_pickup_scores: Optional dict from compute_hot_pickup_scores mapping
            player_key → {recent_z_total, z_delta, is_hot}.
        trending_data: Optional dict from fetch_trending_players mapping
            normalized_name → {percent_owned, percent_owned_delta, is_trending}.
        player_news: Optional dict from analyze_player_news mapping
            normalized_name → {news_multiplier, news_labels, news_summary}.

    Returns:
        DataFrame of ranked waiver recommendations.
    """
    # Build a mapping from category name back to z-column
    cat_name_to_z_col = {}
    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        cat_name_to_z_col[cat_info["name"]] = f"Z_{stat_key}"

    # Pre-build per-team multi-week game counts for decay-weighted multiplier
    team_week_data: dict[str, list[tuple[int, float]]] = {}
    team_total_remaining: dict[str, int] = {}  # total games left in tracked weeks
    if schedule_analysis and schedule_analysis.get("weeks"):
        from src.schedule_analyzer import normalize_team_abbr as _norm
        weeks_data = schedule_analysis["weeks"]
        all_teams: set[str] = set()
        for wk in weeks_data:
            all_teams.update(wk["game_counts"].keys())
        for team in all_teams:
            team_week_data[team] = [
                (wk["game_counts"].get(team, 0), wk["avg_games"])
                for wk in weeks_data
            ]
        # Also grab pre-computed totals for suspension math
        team_total_remaining = schedule_analysis.get("total_game_counts", {})

    recommendations = []

    for _, row in available_stats.iterrows():
        player_key = str(row.get("PLAYER_KEY", ""))
        gp = int(row.get("GP", 0))
        team_gp = int(row.get("TEAM_GP", gp))
        avail_rate = row.get("AVAIL_RATE", 1.0)
        avail_flag = row.get("AVAIL_FLAG", "Unknown")
        avail_mult = row.get("AVAIL_MULTIPLIER", 1.0)

        rec = {
            "Player": row.get("PLAYER_NAME", "Unknown"),
            "Team": row.get("TEAM_ABBREVIATION", ""),
            "GP": gp,
            "MIN": round(row.get("MIN", 0), 1),
            "Avail%": f"{avail_rate:.0%}",
            "Health": avail_flag,
        }

        # Check recent activity if available
        if recent_activity and player_key and player_key in recent_activity:
            activity = recent_activity[player_key]
            rec["Last Game"] = activity.get("last_game_date", "?") or "?"
            rec["Recent"] = activity.get("recent_flag", "?")
            games_14d = activity.get("games_last_14d", 0)
            rec["G/14d"] = games_14d

            # Extra penalty for currently inactive players
            if activity.get("is_inactive"):
                avail_mult *= 0.3  # Harsh penalty — they're not playing at all
            elif activity.get("recent_flag") == "Questionable":
                avail_mult *= 0.75  # Moderate penalty — haven't played very recently
        else:
            rec["Last Game"] = "-"
            rec["Recent"] = "-"
            rec["G/14d"] = "-"

        # Check injury report (overrides game-log heuristics with real news)
        player_name = row.get("PLAYER_NAME", "Unknown")
        injury_info = None
        injury_mult = 1.0
        if injury_lookup:
            injury_info = get_player_injury_status(player_name, injury_lookup)
        if injury_info:
            rec["Injury"] = injury_info["severity_label"]
            rec["Injury_Note"] = format_injury_note(
                injury_info, max_blurb_len=config.INJURY_BLURB_MAX_LENGTH
            )
            injury_mult = injury_info["severity_multiplier"]

            # --- Dynamic suspension multiplier ---
            # Sentinel -1.0 means the injury module deferred to us
            # so we can factor in remaining fantasy-season games.
            if injury_mult == -1.0:
                from src.schedule_analyzer import normalize_team_abbr as _norm_t
                susp_games = injury_info.get("suspension_games")
                team_abbr = _norm_t(str(row.get("TEAM_ABBREVIATION", "")))
                remaining = team_total_remaining.get(team_abbr, 0)

                if susp_games is None:
                    # Unknown suspension length — assume harsh
                    injury_mult = 0.05
                elif remaining <= 0:
                    # No schedule data — fall back to static thresholds
                    if susp_games >= 10:
                        injury_mult = 0.0
                    elif susp_games >= 5:
                        injury_mult = 0.03
                    elif susp_games >= 2:
                        injury_mult = 0.15
                    else:
                        injury_mult = 0.85
                else:
                    # Compute fraction of remaining games the player
                    # will actually be available for.
                    games_available = max(remaining - susp_games, 0)
                    avail_frac = games_available / remaining

                    if avail_frac == 0:
                        injury_mult = 0.0    # misses entire remaining schedule
                    elif avail_frac <= 0.15:
                        injury_mult = 0.03   # nearly season-ending
                    elif avail_frac <= 0.35:
                        injury_mult = 0.10   # misses most remaining games
                    elif avail_frac <= 0.60:
                        injury_mult = 0.30   # misses a significant chunk
                    elif avail_frac <= 0.85:
                        injury_mult = 0.60   # moderate miss
                    else:
                        injury_mult = 0.85   # minor miss (1-2 games)
        else:
            rec["Injury"] = "-"
            rec["Injury_Note"] = "-"

        # Add raw stat values for each 9-cat category
        for stat_key, cat_info in config.STAT_CATEGORIES.items():
            if stat_key in row.index:
                val = row[stat_key]
                if "PCT" in stat_key:
                    rec[cat_info["name"]] = f"{val:.3f}" if pd.notna(val) else "-"
                else:
                    rec[cat_info["name"]] = round(val, 1) if pd.notna(val) else "-"

        # Overall z-score value (raw talent)
        z_total = row.get("Z_TOTAL", 0)
        rec["Z_Value"] = round(z_total, 2)

        # Compute a need-adjusted score boosting players in weak categories
        # (team_needs already excludes punted categories)
        need_score = z_total
        if team_needs:
            weakest_cats = list(team_needs.keys())[:3]  # top 3 weakest
            for cat_name in weakest_cats:
                z_col = cat_name_to_z_col.get(cat_name)
                if z_col and z_col in row.index:
                    need_score += row[z_col] * 0.5  # 50% bonus for weak cats

        # Schedule multiplier for upcoming games (week-decay weighted)
        schedule_mult = 1.0
        if schedule_game_counts:
            from src.schedule_analyzer import normalize_team_abbr, compute_schedule_multiplier
            team_abbr = normalize_team_abbr(str(row.get("TEAM_ABBREVIATION", "")))
            games = schedule_game_counts.get(team_abbr, 0)

            # Use multi-week decay-weighted multiplier when available
            week_counts = team_week_data.get(team_abbr)
            schedule_mult = compute_schedule_multiplier(
                games, avg_games_per_week, week_game_counts=week_counts,
            )
            rec["Games_Wk"] = games
        else:
            rec["Games_Wk"] = "-"

        # ---------------------------------------------------------------
        # Hot-pickup boost: recent breakout performance
        # ---------------------------------------------------------------
        recency_boost = 0.0
        rec["Recent_Z"] = "-"
        rec["Z_Delta"] = "-"
        rec["Hot"] = ""

        if hot_pickup_scores and player_key and player_key in hot_pickup_scores:
            hp = hot_pickup_scores[player_key]
            rec["Recent_Z"] = hp["recent_z_total"]
            z_delta = hp["z_delta"]
            rec["Z_Delta"] = z_delta
            # Boost = weight × z_delta (only positive — don't penalize slumps
            # beyond what the season stats already reflect)
            if z_delta > 0:
                recency_boost = config.HOT_PICKUP_RECENCY_WEIGHT * z_delta
            if hp.get("is_hot"):
                rec["Hot"] = "🔥"

        # ---------------------------------------------------------------
        # Player news multiplier: role/performance signals from ESPN blurbs
        # ---------------------------------------------------------------
        news_mult = 1.0
        rec["News"] = "-"

        if player_news:
            norm_name = normalize_name(player_name)
            news_info = player_news.get(norm_name)
            if news_info:
                news_mult = news_info["news_multiplier"]
                rec["News"] = news_info["news_summary"]

        # ---------------------------------------------------------------
        # Trending boost: ownership spike across Yahoo leagues
        # ---------------------------------------------------------------
        trending_boost = 0.0
        rec["%Own"] = "-"
        rec["Δ%Own"] = "-"
        rec["Trending"] = ""

        if trending_data:
            norm_name = normalize_name(player_name)
            trend_info = trending_data.get(norm_name)
            if trend_info:
                pct = trend_info["percent_owned"]
                delta = trend_info["percent_owned_delta"]
                rec["%Own"] = f"{pct:.0f}%"
                rec["Δ%Own"] = f"{delta:+.0f}%" if delta else "0%"
                if trend_info["is_trending"]:
                    rec["Trending"] = "📈"
                    # Trending boost scales with the delta magnitude
                    # A +20% spike is a stronger signal than +5%
                    trending_boost = (
                        config.HOT_PICKUP_TRENDING_WEIGHT
                        * min(delta / 10.0, 3.0)  # cap at ~30% delta equivalent
                    )

        # ---------------------------------------------------------------
        # Apply availability discount, injury penalty, schedule multiplier,
        # PLUS additive hot-pickup and trending boosts
        # ---------------------------------------------------------------

        # Hard-skip players who are completely eliminated (OUT-SEASON,
        # long suspension, etc.) — multiplier of exactly 0.0 means
        # they won't play again this fantasy season.
        if injury_mult == 0.0:
            continue

        # For near-eliminated players (extended OUT, long suspension)
        # zero out additive boosts so they can't be rescued by
        # trending/recency signals alone.
        if injury_mult <= 0.05:
            recency_boost = 0.0
            trending_boost = 0.0

        adj_score = (
            need_score * avail_mult * injury_mult * schedule_mult * news_mult
            + recency_boost
            + trending_boost
        )
        rec["Adj_Score"] = round(adj_score, 2)

        recommendations.append(rec)

    if not recommendations:
        return pd.DataFrame()

    rec_df = pd.DataFrame(recommendations)
    rec_df = rec_df.sort_values("Adj_Score", ascending=False).reset_index(drop=True)
    rec_df.index += 1  # 1-based ranking
    rec_df.index.name = "Rank"

    return rec_df


def format_recommendations(
    rec_df: pd.DataFrame,
    top_n: int | None = None,
    compact: bool = False,
) -> str:
    """Format waiver recommendations as a readable table.

    Args:
        rec_df: Ranked recommendations DataFrame.
        top_n: Max rows to display.
        compact: If True, show only Player, Team, Z_Value, Adj_Score,
                 Injury, and Games_Wk columns.
    """
    from src.colors import (
        cyan, bold, colorize_injury, colorize_health, colorize_z_score,
    )

    if top_n is None:
        top_n = config.TOP_N_RECOMMENDATIONS

    df_display = rec_df.head(top_n).copy()

    # Select display columns
    if compact:
        display_cols = ["Player", "Team", "Games_Wk", "Injury", "News", "Z_Value", "Adj_Score"]
        # Add hot-pickup columns if data is present
        if "Hot" in df_display.columns:
            display_cols.insert(-1, "Hot")
        if "Trending" in df_display.columns:
            display_cols.insert(-1, "Trending")
    else:
        display_cols = ["Player", "Team", "GP", "MIN", "Games_Wk", "Avail%", "Health", "Injury", "News", "Recent", "G/14d"]
        for cat_info in config.STAT_CATEGORIES.values():
            if cat_info["name"] in df_display.columns:
                display_cols.append(cat_info["name"])
        display_cols.extend(["Z_Value"])
        # Add hot-pickup columns before Adj_Score
        for col in ["Z_Delta", "Hot", "%Own", "Δ%Own", "Trending"]:
            if col in df_display.columns:
                display_cols.append(col)
        display_cols.append("Adj_Score")

    # Only keep columns that exist
    display_cols = [c for c in display_cols if c in df_display.columns]

    # Colorize cell values before passing to tabulate
    if "Injury" in df_display.columns:
        df_display["Injury"] = df_display["Injury"].apply(colorize_injury)
    if "Health" in df_display.columns:
        df_display["Health"] = df_display["Health"].apply(colorize_health)
    if "Z_Value" in df_display.columns:
        df_display["Z_Value"] = df_display["Z_Value"].apply(
            lambda v: colorize_z_score(float(v)) if v != "-" else v
        )
    if "Z_Delta" in df_display.columns:
        from src.colors import green, red
        df_display["Z_Delta"] = df_display["Z_Delta"].apply(
            lambda v: green(f"{v:+.1f}") if isinstance(v, (int, float)) and v >= 1.0
            else red(f"{v:+.1f}") if isinstance(v, (int, float)) and v <= -1.0
            else (f"{v:+.1f}" if isinstance(v, (int, float)) else v)
        )
    if "Adj_Score" in df_display.columns:
        df_display["Adj_Score"] = df_display["Adj_Score"].apply(
            lambda v: colorize_z_score(float(v)) if v != "-" else v
        )

    lines = []
    title = "TOP WAIVER WIRE RECOMMENDATIONS"
    if compact:
        title += " (compact)"
    lines.append(cyan("=" * 100))
    lines.append(cyan(title))
    lines.append(cyan("=" * 100))
    lines.append("")
    lines.append(
        tabulate(
            df_display[display_cols],
            headers="keys",
            tablefmt="simple",
            showindex=True,
            numalign="right",
        )
    )
    lines.append("")
    lines.append("Z_Value   = Raw 9-cat z-score (higher = better all-around)")
    lines.append("Adj_Score = Z_Value weighted by team needs, availability, injury, schedule, + hot-pickup boost")
    lines.append("Games_Wk  = Remaining games this week (games already played are excluded)")
    if not compact:
        lines.append("Z_Delta   = Recent-game z-score minus season z-score (breakout signal)")
        lines.append("🔥 Hot     = Performing 1+ z-score above season average in last 3 games")
        lines.append("📈 Trending = Ownership spiking across Yahoo leagues (early pickup signal)")
        lines.append("Avail%    = Games Played / Team Games (season durability)")
        lines.append("Health    = Healthy (>=80%) | Moderate (60-80%) | Risky (40-60%) | Fragile (<40%)  [based on games played ratio, NOT current injury]")
        lines.append("Injury    = Current ESPN injury status: OUT-SEASON | OUT | SUSP | DTD (Day-To-Day) | - (not on report)")
        lines.append("News      = Role/performance signals from ESPN blurbs (Starting, Benched, Career High, etc.)")
        lines.append("Recent    = Active (played <3d ago) | Questionable (3-10d) | Inactive (>10d)")

    # Show injury notes for any recommended player with an injury
    if "Injury_Note" in rec_df.head(top_n).columns:
        injured_players = rec_df.head(top_n)[
            rec_df.head(top_n)["Injury_Note"] != "-"
        ]
        if not injured_players.empty:
            lines.append("")
            lines.append(cyan("=" * 100))
            lines.append(cyan("INJURY REPORT NOTES (source: ESPN)"))
            lines.append(cyan("=" * 100))
            for _, row in injured_players.iterrows():
                note = row['Injury_Note']
                lines.append(f"  {row['Player']:<25} {note}")

    # Show player news signals for recommended players
    if "News" in rec_df.head(top_n).columns:
        news_players = rec_df.head(top_n)[
            rec_df.head(top_n)["News"] != "-"
        ]
        if not news_players.empty:
            lines.append("")
            lines.append(cyan("=" * 100))
            lines.append(cyan("PLAYER NEWS SIGNALS (source: ESPN blurbs + Yahoo notes)"))
            lines.append(cyan("=" * 100))
            for _, row in news_players.iterrows():
                lines.append(f"  {row['Player']:<25} {row['News']}")

    return "\n".join(lines)


def run_streaming_analysis(return_data: bool = False) -> "pd.DataFrame | None":
    """Streaming mode: find the best available player with a game *tomorrow*.

    Identifies your weakest roster spot, filters the waiver pool to only
    players whose team plays tomorrow, and ranks them with need-weighting.
    Designed for daily streaming add/drops to maximise counting stats for the next day (for overnight FAAB leagues).

    Args:
        return_data: If True, return the recommendations DataFrame for
                     downstream use (e.g. email notification).

    Returns:
        None normally, or recommendations DataFrame if return_data=True.
    """
    from datetime import date as _date, timedelta

    from src.colors import cyan, green, red, bold, colorize_z_score

    tomorrow = _date.today() + timedelta(days=1)
    print(cyan("=" * 70))
    print(cyan(f"  STREAMING ADVISOR — {tomorrow.strftime('%A %B %d, %Y')} (tomorrow's games)"))
    print(cyan("=" * 70))
    print()

    # ---- Yahoo connection ----
    print("Connecting to Yahoo Fantasy Sports...")
    query = create_yahoo_query()

    # League settings (for auto-detect)
    league_settings: dict = {}
    game_weeks: list[dict] | None = None
    try:
        from src.league_settings import (
            fetch_league_settings as fetch_settings,
            apply_yahoo_settings,
            fetch_game_weeks,
        )
        league_settings = fetch_settings(query)
        if league_settings:
            auto_msgs = apply_yahoo_settings(league_settings)
            if auto_msgs:
                print("\n  Auto-detected league settings:")
                for msg in auto_msgs:
                    print(f"    {msg}")
        game_weeks = fetch_game_weeks(query)
    except Exception as e:
        print(f"  Warning: could not fetch league settings: {e}")

    # ---- Rosters ----
    print("\nFetching all team rosters...")
    all_rosters, owned_names = get_all_team_rosters(query)
    my_roster = get_my_team_roster(query)
    print(f"  {len(all_rosters)} teams, {len(owned_names)} owned players\n")

    # ---- Player stats (via Yahoo Fantasy API) ----
    nba_stats = build_player_stats_table(query)
    nba_stats["_norm_name"] = nba_stats["PLAYER_NAME"].apply(normalize_name)
    available_mask = ~nba_stats["_norm_name"].isin(owned_names)
    available_stats = nba_stats[available_mask].copy()
    print(f"  {len(available_stats)} players on waivers\n")

    # ---- Tomorrow's schedule ----
    print("Checking tomorrow's NBA schedule...")
    try:
        from src.schedule_analyzer import (
            fetch_nba_schedule,
            normalize_team_abbr,
            get_upcoming_weeks,
            build_schedule_analysis,
        )
        schedule = fetch_nba_schedule()
    except Exception as e:
        print(f"  ERROR: Could not fetch schedule: {e}")
        return


    teams_tomorrow: set[str] = set()
    for game in schedule:
        if game["game_date"] == tomorrow:
            teams_tomorrow.add(game["home_team"])
            teams_tomorrow.add(game["away_team"])

    if not teams_tomorrow:
        print(red("\n  No NBA games scheduled for tomorrow. Nothing to stream."))
        return

    print(f"  {len(teams_tomorrow) // 2} games tomorrow — {len(teams_tomorrow)} teams playing")

    # Filter available players to only those on teams playing tomorrow
    available_stats["_team_norm"] = available_stats["TEAM_ABBREVIATION"].apply(
        lambda t: normalize_team_abbr(str(t))
    )
    streaming_pool = available_stats[available_stats["_team_norm"].isin(teams_tomorrow)].copy()
    print(f"  {len(streaming_pool)} available players with a game tomorrow\n")

    if streaming_pool.empty:
        print(red("  No unowned players have a game tomorrow."))
        return

    # ---- Roster analysis ----
    print("Analyzing your roster...")
    roster_df = analyze_roster(my_roster, nba_stats)
    team_needs = identify_team_needs(roster_df)
    droppable = identify_droppable_players(roster_df)

    # Show weakest roster spot
    if droppable:
        worst_player = droppable[0]
        worst_idx = match_yahoo_to_nba(worst_player, nba_stats)
        worst_z = nba_stats.loc[worst_idx, "Z_TOTAL"] if worst_idx is not None else 0
        print(f"  Weakest roster spot: {bold(worst_player)} (z-score: {red(f'{worst_z:.2f}')})")
    if team_needs:
        weakest_cats = list(team_needs.keys())[:3]
        print(f"  Target categories: {', '.join(weakest_cats)}\n")

    # ---- IL/IL+ compliance check (smart stream evaluation) ----
    il_action = None  # Will hold recommendation dict if IL violation exists
    try:
        from src.transactions import check_il_compliance, evaluate_il_resolution
        il_violations = check_il_compliance(query)
        if il_violations:
            print(cyan("  ── IL/IL+ COMPLIANCE ──"))
            for v in il_violations:
                print(f"  ⚠ {v['player']} in {v['slot']} slot — "
                      f"status: {v['status']} (needs: {v['eligible_statuses']})")

            il_strategies = evaluate_il_resolution(
                il_violations, roster_df, nba_stats,
                droppable, mode="stream",
            )

            for st in il_strategies:
                v = st["violation"]
                il_name = v["player"]
                il_z = st["il_z"]
                reg_name = st.get("regular_player", "?")
                reg_z = st.get("regular_z", 0)

                if st["strategy"] == "drop_regular":
                    print(f"  → Recommended: DROP {red(reg_name)} (z: {red(f'{reg_z:+.2f}')}),"
                          f" ACTIVATE {green(il_name)} (z: {green(f'{il_z:+.2f}')})")
                    print(f"    {il_name} replaces {reg_name} as a roster upgrade — "
                          f"no streaming add needed.")
                    il_action = {
                        "strategy": "drop_regular",
                        "il_player": il_name, "il_z": il_z,
                        "drop_player": reg_name, "drop_z": reg_z,
                        "slot": v["slot"],
                    }
                else:
                    print(f"  → Recommended: DROP {red(il_name)} (z: {red(f'{il_z:+.2f}')}) "
                          f"from {v['slot']} to clear violation, then stream normally.")
                    il_action = {
                        "strategy": "drop_il",
                        "il_player": il_name, "il_z": il_z,
                        "drop_player": il_name, "drop_z": il_z,
                        "slot": v["slot"],
                    }
            print()
    except Exception as e:
        print(f"  Warning: could not check IL compliance: {e}\n")

    # ---- Score streaming candidates ----
    # Fetch injury data
    injury_lookup = {}
    if config.INJURY_REPORT_ENABLED:
        from src.injury_news import fetch_injury_report, build_injury_lookup
        injuries = fetch_injury_report()
        injury_lookup = build_injury_lookup(injuries)

    # Build schedule counts for tomorrow only (1 game for each playing team)
    tomorrow_game_counts = {team: 1 for team in teams_tomorrow}

    # Recent activity check for the streaming pool
    candidate_keys = (
        streaming_pool.sort_values("Z_TOTAL", ascending=False)
        .head(config.DETAILED_LOG_LIMIT)["PLAYER_KEY"]
        .dropna().astype(str).tolist()
    )
    recent_activity = {}
    if candidate_keys:
        recent_activity = check_recent_activity(
            candidate_keys, query, stats_df=nba_stats
        )

    # Score with need-weighting (schedule mult disabled — all have 1 game)
    recommendations = score_available_players(
        streaming_pool,
        team_needs=team_needs,
        recent_activity=recent_activity,
        injury_lookup=injury_lookup,
        schedule_game_counts=None,  # Skip schedule mult — all have games tomorrow
        avg_games_per_week=3.5,
    )

    if recommendations.empty:
        print(red("  No viable streaming options found."))
        return

    # ---- Display results ----
    top_n = min(config.TOP_N_RECOMMENDATIONS, len(recommendations))
    df_show = recommendations.head(top_n).copy()

    # Simplified display columns for streaming
    display_cols = ["Player", "Team", "Injury"]
    # Add stat category columns
    for cat_info in config.STAT_CATEGORIES.values():
        if cat_info["name"] in df_show.columns:
            display_cols.append(cat_info["name"])
    display_cols.extend(["Z_Value", "Adj_Score"])
    display_cols = [c for c in display_cols if c in df_show.columns]

    # Colorize
    if "Injury" in df_show.columns:
        from src.colors import colorize_injury
        df_show["Injury"] = df_show["Injury"].apply(colorize_injury)
    if "Z_Value" in df_show.columns:
        df_show["Z_Value"] = df_show["Z_Value"].apply(
            lambda v: colorize_z_score(float(v)) if v != "-" else v
        )
    if "Adj_Score" in df_show.columns:
        df_show["Adj_Score"] = df_show["Adj_Score"].apply(
            lambda v: colorize_z_score(float(v)) if v != "-" else v
        )

    print(cyan("=" * 90))
    print(cyan(f"BEST STREAMING PICKUPS FOR TOMORROW ({tomorrow.strftime('%b %d')})"))
    print(cyan("=" * 90))
    print()
    print(
        tabulate(
            df_show[display_cols],
            headers="keys",
            tablefmt="simple",
            showindex=True,
            numalign="right",
        )
    )
    print()

    # Roster impact for top pick vs weakest player
    if il_action and il_action["strategy"] == "drop_regular":
        # IL player replaces worst regular player — that IS the streaming move
        print(f"  ★ Best move tomorrow: ACTIVATE {green(il_action['il_player'])} "
              f"from {il_action['slot']} / DROP {red(il_action['drop_player'])}")
        impact = compute_roster_impact(
            il_action["il_player"], il_action["drop_player"], nba_stats
        )
        if impact:
            print(f"  Roster impact:  {impact['summary']}")
        print()
        print("  Your IL player returning is a better upgrade than streaming tomorrow.")
        print("  Clear the IL violation first, then evaluate streaming picks.\n")
    elif droppable and not recommendations.empty:
        top_pick = recommendations.iloc[0]["Player"]
        drop_target = droppable[0]
        # If there's a drop_il action, note it above the streaming suggestion
        if il_action and il_action["strategy"] == "drop_il":
            print(f"  ★ First: DROP {red(il_action['il_player'])} from "
                  f"{il_action['slot']} to clear IL violation")
        impact = compute_roster_impact(top_pick, drop_target, nba_stats)
        if impact:
            print(f"  Suggested move: ADD {green(top_pick)} / DROP {red(drop_target)}")
            print(f"  Roster impact:  {impact['summary']}")
            print()

    print("  Streaming = daily add/drop to fill your roster with players who have games tomorrow.")
    print("  Run with --claim to submit the transaction.\n")

    if return_data:
        # Attach IL action metadata so the email report can include it
        recommendations.attrs["il_action"] = il_action
        return recommendations
    return None


def run_waiver_analysis(
    skip_yahoo: bool = False,
    return_data: bool = False,
    compact: bool = False,
):
    """Run the full waiver wire analysis pipeline.

    The flow is Yahoo-first:
      1. Query Yahoo Fantasy to get all league rosters (who is owned)
      2. Fetch NBA stats via Yahoo Fantasy API
      3. Filter stats to only available (unowned) players
      4. Analyze your roster and rank available players by need

    Args:
        skip_yahoo: If True, show overall NBA stats rankings without Yahoo
                    roster data (useful for testing without Yahoo API setup).
        return_data: If True, return (query, rec_df) tuple for downstream use
                     (e.g. transaction submission). Only applies when not skipping Yahoo.

    Returns:
        None normally, or (query, rec_df, nba_stats, schedule_analysis) if return_data=True.
    """
    if skip_yahoo:
        # All stats now come from Yahoo Fantasy API — cannot skip.
        print("ERROR: Stats are fetched via Yahoo Fantasy API. Cannot skip Yahoo.")
        print("Remove --skip-yahoo or run normally.")
        return

    # ---------------------------------------------------------------
    # STEP 1: Connect to Yahoo and fetch ALL league rosters
    # ---------------------------------------------------------------
    print("Connecting to Yahoo Fantasy Sports...")
    query = create_yahoo_query()

    # ---------------------------------------------------------------
    # STEP 1b: Fetch league settings & constraints
    # ---------------------------------------------------------------
    league_settings = {}
    game_weeks: list[dict] | None = None
    try:
        from src.league_settings import (
            fetch_league_settings as fetch_settings,
            format_settings_report,
            fetch_game_weeks,
            apply_yahoo_settings,
        )
        league_settings = fetch_settings(query)
        if league_settings:
            # Auto-override config defaults with actual Yahoo league rules
            auto_msgs = apply_yahoo_settings(league_settings)
            if auto_msgs:
                print("\n  Auto-detected league settings:")
                for msg in auto_msgs:
                    print(f"    {msg}")
            print(format_settings_report(league_settings))
            print()
        game_weeks = fetch_game_weeks(query)
    except Exception as e:
        print(f"  Warning: could not fetch league settings: {e}\n")

    print("\nFetching all team rosters in the league...")
    all_rosters, owned_names = get_all_team_rosters(query)
    total_owned = len(owned_names)
    print(f"\n  {len(all_rosters)} teams, {total_owned} total owned players\n")

    # Identify your roster from the full league data
    my_roster = get_my_team_roster(query)
    my_roster_details = [extract_player_details(p) for p in my_roster]
    my_player_names = [d["name"] for d in my_roster_details]
    print(f"Your roster ({len(my_player_names)} players):")
    for d in my_roster_details:
        slot = d.get("selected_position", "")
        slot_tag = f"  [{slot}]" if slot in ("IL", "IL+") else ""
        print(f"    {d['name']:<25} {d['team'].upper()}{slot_tag}")
    print()

    # ---------------------------------------------------------------
    # STEP 2: Fetch NBA stats and compute z-scores
    # ---------------------------------------------------------------
    nba_stats = build_player_stats_table(query)
    print(f"  Loaded stats for {len(nba_stats)} NBA players\n")

    # ---------------------------------------------------------------
    # STEP 3: Filter to ONLY available (unowned) players
    # ---------------------------------------------------------------
    nba_stats["_norm_name"] = nba_stats["PLAYER_NAME"].apply(normalize_name)
    available_mask = ~nba_stats["_norm_name"].isin(owned_names)
    available_stats = nba_stats[available_mask].copy()
    owned_stats = nba_stats[~available_mask].copy()

    print(f"  {len(owned_stats)} players owned in your league")
    print(f"  {len(available_stats)} players available on waivers\n")

    # ---------------------------------------------------------------
    # STEP 4: Analyze your roster's strengths and weaknesses
    # ---------------------------------------------------------------
    print("Analyzing your roster's 9-cat profile...")
    roster_df = analyze_roster(my_roster, nba_stats)
    team_needs = identify_team_needs(roster_df)
    print(format_team_analysis(roster_df, team_needs))
    print()

    # ---------------------------------------------------------------
    # STEP 5: Check recent activity for top waiver candidates
    # ---------------------------------------------------------------
    # Sort available players by raw Z_TOTAL to find top candidates
    available_stats = available_stats.sort_values("Z_TOTAL", ascending=False)

    candidate_limit = config.DETAILED_LOG_LIMIT

    top_candidate_keys = (
        available_stats.head(candidate_limit)["PLAYER_KEY"]
        .dropna()
        .astype(str)
        .tolist()
    )

    recent_activity = {}
    if top_candidate_keys:
        print(f"Checking recent game activity for top {len(top_candidate_keys)} candidates...")
        recent_activity = check_recent_activity(
            top_candidate_keys, query, stats_df=nba_stats
        )
        active_count = sum(1 for v in recent_activity.values() if v.get("recent_flag") == "Active")
        inactive_count = sum(1 for v in recent_activity.values() if v.get("is_inactive"))
        print(f"  {active_count} active, {inactive_count} inactive/injured\n")

    # ---------------------------------------------------------------
    # STEP 5a: Hot-pickup analysis (ESPN boxscores → z-delta detection)
    # ---------------------------------------------------------------
    # Fetch ESPN boxscores for the last 3 days.  This provides:
    #   1. Full stat lines for hot-pickup z-delta (replaces Yahoo per-date)
    #   2. Standout signals (waiver-calibrated thresholds)
    #   3. Starter/bench flags (starting-tomorrow detection)
    # Falls back to Yahoo per-date stats only if ESPN fails.
    hot_pickup_scores = None
    espn_boxscores = None  # shared with Step 5b-ii
    if config.HOT_PICKUP_ENABLED and top_candidate_keys:
        try:
            from src.player_news import (
                fetch_espn_boxscores,
                convert_boxscores_to_recent_stats,
            )
            candidate_names = available_stats.head(candidate_limit)["PLAYER_NAME"].tolist()
            print(f"Fetching ESPN boxscores for hot-pickup analysis "
                  f"({config.HOT_PICKUP_RECENT_GAMES} games, {len(candidate_names)} players)...")

            espn_boxscores = fetch_espn_boxscores(
                player_names=candidate_names,
                days=config.HOT_PICKUP_RECENT_GAMES + 4,  # scan extra days to find enough games
            )
            print(f"  {espn_boxscores.api_calls} ESPN API calls, "
                  f"{len(espn_boxscores.stat_lines)} players found in boxscores")

            # Build name → player_key mapping for conversion
            name_to_key: dict[str, str] = {}
            for _, row in available_stats.head(candidate_limit).iterrows():
                norm = normalize_name(row["PLAYER_NAME"])
                name_to_key[norm] = str(row["PLAYER_KEY"])

            recent_game_stats = convert_boxscores_to_recent_stats(
                espn_boxscores, name_to_key,
                last_n=config.HOT_PICKUP_RECENT_GAMES,
            )
            if recent_game_stats:
                hot_pickup_scores = compute_hot_pickup_scores(recent_game_stats, nba_stats)
                hot_count = sum(1 for v in hot_pickup_scores.values() if v.get("is_hot"))
                print(f"  {len(recent_game_stats)} players evaluated via ESPN, "
                      f"{hot_count} breaking out 🔥\n")
            else:
                print("  No ESPN stat lines matched candidates\n")

        except Exception as e:
            print(f"  ESPN boxscore fetch failed ({e}), falling back to Yahoo...")
            try:
                hot_keys = top_candidate_keys[: config.DETAILED_LOG_LIMIT]
                recent_game_stats = compute_recent_game_stats(hot_keys, query)
                hot_pickup_scores = compute_hot_pickup_scores(recent_game_stats, nba_stats)
                hot_count = sum(1 for v in hot_pickup_scores.values() if v.get("is_hot"))
                print(f"  {len(recent_game_stats)} players evaluated via Yahoo, "
                      f"{hot_count} breaking out 🔥\n")
            except Exception as e2:
                print(f"  Warning: hot-pickup analysis failed: {e2}\n")

    # ---------------------------------------------------------------
    # STEP 5a-ii: Yahoo trending/ownership data
    # ---------------------------------------------------------------
    trending_data = None
    if config.HOT_PICKUP_ENABLED:
        try:
            from src.yahoo_fantasy import fetch_trending_players
            candidate_names = available_stats.head(candidate_limit)["PLAYER_NAME"].tolist()
            trending_data = fetch_trending_players(query, candidate_names, owned_names)
        except Exception as e:
            print(f"  Warning: trending data fetch failed: {e}\n")

    # ---------------------------------------------------------------
    # STEP 5b: Fetch injury report from ESPN
    # ---------------------------------------------------------------
    injury_lookup = {}
    if config.INJURY_REPORT_ENABLED:
        injuries = fetch_injury_report()
        injury_lookup = build_injury_lookup(injuries)
        injured_available = sum(
            1 for _, row in available_stats.iterrows()
            if get_player_injury_status(row["PLAYER_NAME"], injury_lookup)
        )
        print(f"  {len(injuries)} players on injury report, {injured_available} available but injured\n")

    # ---------------------------------------------------------------
    # STEP 5b-ii: Player news keyword analysis (ESPN blurbs + Yahoo notes)
    # ---------------------------------------------------------------
    player_news = None
    try:
        from src.player_news import (
            analyze_player_news,
            fetch_espn_player_news,
            fetch_espn_boxscores,
        )
        candidate_names = available_stats.head(candidate_limit)["PLAYER_NAME"].tolist()

        # Build Yahoo recent-notes lookup from DataFrame
        yahoo_notes: dict[str, bool] = {}
        if "HAS_RECENT_NOTES" in nba_stats.columns:
            for _, row in nba_stats.iterrows():
                if row.get("HAS_RECENT_NOTES"):
                    yahoo_notes[normalize_name(row["PLAYER_NAME"])] = True

        # Mine ESPN injury blurbs for performance keywords
        player_news = analyze_player_news(
            injury_lookup, player_names=candidate_names,
            yahoo_notes=yahoo_notes,
        )

        # Also scan ESPN general news for non-injury signals
        espn_news = fetch_espn_player_news(player_names=candidate_names)
        for norm, info in espn_news.items():
            if norm not in player_news:
                player_news[norm] = info

        # Use ESPN boxscore standout signals (already fetched in Step 5a)
        # If boxscores weren't fetched yet, fetch them now
        if espn_boxscores is None:
            try:
                espn_boxscores = fetch_espn_boxscores(
                    player_names=candidate_names, days=3,
                )
            except Exception:
                pass

        if espn_boxscores is not None:
            # Merge standout signals
            for norm, info in espn_boxscores.standout_signals.items():
                if norm in player_news:
                    existing = player_news[norm]
                    for lbl in info["news_labels"]:
                        if lbl not in existing["news_labels"]:
                            existing["news_labels"].append(lbl)
                    existing["news_summary"] = ", ".join(existing["news_labels"])
                    existing["news_multiplier"] = round(
                        max(existing["news_multiplier"], info["news_multiplier"]), 3
                    )
                else:
                    player_news[norm] = info

            # Add "Recent Starter" signal for candidates who started
            # their most recent game (strong indicator they'll start
            # tomorrow too — relevant since pickups are for next day)
            for norm, sinfo in espn_boxscores.starter_info.items():
                if sinfo["started_last"] and sinfo["games_started"] >= 1:
                    label = "Recent Starter"
                    mult = 1.08
                    if norm in player_news:
                        existing = player_news[norm]
                        if label not in existing["news_labels"]:
                            existing["news_labels"].append(label)
                            existing["news_summary"] = ", ".join(existing["news_labels"])
                            existing["news_multiplier"] = round(
                                max(existing["news_multiplier"], mult), 3
                            )
                    else:
                        player_news[norm] = {
                            "news_multiplier": mult,
                            "news_labels": [label],
                            "news_summary": label,
                            "has_yahoo_notes": False,
                        }

        if player_news:
            print(f"  {len(player_news)} players with news signals")
            for norm, info in list(player_news.items())[:5]:
                print(f"    {norm}: {info['news_summary']} (x{info['news_multiplier']:.2f})")
            print()
    except Exception as e:
        print(f"  Warning: player news analysis failed: {e}\n")

    # ---------------------------------------------------------------
    # STEP 5c: Fetch upcoming NBA schedule
    # ---------------------------------------------------------------
    schedule_game_counts = None
    avg_games_per_week = 3.5
    schedule_analysis = None
    try:
        from src.schedule_analyzer import (
            fetch_nba_schedule, get_upcoming_weeks, build_schedule_analysis,
            format_schedule_report as fmt_sched,
        )
        schedule = fetch_nba_schedule()
        _current_wk = league_settings.get("current_week") if league_settings else None
        weeks = get_upcoming_weeks(current_fantasy_week=_current_wk, game_weeks=game_weeks)
        schedule_analysis = build_schedule_analysis(schedule, weeks)

        if schedule_analysis and schedule_analysis.get("weeks"):
            schedule_game_counts = schedule_analysis["weeks"][0]["game_counts"]
            avg_games_per_week = schedule_analysis["avg_games_per_week"]
    except Exception as e:
        print(f"  Warning: schedule analysis failed: {e}\n")

    # ---------------------------------------------------------------
    # STEP 6: Rank available players by need-weighted, schedule-adjusted score
    # ---------------------------------------------------------------
    print("Ranking available players (need + availability + injury + schedule + news + hot-pickup adjusted)...")
    recommendations = score_available_players(
        available_stats, team_needs, recent_activity, injury_lookup,
        schedule_game_counts=schedule_game_counts,
        avg_games_per_week=avg_games_per_week,
        schedule_analysis=schedule_analysis,
        hot_pickup_scores=hot_pickup_scores,
        trending_data=trending_data,
        player_news=player_news,
    )
    print(format_recommendations(recommendations, compact=compact))

    # ---------------------------------------------------------------
    # STEP 6b: Print schedule comparison report
    # ---------------------------------------------------------------
    droppable_names = identify_droppable_players(roster_df)
    if schedule_analysis:
        try:
            sched_report = fmt_sched(
                schedule_analysis,
                waiver_df=recommendations,
                droppable_names=droppable_names,
                nba_stats=nba_stats,
            )
            print(sched_report)
        except Exception as e:
            print(f"  Warning: schedule report failed: {e}")

    # Save results
    output_file = config.OUTPUT_DIR / "waiver_recommendations.csv"
    recommendations.to_csv(output_file)
    print(f"\nResults saved to {output_file}")

    if return_data:
        return query, recommendations, nba_stats, schedule_analysis

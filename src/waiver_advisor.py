"""Waiver wire recommendation engine.

Combines NBA stats (from nba_api) with Yahoo Fantasy roster data (from yfpy)
to identify the best available pickups for a 9-category league.

Flow:
  1. Connect to Yahoo Fantasy and fetch ALL team rosters in the league
  2. Build a set of owned player names (unavailable)
  3. Fetch NBA stats from nba_api and compute 9-cat z-scores
  4. Filter NBA stats to only players NOT owned in the league
  5. Analyze your roster's strengths/weaknesses
  6. Rank available players with need-weighted scoring
"""

import pandas as pd
from tabulate import tabulate

import config
from src.injury_news import (
    build_injury_lookup,
    fetch_injury_report,
    format_injury_note,
    get_player_injury_status,
)
from src.nba_stats import build_player_stats_table, check_recent_activity, find_player_id
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
        nba_name: Player name from nba_api (PLAYER_NAME column).
        owned_names: Set of normalized names of all owned players.

    Returns:
        True if the player is owned (unavailable), False if available.
    """
    return normalize_name(nba_name) in owned_names


def match_yahoo_to_nba(yahoo_name: str, nba_df: pd.DataFrame) -> int | None:
    """Match a Yahoo Fantasy player name to the nba_api stats DataFrame.

    Args:
        yahoo_name: Player name from Yahoo Fantasy.
        nba_df: DataFrame from nba_api with PLAYER_NAME column.

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


def format_team_analysis(roster_df: pd.DataFrame, team_needs: dict) -> str:
    """Format team analysis as a readable string."""
    lines = []
    lines.append("=" * 70)
    lines.append("YOUR TEAM CATEGORY ANALYSIS")
    lines.append("=" * 70)

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
        lines.append(f"{cat_name:<12} {z_avg:>12.2f} {assessment:>15}")

    # Identify punt candidates and strengths
    strengths = [c for c, z in team_needs.items() if z >= 0.3]
    weaknesses = [c for c, z in team_needs.items() if z <= -0.3]

    if strengths:
        lines.append(f"\nStrengths: {', '.join(strengths)}")
    if weaknesses:
        lines.append(f"Weaknesses: {', '.join(weaknesses)}")
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

    Returns:
        DataFrame of ranked waiver recommendations.
    """
    # Build a mapping from category name back to z-column
    cat_name_to_z_col = {}
    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        cat_name_to_z_col[cat_info["name"]] = f"Z_{stat_key}"

    # Pre-build per-team multi-week game counts for decay-weighted multiplier
    team_week_data: dict[str, list[tuple[int, float]]] = {}
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

    recommendations = []

    for _, row in available_stats.iterrows():
        player_id = row.get("PLAYER_ID", None)
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
        if recent_activity and player_id and int(player_id) in recent_activity:
            activity = recent_activity[int(player_id)]
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

        # Apply availability discount, injury penalty, AND schedule multiplier
        adj_score = need_score * avail_mult * injury_mult * schedule_mult
        rec["Adj_Score"] = round(adj_score, 2)

        recommendations.append(rec)

    if not recommendations:
        return pd.DataFrame()

    rec_df = pd.DataFrame(recommendations)
    rec_df = rec_df.sort_values("Adj_Score", ascending=False).reset_index(drop=True)
    rec_df.index += 1  # 1-based ranking
    rec_df.index.name = "Rank"

    return rec_df


def format_recommendations(rec_df: pd.DataFrame, top_n: int | None = None) -> str:
    """Format waiver recommendations as a readable table."""
    if top_n is None:
        top_n = config.TOP_N_RECOMMENDATIONS

    df_display = rec_df.head(top_n).copy()

    # Select display columns
    display_cols = ["Player", "Team", "GP", "MIN", "Games_Wk", "Avail%", "Health", "Injury", "Recent", "G/14d"]
    for cat_info in config.STAT_CATEGORIES.values():
        if cat_info["name"] in df_display.columns:
            display_cols.append(cat_info["name"])
    display_cols.extend(["Z_Value", "Adj_Score"])

    # Only keep columns that exist
    display_cols = [c for c in display_cols if c in df_display.columns]

    lines = []
    lines.append("=" * 100)
    lines.append("TOP WAIVER WIRE RECOMMENDATIONS")
    lines.append("=" * 100)
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
    lines.append("Adj_Score = Z_Value weighted by team needs, availability, injury, AND schedule")
    lines.append("Games_Wk  = Games this upcoming week (more games = more stat production)")
    lines.append("Avail%    = Games Played / Team Games (season durability)")
    lines.append("Health    = Healthy (>=80%) | Moderate (60-80%) | Risky (40-60%) | Fragile (<40%)")
    lines.append("Injury    = OUT-SEASON | OUT | DTD (Day-To-Day) | - (not on injury report)")
    lines.append("Recent    = Active (played <3d ago) | Questionable (3-10d) | Inactive (>10d)")

    # Show injury notes for any recommended player with an injury
    if "Injury_Note" in df_display.columns:
        injured_players = df_display[df_display["Injury_Note"] != "-"]
        if not injured_players.empty:
            lines.append("")
            lines.append("=" * 100)
            lines.append("INJURY REPORT NOTES (source: ESPN)")
            lines.append("=" * 100)
            for _, row in injured_players.iterrows():
                lines.append(f"  {row['Player']:<25} {row['Injury_Note']}")

    return "\n".join(lines)


def run_waiver_analysis(skip_yahoo: bool = False, return_data: bool = False):
    """Run the full waiver wire analysis pipeline.

    The flow is Yahoo-first:
      1. Query Yahoo Fantasy to get all league rosters (who is owned)
      2. Fetch NBA stats from nba_api
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
        # Fallback: just show top NBA players by z-score
        nba_stats = build_player_stats_table()
        print(f"  Loaded stats for {len(nba_stats)} players\n")

        # Fetch injury report
        injury_lookup = {}
        if config.INJURY_REPORT_ENABLED:
            injuries = fetch_injury_report()
            injury_lookup = build_injury_lookup(injuries)
            injured_in_pool = sum(
                1 for _, row in nba_stats.iterrows()
                if get_player_injury_status(row["PLAYER_NAME"], injury_lookup)
            )
            print(f"  {len(injuries)} players on injury report, {injured_in_pool} in stats pool\n")

        # Fetch schedule
        schedule_game_counts = None
        avg_games_per_week = 3.5
        schedule_analysis = None
        try:
            from src.schedule_analyzer import (
                fetch_nba_schedule, get_upcoming_weeks, build_schedule_analysis,
            )
            schedule = fetch_nba_schedule()
            _wk0 = league_settings.get("current_week") if league_settings else None
            weeks = get_upcoming_weeks(current_fantasy_week=_wk0, game_weeks=game_weeks)
            schedule_analysis = build_schedule_analysis(schedule, weeks)
            if schedule_analysis and schedule_analysis.get("weeks"):
                schedule_game_counts = schedule_analysis["weeks"][0]["game_counts"]
                avg_games_per_week = schedule_analysis["avg_games_per_week"]
        except Exception as e:
            print(f"  Warning: schedule analysis failed: {e}")

        print("=" * 70)
        print("TOP NBA PLAYERS BY 9-CATEGORY Z-SCORE VALUE")
        print("(Yahoo Fantasy integration skipped)")
        print("=" * 70)

        # Use the full scoring pipeline (without team needs) to apply
        # availability + injury + schedule multipliers
        recommendations = score_available_players(
            nba_stats, team_needs=None, recent_activity=None,
            injury_lookup=injury_lookup,
            schedule_game_counts=schedule_game_counts,
            avg_games_per_week=avg_games_per_week,
            schedule_analysis=schedule_analysis,
        )
        print(format_recommendations(recommendations))
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
        )
        league_settings = fetch_settings(query)
        if league_settings:
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
        print(f"    {d['name']:<25} {d['position']:<10} {d['team'].upper()}")
    print()

    # ---------------------------------------------------------------
    # STEP 2: Fetch NBA stats and compute z-scores
    # ---------------------------------------------------------------
    nba_stats = build_player_stats_table()
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
    top_candidate_ids = (
        available_stats.head(config.DETAILED_LOG_LIMIT)["PLAYER_ID"]
        .dropna()
        .astype(int)
        .tolist()
    )

    recent_activity = {}
    if top_candidate_ids:
        print(f"Checking recent game activity for top {len(top_candidate_ids)} candidates...")
        recent_activity = check_recent_activity(top_candidate_ids)
        active_count = sum(1 for v in recent_activity.values() if v.get("recent_flag") == "Active")
        inactive_count = sum(1 for v in recent_activity.values() if v.get("is_inactive"))
        print(f"  {active_count} active, {inactive_count} inactive/injured\n")

    # ---------------------------------------------------------------
    # STEP 5b: Fetch injury report from Basketball-Reference
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
    print("Ranking available players (need + availability + injury + schedule adjusted)...")
    recommendations = score_available_players(
        available_stats, team_needs, recent_activity, injury_lookup,
        schedule_game_counts=schedule_game_counts,
        avg_games_per_week=avg_games_per_week,
        schedule_analysis=schedule_analysis,
    )
    print(format_recommendations(recommendations))

    # ---------------------------------------------------------------
    # STEP 6b: Print schedule comparison report
    # ---------------------------------------------------------------
    if schedule_analysis:
        try:
            sched_report = fmt_sched(
                schedule_analysis,
                waiver_df=recommendations,
                droppable_names=list(config.DROPPABLE_PLAYERS),
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

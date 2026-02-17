"""NBA schedule analysis for waiver wire decisions.

Fetches the NBA schedule and analyzes upcoming games to quantify the
value of picking up (or dropping) players based on their team's
upcoming game count. Players on teams with more games provide more
stat production opportunities.

Data source: NBA.com CDN schedule JSON
Fallback:    nba_api scoreboardv2 per-day lookup
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from nba_api.stats.endpoints import scoreboardv2
from nba_api.stats.static import teams as nba_teams
from tabulate import tabulate

import config
from src.yahoo_fantasy import normalize_name

# NBA.com full-season schedule JSON (updates each season)
NBA_SCHEDULE_URL = (
    "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
)

# Yahoo → NBA.com team abbreviation differences
YAHOO_TO_NBA_ABBR: dict[str, str] = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "WSH": "WAS",
    "PHO": "PHX",
    "BKN": "BKN",  # same, but listed for completeness
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_team_abbr(abbr: str) -> str:
    """Normalize a team abbreviation to NBA.com tricode (uppercase, 3-letter)."""
    upper = abbr.strip().upper()
    return YAHOO_TO_NBA_ABBR.get(upper, upper)


# ---------------------------------------------------------------------------
# Schedule fetching
# ---------------------------------------------------------------------------

def fetch_nba_schedule() -> list[dict]:
    """Fetch the full NBA season schedule from NBA.com CDN.

    Returns:
        List of game dicts:
          {"game_date": date, "home_team": str, "away_team": str, "game_id": str}
    """
    print("  Fetching NBA schedule from NBA.com...")
    try:
        resp = requests.get(
            NBA_SCHEDULE_URL,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        games: list[dict] = []
        league_schedule = data.get("leagueSchedule", {})
        for date_group in league_schedule.get("gameDates", []):
            for game in date_group.get("games", []):
                game_date_str = game.get("gameDateEst", "")
                if not game_date_str:
                    continue
                try:
                    game_date = datetime.strptime(
                        game_date_str[:10], "%Y-%m-%d"
                    ).date()
                except ValueError:
                    continue

                home = game.get("homeTeam", {}).get("teamTricode", "")
                away = game.get("awayTeam", {}).get("teamTricode", "")

                if home and away:
                    games.append({
                        "game_date": game_date,
                        "home_team": home,
                        "away_team": away,
                        "game_id": game.get("gameId", ""),
                    })

        print(f"  Loaded {len(games)} games from NBA schedule")
        return games

    except Exception as e:
        print(f"  Warning: CDN schedule fetch failed ({e}), trying per-day fallback")
        return []


def _fetch_schedule_per_day(
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Fallback: use nba_api scoreboardv2 to get games per day."""
    # Build team-ID → abbreviation mapping
    team_map: dict[int, str] = {}
    for t in nba_teams.get_teams():
        team_map[t["id"]] = t["abbreviation"]

    games: list[dict] = []
    current = start_date
    while current <= end_date:
        try:
            board = scoreboardv2.ScoreboardV2(
                game_date=current.strftime("%Y-%m-%d"),
                timeout=30,
            )
            time.sleep(0.6)
            headers_df = board.get_data_frames()[0]

            for _, row in headers_df.iterrows():
                home_id = row.get("HOME_TEAM_ID")
                away_id = row.get("VISITOR_TEAM_ID")
                home_abbr = team_map.get(home_id, "")
                away_abbr = team_map.get(away_id, "")
                if home_abbr and away_abbr:
                    games.append({
                        "game_date": current,
                        "home_team": home_abbr,
                        "away_team": away_abbr,
                        "game_id": str(row.get("GAME_ID", "")),
                    })
        except Exception:
            pass
        current += timedelta(days=1)

    return games


# ---------------------------------------------------------------------------
# Week boundary helpers
# ---------------------------------------------------------------------------

def get_upcoming_weeks(
    weeks_ahead: int | None = None,
    current_fantasy_week: int | None = None,
    game_weeks: list[dict] | None = None,
) -> list[tuple[date, date, str]]:
    """Get (start, end, label) tuples for upcoming fantasy weeks.

    When *game_weeks* (from Yahoo's ``get_game_weeks_by_game_id``) is
    provided, the function uses the **actual** Yahoo week boundaries.  This
    is critical for extended fantasy weeks such as the All-Star break, which
    can span two calendar weeks.

    Without *game_weeks* it falls back to assuming Mon-Sun calendar weeks.

    Args:
        weeks_ahead: Number of weeks to return (default: config.SCHEDULE_WEEKS_AHEAD).
        current_fantasy_week: The current fantasy week number (e.g. 17). If
            provided, labels will say "Week 17", "Week 18", etc. If None,
            labels use relative numbering ("Week 1", "Week 2", …).
        game_weeks: List of dicts with keys ``week`` (int), ``start`` (date),
            ``end`` (date) — as returned by
            :pyfunc:`src.league_settings.fetch_game_weeks`.

    Returns:
        List of (start_date, end_date, label) tuples.
    """
    if weeks_ahead is None:
        weeks_ahead = config.SCHEDULE_WEEKS_AHEAD

    today = date.today()

    # ------------------------------------------------------------------
    # If we have Yahoo game-week data, use exact boundaries
    # ------------------------------------------------------------------
    if game_weeks and current_fantasy_week is not None:
        # Build a lookup {week_num: (start, end)}
        gw_lookup = {gw["week"]: (gw["start"], gw["end"]) for gw in game_weeks}
        weeks: list[tuple[date, date, str]] = []
        for i in range(weeks_ahead):
            wk = current_fantasy_week + i
            if wk in gw_lookup:
                start, end = gw_lookup[wk]
            else:
                # Past the schedule data — estimate with Mon-Sun
                base_monday = today - timedelta(days=today.weekday())
                start = base_monday + timedelta(weeks=i)
                end = start + timedelta(days=6)
            label = f"Week {wk}: {start.strftime('%b %d')} – {end.strftime('%b %d')}"
            weeks.append((start, end, label))
        return weeks

    # ------------------------------------------------------------------
    # Fallback: assume standard Mon-Sun calendar weeks
    # ------------------------------------------------------------------
    current_monday = today - timedelta(days=today.weekday())

    weeks = []
    for i in range(weeks_ahead):
        monday = current_monday + timedelta(weeks=i)
        sunday = monday + timedelta(days=6)
        if current_fantasy_week is not None:
            week_num = current_fantasy_week + i
        else:
            week_num = i + 1
        label = f"Week {week_num}: {monday.strftime('%b %d')} – {sunday.strftime('%b %d')}"
        weeks.append((monday, sunday, label))

    return weeks


# ---------------------------------------------------------------------------
# Game counting
# ---------------------------------------------------------------------------

def get_team_game_counts(
    schedule: list[dict],
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Count games per team within a date range (inclusive)."""
    counts: dict[str, int] = defaultdict(int)
    for game in schedule:
        gd = game["game_date"]
        if start_date <= gd <= end_date:
            counts[game["home_team"]] += 1
            counts[game["away_team"]] += 1
    return dict(counts)


def get_team_game_dates(
    schedule: list[dict],
    start_date: date,
    end_date: date,
) -> dict[str, list[date]]:
    """Get sorted game dates per team within a date range."""
    dates: dict[str, list[date]] = defaultdict(list)
    for game in schedule:
        gd = game["game_date"]
        if start_date <= gd <= end_date:
            dates[game["home_team"]].append(gd)
            dates[game["away_team"]].append(gd)
    for team in dates:
        dates[team].sort()
    return dict(dates)


# ---------------------------------------------------------------------------
# Schedule analysis builder
# ---------------------------------------------------------------------------

def build_schedule_analysis(
    schedule: list[dict],
    weeks: list[tuple[date, date, str]] | None = None,
) -> dict:
    """Build a multi-week schedule analysis.

    Returns:
        Dict with:
          "weeks": list of per-week analysis dicts
          "total_game_counts": {team: total across all weeks}
          "avg_games_per_week": float (mean across teams)
    """
    if weeks is None:
        weeks = get_upcoming_weeks()

    # If CDN schedule was empty, try per-day fallback for the needed range
    if not schedule and weeks:
        start = weeks[0][0]
        end = weeks[-1][1]
        print("  Using per-day fallback for schedule data...")
        schedule = _fetch_schedule_per_day(start, end)

    total_counts: dict[str, int] = defaultdict(int)
    week_analyses: list[dict] = []

    for monday, sunday, label in weeks:
        counts = get_team_game_counts(schedule, monday, sunday)
        dates = get_team_game_dates(schedule, monday, sunday)

        for team, count in counts.items():
            total_counts[team] += count

        count_vals = list(counts.values()) or [0]
        week_analyses.append({
            "label": label,
            "start": monday,
            "end": sunday,
            "game_counts": counts,
            "game_dates": dates,
            "avg_games": round(sum(count_vals) / max(len(count_vals), 1), 1),
            "max_games": max(count_vals),
            "min_games": min(count_vals),
        })

    total_counts_dict = dict(total_counts)
    num_weeks = len(weeks)
    if total_counts_dict and num_weeks:
        avg_gpw = sum(total_counts_dict.values()) / len(total_counts_dict) / num_weeks
    else:
        avg_gpw = 3.5

    return {
        "weeks": week_analyses,
        "total_game_counts": total_counts_dict,
        "avg_games_per_week": round(avg_gpw, 2),
        "schedule": schedule,
    }


# ---------------------------------------------------------------------------
# Schedule-based value computation
# ---------------------------------------------------------------------------

def compute_schedule_multiplier(
    games_this_week: int,
    avg_games: float = 3.5,
    week_game_counts: list[tuple[int, float]] | None = None,
) -> float:
    """Compute a score multiplier based on game count vs league average.

    When only *games_this_week* is provided (single-week mode), the
    multiplier is a simple delta from the league average::

        multiplier = 1.0 + SCHEDULE_WEIGHT × (games − avg)

    When *week_game_counts* is provided (multi-week mode), future weeks
    are discounted by ``SCHEDULE_WEEK_DECAY`` so that this week's games
    carry more weight than next week's::

        weighted_delta = Σ decay^i × (games_i − avg_i) / Σ decay^i
        multiplier     = 1.0 + SCHEDULE_WEIGHT × weighted_delta

    Args:
        games_this_week: Game count for the current week (used in
            single-week fallback).
        avg_games: League average games per week (single-week fallback).
        week_game_counts: Optional list of ``(games, avg_games)`` tuples,
            one per upcoming week (week 0 = current).  When provided,
            *games_this_week* and *avg_games* are ignored.

    Returns:
        Schedule multiplier (centred on 1.0).
    """
    decay = config.SCHEDULE_WEEK_DECAY

    if week_game_counts and len(week_game_counts) > 1:
        total_weight = 0.0
        weighted_delta = 0.0
        for i, (games_i, avg_i) in enumerate(week_game_counts):
            w = decay ** i          # 1.0, 0.5, 0.25, …
            weighted_delta += w * (games_i - avg_i)
            total_weight += w
        if total_weight > 0:
            weighted_delta /= total_weight
        return round(1.0 + config.SCHEDULE_WEIGHT * weighted_delta, 3)

    # Single-week fallback
    delta = games_this_week - avg_games
    return round(1.0 + config.SCHEDULE_WEIGHT * delta, 3)


def get_player_weekly_value(
    z_per_game: float,
    games: int,
) -> float:
    """Projected weekly z-value = z/game × games this week."""
    return round(z_per_game * games, 2)


# ---------------------------------------------------------------------------
# Head-to-head comparisons
# ---------------------------------------------------------------------------

def compare_waiver_vs_droppable(
    waiver_df: pd.DataFrame,
    droppable_names: list[str],
    nba_stats: pd.DataFrame,
    game_counts: dict[str, int],
    top_n: int = 10,
) -> list[dict]:
    """Compare waiver targets against droppable players by weekly value.

    For each top waiver target, computes the weekly z-value for the upcoming
    week and shows the net gain vs each droppable player.

    Returns:
        List of comparison dicts.
    """
    # Build droppable player z-values
    droppable_info: list[dict] = []
    for name in droppable_names:
        norm = normalize_name(name)
        matched = False
        for _, row in nba_stats.iterrows():
            if normalize_name(str(row.get("PLAYER_NAME", ""))) == norm:
                team_abbr = normalize_team_abbr(
                    str(row.get("TEAM_ABBREVIATION", ""))
                )
                z_val = float(row.get("Z_TOTAL", 0))
                games = game_counts.get(team_abbr, 0)
                droppable_info.append({
                    "name": name,
                    "team": team_abbr,
                    "z_per_game": z_val,
                    "games": games,
                    "weekly_z": get_player_weekly_value(z_val, games),
                })
                matched = True
                break
        if not matched:
            droppable_info.append({
                "name": name,
                "team": "?",
                "z_per_game": 0.0,
                "games": 0,
                "weekly_z": 0.0,
            })

    # Build waiver target comparisons
    comparisons: list[dict] = []
    for i, (_, row) in enumerate(waiver_df.head(top_n).iterrows()):
        player = str(row.get("Player", "Unknown"))
        team = normalize_team_abbr(str(row.get("Team", "")))
        z_val = float(row.get("Z_Value", 0))
        adj_score = float(row.get("Adj_Score", 0))
        games = game_counts.get(team, 0)
        weekly_z = get_player_weekly_value(z_val, games)

        comp = {
            "rank": i + 1,
            "player": player,
            "team": team,
            "z_per_game": z_val,
            "games": games,
            "weekly_z": weekly_z,
            "adj_score": adj_score,
            "vs_droppable": [],
        }

        for dp in droppable_info:
            net_gain = round(weekly_z - dp["weekly_z"], 2)
            comp["vs_droppable"].append({
                "drop_player": dp["name"],
                "drop_games": dp["games"],
                "drop_weekly_z": dp["weekly_z"],
                "net_gain": net_gain,
            })

        comparisons.append(comp)

    return comparisons


# ---------------------------------------------------------------------------
# Display / reporting
# ---------------------------------------------------------------------------

def format_schedule_report(
    analysis: dict,
    waiver_df: pd.DataFrame | None = None,
    droppable_names: list[str] | None = None,
    nba_stats: pd.DataFrame | None = None,
) -> str:
    """Format the full schedule analysis as a readable report."""
    lines: list[str] = []

    # ── Per-week team schedule grid ──────────────────────────────────
    for week_data in analysis.get("weeks", []):
        lines.append(f"\n{'=' * 70}")
        lines.append(f"  UPCOMING SCHEDULE: {week_data['label']}")
        lines.append(f"{'=' * 70}")

        counts = week_data["game_counts"]
        dates = week_data["game_dates"]
        sorted_teams = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

        rows = []
        for team, count in sorted_teams:
            team_dates = dates.get(team, [])
            date_strs = [d.strftime("%a %m/%d") for d in team_dates]
            rows.append({
                "Team": team,
                "Games": count,
                "Dates": ", ".join(date_strs),
            })

        if rows:
            lines.append("")
            lines.append(tabulate(rows, headers="keys", tablefmt="simple"))

        avg = week_data["avg_games"]
        lines.append(
            f"\n  Average: {avg} games/team  |  "
            f"Range: {week_data['min_games']}–{week_data['max_games']}"
        )

    # ── Waiver target schedule value ─────────────────────────────────
    if waiver_df is not None and not waiver_df.empty and analysis.get("weeks"):
        first_week = analysis["weeks"][0]
        counts = first_week["game_counts"]
        avg_g = first_week["avg_games"]

        lines.append(f"\n{'=' * 70}")
        lines.append(
            f"  WAIVER TARGET SCHEDULE VALUE ({first_week['label']})"
        )
        lines.append(f"{'=' * 70}")

        target_rows = []
        for i, (_, row) in enumerate(waiver_df.head(15).iterrows()):
            player = str(row.get("Player", "Unknown"))
            team = normalize_team_abbr(str(row.get("Team", "")))
            z_val = float(row.get("Z_Value", 0))
            games = counts.get(team, 0)
            weekly_z = get_player_weekly_value(z_val, games)
            sched_mult = compute_schedule_multiplier(games, avg_g)
            target_rows.append({
                "#": i + 1,
                "Player": player[:25],
                "Team": team,
                "Games": games,
                "Z/Game": round(z_val, 2),
                "Week_Z": weekly_z,
                "Sched×": f"{sched_mult:.2f}",
            })

        if target_rows:
            lines.append("")
            lines.append(tabulate(target_rows, headers="keys", tablefmt="simple"))

    # ── Droppable player schedule ────────────────────────────────────
    if droppable_names and nba_stats is not None and analysis.get("weeks"):
        first_week = analysis["weeks"][0]
        counts = first_week["game_counts"]

        lines.append(f"\n{'=' * 70}")
        lines.append(
            f"  DROPPABLE PLAYERS SCHEDULE ({first_week['label']})"
        )
        lines.append(f"{'=' * 70}")

        drop_rows = []
        for name in droppable_names:
            norm = normalize_name(name)
            matched = False
            for _, row in nba_stats.iterrows():
                if normalize_name(str(row.get("PLAYER_NAME", ""))) == norm:
                    team = normalize_team_abbr(
                        str(row.get("TEAM_ABBREVIATION", ""))
                    )
                    z_val = float(row.get("Z_TOTAL", 0))
                    games = counts.get(team, 0)
                    weekly_z = get_player_weekly_value(z_val, games)
                    drop_rows.append({
                        "Player": name[:25],
                        "Team": team,
                        "Games": games,
                        "Z/Game": round(z_val, 2),
                        "Week_Z": weekly_z,
                    })
                    matched = True
                    break
            if not matched:
                drop_rows.append({
                    "Player": name[:25],
                    "Team": "?",
                    "Games": "?",
                    "Z/Game": "?",
                    "Week_Z": "?",
                })

        if drop_rows:
            lines.append("")
            lines.append(tabulate(drop_rows, headers="keys", tablefmt="simple"))

    # ── Net value comparison ─────────────────────────────────────────
    if (
        waiver_df is not None
        and not waiver_df.empty
        and droppable_names
        and nba_stats is not None
        and analysis.get("weeks")
    ):
        first_week = analysis["weeks"][0]
        counts = first_week["game_counts"]

        comparisons = compare_waiver_vs_droppable(
            waiver_df, droppable_names, nba_stats, counts, top_n=10,
        )

        lines.append(f"\n{'=' * 70}")
        lines.append(
            f"  NET VALUE: WAIVER TARGETS vs DROPPABLE PLAYERS"
        )
        lines.append(f"  ({first_week['label']})")
        lines.append(f"{'=' * 70}")

        comp_rows = []
        for comp in comparisons:
            for vs in comp["vs_droppable"]:
                sign = "+" if vs["net_gain"] >= 0 else ""
                comp_rows.append({
                    "#": comp["rank"],
                    "Add Player": comp["player"][:22],
                    "Add(G)": comp["games"],
                    "Add Wk_Z": comp["weekly_z"],
                    "Drop Player": vs["drop_player"][:22],
                    "Drop(G)": vs["drop_games"],
                    "Drop Wk_Z": vs["drop_weekly_z"],
                    "Net": f"{sign}{vs['net_gain']}",
                })

        if comp_rows:
            lines.append("")
            lines.append(tabulate(comp_rows, headers="keys", tablefmt="simple"))
            lines.append(
                "\n  Net = Add_Weekly_Z − Drop_Weekly_Z  "
                "(positive = upgrade)"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def run_schedule_analysis(
    waiver_df: pd.DataFrame | None = None,
    droppable_names: list[str] | None = None,
    nba_stats: pd.DataFrame | None = None,
    weeks_ahead: int | None = None,
) -> dict:
    """Run the full schedule analysis and print the report.

    Args:
        waiver_df: Recommendations DataFrame.
        droppable_names: List of droppable player names.
        nba_stats: Full NBA stats DataFrame (all players, not just available).
        weeks_ahead: Number of upcoming weeks to analyze.

    Returns:
        Schedule analysis dict from build_schedule_analysis().
    """
    schedule = fetch_nba_schedule()
    weeks = get_upcoming_weeks(weeks_ahead)
    analysis = build_schedule_analysis(schedule, weeks)

    report = format_schedule_report(
        analysis,
        waiver_df=waiver_df,
        droppable_names=droppable_names,
        nba_stats=nba_stats,
    )
    print(report)

    return analysis

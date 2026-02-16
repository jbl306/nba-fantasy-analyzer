"""NBA stats scraper using nba_api.

Fetches current season player stats, recent game logs, and player metadata
to power waiver wire recommendations. Includes availability rate computation
and recent activity checks for injury-risk-aware rankings.
"""

import time
from datetime import datetime, timedelta

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguegamelog,
    playergamelog,
    scoreboardv2,
)
from nba_api.stats.static import players as nba_players
from nba_api.stats.static import teams as nba_teams

import config


def get_all_active_players() -> list[dict]:
    """Return a list of all active NBA players with id, full_name, etc."""
    return nba_players.get_active_players()


def find_player_id(player_name: str) -> int | None:
    """Look up an NBA player's ID by name (case-insensitive partial match)."""
    matches = nba_players.find_players_by_full_name(player_name)
    if matches:
        # Prefer active players
        active = [p for p in matches if p.get("is_active")]
        return active[0]["id"] if active else matches[0]["id"]
    return None


def get_season_string() -> str:
    """Return the current NBA season string (e.g., '2025-26')."""
    today = datetime.now()
    # NBA season starts in October; if we're before October, season started last year
    if today.month >= 10:
        start_year = today.year
    else:
        start_year = today.year - 1
    end_year_short = str(start_year + 1)[-2:]
    return f"{start_year}-{end_year_short}"


def get_league_dash_player_stats(
    season: str | None = None,
    per_mode: str = "PerGame",
) -> pd.DataFrame:
    """Fetch league-wide player stats for the season.

    Args:
        season: NBA season string (e.g. '2025-26'). Defaults to current season.
        per_mode: 'PerGame', 'Totals', or 'Per36'.

    Returns:
        DataFrame with per-game (or specified mode) stats for all qualifying players.
    """
    if season is None:
        season = get_season_string()

    print(f"  Fetching league-wide player stats for {season} ({per_mode})...")
    stats = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed=per_mode,
        timeout=60,
    )
    time.sleep(0.6)  # respect rate limits
    df = stats.get_data_frames()[0]
    return df


def get_player_game_log(
    player_id: int,
    season: str | None = None,
    last_n_games: int = 0,
) -> pd.DataFrame:
    """Fetch a player's game log for the season.

    Args:
        player_id: NBA player ID.
        season: NBA season string. Defaults to current season.
        last_n_games: If > 0, only return the last N games.

    Returns:
        DataFrame with game-by-game stats.
    """
    if season is None:
        season = get_season_string()

    log = playergamelog.PlayerGameLog(
        player_id=player_id,
        season=season,
        timeout=60,
    )
    time.sleep(0.6)
    df = log.get_data_frames()[0]

    if last_n_games > 0:
        df = df.head(last_n_games)

    return df


def get_todays_games() -> pd.DataFrame:
    """Get today's NBA scoreboard."""
    board = scoreboardv2.ScoreboardV2(
        game_date=datetime.now().strftime("%Y-%m-%d"),
        timeout=60,
    )
    time.sleep(0.6)
    return board.get_data_frames()[0]


def get_recent_player_stats(days: int | None = None) -> pd.DataFrame:
    """Get per-game stats for all players over a recent window.

    Fetches the full season stats and also computes a 'recent form' score
    using the last N days of game logs for top candidates.

    Args:
        days: Number of days to look back. Defaults to config.RECENT_GAMES_WINDOW.

    Returns:
        DataFrame with season stats plus a RECENT_AVG_FANTASY_VALUE column.
    """
    if days is None:
        days = config.RECENT_GAMES_WINDOW

    season = get_season_string()
    season_stats = get_league_dash_player_stats(season=season, per_mode="PerGame")

    # Filter to players with meaningful minutes
    season_stats = season_stats[season_stats["MIN"] >= 15.0].copy()
    season_stats = season_stats[season_stats["GP"] >= 5].copy()

    return season_stats


def compute_9cat_z_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Compute z-scores for each 9-category stat and an overall value.

    For each stat category, computes how many standard deviations above/below
    the league average a player is. Turnovers are inverted (lower is better).

    Args:
        df: DataFrame with player stats (must include the stat columns).

    Returns:
        Same DataFrame with added z-score columns and a Z_TOTAL column.
    """
    df = df.copy()

    z_columns = []
    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        if stat_key not in df.columns:
            continue

        col = df[stat_key].astype(float)
        mean = col.mean()
        std = col.std()

        if std == 0:
            df[f"Z_{stat_key}"] = 0.0
        else:
            z = (col - mean) / std
            if not cat_info["higher_is_better"]:
                z = -z  # invert for turnovers
            df[f"Z_{stat_key}"] = z

        z_columns.append(f"Z_{stat_key}")

    # Overall value = sum of z-scores across all categories
    df["Z_TOTAL"] = df[z_columns].sum(axis=1)

    return df


def get_team_games_played() -> int:
    """Estimate the number of games each team has played this season.

    Uses the max GP value across all players in the league stats as a proxy
    for how many games teams have played so far.

    Returns:
        Approximate number of team games played this season.
    """
    # The max GP among any player is a good proxy for team games played
    # (teams in the NBA play roughly the same number of games at any point)
    season = get_season_string()
    try:
        stats = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            per_mode_detailed="PerGame",
            timeout=60,
        )
        time.sleep(0.6)
        df = stats.get_data_frames()[0]
        return int(df["GP"].max())
    except Exception:
        # Fallback: estimate based on date in season
        today = datetime.now()
        season_start = datetime(today.year if today.month >= 10 else today.year - 1, 10, 22)
        days_in = (today - season_start).days
        return max(1, int(days_in * 82 / 180))  # rough estimate


def compute_availability_rate(df: pd.DataFrame, team_gp: int | None = None) -> pd.DataFrame:
    """Add availability rate and health flags to a player stats DataFrame.

    Columns added:
        TEAM_GP: Number of games the team has played
        AVAIL_RATE: GP / TEAM_GP (0.0 to 1.0)
        AVAIL_FLAG: 'Healthy', 'Moderate', 'Risky', or 'Fragile'
        AVAIL_MULTIPLIER: Score discount factor (1.0 = no penalty)

    Args:
        df: Player stats DataFrame with GP column.
        team_gp: Override for team games played. If None, auto-detected.

    Returns:
        DataFrame with availability columns added.
    """
    df = df.copy()

    if team_gp is None:
        team_gp = int(df["GP"].max())  # use the max GP in the dataset as proxy

    df["TEAM_GP"] = team_gp
    df["AVAIL_RATE"] = (df["GP"] / team_gp).clip(0, 1)

    def _flag(rate: float) -> str:
        if rate >= config.AVAILABILITY_HEALTHY:
            return "Healthy"
        elif rate >= config.AVAILABILITY_MODERATE:
            return "Moderate"
        elif rate >= config.AVAILABILITY_RISKY:
            return "Risky"
        else:
            return "Fragile"

    def _multiplier(rate: float) -> float:
        if rate >= config.AVAILABILITY_HEALTHY:
            return 1.0
        elif rate >= config.AVAILABILITY_MODERATE:
            return 0.85  # 15% penalty
        elif rate >= config.AVAILABILITY_RISKY:
            return 0.65  # 35% penalty
        else:
            return 0.45  # 55% penalty

    df["AVAIL_FLAG"] = df["AVAIL_RATE"].apply(_flag)
    df["AVAIL_MULTIPLIER"] = df["AVAIL_RATE"].apply(_multiplier)

    return df


def check_recent_activity(
    player_ids: list[int],
    days: int | None = None,
) -> dict[int, dict]:
    """Check recent game activity for a list of players.

    Fetches game logs and determines if the player has been active recently.

    Args:
        player_ids: List of NBA player IDs to check.
        days: Number of days to look back. Defaults to config.INACTIVE_DAYS_THRESHOLD.

    Returns:
        Dict mapping player_id -> {
            'last_game_date': str or None,
            'days_since_last_game': int or None,
            'games_last_14d': int,
            'is_inactive': bool,
            'recent_flag': str  ('Active', 'Questionable', 'Inactive')
        }
    """
    if days is None:
        days = config.INACTIVE_DAYS_THRESHOLD

    today = datetime.now()
    season = get_season_string()
    results = {}

    for pid in player_ids:
        try:
            log = playergamelog.PlayerGameLog(
                player_id=pid,
                season=season,
                timeout=30,
            )
            time.sleep(0.6)  # rate limit
            df = log.get_data_frames()[0]

            if df.empty:
                results[pid] = {
                    "last_game_date": None,
                    "days_since_last_game": None,
                    "games_last_14d": 0,
                    "is_inactive": True,
                    "recent_flag": "Inactive",
                }
                continue

            # Parse game dates
            df["GAME_DATE_DT"] = pd.to_datetime(df["GAME_DATE"])
            last_game = df["GAME_DATE_DT"].max()
            days_since = (today - last_game).days

            # Games in the last 14 days
            cutoff = today - timedelta(days=14)
            recent_games = len(df[df["GAME_DATE_DT"] >= cutoff])

            is_inactive = days_since > days

            if days_since <= 3:
                flag = "Active"
            elif days_since <= days:
                flag = "Questionable"
            else:
                flag = "Inactive"

            results[pid] = {
                "last_game_date": last_game.strftime("%Y-%m-%d"),
                "days_since_last_game": days_since,
                "games_last_14d": recent_games,
                "is_inactive": is_inactive,
                "recent_flag": flag,
            }
        except Exception:
            results[pid] = {
                "last_game_date": None,
                "days_since_last_game": None,
                "games_last_14d": 0,
                "is_inactive": True,
                "recent_flag": "Unknown",
            }

    return results


def build_player_stats_table() -> pd.DataFrame:
    """Build a comprehensive player stats table with z-scores and availability.

    Returns:
        DataFrame sorted by total z-score value (best players first),
        with availability rate and health flags included.
    """
    print("Fetching NBA player stats...")
    stats = get_recent_player_stats()
    stats = compute_9cat_z_scores(stats)
    print("  Computing availability rates...")
    stats = compute_availability_rate(stats)
    stats = stats.sort_values("Z_TOTAL", ascending=False).reset_index(drop=True)
    return stats

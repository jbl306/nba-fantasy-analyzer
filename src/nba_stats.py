"""NBA stats scraper using nba_api.

Fetches current season player stats, recent game logs, and player metadata
to power waiver wire recommendations. Includes availability rate computation
and recent activity checks for injury-risk-aware rankings.
"""

import time
from datetime import datetime, timedelta

import pandas as pd
from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    leaguegamelog,
    playergamelog,
    scoreboardv2,
)
from nba_api.stats.static import players as nba_players
from nba_api.stats.static import teams as nba_teams

import config


# ---------------------------------------------------------------------------
# Retry helper for nba_api calls (stats.nba.com throttles datacenter IPs)
# ---------------------------------------------------------------------------

def _nba_api_call(fn, *args, retries: int = 3, base_timeout: int = 60, **kwargs):
    """Call an nba_api endpoint constructor with retry + exponential backoff.

    stats.nba.com frequently times out from cloud hosts (GitHub Actions, etc.).
    This retries with increasing timeouts (60s → 120s → 180s) and a backoff
    delay between attempts.

    Args:
        fn: The nba_api endpoint class (e.g., ``leaguedashplayerstats.LeagueDashPlayerStats``).
        *args: Positional args forwarded to the endpoint constructor.
        retries: Number of attempts before giving up.
        base_timeout: Starting timeout in seconds (doubled each retry).
        **kwargs: Keyword args forwarded to the endpoint constructor.

    Returns:
        The constructed endpoint object (call ``.get_data_frames()`` on it).
    """
    last_exc = None
    for attempt in range(1, retries + 1):
        timeout = base_timeout * attempt
        try:
            result = fn(*args, timeout=timeout, **kwargs)
            time.sleep(0.6)  # respect rate limits
            return result
        except (ReadTimeout, ReqConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                wait = 3 * attempt
                print(f"    ⚠ stats.nba.com timeout (attempt {attempt}/{retries}), "
                      f"retrying in {wait}s with {timeout * 2}s timeout...")
                time.sleep(wait)
            else:
                print(f"    ✗ stats.nba.com failed after {retries} attempts")
    raise last_exc  # type: ignore[misc]


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
    stats = _nba_api_call(
        leaguedashplayerstats.LeagueDashPlayerStats,
        season=season,
        per_mode_detailed=per_mode,
    )
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

    log = _nba_api_call(
        playergamelog.PlayerGameLog,
        player_id=player_id,
        season=season,
    )
    df = log.get_data_frames()[0]

    if last_n_games > 0:
        df = df.head(last_n_games)

    return df


def get_todays_games() -> pd.DataFrame:
    """Get today's NBA scoreboard."""
    board = _nba_api_call(
        scoreboardv2.ScoreboardV2,
        game_date=datetime.now().strftime("%Y-%m-%d"),
    )
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

    For counting stats (3PM, PTS, REB, AST, STL, BLK, TO), computes a
    standard z-score: ``(x - mean) / std``.

    For **percentage stats** (FG%, FT%), uses **volume-weighted impact**
    z-scores so that high-volume shooters get proportionally more credit.
    The impact of a player on your team's FG% depends on both accuracy
    *and* shot attempts::

        impact_i = FGA_i × (FG%_i − league_avg_FG%)
        z_FG%    = (impact_i − mean(impact)) / std(impact)

    This prevents a player shooting .650 on 2 FGA/game from outranking a
    player shooting .520 on 16 FGA/game, which better reflects real H2H
    category math where team FG% = total_FGM / total_FGA.

    Turnovers are inverted (fewer is better).

    Categories listed in ``config.PUNT_CATEGORIES`` are still computed
    (individual z-columns remain) but are **excluded** from ``Z_TOTAL``.

    Args:
        df: DataFrame with player stats (must include the stat columns).

    Returns:
        Same DataFrame with added z-score columns and a Z_TOTAL column.
    """
    df = df.copy()

    punt_names = {c.upper() for c in config.PUNT_CATEGORIES}
    z_columns: list[str] = []
    z_columns_for_total: list[str] = []

    for stat_key, cat_info in config.STAT_CATEGORIES.items():
        if stat_key not in df.columns:
            continue

        z_col = f"Z_{stat_key}"
        volume_col = cat_info.get("volume_col")

        if volume_col and volume_col in df.columns:
            # --- Volume-weighted impact z-score (FG%, FT%) ---
            pct = df[stat_key].astype(float)
            vol = df[volume_col].astype(float)
            league_avg_pct = pct.mean()

            # Impact = attempts × (player_pct − league_avg_pct)
            impact = vol * (pct - league_avg_pct)
            imp_mean = impact.mean()
            imp_std = impact.std()

            if imp_std == 0:
                df[z_col] = 0.0
            else:
                z = (impact - imp_mean) / imp_std
                if not cat_info["higher_is_better"]:
                    z = -z
                df[z_col] = z
        else:
            # --- Standard z-score (counting stats) ---
            col = df[stat_key].astype(float)
            mean = col.mean()
            std = col.std()

            if std == 0:
                df[z_col] = 0.0
            else:
                z = (col - mean) / std
                if not cat_info["higher_is_better"]:
                    z = -z
                df[z_col] = z

        z_columns.append(z_col)

        # Only include non-punted categories in Z_TOTAL
        if cat_info["name"].upper() not in punt_names:
            z_columns_for_total.append(z_col)

    # Overall value = sum of z-scores across non-punted categories
    df["Z_TOTAL"] = df[z_columns_for_total].sum(axis=1) if z_columns_for_total else 0.0

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
        stats = _nba_api_call(
            leaguedashplayerstats.LeagueDashPlayerStats,
            season=season,
            per_mode_detailed="PerGame",
        )
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
            log = _nba_api_call(
                playergamelog.PlayerGameLog,
                player_id=pid,
                season=season,
            )
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


def compute_recent_game_stats(
    player_ids: list[int],
    last_n: int | None = None,
) -> dict[int, dict]:
    """Compute per-game averages from a player's last N games.

    Returns a dict mapping player_id → {stat_col: avg_value, ...} for all
    the 9-cat stat columns plus MIN.  The caller can then z-score these
    against the league season averages to identify breakout performers.

    Args:
        player_ids: NBA player IDs to evaluate.
        last_n: Number of recent games. Defaults to config.HOT_PICKUP_RECENT_GAMES.

    Returns:
        Dict of player_id → recent per-game averages dict.
    """
    if last_n is None:
        last_n = config.HOT_PICKUP_RECENT_GAMES

    season = get_season_string()
    stat_cols = [
        "MIN", "FGM", "FGA", "FG_PCT", "FTM", "FTA", "FT_PCT",
        "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV",
    ]
    results: dict[int, dict] = {}

    for pid in player_ids:
        try:
            log = _nba_api_call(
                playergamelog.PlayerGameLog,
                player_id=pid,
                season=season,
            )
            df = log.get_data_frames()[0]

            if df.empty or len(df) < 1:
                continue

            recent = df.head(last_n)
            averages: dict[str, float] = {"games_used": len(recent)}

            for col in stat_cols:
                if col in recent.columns:
                    averages[col] = float(recent[col].mean())

            # Recompute FG% and FT% from totals (more accurate than avg of avgs)
            fgm = recent.get("FGM")
            fga = recent.get("FGA")
            if fgm is not None and fga is not None:
                total_fga = fga.sum()
                averages["FG_PCT"] = (fgm.sum() / total_fga) if total_fga > 0 else 0.0
            ftm = recent.get("FTM")
            fta = recent.get("FTA")
            if ftm is not None and fta is not None:
                total_fta = fta.sum()
                averages["FT_PCT"] = (ftm.sum() / total_fta) if total_fta > 0 else 0.0

            results[pid] = averages
        except Exception:
            pass

    return results


def compute_hot_pickup_scores(
    recent_stats: dict[int, dict],
    season_df: pd.DataFrame,
) -> dict[int, dict]:
    """Score recent performance against season-wide league averages.

    For each player with recent game stats, compute how their last-N-game
    averages compare to the league-wide *season* averages using z-scores.
    A high ``recent_z`` means the player is performing ABOVE their season
    norm — a breakout signal.

    Also computes a ``z_delta`` = recent_z − season_z for each player,
    which captures improvement rather than just raw talent.

    Args:
        recent_stats: From :func:`compute_recent_game_stats`.
        season_df: Full season DataFrame with z-scores (from build_player_stats_table).

    Returns:
        Dict of player_id → {recent_z_total, season_z_total, z_delta, is_hot}.
    """
    # Compute league-wide season means and stds for z-scoring recent stats
    counting_cols = ["FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]
    league_means: dict[str, float] = {}
    league_stds: dict[str, float] = {}

    for col in counting_cols:
        if col in season_df.columns:
            league_means[col] = float(season_df[col].mean())
            league_stds[col] = float(season_df[col].std())

    # Volume-weighted means for FG% and FT%
    for pct_col, vol_col in [("FG_PCT", "FGA"), ("FT_PCT", "FTA")]:
        if pct_col in season_df.columns and vol_col in season_df.columns:
            pct = season_df[pct_col].astype(float)
            vol = season_df[vol_col].astype(float)
            avg_pct = pct.mean()
            impact = vol * (pct - avg_pct)
            league_means[f"{pct_col}_impact_mean"] = float(impact.mean())
            league_stds[f"{pct_col}_impact_std"] = float(impact.std())
            league_means[f"{pct_col}_avg"] = float(avg_pct)

    punt_names = {c.upper() for c in config.PUNT_CATEGORIES}
    results: dict[int, dict] = {}

    # Build a quick PLAYER_ID → season Z_TOTAL lookup
    season_z_lookup: dict[int, float] = {}
    if "PLAYER_ID" in season_df.columns and "Z_TOTAL" in season_df.columns:
        for _, row in season_df.iterrows():
            season_z_lookup[int(row["PLAYER_ID"])] = float(row["Z_TOTAL"])

    for pid, stats in recent_stats.items():
        z_sum = 0.0
        n_cats = 0

        for stat_key, cat_info in config.STAT_CATEGORIES.items():
            cat_name_upper = cat_info["name"].upper()
            if cat_name_upper in punt_names:
                continue

            vol_col = cat_info.get("volume_col")

            if vol_col and stat_key in stats:
                # Volume-weighted impact z-score for %-based stats
                pct_val = stats.get(stat_key, 0)
                vol_val = stats.get(vol_col, 0)
                avg_pct = league_means.get(f"{stat_key}_avg", 0)
                impact = vol_val * (pct_val - avg_pct)
                imp_mean = league_means.get(f"{stat_key}_impact_mean", 0)
                imp_std = league_stds.get(f"{stat_key}_impact_std", 1)
                if imp_std > 0:
                    z = (impact - imp_mean) / imp_std
                    if not cat_info["higher_is_better"]:
                        z = -z
                    z_sum += z
                    n_cats += 1
            elif stat_key in stats:
                # Standard z-score for counting stats
                val = stats[stat_key]
                mean = league_means.get(stat_key, 0)
                std = league_stds.get(stat_key, 1)
                if std > 0:
                    z = (val - mean) / std
                    if not cat_info["higher_is_better"]:
                        z = -z
                    z_sum += z
                    n_cats += 1

        season_z = season_z_lookup.get(pid, 0.0)
        z_delta = z_sum - season_z

        results[pid] = {
            "recent_z_total": round(z_sum, 2),
            "season_z_total": round(season_z, 2),
            "z_delta": round(z_delta, 2),
            "games_used": stats.get("games_used", 0),
            "is_hot": z_delta >= 1.0,  # performing 1+ z-score above season avg
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

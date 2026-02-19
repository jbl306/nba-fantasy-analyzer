"""Player stats via the Yahoo Fantasy API.

All stat data comes through the authenticated Yahoo Fantasy API — no
scraping needed. ESPN public APIs provide boxscores, injuries, and news.

Public surface (used by waiver_advisor.py):
    build_player_stats_table(query)
    check_recent_activity(player_keys, query)
    compute_recent_game_stats(player_keys, query)
    compute_hot_pickup_scores(recent_stats, season_df)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from yfpy.query import YahooFantasySportsQuery

import config


# ---------------------------------------------------------------------------
# Yahoo stat-id → DataFrame column name mapping
# ---------------------------------------------------------------------------
# Full mapping (limit_to_league_stats=False).  Stat-ids come from
# query.get_game_stat_categories_by_game_id().
_YAHOO_STAT_ID_TO_COL: dict[int, str] = {
    0:  "GP",
    1:  "GS",
    2:  "MIN",
    3:  "FGA",
    4:  "FGM",
    5:  "FG_PCT",
    6:  "FTA",
    7:  "FTM",
    8:  "FT_PCT",
    9:  "FG3A",
    10: "FG3M",
    11: "FG3_PCT",
    12: "PTS",
    13: "OREB",
    14: "DREB",
    15: "REB",
    16: "AST",
    17: "STL",
    18: "BLK",
    19: "TOV",
    20: "A_T",
    21: "PF",
    22: "DISQ",
    23: "TECH",
    24: "EJCT",
    25: "FF",
    26: "MPG",
    27: "DD",
    28: "TD",
}

# Yahoo stat-ids that are season totals (not rates/percentages).
# These need to be divided by GP to get per-game values.
_COUNTING_STAT_IDS: frozenset[int] = frozenset([
    2, 3, 4, 6, 7, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 21,
])

# Stat-ids that are already per-game rates/percentages — leave them as-is.
_RATE_STAT_IDS: frozenset[int] = frozenset([5, 8, 11, 20, 26])

# Only the 9-cat + volume columns we need for the DataFrame.
_REQUIRED_COLS: list[str] = [
    "GP", "MIN", "FGA", "FGM", "FTA", "FTM",
    "FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV",
]

# Yahoo NBA team abbreviation mapping.  Yahoo sometimes uses abbreviations
# that differ from the NBA-official ones.
_YAHOO_TEAM_ABBR_MAP: dict[str, str] = {
    "GS": "GSW", "NY": "NYK", "NO": "NOP",
    "SA": "SAS", "Uta": "UTA",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_team_abbr(abbr: str) -> str:
    """Normalise a Yahoo team abbreviation to match schedule data."""
    upper = abbr.upper().strip()
    return _YAHOO_TEAM_ABBR_MAP.get(upper, upper)


def _parse_player_stats(player_obj, per_game: bool = True) -> dict[str, Any] | None:
    """Extract stat values from a yfpy Player object.

    Args:
        player_obj: A yfpy Player (may be wrapped in an outer container).
        per_game: If True, convert counting stats to per-game by dividing by GP.

    Returns:
        Dict with column names as keys, or None if no stats available.
    """
    player = player_obj.player if hasattr(player_obj, "player") else player_obj

    stats_obj = getattr(player, "player_stats", None)
    if not stats_obj:
        return None
    stat_list = getattr(stats_obj, "stats", [])
    if not stat_list:
        return None

    raw: dict[int, float] = {}
    for s in stat_list:
        st = s.stat if hasattr(s, "stat") else s
        sid = getattr(st, "stat_id", None)
        val = getattr(st, "value", None)
        if sid is not None and val is not None:
            try:
                raw[int(sid)] = float(val)
            except (ValueError, TypeError):
                pass

    gp = raw.get(0, 0)
    if gp < 1:
        return None  # no games played — skip

    result: dict[str, Any] = {}
    for sid, col in _YAHOO_STAT_ID_TO_COL.items():
        if col not in _REQUIRED_COLS:
            continue
        val = raw.get(sid)
        if val is None:
            result[col] = 0.0
            continue

        if per_game and sid in _COUNTING_STAT_IDS and gp > 0:
            result[col] = val / gp
        else:
            result[col] = val

    # Ensure GP is always the raw total (not divided)
    result["GP"] = int(gp)

    return result


def _extract_player_meta(player_obj) -> dict[str, Any]:
    """Pull identifying metadata from a yfpy Player object."""
    player = player_obj.player if hasattr(player_obj, "player") else player_obj

    name_obj = getattr(player, "name", None)
    full_name = "Unknown"
    if name_obj and hasattr(name_obj, "full"):
        full_name = name_obj.full
    elif name_obj and hasattr(name_obj, "first"):
        full_name = f"{name_obj.first} {getattr(name_obj, 'last', '')}"

    return {
        "PLAYER_NAME": full_name,
        "PLAYER_KEY": getattr(player, "player_key", ""),
        "PLAYER_ID": getattr(player, "player_id", 0),
        "TEAM_ABBREVIATION": _normalise_team_abbr(
            str(getattr(player, "editorial_team_abbr", "") or "")
        ),
        "POSITION": str(getattr(player, "display_position", "") or ""),
        "STATUS": str(getattr(player, "status", "") or ""),
        "HAS_RECENT_NOTES": bool(getattr(player, "has_recent_player_notes", 0)),
        "INJURY_NOTE": str(getattr(player, "injury_note", "") or ""),
    }


def _batch_fetch_full_stats(
    player_keys: list[str],
    query: YahooFantasySportsQuery,
    batch_size: int = 25,
    per_game: bool = True,
) -> list[dict[str, Any]]:
    """Fetch full stats (incl. GP) for a list of player_keys via the game-level endpoint.

    Uses ``fantasy/v2/players;player_keys=.../stats`` (no league scoping)
    so that ALL stat categories are returned — not just the league's
    scoring categories.

    Args:
        player_keys: List of Yahoo player keys (e.g. ``["466.p.5352", ...]``).
        query: Authenticated yfpy query instance.
        batch_size: Max keys per request (Yahoo limit ~25).
        per_game: Whether to convert counting stats to per-game.

    Returns:
        List of dicts, each containing player metadata + per-game stat columns.
    """
    results: list[dict[str, Any]] = []

    for i in range(0, len(player_keys), batch_size):
        batch_keys = player_keys[i : i + batch_size]
        keys_param = ",".join(batch_keys)
        try:
            data = query.query(
                f"https://fantasysports.yahooapis.com/fantasy/v2/players;"
                f"player_keys={keys_param}/stats",
                ["players"],
            )
        except Exception as exc:
            print(f"    Warning: batch stat fetch failed ({len(batch_keys)} players): {exc}")
            continue

        if not isinstance(data, list):
            data = [data]

        for item in data:
            meta = _extract_player_meta(item)
            stats = _parse_player_stats(item, per_game=per_game)
            if stats and meta.get("PLAYER_KEY"):
                row = {**meta, **stats}
                results.append(row)

        time.sleep(0.3)  # gentle throttle

    return results


# ---------------------------------------------------------------------------
# Public API — drop-in replacements for nba_stats.py
# ---------------------------------------------------------------------------

def build_player_stats_table(query: YahooFantasySportsQuery) -> pd.DataFrame:
    """Build a comprehensive player stats table with z-scores and availability.

    Fetches ALL players registered in the Yahoo league (rostered + free agents),
    retrieves their full season stats from the game-level API (including GP),
    converts to per-game averages, computes 9-category z-scores, and adds
    availability/health flags.

    Args:
        query: Authenticated yfpy query instance.

    Returns:
        DataFrame sorted by Z_TOTAL (best players first) with columns:
            PLAYER_KEY, PLAYER_ID, PLAYER_NAME, TEAM_ABBREVIATION, POSITION,
            GP, MIN, FGA, FGM, FTA, FTM,
            FG_PCT, FT_PCT, FG3M, PTS, REB, AST, STL, BLK, TOV,
            Z_FG_PCT, ..., Z_TOV, Z_TOTAL,
            TEAM_GP, AVAIL_RATE, AVAIL_FLAG, AVAIL_MULTIPLIER.
    """
    print("Fetching NBA player stats from Yahoo Fantasy API...")

    # Phase 1: Fetch ALL league players to collect player_keys.
    # get_league_players() handles internal pagination (25/request).
    # yfpy logs an ERROR when pagination ends (normal behavior) — suppress
    # that misleading noise so only real errors surface.
    _yfpy_logger = logging.getLogger("yfpy.query")
    try:
        _prev_level = _yfpy_logger.level
        _yfpy_logger.setLevel(logging.CRITICAL)
        all_players = query.get_league_players()
    except Exception as exc:
        print(f"  ERROR fetching league players: {exc}")
        all_players = []
    finally:
        _yfpy_logger.setLevel(_prev_level)

    print(f"  Found {len(all_players)} players in league database")

    # Collect player keys and notes flags from league-level data
    player_keys: list[str] = []
    notes_lookup: dict[str, bool] = {}  # player_key → has_recent_notes
    for p_obj in all_players:
        player = p_obj.player if hasattr(p_obj, "player") else p_obj
        pk = getattr(player, "player_key", None)
        if pk:
            pk_str = str(pk)
            player_keys.append(pk_str)
            if getattr(player, "has_recent_player_notes", 0):
                notes_lookup[pk_str] = True

    if not player_keys:
        print("  ERROR: No player keys found — cannot build stats table")
        return pd.DataFrame()

    # Phase 2: Batch-fetch full stats (including GP) via game-level endpoint
    print(f"  Fetching full season stats for {len(player_keys)} players...")
    rows = _batch_fetch_full_stats(player_keys, query, per_game=True)
    print(f"  Got stats for {len(rows)} players with games played")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Merge Yahoo player-notes flags from Phase 1 (league-level data)
    if "PLAYER_KEY" in df.columns and notes_lookup:
        df["HAS_RECENT_NOTES"] = df["PLAYER_KEY"].map(
            lambda pk: notes_lookup.get(str(pk), False)
        )
    elif "HAS_RECENT_NOTES" not in df.columns:
        df["HAS_RECENT_NOTES"] = False

    # Filter to meaningful players (≥ 5 GP and ≥ 15 MIN per game)
    df = df[df["GP"] >= 5].copy()
    df = df[df["MIN"] >= 15.0].copy()
    print(f"  {len(df)} players after filtering (≥5 GP, ≥15 MIN)")

    # Phase 3: Compute 9-category z-scores
    df = compute_9cat_z_scores(df)

    # Phase 4: Compute availability rate
    df = compute_availability_rate(df)

    df = df.sort_values("Z_TOTAL", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Z-score computation
# ---------------------------------------------------------------------------

def compute_9cat_z_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Compute z-scores for each 9-category stat and an overall value.

    For counting stats, uses standard z-scores.  For percentage stats
    (FG%, FT%), uses volume-weighted impact z-scores so high-volume
    shooters get proportional credit.

    Categories listed in ``config.PUNT_CATEGORIES`` are excluded from
    ``Z_TOTAL`` but their individual z-columns are still computed.
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
            # Volume-weighted impact z-score (FG%, FT%)
            pct = df[stat_key].astype(float)
            vol = df[volume_col].astype(float)
            league_avg_pct = pct.mean()

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
            # Standard z-score (counting stats)
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

        if cat_info["name"].upper() not in punt_names:
            z_columns_for_total.append(z_col)

    df["Z_TOTAL"] = df[z_columns_for_total].sum(axis=1) if z_columns_for_total else 0.0
    return df


# ---------------------------------------------------------------------------
# Availability rate computation
# ---------------------------------------------------------------------------

def compute_availability_rate(df: pd.DataFrame, team_gp: int | None = None) -> pd.DataFrame:
    """Add availability rate and health flags to a player stats DataFrame.

    Columns added: TEAM_GP, AVAIL_RATE, AVAIL_FLAG, AVAIL_MULTIPLIER.
    """
    df = df.copy()

    if team_gp is None:
        team_gp = int(df["GP"].max())

    df["TEAM_GP"] = team_gp
    df["AVAIL_RATE"] = (df["GP"] / team_gp).clip(0, 1)

    def _flag(rate: float) -> str:
        if rate >= config.AVAILABILITY_HEALTHY:
            return "Healthy"
        elif rate >= config.AVAILABILITY_MODERATE:
            return "Moderate"
        elif rate >= config.AVAILABILITY_RISKY:
            return "Risky"
        return "Fragile"

    def _multiplier(rate: float) -> float:
        if rate >= config.AVAILABILITY_HEALTHY:
            return 1.0
        elif rate >= config.AVAILABILITY_MODERATE:
            return 0.85
        elif rate >= config.AVAILABILITY_RISKY:
            return 0.65
        return 0.45

    df["AVAIL_FLAG"] = df["AVAIL_RATE"].apply(_flag)
    df["AVAIL_MULTIPLIER"] = df["AVAIL_RATE"].apply(_multiplier)
    return df


# ---------------------------------------------------------------------------
# Recent activity check (DataFrame-based — no extra API calls)
# ---------------------------------------------------------------------------

def check_recent_activity(
    player_keys: list[str],
    query: YahooFantasySportsQuery,
    stats_df: pd.DataFrame | None = None,
    days: int | None = None,
) -> dict[str, dict]:
    """Estimate recent activity from season stats already in the DataFrame.

    Instead of making per-date API calls (expensive and rate-limited), this
    uses the availability rate (GP / TEAM_GP) and player status from the
    DataFrame to estimate whether a player is active.

    Heuristic:
    - AVAIL_RATE >= 0.85 and STATUS is empty → "Active"
    - AVAIL_RATE 0.60-0.85 or STATUS is DTD/GTD → "Questionable"
    - AVAIL_RATE < 0.60 or STATUS is INJ/O/SUSP → "Inactive"

    Args:
        player_keys: Yahoo player keys to check.
        query: Authenticated yfpy query instance (unused — kept for API compat).
        stats_df: Optional DataFrame with PLAYER_KEY, GP, AVAIL_RATE, STATUS.
            If None, returns basic results with limited accuracy.
        days: Number of days threshold (defaults to config.INACTIVE_DAYS_THRESHOLD).

    Returns:
        Dict mapping player_key → {
            last_game_date, days_since_last_game, games_last_14d,
            is_inactive, recent_flag
        }.
    """
    if days is None:
        days = config.INACTIVE_DAYS_THRESHOLD

    results: dict[str, dict] = {}

    # Build lookup from DataFrame if provided
    df_lookup: dict[str, dict] = {}
    if stats_df is not None and not stats_df.empty:
        for _, row in stats_df.iterrows():
            pk = str(row.get("PLAYER_KEY", ""))
            if pk:
                df_lookup[pk] = {
                    "gp": int(row.get("GP", 0)),
                    "avail_rate": float(row.get("AVAIL_RATE", 0)),
                    "status": str(row.get("STATUS", "") or ""),
                    "avail_flag": str(row.get("AVAIL_FLAG", "Unknown")),
                }

    for pk in player_keys:
        info = df_lookup.get(pk, {})
        gp = info.get("gp", 0)
        avail_rate = info.get("avail_rate", 0)
        status = info.get("status", "").upper()

        # Estimate games in last 14 days from GP and availability rate
        # Rough: teams play ~4 games per week → ~8 in 14 days
        games_14d = int(avail_rate * 8) if avail_rate > 0 else 0

        # Determine activity flag
        injury_statuses = {"INJ", "O", "SUSP", "NA", "OUT"}
        questionable_statuses = {"DTD", "GTD"}

        if status in injury_statuses:
            flag = "Inactive"
            is_inactive = True
            days_since = days + 1  # unknown but likely > threshold
        elif status in questionable_statuses:
            flag = "Questionable"
            is_inactive = False
            days_since = 3
        elif avail_rate >= config.AVAILABILITY_HEALTHY:
            flag = "Active"
            is_inactive = False
            days_since = 1  # recently played
        elif avail_rate >= config.AVAILABILITY_MODERATE:
            flag = "Questionable"
            is_inactive = False
            days_since = 5
        elif avail_rate >= config.AVAILABILITY_RISKY:
            flag = "Questionable"
            is_inactive = False
            days_since = 7
        else:
            flag = "Inactive"
            is_inactive = True
            days_since = days + 1

        results[pk] = {
            "last_game_date": None,  # unknown without per-date API calls
            "days_since_last_game": days_since,
            "games_last_14d": games_14d,
            "is_inactive": is_inactive,
            "recent_flag": flag,
        }

    return results


# ---------------------------------------------------------------------------
# Recent game stats for hot-pickup analysis
# ---------------------------------------------------------------------------

def compute_recent_game_stats(
    player_keys: list[str],
    query: YahooFantasySportsQuery,
    last_n: int | None = None,
) -> dict[str, dict]:
    """Compute per-game averages from a player's last N games via Yahoo date-stats.

    Scans recent dates, collects game-day stat lines, and averages the most
    recent ``last_n`` games.

    Args:
        player_keys: Yahoo player keys to evaluate.
        query: Authenticated yfpy query instance.
        last_n: Number of recent games. Defaults to config.HOT_PICKUP_RECENT_GAMES.

    Returns:
        Dict of player_key → {stat_col: avg_value, ..., games_used: int}.
    """
    if last_n is None:
        last_n = config.HOT_PICKUP_RECENT_GAMES

    today = datetime.now()
    # Scan up to 21 days back to find enough games
    max_lookback = 21
    dates = [(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(max_lookback)]

    stat_cols = [
        "MIN", "FGM", "FGA", "FG_PCT", "FTM", "FTA", "FT_PCT",
        "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV",
    ]
    # Stat-ids for the columns we care about (for date-level stats which are
    # league-scoped and use the league's stat_ids only).
    _DATE_SID_TO_COL: dict[int, str] = {
        5: "FG_PCT", 8: "FT_PCT", 10: "FG3M", 12: "PTS",
        15: "REB", 16: "AST", 17: "STL", 18: "BLK", 19: "TOV",
    }

    results: dict[str, dict] = {}

    for pk in player_keys:
        game_lines: list[dict[str, float]] = []

        for date_str in dates:
            if len(game_lines) >= last_n:
                break
            try:
                data = query.get_player_stats_by_date(pk, chosen_date=date_str)
                ps = getattr(data, "player_stats", None)
                stat_list = getattr(ps, "stats", []) if ps else []

                line: dict[str, float] = {}
                for s in stat_list:
                    st = s.stat if hasattr(s, "stat") else s
                    sid = getattr(st, "stat_id", None)
                    val = float(getattr(st, "value", 0) or 0)
                    if sid is not None and int(sid) in _DATE_SID_TO_COL:
                        line[_DATE_SID_TO_COL[int(sid)]] = val

                # Did the player actually play?  Check PTS or any counting stat > 0.
                pts = line.get("PTS", 0)
                reb = line.get("REB", 0)
                ast = line.get("AST", 0)
                if pts > 0 or reb > 0 or ast > 0:
                    game_lines.append(line)

            except Exception:
                pass

            time.sleep(0.1)

        if not game_lines:
            continue

        # Compute averages
        averages: dict[str, float] = {"games_used": len(game_lines)}
        for col in stat_cols:
            vals = [g.get(col, 0) for g in game_lines]
            if vals:
                averages[col] = sum(vals) / len(vals)

        # Recompute FG%/FT% from totals if we have the counting stats
        total_fga = sum(g.get("FGA", 0) for g in game_lines)
        total_fgm = sum(g.get("FGM", 0) for g in game_lines)
        if total_fga > 0:
            averages["FG_PCT"] = total_fgm / total_fga

        total_fta = sum(g.get("FTA", 0) for g in game_lines)
        total_ftm = sum(g.get("FTM", 0) for g in game_lines)
        if total_fta > 0:
            averages["FT_PCT"] = total_ftm / total_fta

        results[pk] = averages

    return results


# ---------------------------------------------------------------------------
# Hot-pickup scoring (works with both Yahoo per-date stats and ESPN boxscores,
# keyed by player_key instead of player_id)
# ---------------------------------------------------------------------------

def compute_hot_pickup_scores(
    recent_stats: dict[str, dict],
    season_df: pd.DataFrame,
) -> dict[str, dict]:
    """Score recent performance against season-wide league averages.

    For each player with recent game stats, compute how their last-N-game
    averages compare to the league-wide season averages.  A high ``z_delta``
    means the player is performing above their season norm.

    Args:
        recent_stats: From :func:`compute_recent_game_stats` (keyed by player_key).
        season_df: Full season DataFrame with z-scores.

    Returns:
        Dict of player_key → {recent_z_total, season_z_total, z_delta, is_hot, games_used}.
    """
    counting_cols = ["FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV"]
    league_means: dict[str, float] = {}
    league_stds: dict[str, float] = {}

    for col in counting_cols:
        if col in season_df.columns:
            league_means[col] = float(season_df[col].mean())
            league_stds[col] = float(season_df[col].std())

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

    # Build player_key → season Z_TOTAL lookup
    season_z_lookup: dict[str, float] = {}
    if "PLAYER_KEY" in season_df.columns and "Z_TOTAL" in season_df.columns:
        for _, row in season_df.iterrows():
            season_z_lookup[str(row["PLAYER_KEY"])] = float(row["Z_TOTAL"])

    results: dict[str, dict] = {}

    for pk, stats in recent_stats.items():
        z_sum = 0.0
        n_cats = 0

        for stat_key, cat_info in config.STAT_CATEGORIES.items():
            cat_name_upper = cat_info["name"].upper()
            if cat_name_upper in punt_names:
                continue

            vol_col = cat_info.get("volume_col")

            if vol_col and stat_key in stats:
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
                val = stats[stat_key]
                mean = league_means.get(stat_key, 0)
                std = league_stds.get(stat_key, 1)
                if std > 0:
                    z = (val - mean) / std
                    if not cat_info["higher_is_better"]:
                        z = -z
                    z_sum += z
                    n_cats += 1

        season_z = season_z_lookup.get(pk, 0.0)
        z_delta = z_sum - season_z

        results[pk] = {
            "recent_z_total": round(z_sum, 2),
            "season_z_total": round(season_z, 2),
            "z_delta": round(z_delta, 2),
            "games_used": stats.get("games_used", 0),
            "is_hot": z_delta >= 1.0,
        }

    return results

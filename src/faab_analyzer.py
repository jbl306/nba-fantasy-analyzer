"""FAAB bid analyzer — historical bid analysis and smart bid suggestions.

Fetches all league transactions from Yahoo Fantasy, extracts FAAB bid data,
and builds a statistical model of bidding behavior to suggest optimal bids.

Key concepts:
  - Player quality tiers based on % rostered / Adj_Score
  - Bid distribution analysis (median, P25, P75, max) per tier
  - Suggested bid = function of player quality + league bidding patterns
  - Supports viewing your remaining FAAB budget
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

import pandas as pd
from tabulate import tabulate

import config
from src.yahoo_fantasy import (
    create_yahoo_query,
    extract_player_details,
    normalize_name,
)


# ---------------------------------------------------------------------------
# Quality tiers for bucketing players
# ---------------------------------------------------------------------------

# *Fallback* Adj_Score thresholds when no waiver-pool data is available.
# When a recommendations DataFrame is provided, percentile-based thresholds
# computed from the **current** waiver pool replace these.  This makes tiers
# adapt to league depth (shallow 8-team vs. deep 14-team leagues).
DEFAULT_TIER_THRESHOLDS: list[tuple[str, float | None]] = [
    ("Elite",    6.0),   # Adj_Score >= 6.0
    ("Strong",   4.0),   # 4.0 - 5.99
    ("Solid",    2.5),   # 2.5 - 3.99
    ("Streamer", 1.0),   # 1.0 - 2.49
    ("Dart",     None),  # < 1.0
]

# Kept for backward compatibility — code that references TIER_THRESHOLDS
# (e.g. display ordering) continues to work.
TIER_THRESHOLDS = DEFAULT_TIER_THRESHOLDS

# Percentile boundaries used to compute league-relative tiers.
# These map to the *available waiver pool's* Adj_Score distribution.
_TIER_PERCENTILES: list[tuple[str, float]] = [
    ("Elite",    90),   # Top 10%
    ("Strong",   70),   # 70th–90th percentile
    ("Solid",    40),   # 40th–70th percentile
    ("Streamer", 15),   # 15th–40th percentile
    # Below 15th → "Dart"
]

# Minimum absolute Adj_Score floors per tier.  The percentile approach
# adapts to league depth, but without floors a shallow waiver pool can
# inflate labels (e.g. a 0.48 Adj_Score player being called "Elite").
# Each tier threshold is the MAX of the percentile-derived value and
# its floor, so tier labels always carry meaningful absolute weight.
_TIER_MIN_FLOORS: dict[str, float] = {
    "Elite":    4.0,
    "Strong":   2.5,
    "Solid":    1.5,
    "Streamer": 0.5,
}


def compute_relative_tiers(rec_df: pd.DataFrame) -> list[tuple[str, float | None]]:
    """Compute tier thresholds from the current waiver pool's Adj_Score.

    Uses percentile boundaries so tier labels reflect the league's actual
    talent distribution rather than hard-coded score cutoffs.  Each
    percentile-derived threshold is clamped to a minimum absolute floor
    so that tier labels remain meaningful when the pool is weak.

    Args:
        rec_df: Recommendations DataFrame with an ``Adj_Score`` column.

    Returns:
        Tier thresholds list in the same format as ``DEFAULT_TIER_THRESHOLDS``.
    """
    if rec_df is None or rec_df.empty or "Adj_Score" not in rec_df.columns:
        return list(DEFAULT_TIER_THRESHOLDS)

    scores = rec_df["Adj_Score"].dropna().astype(float)
    if len(scores) < 10:
        return list(DEFAULT_TIER_THRESHOLDS)

    import numpy as np
    thresholds: list[tuple[str, float | None]] = []
    for tier_name, pct in _TIER_PERCENTILES:
        pct_value = round(float(np.percentile(scores, pct)), 2)
        floor = _TIER_MIN_FLOORS.get(tier_name, 0.0)
        thresholds.append((tier_name, max(pct_value, floor)))
    thresholds.append(("Dart", None))
    return thresholds


def score_to_tier(
    adj_score: float,
    tier_thresholds: list[tuple[str, float | None]] | None = None,
) -> str:
    """Map an Adj_Score to a quality tier label.

    Args:
        adj_score: The player's adjusted score.
        tier_thresholds: Custom tier thresholds (from
            :func:`compute_relative_tiers`).  Falls back to
            ``DEFAULT_TIER_THRESHOLDS`` when ``None``.
    """
    if tier_thresholds is None:
        tier_thresholds = DEFAULT_TIER_THRESHOLDS
    for tier_name, threshold in tier_thresholds:
        if threshold is not None and adj_score >= threshold:
            return tier_name
    return "Dart"


# ---------------------------------------------------------------------------
# Fetch and parse historical transactions
# ---------------------------------------------------------------------------

def fetch_league_transactions(query) -> list[dict[str, Any]]:
    """Fetch all league transactions from Yahoo and extract FAAB bid data.

    Returns a list of dicts, each representing one add/drop transaction
    with FAAB bid information:
      {
        "transaction_id": str,
        "timestamp": str,
        "type": "add" | "add/drop",
        "faab_bid": int,
        "add_player_name": str,
        "add_player_key": str,
        "drop_player_name": str | None,
        "drop_player_key": str | None,
        "team_name": str,
        "team_key": str,
        "status": str,
      }
    """
    raw_transactions = query.get_league_transactions()
    parsed = []

    for txn_obj in raw_transactions:
        txn = txn_obj
        if hasattr(txn_obj, "transaction"):
            txn = txn_obj.transaction

        # Extract transaction-level fields
        txn_type = _get_attr(txn, "type", "")
        status = _get_attr(txn, "status", "")
        txn_id = _get_attr(txn, "transaction_id", "")
        timestamp = _get_attr(txn, "timestamp", "")

        # Only care about add or add/drop transactions
        if txn_type not in ("add", "add/drop"):
            continue

        # FAAB bid — may be int, str, or missing
        faab_bid = _get_faab_bid(txn)
        if faab_bid is None:
            # Yahoo didn't return a FAAB amount for this transaction.
            # This typically means it was a $0 free-agent pickup, but can
            # also occur when the league doesn't use FAAB.  We record it as
            # $0 so the free-pickup count stays accurate; downstream code
            # separates free ($0) from paid (>$0) bids.
            faab_bid = 0

        # Parse player data
        add_player_name = None
        add_player_key = None
        drop_player_name = None
        drop_player_key = None
        team_name = ""
        team_key = ""

        players = _get_attr(txn, "players", [])
        if not players:
            players = _get_attr(txn, "player", [])
        if isinstance(players, dict):
            players = [players]

        for player_entry in players:
            player_data = player_entry
            if hasattr(player_entry, "player"):
                player_data = player_entry.player
            if isinstance(player_entry, dict) and "player" in player_entry:
                player_data = player_entry["player"]

            # Get player name
            p_name = _extract_name(player_data)
            p_key = _get_attr(player_data, "player_key", "")

            # Get transaction_data to determine add vs drop
            td = _get_attr(player_data, "transaction_data", None)
            if td is None and isinstance(player_data, dict):
                td = player_data.get("transaction_data", None)

            if td:
                td_type = _get_attr(td, "type", "")
                if isinstance(td, dict):
                    td_type = td.get("type", "")

                if td_type == "add":
                    add_player_name = p_name
                    add_player_key = str(p_key)
                    # Get destination team info
                    team_key = _get_attr(td, "destination_team_key", "")
                    team_name = _get_attr(td, "destination_team_name", "")
                    if isinstance(td, dict):
                        team_key = td.get("destination_team_key", team_key)
                        team_name = td.get("destination_team_name", team_name)
                elif td_type == "drop":
                    drop_player_name = p_name
                    drop_player_key = str(p_key)

        if add_player_name:
            parsed.append({
                "transaction_id": str(txn_id),
                "timestamp": str(timestamp),
                "type": str(txn_type),
                "faab_bid": faab_bid,
                "add_player_name": add_player_name,
                "add_player_key": add_player_key or "",
                "drop_player_name": drop_player_name,
                "drop_player_key": drop_player_key or "",
                "team_name": str(team_name),
                "team_key": str(team_key),
                "status": str(status),
            })

    return parsed


def _get_attr(obj, attr: str, default=None):
    """Safely get an attribute from an object or dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _get_faab_bid(txn) -> int | None:
    """Extract FAAB bid from a transaction object."""
    bid = _get_attr(txn, "faab_bid", None)
    if bid is not None:
        try:
            return int(bid)
        except (ValueError, TypeError):
            return None
    return None


def _extract_name(player_data) -> str:
    """Extract player name from various yfpy player object shapes."""
    # Standard yfpy Player object
    name_obj = _get_attr(player_data, "name", None)
    if name_obj:
        full = _get_attr(name_obj, "full", None)
        if full:
            return str(full)
        first = _get_attr(name_obj, "first", "")
        last = _get_attr(name_obj, "last", "")
        if first or last:
            return f"{first} {last}".strip()

    # Dict with nested name
    if isinstance(player_data, dict):
        name_dict = player_data.get("name", {})
        if isinstance(name_dict, dict):
            full = name_dict.get("full", "")
            if full:
                return str(full)

    return "Unknown"


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------

def _classify_bids(
    faab_bids: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], float]:
    """Classify bids into standard and premium using IQR outlier detection.

    Premium bids are statistical outliers — typically returning star players
    (e.g., Paul George, Jayson Tatum) who command disproportionately high
    bids when they become available after extended injury absences. These are
    separated so they don't inflate the statistics used for normal waiver bid
    suggestions.

    Uses the IQR method: bids above Q3 + 1.5×IQR are flagged as outliers.
    A minimum floor (PREMIUM_BID_FLOOR) prevents false positives in pools
    with uniformly low bids.

    Returns:
        (standard_bids, premium_bids, outlier_threshold)
    """
    if not faab_bids:
        return [], [], 0.0

    amounts = [t["faab_bid"] for t in faab_bids]

    if len(amounts) < 4:
        # Not enough data for IQR — treat all as standard
        return list(faab_bids), [], 0.0

    sorted_amounts = sorted(amounts)
    n = len(sorted_amounts)
    q1 = sorted_amounts[n // 4]
    q3 = sorted_amounts[3 * n // 4]
    iqr = q3 - q1

    # IQR upper fence
    upper_fence = q3 + config.OUTLIER_IQR_FACTOR * iqr

    # Ensure minimum floor for premium classification
    threshold = max(upper_fence, config.PREMIUM_BID_FLOOR)

    standard = [t for t in faab_bids if t["faab_bid"] < threshold]
    premium = [t for t in faab_bids if t["faab_bid"] >= threshold]

    return standard, premium, threshold


# ---------------------------------------------------------------------------
# Bid distribution analysis
# ---------------------------------------------------------------------------

def analyze_bid_history(
    transactions: list[dict[str, Any]],
    rec_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Analyze historical FAAB bid data and compute statistics.

    Uses IQR-based outlier detection to separate standard waiver bids from
    premium bids (returning stars who command disproportionately high bids).
    Tier statistics are computed from standard bids only so outliers don't
    inflate suggestions for normal waiver moves.

    Args:
        transactions: Parsed transaction list from fetch_league_transactions.
        rec_df: Optional current recommendations to cross-reference quality.

    Returns:
        Dict with:
          - "summary": overall league stats (standard bids only)
          - "by_tier": stats bucketed by player quality tier (standard only)
          - "by_team": per-team bidding summary (all bids)
          - "all_bids": full sorted bid list
          - "standard_bids": non-outlier bids
          - "premium_bids": outlier bids (returning stars)
          - "premium_summary": stats for the premium pool
          - "outlier_threshold": the IQR-based cutoff used
          - "your_bids": bids from your team
    """
    if not transactions:
        return {
            "summary": {"total_transactions": 0},
            "by_tier": {},
            "by_team": {},
            "all_bids": [],
            "standard_bids": [],
            "premium_bids": [],
            "premium_summary": {},
            "outlier_threshold": 0,
            "your_bids": [],
        }

    # Build a lookup of player Adj_Scores from recommendations (if available)
    score_lookup: dict[str, float] = {}
    if rec_df is not None and "Player" in rec_df.columns and "Adj_Score" in rec_df.columns:
        for _, row in rec_df.iterrows():
            norm = normalize_name(str(row["Player"]))
            score_lookup[norm] = float(row.get("Adj_Score", 0))

    # Compute league-relative tier thresholds from the waiver pool
    tier_thresholds = compute_relative_tiers(rec_df)

    # Separate FAAB bids from free pickups
    faab_bids = [t for t in transactions if t["faab_bid"] > 0]
    free_pickups = [t for t in transactions if t["faab_bid"] == 0]

    # Assign tiers where possible (using relative thresholds)
    for txn in transactions:
        norm = normalize_name(txn["add_player_name"])
        score = score_lookup.get(norm, None)
        if score is not None:
            txn["adj_score"] = score
            txn["tier"] = score_to_tier(score, tier_thresholds)
        else:
            txn["adj_score"] = None
            txn["tier"] = "Unknown"

    # --- Outlier detection: separate standard from premium bids ---
    standard_bids, premium_bids, outlier_threshold = _classify_bids(faab_bids)

    # Overall summary — computed from standard bids (not skewed by outliers)
    std_amounts = [t["faab_bid"] for t in standard_bids]
    all_amounts = [t["faab_bid"] for t in faab_bids]
    summary = {
        "total_transactions": len(transactions),
        "faab_bids": len(faab_bids),
        "free_pickups": len(free_pickups),
        "standard_bids_count": len(standard_bids),
        "premium_bids_count": len(premium_bids),
        "outlier_threshold": outlier_threshold,
    }
    if std_amounts:
        summary["bid_mean"] = round(statistics.mean(std_amounts), 1)
        summary["bid_median"] = round(statistics.median(std_amounts), 1)
        summary["bid_max"] = max(std_amounts)
        summary["bid_min"] = min(std_amounts)
        if len(std_amounts) >= 2:
            summary["bid_stdev"] = round(statistics.stdev(std_amounts), 1)
    # Unfiltered stats for context
    if all_amounts:
        summary["raw_mean"] = round(statistics.mean(all_amounts), 1)
        summary["raw_max"] = max(all_amounts)

    # Per-tier analysis — standard bids only (outliers excluded)
    tier_bids: dict[str, list[int]] = defaultdict(list)
    for txn in standard_bids:
        tier_bids[txn.get("tier", "Unknown")].append(txn["faab_bid"])

    by_tier = {}
    for tier_name, bids in tier_bids.items():
        sorted_bids = sorted(bids)
        tier_stats = {
            "count": len(bids),
            "mean": round(statistics.mean(bids), 1),
            "median": round(statistics.median(bids), 1),
            "min": min(bids),
            "max": max(bids),
        }
        if len(bids) >= 4:
            q1_idx = len(sorted_bids) // 4
            q3_idx = (3 * len(sorted_bids)) // 4
            tier_stats["p25"] = sorted_bids[q1_idx]
            tier_stats["p75"] = sorted_bids[q3_idx]
        by_tier[tier_name] = tier_stats

    # Per-team spending
    team_spending: dict[str, dict] = defaultdict(lambda: {"total_spent": 0, "num_bids": 0, "bids": []})
    for txn in faab_bids:
        t = txn["team_name"] or txn["team_key"]
        team_spending[t]["total_spent"] += txn["faab_bid"]
        team_spending[t]["num_bids"] += 1
        team_spending[t]["bids"].append(txn["faab_bid"])

    for t_data in team_spending.values():
        t_data["avg_bid"] = round(t_data["total_spent"] / max(t_data["num_bids"], 1), 1)
        t_data["max_bid"] = max(t_data["bids"]) if t_data["bids"] else 0

    # Premium bid summary
    premium_summary = {}
    if premium_bids:
        p_amounts = [t["faab_bid"] for t in premium_bids]
        premium_summary = {
            "count": len(premium_bids),
            "mean": round(statistics.mean(p_amounts), 1),
            "median": round(statistics.median(p_amounts), 1),
            "min": min(p_amounts),
            "max": max(p_amounts),
        }

    # Your team's bids
    my_team_suffix = f".t.{config.YAHOO_TEAM_ID}"
    your_bids = [
        t for t in transactions
        if str(t.get("team_key", "")).endswith(my_team_suffix)
    ]

    return {
        "summary": summary,
        "by_tier": by_tier,
        "by_team": dict(team_spending),
        "all_bids": sorted(faab_bids, key=lambda x: x["faab_bid"], reverse=True),
        "standard_bids": sorted(standard_bids, key=lambda x: x["faab_bid"], reverse=True),
        "premium_bids": sorted(premium_bids, key=lambda x: x["faab_bid"], reverse=True),
        "premium_summary": premium_summary,
        "outlier_threshold": outlier_threshold,
        "your_bids": your_bids,
        "tier_thresholds": tier_thresholds,
    }


# ---------------------------------------------------------------------------
# Smart bid suggestion
# ---------------------------------------------------------------------------

def suggest_bid(
    player_name: str,
    adj_score: float,
    analysis: dict[str, Any],
    strategy: str = "competitive",
    budget_status: dict[str, Any] | None = None,
    schedule_games: int | None = None,
    avg_games: float = 3.5,
    roster_strength: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Suggest a FAAB bid for a player based on historical data.

    Uses cleaned (outlier-removed) tier statistics for standard waiver
    suggestions. Also provides premium bid range context for elite targets.

    Budget-aware: when budget_status is provided, the suggestion scales
    with remaining budget health.  If flush, bids can be above historical
    norms; if tight, bids are reduced.

    Schedule-aware: when schedule_games is provided, the bid is nudged
    higher for players with more upcoming games (more stat production).

    Roster-strength-aware: when roster_strength is provided, bids are
    adjusted based on how strong your roster is relative to the field.
    Weak rosters bid more aggressively; strong rosters bid conservatively.

    Strategies:
      - "value":       Bid at the 25th percentile for the tier (bargain)
      - "competitive": Bid at the median for the tier (market rate)
      - "aggressive":  Bid at the 75th percentile for the tier (ensure win)

    Args:
        player_name: Name of the player to bid on.
        adj_score: Player's Adj_Score from recommendations.
        analysis: Output from analyze_bid_history.
        strategy: One of "value", "competitive", "aggressive".
        budget_status: Optional dict from compute_budget_status().
        schedule_games: Optional game count for the upcoming week.
        avg_games: League average games per week (for schedule scaling).
        roster_strength: Optional dict from compute_roster_strength().

    Returns:
        Dict with suggested bid, reasoning, and optional premium_range.
    """
    tier = score_to_tier(adj_score, analysis.get("tier_thresholds"))
    tier_data = analysis.get("by_tier", {}).get(tier, None)

    suggestion = {
        "player": player_name,
        "adj_score": round(adj_score, 2),
        "tier": tier,
        "strategy": strategy,
        "premium_range": None,
    }

    # Build premium range context from historical premium bids
    premium_bids = analysis.get("premium_bids", [])
    if premium_bids:
        p_amounts = [t["faab_bid"] for t in premium_bids]
        suggestion["premium_range"] = {
            "min": min(p_amounts),
            "max": max(p_amounts),
            "median": round(statistics.median(p_amounts), 1),
            "count": len(p_amounts),
        }

    if not tier_data or tier_data["count"] < 2:
        # Not enough data for this tier — use overall league stats or a
        # simple score-based heuristic
        summary = analysis.get("summary", {})
        league_median = summary.get("bid_median", config.DEFAULT_FAAB_BID)

        # Scale by score: higher score = higher fraction of budget
        score_multiplier = min(adj_score / 5.0, 2.0)  # cap at 2x
        base = max(1, int(league_median * score_multiplier))

        if strategy == "value":
            bid = max(1, int(base * 0.7))
        elif strategy == "aggressive":
            bid = int(base * 1.4)
        else:
            bid = base

        # Apply budget, schedule, and roster strength adjustments (low-confidence path)
        bid = _apply_budget_schedule_adjustments(
            bid, budget_status, schedule_games, avg_games,
            roster_strength=roster_strength,
        )

        suggestion["suggested_bid"] = bid
        suggestion["confidence"] = "low"
        reason_parts = [
            f"Limited tier data ({tier_data['count'] if tier_data else 0} std bids). ",
            f"Estimate based on league median (${league_median}) \u00d7 score factor.",
        ]
        if budget_status:
            reason_parts.append(f" Budget: {budget_status['status']}.")
        if roster_strength:
            reason_parts.append(f" Roster: {roster_strength['label']}.")
        if schedule_games is not None:
            reason_parts.append(f" Games/wk: {schedule_games}.")
        suggestion["reason"] = "".join(reason_parts)
        return suggestion

    # Use tier percentile data (cleaned — outliers excluded)
    if strategy == "value":
        bid = tier_data.get("p25", tier_data["min"])
        suggestion["reason"] = f"P25 for {tier} tier (bargain, std bids)"
    elif strategy == "aggressive":
        bid = tier_data.get("p75", tier_data["max"])
        suggestion["reason"] = f"P75 for {tier} tier (higher win rate, std bids)"
    else:
        bid = tier_data["median"]
        suggestion["reason"] = f"Median for {tier} tier (market rate, std bids)"

    # Adjust for player quality within the tier
    thresholds_used = analysis.get("tier_thresholds") or DEFAULT_TIER_THRESHOLDS
    tier_index = [t[0] for t in thresholds_used].index(tier)
    if tier_index == 0:  # Elite — bump up slightly
        bid = bid + max(1, int(round(bid * 0.1)))

    # Apply budget, schedule, and roster strength adjustments
    bid = _apply_budget_schedule_adjustments(
        int(bid), budget_status, schedule_games, avg_games,
        roster_strength=roster_strength,
    )

    suggestion["suggested_bid"] = bid
    suggestion["confidence"] = "high" if tier_data["count"] >= 5 else "medium"
    suggestion["tier_stats"] = tier_data

    # Append context to reason
    extras = []
    if budget_status:
        rank = budget_status.get("league_rank")
        size = budget_status.get("league_size")
        rank_str = f" #{rank}/{size}" if rank and size else ""
        extras.append(f"Budget: {budget_status['status']}{rank_str}")
    if roster_strength:
        extras.append(f"Roster: {roster_strength['label']}")
    if schedule_games is not None:
        extras.append(f"{schedule_games}G this week")
    if extras:
        suggestion["reason"] += f" ({', '.join(extras)})"

    return suggestion


def _apply_budget_schedule_adjustments(
    bid: int,
    budget_status: dict[str, Any] | None = None,
    schedule_games: int | None = None,
    avg_games: float = 3.5,
    roster_strength: dict[str, Any] | None = None,
) -> int:
    """Apply budget-factor, schedule-factor, and roster-strength scaling to a raw bid.

    Roster strength adjustment:
      - Weak roster → bid_factor > 1 → bid increases (be more aggressive)
      - Strong roster → bid_factor < 1 → bid decreases (be selective)
    """
    # Budget scaling
    if budget_status:
        factor = budget_status.get("budget_factor", 1.0)
        bid = int(bid * factor)
        # Hard cap: never exceed max_single_bid
        max_bid = budget_status.get("max_single_bid")
        if max_bid is not None:
            bid = min(bid, max_bid)

    # Schedule scaling: more games → higher value → slightly higher bid
    if schedule_games is not None:
        delta = schedule_games - avg_games
        sched_factor = 1.0 + 0.15 * delta   # ±15% per game delta
        bid = int(bid * sched_factor)

    # Roster strength scaling: weak roster → bid up, strong → bid down
    if roster_strength:
        bid = int(bid * roster_strength.get("bid_factor", 1.0))

    return max(1, bid)


def suggest_bids_for_recommendations(
    rec_df: pd.DataFrame,
    analysis: dict[str, Any],
    strategy: str = "competitive",
    top_n: int = 10,
    budget_status: dict[str, Any] | None = None,
    schedule_game_counts: dict[str, int] | None = None,
    avg_games: float = 3.5,
    roster_strength: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Generate bid suggestions for the top N recommendations.

    Args:
        rec_df: Recommendations DataFrame with Player and Adj_Score columns.
        analysis: Output from analyze_bid_history.
        strategy: Bidding strategy ("value", "competitive", "aggressive").
        top_n: Number of top players to suggest bids for.
        budget_status: Optional budget health dict.
        schedule_game_counts: Optional {team_abbr: games} for the upcoming week.
        avg_games: League average games per week.
        roster_strength: Optional roster strength dict for bid scaling.

    Returns:
        DataFrame with columns: Player, Adj_Score, Tier, Suggested_Bid, Confidence, Reason.
    """
    from src.schedule_analyzer import normalize_team_abbr

    suggestions = []
    for i, (_, row) in enumerate(rec_df.iterrows()):
        if i >= top_n:
            break
        name = row.get("Player", "Unknown")
        score = float(row.get("Adj_Score", 0))

        # Determine schedule games for this player
        sched_games = None
        if schedule_game_counts:
            team = normalize_team_abbr(str(row.get("Team", "")))
            sched_games = schedule_game_counts.get(team)

        sug = suggest_bid(
            name, score, analysis, strategy,
            budget_status=budget_status,
            schedule_games=sched_games,
            avg_games=avg_games,
            roster_strength=roster_strength,
        )
        premium_range = sug.get("premium_range")
        premium_str = ""
        if premium_range:
            premium_str = f"${premium_range['min']}-${premium_range['max']}"

        games_str = str(sched_games) if sched_games is not None else "-"
        suggestions.append({
            "Player": name,
            "Adj_Score": sug["adj_score"],
            "Tier": sug["tier"],
            "Games": games_str,
            "Bid": f"${sug['suggested_bid']}",
            "Premium": premium_str or "-",
            "Confidence": sug["confidence"],
            "Reason": sug["reason"],
        })

    return pd.DataFrame(suggestions)


# ---------------------------------------------------------------------------
# Display / reporting
# ---------------------------------------------------------------------------

def format_faab_report(analysis: dict[str, Any]) -> str:
    """Format the FAAB analysis as a readable report."""
    lines = []
    summary = analysis["summary"]
    threshold = analysis.get("outlier_threshold", 0)

    lines.append("=" * 70)
    lines.append("  FAAB BID HISTORY ANALYSIS")
    lines.append("=" * 70)

    lines.append(f"\n  Total transactions:  {summary.get('total_transactions', 0)}")
    lines.append(f"  FAAB bids:           {summary.get('faab_bids', 0)}")
    lines.append(f"  Free pickups ($0):   {summary.get('free_pickups', 0)}")
    lines.append(f"  Standard bids:       {summary.get('standard_bids_count', 0)}")
    lines.append(f"  Premium bids:        {summary.get('premium_bids_count', 0)}"
                 f"  (outlier threshold: ${threshold:.0f})")

    if summary.get("bid_mean"):
        lines.append(f"\n  Standard bid mean:   ${summary['bid_mean']}")
        lines.append(f"  Standard bid median: ${summary['bid_median']}")
        lines.append(f"  Standard bid max:    ${summary.get('bid_max', '?')}")
        lines.append(f"  Standard bid min:    ${summary.get('bid_min', '?')}")
        if "bid_stdev" in summary:
            lines.append(f"  Bid std deviation:   ${summary['bid_stdev']}")
        if "raw_mean" in summary:
            lines.append(f"  Raw mean (all bids): ${summary['raw_mean']}"
                         f"  (includes premium)")

    # Premium pickups section
    premium_bids = analysis.get("premium_bids", [])
    premium_summary = analysis.get("premium_summary", {})
    if premium_bids:
        lines.append(f"\n{'='*70}")
        lines.append("  PREMIUM PICKUPS (returning stars / outlier bids)")
        lines.append(f"{'='*70}")
        lines.append(f"\n  These bids are statistical outliers (>= ${threshold:.0f}) and are")
        lines.append(f"  excluded from standard tier statistics to prevent inflation.")

        if premium_summary:
            lines.append(f"\n  Premium bid count:   {premium_summary['count']}")
            lines.append(f"  Premium bid mean:    ${premium_summary['mean']}")
            lines.append(f"  Premium bid median:  ${premium_summary['median']}")
            lines.append(f"  Premium bid range:   ${premium_summary['min']} - ${premium_summary['max']}")

        premium_rows = []
        for txn in premium_bids:
            premium_rows.append({
                "Player": txn["add_player_name"][:25],
                "Bid": f"${txn['faab_bid']}",
                "Team": (txn["team_name"] or "?")[:20],
                "Tier": txn.get("tier", "?"),
                "Dropped": (txn.get("drop_player_name") or "-")[:20],
            })
        lines.append("")
        lines.append(tabulate(premium_rows, headers="keys", tablefmt="simple"))

    # Per-tier breakdown (standard bids only)
    by_tier = analysis.get("by_tier", {})
    if by_tier:
        lines.append(f"\n{'='*70}")
        lines.append("  STANDARD BIDS BY PLAYER QUALITY TIER")
        lines.append(f"{'='*70}")
        lines.append("  (premium outliers excluded for accurate bid suggestions)")

        tier_rows = []
        tier_order = [t[0] for t in TIER_THRESHOLDS] + ["Unknown"]
        for tier_name in tier_order:
            if tier_name in by_tier:
                t = by_tier[tier_name]
                tier_rows.append({
                    "Tier": tier_name,
                    "Count": t["count"],
                    "Mean": f"${t['mean']}",
                    "Median": f"${t['median']}",
                    "Min": f"${t['min']}",
                    "Max": f"${t['max']}",
                    "P25": f"${t.get('p25', '-')}",
                    "P75": f"${t.get('p75', '-')}",
                })

        if tier_rows:
            lines.append("")
            lines.append(tabulate(tier_rows, headers="keys", tablefmt="simple"))

    # Per-team spending (all bids — including premium)
    by_team = analysis.get("by_team", {})
    if by_team:
        lines.append(f"\n{'='*70}")
        lines.append("  SPENDING BY TEAM (all bids)")
        lines.append(f"{'='*70}")

        team_rows = []
        for team_name, t_data in sorted(by_team.items(), key=lambda x: x[1]["total_spent"], reverse=True):
            team_rows.append({
                "Team": team_name[:30],
                "Total Spent": f"${t_data['total_spent']}",
                "# Bids": t_data["num_bids"],
                "Avg Bid": f"${t_data['avg_bid']}",
                "Max Bid": f"${t_data['max_bid']}",
            })

        lines.append("")
        lines.append(tabulate(team_rows, headers="keys", tablefmt="simple"))

    # Top 10 biggest bids (all)
    all_bids = analysis.get("all_bids", [])
    if all_bids:
        lines.append(f"\n{'='*70}")
        lines.append("  TOP 10 BIGGEST FAAB BIDS")
        lines.append(f"{'='*70}")

        top_rows = []
        for txn in all_bids[:10]:
            is_premium = txn["faab_bid"] >= threshold if threshold else False
            top_rows.append({
                "Player": txn["add_player_name"][:25],
                "Bid": f"${txn['faab_bid']}",
                "Category": "PREMIUM" if is_premium else "standard",
                "Team": (txn["team_name"] or "?")[:20],
                "Dropped": (txn.get("drop_player_name") or "-")[:20],
            })

        lines.append("")
        lines.append(tabulate(top_rows, headers="keys", tablefmt="simple"))

    return "\n".join(lines)


def format_bid_suggestions(
    suggestions_df: pd.DataFrame,
    strategy: str = "competitive",
) -> str:
    """Format bid suggestions as a readable table."""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  SUGGESTED FAAB BIDS (strategy: {strategy})")
    lines.append(f"{'='*70}")

    if suggestions_df.empty:
        lines.append("\n  No suggestions available.")
        return "\n".join(lines)

    lines.append("")
    lines.append(tabulate(
        suggestions_df,
        headers="keys",
        tablefmt="simple",
        showindex=True,
    ))

    lines.append("")
    lines.append("Strategies: value (bargain) | competitive (market rate) | aggressive (ensure win)")
    lines.append("Premium column shows the historical range for returning-star / outlier bids.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level runners
# ---------------------------------------------------------------------------

def run_faab_analysis(
    query=None,
    rec_df: pd.DataFrame | None = None,
    budget_status: dict[str, Any] | None = None,
    schedule_game_counts: dict[str, int] | None = None,
    avg_games: float = 3.5,
    roster_strength: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full FAAB history analysis and print reports.

    Args:
        query: Authenticated yfpy query instance (creates one if None).
        rec_df: Optional recommendations for quality tier tagging.
        budget_status: Optional budget health dict (from league_settings).
        schedule_game_counts: Optional {team: games} for upcoming week.
        avg_games: League average games per week.
        roster_strength: Optional roster strength dict for bid scaling.

    Returns:
        Analysis dict from analyze_bid_history.
    """
    if query is None:
        from src.yahoo_fantasy import create_yahoo_query
        print("Connecting to Yahoo Fantasy Sports...")
        query = create_yahoo_query()

    print("\nFetching league transaction history...")
    transactions = fetch_league_transactions(query)
    print(f"  Found {len(transactions)} add/drop transactions")

    print("Analyzing FAAB bid patterns...")
    analysis = analyze_bid_history(transactions, rec_df)
    print(format_faab_report(analysis))

    # Show bid suggestions if we have recommendation data
    if rec_df is not None and not rec_df.empty:
        for strategy in ("value", "competitive", "aggressive"):
            sug_df = suggest_bids_for_recommendations(
                rec_df, analysis, strategy, top_n=10,
                budget_status=budget_status,
                schedule_game_counts=schedule_game_counts,
                avg_games=avg_games,
                roster_strength=roster_strength,
            )
            print(format_bid_suggestions(sug_df, strategy))

    # Save analysis
    output_file = config.OUTPUT_DIR / "faab_analysis.csv"
    if analysis.get("all_bids"):
        pd.DataFrame(analysis["all_bids"]).to_csv(output_file, index=False)
        print(f"\nFAAB history saved to {output_file}")

    return analysis

"""Player news analysis for waiver wire decisions.

Augments the existing ESPN injury report with **performance / role keywords**
extracted from ESPN blurbs, Yahoo player-note flags, and ESPN scoreboard data.
The goal is to detect signals that affect a player's *future* fantasy value
beyond raw season stats — things like:

    • Starting lineup promotion  (→ more minutes, higher value)
    • Moved to bench             (→ fewer minutes, lower value)
    • Career / season-high game  (→ breakout signal)
    • Returning from injury soon (→ stash candidate)
    • Teammate injury opens role (→ opportunity signal)
    • Load management / rest     (→ availability risk)
    • Trade / new team           (→ role change, uncertain minutes)
    • Recent standout box score  (→ performance breakout)
    • Re-evaluation timeline     (→ longer absence than expected)

Sources (in order of cost):
    1. ESPN public injury API blurbs (``longComment`` / ``shortComment``)
       — already fetched by ``injury_news.py``; we mine the same blurbs
       for non-injury keywords.  **0 additional API calls.**
    2. Yahoo ``has_recent_player_notes`` flag — available on every player
       object at no additional API cost.  Players with recent notes are
       flagged for manual review even if ESPN has no blurb.
       **0 additional API calls.**
    3. ESPN game summary endpoint — fetches full boxscores for recent
       games.  Provides every player's stat line (PTS, REB, AST, STL,
       BLK, 3PM, FG, FT, MIN, TO) plus starter/bench flags.  Used for:
       (a) standout detection (waiver-calibrated thresholds),
       (b) hot-pickup z-delta analysis (replaces Yahoo per-date API),
       (c) starting-tomorrow detection (from recent starter flags).
       ~3 scoreboard calls + ~15-24 game summary calls per run.

Public surface:
    analyze_player_news(injury_lookup, player_names) → dict
    fetch_espn_player_news(player_names) → dict
    fetch_espn_boxscores(player_names, days) → BoxscoreResult
    NEWS_BOOST_LABEL  (constant)
"""

from __future__ import annotations

import re
from typing import Any


# ── Keyword categories and their scoring impact ──────────────────────────
# Each entry: (compiled regex, label, multiplier applied to Adj_Score)
#
# Multipliers > 1.0 = positive signal (boost)
# Multipliers < 1.0 = negative signal (discount)
# Multipliers == 1.0 would be neutral (not listed — no point)

_POSITIVE_KEYWORDS: list[tuple[re.Pattern, str, float]] = [
    # ── Starting lineup / expanded role ──────────────────────────────
    (re.compile(r"\bstart(?:ing|ed|s)?\b.*\b(?:lineup|role|five|center|forward|guard)\b", re.I),
     "Starting", 1.15),
    (re.compile(r"\bmov(?:ed|ing)\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.15),
    (re.compile(r"\binsert(?:ed)?\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.15),
    (re.compile(r"\bearn(?:ed|ing)\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.15),
    (re.compile(r"\bpromot(?:ed|ion)\b.*\b(?:start|role|lineup)\b", re.I),
     "Starting", 1.15),
    # "step into the starting role", "stepping into a starting spot"
    (re.compile(r"\bstep(?:ping)?\s+into\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.15),
    # "entering the starting lineup"
    (re.compile(r"\benter(?:ing|ed)\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.15),
    # "run away with the starting … job"
    (re.compile(r"\brun\s+away\s+with\b.*\bstart(?:ing)?\b", re.I),
     "Starting", 1.12),
    # General expanded role / opportunity
    (re.compile(r"\bexpand(?:ed|ing)\b.*\brole\b", re.I),
     "Expanded Role", 1.10),
    (re.compile(r"\bbig(?:ger)?\s+(?:opportunity|role)\b", re.I),
     "Expanded Role", 1.10),
    (re.compile(r"\bfeatured\s+role\b", re.I),
     "Featured Role", 1.10),
    (re.compile(r"\bgreen\s+light\b", re.I),
     "Green Light", 1.08),
    # "next man up" — teammate injury opens role
    (re.compile(r"\bnext\s+man\s+up\b", re.I),
     "Next Man Up", 1.12),

    # ── Career / season highs — breakout signal ──────────────────────
    (re.compile(r"\bcareer[- ]?high\b", re.I),
     "Career High", 1.12),
    (re.compile(r"\bseason[- ]?high\b", re.I),
     "Season High", 1.10),
    (re.compile(r"\bbest\s+game\b", re.I),
     "Best Game", 1.10),
    (re.compile(r"\bbreakout\b", re.I),
     "Breakout", 1.10),
    (re.compile(r"\b(?:3[0-9]|4[0-9]|5[0-9])\+?\s*(?:points?|pts)\b", re.I),
     "Big Scoring", 1.08),
    (re.compile(r"\btriple[- ]?double\b", re.I),
     "Triple-Double", 1.08),
    (re.compile(r"\bdouble[- ]?double\b", re.I),
     "Double-Double", 1.05),

    # ── Returning from injury ────────────────────────────────────────
    (re.compile(r"\breturn(?:ed|ing|s)?\s+(?:to\s+)?(?:action|practice|lineup|play|court)\b", re.I),
     "Returning", 1.10),
    (re.compile(r"\bexpect(?:ed|s)?\s+(?:to\s+)?return\b", re.I),
     "Expected Return", 1.08),
    (re.compile(r"\bnearing\s+(?:a\s+)?return\b", re.I),
     "Near Return", 1.08),
    # "trending towards a return"
    (re.compile(r"\btrending\b.*\breturn\b", re.I),
     "Near Return", 1.08),
    # "eligible to return"
    (re.compile(r"\beligible\s+(?:to\s+)?return\b", re.I),
     "Eligible Return", 1.08),
    (re.compile(r"\bcleared\b.*\b(?:play|return|action|practice|contact)\b", re.I),
     "Cleared", 1.12),
    (re.compile(r"\bfull\s+(?:participant|practice|contact)\b", re.I),
     "Full Practice", 1.08),
    # "no restrictions" / "without restrictions"
    (re.compile(r"\b(?:no|without|lifted)\s+(?:minute[s]?\s+)?restriction[s]?\b", re.I),
     "No Restrictions", 1.10),
    # "ramp up" / "ramping up"
    (re.compile(r"\bramp(?:ing)?\s+up\b", re.I),
     "Ramping Up", 1.06),
    # "debut" — first game with new team or first NBA game
    (re.compile(r"\b(?:making|make|made)?\s*(?:his\s+)?debut\b", re.I),
     "Debut", 1.08),

    # ── Increased minutes ────────────────────────────────────────────
    (re.compile(r"\bincreas(?:ed|ing)\b.*\bminutes\b", re.I),
     "More Minutes", 1.10),
    (re.compile(r"\bmore\s+minutes\b", re.I),
     "More Minutes", 1.08),
    (re.compile(r"\buptick\b.*\b(?:playing\s+time|minutes)\b", re.I),
     "More Minutes", 1.08),

    # ── Fantasy buzz — ESPN/Yahoo articles recommending pickups ──────
    (re.compile(r"\b(?:must[- ]?add|must[- ]?roster|waiver[- ]?wire)\b", re.I),
     "Waiver Buzz", 1.10),
    (re.compile(r"\b(?:pick\s*up|scoop\s+up|add\s+him)\b", re.I),
     "Pickup Buzz", 1.08),

    # ── Starting tomorrow / projected starter (next-day pickups) ─────
    (re.compile(r"\bwill\s+start\b", re.I),
     "Will Start", 1.12),
    (re.compile(r"\bexpected\s+to\s+start\b", re.I),
     "Exp. Starter", 1.10),
    (re.compile(r"\bprojected\s+(?:to\s+)?start\b", re.I),
     "Proj. Starter", 1.10),
    (re.compile(r"\b(?:starting|will\s+get)\s+(?:the\s+)?nod\b", re.I),
     "Starting Nod", 1.10),
    (re.compile(r"\b(?:in|back\s+in)\s+the\s+starting\s+lineup\b", re.I),
     "In Starting Lineup", 1.12),
]

_NEGATIVE_KEYWORDS: list[tuple[re.Pattern, str, float]] = [
    # ── Benched / demoted ────────────────────────────────────────────
    (re.compile(r"\b(?:back|moved|sent|demoted)\b.*\bbench\b", re.I),
     "Benched", 0.85),
    (re.compile(r"\blos(?:t|ing|e)\b.*\bstart(?:ing)?\b", re.I),
     "Lost Starting Role", 0.85),
    (re.compile(r"\bcoming\s+off\s+(?:the\s+)?bench\b", re.I),
     "Bench Role", 0.88),
    (re.compile(r"\breduced\b.*\b(?:role|minutes)\b", re.I),
     "Reduced Role", 0.88),

    # ── Load management / rest ───────────────────────────────────────
    (re.compile(r"\bload\s+management\b", re.I),
     "Load Mgmt", 0.90),
    (re.compile(r"\brest(?:ing|ed)?\b.*\b(?:game|tonight|tomorrow)\b", re.I),
     "Resting", 0.92),
    (re.compile(r"\b(?<!no\s)(?<!without\s)(?<!lifted\s)minutes?\s+(?:restriction|limit)\b", re.I),
     "Mins Restriction", 0.90),

    # ── Extended absence / re-evaluation ─────────────────────────────
    (re.compile(r"\bre[- ]?evaluat(?:ed|ion|e)\b", re.I),
     "Re-Evaluation", 0.82),
    (re.compile(r"\bweek[- ]?to[- ]?week\b", re.I),
     "Week-to-Week", 0.78),
    (re.compile(r"\bno\s+timetable\b", re.I),
     "No Timeline", 0.72),
    (re.compile(r"\bindefinitely\b", re.I),
     "Indefinite", 0.65),
    (re.compile(r"\bsecond\s+opinion\b", re.I),
     "Second Opinion", 0.80),
    (re.compile(r"\bre[- ]?aggravat(?:ed|ion|e)\b", re.I),
     "Re-Injury", 0.75),
    (re.compile(r"\bseason[- ]?ending\b", re.I),
     "Season-Ending", 0.0),

    # ── Trade uncertainty ────────────────────────────────────────────
    (re.compile(r"\btrad(?:ed|e)\b.*\b(?:to|from)\b", re.I),
     "Traded", 0.92),
    (re.compile(r"\btrade\s+deadline\b", re.I),
     "Trade Deadline", 0.95),

    # ── G-League / two-way ───────────────────────────────────────────
    (re.compile(r"\b(?:g[- ]?league|two[- ]?way|sent\s+down)\b", re.I),
     "G-League", 0.70),

    # ── Legal / suspension ───────────────────────────────────────────
    (re.compile(r"\b(?:arrest(?:ed)?|charged|suspended|suspension)\b", re.I),
     "Suspended", 0.60),

    # ── DNP / not playing ────────────────────────────────────────────
    (re.compile(r"\bdnp\b", re.I),
     "DNP", 0.80),
    (re.compile(r"\bshut\s+down\b", re.I),
     "Shut Down", 0.0),

    # ── Sitting tomorrow / confirmed out next game ───────────────────
    (re.compile(r"\b(?:will\s+)?sit\s+(?:out\s+)?(?:tomorrow|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b", re.I),
     "Sitting Tomorrow", 0.80),
    (re.compile(r"\bruled\s+out\b", re.I),
     "Ruled Out", 0.75),
    (re.compile(r"\bwill\s+(?:not|miss)\b.*\b(?:tomorrow|next\s+game)\b", re.I),
     "Out Tomorrow", 0.78),
]

# Label used in recommendation display
NEWS_BOOST_LABEL = "News"


def _scan_keywords(text: str) -> list[tuple[str, float]]:
    """Scan text for performance keywords and return (label, multiplier) hits."""
    if not text:
        return []

    hits: list[tuple[str, float]] = []
    seen_labels: set[str] = set()

    for pattern, label, mult in _POSITIVE_KEYWORDS + _NEGATIVE_KEYWORDS:
        if label not in seen_labels and pattern.search(text):
            hits.append((label, mult))
            seen_labels.add(label)

    return hits


def analyze_player_news(
    injury_lookup: dict[str, dict],
    player_names: list[str] | None = None,
    yahoo_notes: dict[str, bool] | None = None,
) -> dict[str, dict]:
    """Analyze player news for performance/role signals.

    Mines the ``description`` (ESPN blurb) field from each injury_lookup
    entry for performance keywords beyond injury severity.  Also
    incorporates Yahoo ``has_recent_player_notes`` flags when available.

    Args:
        injury_lookup: Dict from ``build_injury_lookup()`` mapping
            normalized player name → injury info dict (with ``description``).
        player_names: Optional list of player names to check.  If given,
            only these players are analyzed.  If None, all entries in
            injury_lookup are analyzed.
        yahoo_notes: Optional dict mapping normalized player name → bool
            (True if Yahoo reports ``has_recent_player_notes``).

    Returns:
        Dict mapping normalized player name → {
            news_multiplier: float (product of all keyword multipliers),
            news_labels: list[str] (labels for matched keywords),
            news_summary: str (one-line summary for display),
            has_yahoo_notes: bool,
        }.
    """
    from src.yahoo_fantasy import normalize_name

    results: dict[str, dict] = {}

    # Determine which names to analyze
    if player_names:
        names_to_check = [normalize_name(n) for n in player_names]
    else:
        names_to_check = list(injury_lookup.keys())

    for norm_name in names_to_check:
        entry = injury_lookup.get(norm_name)

        # Start with defaults
        multiplier = 1.0
        labels: list[str] = []
        has_yahoo = False

        # Scan ESPN blurb for keywords
        if entry:
            blurb = entry.get("description", "")
            hits = _scan_keywords(blurb)
            for label, mult in hits:
                labels.append(label)
                multiplier *= mult

        # Add Yahoo notes flag
        if yahoo_notes and norm_name in yahoo_notes:
            has_yahoo = yahoo_notes[norm_name]
            if has_yahoo and not labels:
                # Player has Yahoo notes but no ESPN blurb keywords found
                labels.append("Yahoo Notes")

        # Only add to results if we found something meaningful
        if labels or has_yahoo:
            summary = ", ".join(labels) if labels else "Recent notes"
            results[norm_name] = {
                "news_multiplier": round(multiplier, 3),
                "news_labels": labels,
                "news_summary": summary,
                "has_yahoo_notes": has_yahoo,
            }

    return results


def fetch_espn_player_news(
    player_names: list[str] | None = None,
) -> dict[str, dict]:
    """Fetch ESPN general NBA news and extract per-player signals.

    Complements the injury API by scanning ESPN's general NBA news feed
    for articles that mention specific players and contain performance
    keywords.  This catches non-injury news like role changes, trade
    impacts, and breakout performances.

    Args:
        player_names: Optional list of names to look for in articles.
            If None, returns all player mentions found.

    Returns:
        Dict mapping normalized player name → {
            news_multiplier, news_labels, news_summary, headline
        }.
    """
    import requests
    from src.yahoo_fantasy import normalize_name

    results: dict[str, dict] = {}

    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news",
            params={"limit": 25},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  Warning: Could not fetch ESPN news: {e}")
        return results

    # Build normalized lookup set from target names
    target_norms: set[str] | None = None
    if player_names:
        target_norms = {normalize_name(n) for n in player_names}

    articles = data.get("articles", [])

    for article in articles:
        headline = article.get("headline", "")
        description = article.get("description", "")
        combined = f"{headline} {description}"

        # Try to find athlete references in the article
        athletes = []
        for cat in article.get("categories", []):
            athlete = cat.get("athlete", {})
            name = athlete.get("displayName", "")
            if name:
                athletes.append(name)

        # If no structured athlete data, try headline parsing
        # (less reliable but catches more articles)
        if not athletes:
            continue

        for athlete_name in athletes:
            norm = normalize_name(athlete_name)
            if target_norms and norm not in target_norms:
                continue

            hits = _scan_keywords(combined)
            if hits:
                labels = [h[0] for h in hits]
                mult = 1.0
                for _, m in hits:
                    mult *= m

                # Keep strongest signal if player appears in multiple articles
                if norm in results:
                    existing = results[norm]["news_multiplier"]
                    if abs(mult - 1.0) <= abs(existing - 1.0):
                        continue

                results[norm] = {
                    "news_multiplier": round(mult, 3),
                    "news_labels": labels,
                    "news_summary": ", ".join(labels),
                    "headline": headline[:100],
                    "has_yahoo_notes": False,
                }

    return results


# ── ESPN Boxscores — recent performances, standouts, starters ───────────

_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)
_SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
)


def _parse_frac(val: str) -> tuple[int, int]:
    """Parse '5-11' → (5, 11).  Returns (0, 0) on failure."""
    try:
        parts = val.split("-")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


class BoxscoreResult:
    """Container for data extracted from ESPN game boxscores.

    Attributes:
        stat_lines: dict of normalized_name → list of per-game stat dicts.
            Each dict has: PTS, REB, AST, STL, BLK, FG3M, FGM, FGA, FTM,
            FTA, MIN, TOV, FG_PCT, FT_PCT, started (bool), date (str).
        standout_signals: dict of normalized_name → {
            news_multiplier, news_labels, news_summary, has_yahoo_notes}.
        starter_info: dict of normalized_name → {
            started_last: bool, games_started: int, games_total: int}.
        api_calls: int — total API calls made.
    """

    def __init__(self) -> None:
        self.stat_lines: dict[str, list[dict]] = {}
        self.standout_signals: dict[str, dict] = {}
        self.starter_info: dict[str, dict] = {}
        self.api_calls: int = 0


# ── Standout thresholds (calibrated for waiver-wire candidates) ──────
# Waiver candidates average ~8-14 PPG, ~4 RPG, ~2.5 APG.  A waiver
# candidate being the team game leader is already notable; thresholds
# are set to flag clearly above-average games for this population.

_STANDOUT_THRESHOLDS = {
    # (min_value, label_fmt, multiplier)
    "PTS": [
        (30, "{v} PTS", 1.08),
        (22, "{v} PTS", 1.05),
        (15, "{v} PTS", 1.03),
    ],
    "REB": [
        (12, "{v} REB", 1.06),
        (8, "{v} REB", 1.04),
    ],
    "AST": [
        (10, "{v} AST", 1.06),
        (6, "{v} AST", 1.04),
    ],
    "STL": [
        (4, "{v} STL", 1.06),
        (3, "{v} STL", 1.04),
    ],
    "BLK": [
        (4, "{v} BLK", 1.06),
        (3, "{v} BLK", 1.04),
    ],
    "FG3M": [
        (6, "{v} 3PM", 1.06),
        (4, "{v} 3PM", 1.04),
    ],
}


def _check_standout(stats: dict) -> list[tuple[str, float]]:
    """Check if a stat line qualifies as a standout performance.

    Returns list of (label, multiplier) for each stat that exceeds
    a waiver-calibrated threshold.
    """
    hits: list[tuple[str, float]] = []
    for stat_key, tiers in _STANDOUT_THRESHOLDS.items():
        val = stats.get(stat_key, 0)
        if not isinstance(val, (int, float)):
            continue
        for min_val, label_fmt, mult in tiers:
            if val >= min_val:
                hits.append((label_fmt.format(v=int(val)), mult))
                break  # highest tier only
    return hits


def fetch_espn_boxscores(
    player_names: list[str] | None = None,
    days: int = 3,
) -> BoxscoreResult:
    """Fetch ESPN game boxscores and extract per-player stat lines.

    This is the primary ESPN data source for the waiver advisor.  It
    fetches the scoreboard for each of the last *days* calendar days,
    then fetches the full game summary (boxscore) for each game.  From
    each boxscore it extracts:

      1. **Full stat lines** for every player (for hot-pickup z-delta).
      2. **Standout signals** using waiver-calibrated thresholds.
      3. **Starter/bench flags** (for starting-tomorrow detection).

    Thresholds are calibrated for waiver-wire candidates (8-14 PPG avg):
      • 15+ PTS, 8+ REB, 6+ AST, 3+ STL, 3+ BLK, 4+ 3PM

    Args:
        player_names: Optional list of candidate names.  If given,
            only these players' stat lines / signals are returned.
            Boxscores are still fetched for all games (required to
            find the players).
        days: Calendar days to look back (default 3).

    Returns:
        BoxscoreResult with stat_lines, standout_signals, starter_info.
    """
    import requests
    from datetime import datetime, timedelta
    from src.yahoo_fantasy import normalize_name

    result = BoxscoreResult()

    target_norms: set[str] | None = None
    if player_names:
        target_norms = {normalize_name(n) for n in player_names}

    today = datetime.now()

    for day_offset in range(days):
        date = today - timedelta(days=day_offset + 1)
        date_str = date.strftime("%Y%m%d")
        date_display = date.strftime("%Y-%m-%d")

        # Fetch scoreboard to get game IDs
        try:
            resp = requests.get(
                _SCOREBOARD_URL,
                params={"dates": date_str},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            result.api_calls += 1
        except Exception as e:
            print(f"  Warning: ESPN scoreboard for {date_str}: {e}")
            continue

        events = data.get("events", [])
        if not events:
            continue

        # Fetch each game's boxscore
        for event in events:
            game_id = event.get("id")
            if not game_id:
                continue

            try:
                sr = requests.get(
                    _SUMMARY_URL,
                    params={"event": game_id},
                    timeout=15,
                )
                sr.raise_for_status()
                summary = sr.json()
                result.api_calls += 1
            except Exception as e:
                continue  # skip this game, don't spam warnings

            boxscore = summary.get("boxscore", {})
            for team_section in boxscore.get("players", []):
                stats_section = team_section.get("statistics", [])
                if not stats_section:
                    continue

                cols = stats_section[0].get("labels", [])
                athletes = stats_section[0].get("athletes", [])

                for ath in athletes:
                    athlete_data = ath.get("athlete", {})
                    display_name = athlete_data.get("displayName", "")
                    if not display_name:
                        continue

                    norm = normalize_name(display_name)
                    if target_norms and norm not in target_norms:
                        continue

                    raw_vals = ath.get("stats", [])
                    if not raw_vals or len(raw_vals) != len(cols):
                        continue

                    stat_map = dict(zip(cols, raw_vals))

                    # Check for DNP (0 or no minutes)
                    min_str = stat_map.get("MIN", "0")
                    try:
                        minutes = int(min_str) if min_str else 0
                    except ValueError:
                        minutes = 0
                    if minutes == 0:
                        continue  # didn't play

                    # Parse shooting stats
                    fgm, fga = _parse_frac(stat_map.get("FG", "0-0"))
                    fg3m, fg3a = _parse_frac(stat_map.get("3PT", "0-0"))
                    ftm, fta = _parse_frac(stat_map.get("FT", "0-0"))

                    game_stats = {
                        "MIN": minutes,
                        "PTS": int(stat_map.get("PTS", 0) or 0),
                        "REB": int(stat_map.get("REB", 0) or 0),
                        "AST": int(stat_map.get("AST", 0) or 0),
                        "STL": int(stat_map.get("STL", 0) or 0),
                        "BLK": int(stat_map.get("BLK", 0) or 0),
                        "TOV": int(stat_map.get("TO", 0) or 0),
                        "FGM": fgm,
                        "FGA": fga,
                        "FG3M": fg3m,
                        "FTM": ftm,
                        "FTA": fta,
                        "FG_PCT": fgm / fga if fga > 0 else 0.0,
                        "FT_PCT": ftm / fta if fta > 0 else 0.0,
                        "started": bool(ath.get("starter", False)),
                        "date": date_display,
                    }

                    # Accumulate stat lines
                    if norm not in result.stat_lines:
                        result.stat_lines[norm] = []
                    result.stat_lines[norm].append(game_stats)

                    # Track starter info
                    if norm not in result.starter_info:
                        result.starter_info[norm] = {
                            "started_last": False,
                            "games_started": 0,
                            "games_total": 0,
                        }
                    info = result.starter_info[norm]
                    info["games_total"] += 1
                    if game_stats["started"]:
                        info["games_started"] += 1
                    # Most recent game (day_offset 0 = yesterday)
                    if day_offset == 0 or (
                        info["games_total"] == 1
                    ):
                        info["started_last"] = game_stats["started"]

                    # Check for standout performance
                    standout_hits = _check_standout(game_stats)
                    if standout_hits:
                        if norm in result.standout_signals:
                            existing = result.standout_signals[norm]
                            for lbl, m in standout_hits:
                                if lbl not in existing["news_labels"]:
                                    existing["news_labels"].append(lbl)
                                existing["news_multiplier"] = round(
                                    max(existing["news_multiplier"], m), 3
                                )
                            existing["news_summary"] = ", ".join(
                                existing["news_labels"]
                            )
                        else:
                            labels = [h[0] for h in standout_hits]
                            top_mult = max(h[1] for h in standout_hits)
                            result.standout_signals[norm] = {
                                "news_multiplier": top_mult,
                                "news_labels": labels,
                                "news_summary": ", ".join(labels),
                                "has_yahoo_notes": False,
                            }

    return result


def convert_boxscores_to_recent_stats(
    boxscore_result: BoxscoreResult,
    player_name_to_key: dict[str, str],
    last_n: int = 3,
) -> dict[str, dict]:
    """Convert ESPN boxscore stat lines to the format used by hot-pickup scoring.

    Produces the same output format as ``yahoo_stats.compute_recent_game_stats``
    so it can be fed directly into ``compute_hot_pickup_scores``.

    Args:
        boxscore_result: From ``fetch_espn_boxscores()``.
        player_name_to_key: Dict mapping normalized player name → Yahoo player key.
        last_n: Number of most recent games to average.

    Returns:
        Dict of player_key → {stat_col: avg_value, ..., games_used: int}.
    """
    stat_cols = [
        "MIN", "FGM", "FGA", "FG_PCT", "FTM", "FTA", "FT_PCT",
        "FG3M", "PTS", "REB", "AST", "STL", "BLK", "TOV",
    ]

    results: dict[str, dict] = {}

    for norm_name, games in boxscore_result.stat_lines.items():
        pk = player_name_to_key.get(norm_name)
        if not pk:
            continue

        # Sort by date descending and take last_n
        sorted_games = sorted(games, key=lambda g: g["date"], reverse=True)[:last_n]
        if not sorted_games:
            continue

        averages: dict[str, float] = {"games_used": len(sorted_games)}
        for col in stat_cols:
            vals = [g.get(col, 0) for g in sorted_games]
            if vals:
                averages[col] = sum(vals) / len(vals)

        # Recompute FG%/FT% from totals
        total_fga = sum(g.get("FGA", 0) for g in sorted_games)
        total_fgm = sum(g.get("FGM", 0) for g in sorted_games)
        if total_fga > 0:
            averages["FG_PCT"] = total_fgm / total_fga

        total_fta = sum(g.get("FTA", 0) for g in sorted_games)
        total_ftm = sum(g.get("FTM", 0) for g in sorted_games)
        if total_fta > 0:
            averages["FT_PCT"] = total_ftm / total_fta

        results[pk] = averages

    return results

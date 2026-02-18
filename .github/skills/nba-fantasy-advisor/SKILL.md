---
name: nba-fantasy-advisor
description: >
  NBA Fantasy Basketball waiver wire advisor with 9-category z-score analysis,
  FAAB bid suggestions, and automated Yahoo transaction submission.
  Use when user asks to "analyze my fantasy roster", "find waiver pickups",
  "suggest FAAB bids", "submit a waiver claim", "check injury reports",
  "analyze NBA schedule", "run fantasy analysis", "who should I pick up",
  or "optimize my fantasy basketball team".
license: Apache-2.0
compatibility: >
  Requires Python 3.10+, Google Chrome (for Yahoo OAuth browser flow),
  and network access to NBA.com, ESPN, and Yahoo Fantasy APIs.
  Yahoo OAuth2 credentials required for roster/transaction features.
metadata:
  author: Joshua Lee
  version: 2.0.0
  category: sports-analytics
  tags: [fantasy-basketball, nba, yahoo-fantasy, waiver-wire, faab]
---

# NBA Fantasy Basketball Waiver Wire Advisor

## Overview

A CLI tool that analyzes NBA player statistics, your Yahoo Fantasy roster, injury
reports, Yahoo trending/ownership data, and the NBA schedule to produce ranked
waiver wire recommendations with hot-pickup detection, optional FAAB bid
suggestions, and direct Yahoo transaction submission.

## Instructions

### Step 1: Environment Setup

Ensure the virtual environment is activated and dependencies are installed:

```bash
cd nba-fantasy-advisor
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

Copy `.env.template` to `.env` and fill in Yahoo OAuth credentials:

```
YAHOO_CONSUMER_KEY=your_key
YAHOO_CONSUMER_SECRET=your_secret
YAHOO_LEAGUE_ID=94443
YAHOO_TEAM_ID=9
```

Expected output: A `.env` file with valid credentials.

### Step 2: Run Full Analysis

```bash
python main.py
```

This executes the full pipeline:

1. Fetch NBA player stats via `nba_api` and compute 9-category z-scores
2. Connect to Yahoo Fantasy API and scan all league rosters
3. Identify unowned players and score them against your roster's category needs
4. Pull real-time injury data from ESPN and apply severity multipliers
5. Analyze the NBA schedule for games-per-week density bonuses
6. Fetch recent game logs and compute hot-pickup z-deltas for breakout detection
7. Query Yahoo ownership trends to identify trending players being widely added
8. Output a ranked recommendations table with adjusted scores, hot (🔥) and trending (📈) indicators

Expected output: A formatted table of top waiver wire pickups printed to console
and saved to `outputs/waiver_recommendations.csv`.

### Step 3: FAAB Bid Analysis (Optional)

```bash
python main.py --faab-history --strategy competitive
```

Analyzes all league FAAB transaction history, classifies players into quality
tiers (Elite/Strong/Solid/Streamer/Dart), and suggests optimal bid amounts.

Strategies: `value` (P25), `competitive` (median), `aggressive` (P75).

### Step 4: Submit a Waiver Claim (Optional)

```bash
python main.py --claim          # Interactive claim flow
python main.py --claim --dry-run  # Preview without submitting
```

Walks through player selection, drop candidate, FAAB bid amount, and submits
directly to Yahoo via XML API POST.

## CLI Reference

| Flag | Description |
|------|-------------|
| `--skip-yahoo` | NBA stats only — no Yahoo auth required |
| `--top N` | Show top N recommendations (default: 15) |
| `--days N` | Evaluate last N days of recent form (default: 14) |
| `--claim` | Run analysis then interactively submit a waiver claim |
| `--dry-run` | Preview a claim without submitting |
| `--faab-history` | Analyze league FAAB bid history |
| `--strategy` | FAAB bid strategy: value / competitive / aggressive |
| `--compact` | Condensed table: Player, Team, Z_Value, Adj_Score, Injury, Games_Wk, Hot, Trending |

## Architecture

```
main.py                    # CLI entry point & pipeline orchestration
config.py                  # All settings & environment config
src/
  nba_stats.py             # NBA stats + z-score engine (volume-weighted FG%/FT%) + hot-pickup z-delta
  yahoo_fantasy.py         # Yahoo API wrapper (OAuth2, roster scanning, trending players)
  waiver_advisor.py        # Core recommendation engine (need-weighted + recency/trending boosts)
  injury_news.py           # ESPN injury API integration
  schedule_analyzer.py     # NBA schedule density analysis
  faab_analyzer.py         # FAAB bid history & tier-based suggestions
  league_settings.py       # League rules, FAAB budget tracking
  transactions.py          # Yahoo waiver claim / FAAB bid submission
  colors.py                # ANSI color utilities for terminal output
```

## Key Technical Details

- **Z-Score Engine**: 9-category (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO).
  FG% and FT% use volume-weighted impact z-scores (accuracy x attempts).
  Turnovers are inverted (lower = better).
- **Roster Need Analysis**: Computes your roster's category z-scores, identifies
  weaknesses, and applies need-weight multipliers to boost players who fill gaps.
- **Punt Categories**: Configure `PUNT_CATEGORIES` in `config.py` to exclude
  categories from scoring (e.g., `["TO", "FT%"]`).
- **Injury Multipliers**: Out For Season = 0.0x, Out = 0.10x, Day-to-Day = 0.90x.
  Extended-absence and return-soon keywords shift multipliers further.
- **Schedule Weighting**: Games-per-week for 3 weeks ahead with decay
  (wk1=1.0, wk2=0.5, wk3=0.25). Each game above average adds
  `SCHEDULE_WEIGHT` (0.10) to Adj_Score.
- **Availability Rate**: GP/team-GP ratio → Healthy/Moderate/Risky/Fragile
  tiers with 0% to 55% score penalties.
- **FAAB Tiers**: Elite/Strong/Solid/Streamer/Dart with IQR outlier detection
  separating premium bids from standard bids. Tier minimum floors prevent
  $0 suggestions.
- **Unicode Normalization**: NFKD decomposition for cross-source player name
  matching (handles diacritics like Doncic, Nurkic, Porzingis).
- **Dynamic game_id**: Yahoo season `game_id` auto-resolved via API each run.
- **OAuth Retry**: Patches yfpy's 401 handling with automatic re-auth and
  exponential back-off (up to 3 retries).
- **Auto-Detect Droppable Players**: When `AUTO_DETECT_DROPPABLE = True`,
  ranks your roster by Z_TOTAL and flags the bottom N as drop candidates.
  `UNDDROPPABLE_PLAYERS` protects stashed stars. Falls back to manual
  `DROPPABLE_PLAYERS` list when disabled.
- **Transaction Safety**: IL/IL+ compliance checks block invalid transactions.
  Weekly transaction limit tracked with unique-drop counting.
- **Color-Coded Output**: ANSI colors for injury status (red=OUT, yellow=DTD,
  green=Healthy), category assessments, z-scores, and budget status. Respects
  `NO_COLOR` env var. Windows VT processing enabled automatically.
- **Compact Display**: `--compact` flag reduces the recommendation table to
  key columns (Player, Team, Games_Wk, Injury, Z_Value, Adj_Score, Hot, Trending).
- **Hot-Pickup Detection**: Fetches last N game logs per candidate and computes
  recent z-scores against league-wide season averages. Players with z_delta ≥ 1.0
  are flagged as 🔥 Hot. A recency boost (`RECENCY_WEIGHT × z_delta`) is added
  to Adj_Score for improving players, surfacing breakout performers.
- **Yahoo Trending Integration**: Queries Yahoo ownership-change data in batches.
  Players gaining ≥ `HOT_PICKUP_MIN_DELTA` (default: 5%) ownership are flagged
  as 📈 Trending with an additive score boost. Helps identify players being
  widely added before they're unavailable.
- **Expanded Candidate Pool**: When hot-pickup is enabled, the candidate pool
  is expanded to `TOP_N × 3` to ensure breakout performers ranked lower by
  season z-score are still evaluated and can surface in recommendations.
- **Roster-Strength-Aware FAAB**: Bids adjusted based on overall roster
  strength — weak rosters bid more aggressively, strong rosters bid
  conservatively. Factor displayed in transaction flow.

## Troubleshooting

### Error: Yahoo OAuth fails or 401 errors

Cause: Expired or invalid credentials, or Yahoo's token refresh issue.
Solution:
1. Verify `YAHOO_CONSUMER_KEY` and `YAHOO_CONSUMER_SECRET` in `.env`
2. Delete any cached token files and re-authenticate
3. The built-in retry logic will attempt up to 3 re-auth cycles automatically

### Error: "No stats returned from NBA API"

Cause: NBA.com API may be down or rate-limited.
Solution:
1. Wait a few minutes and retry
2. Check if `nba_api` has a newer version: `pip install --upgrade nba_api`

### Error: ESPN injury data empty

Cause: ESPN API endpoint changed or is temporarily unavailable.
Solution: The tool falls back gracefully — recommendations still work without
injury data, just without injury multipliers applied.

### Error: Transaction blocked — IL compliance

Cause: A player on your IL/IL+ slot is no longer injury-eligible.
Solution: Move the player off IL first, then retry the waiver claim.

## Examples

### Example 1: Weekly Waiver Analysis

User says: "Analyze my fantasy roster and find the best waiver pickups"

Actions:
1. Connect to Yahoo and scan all 12 team rosters
2. Fetch current NBA stats and compute z-scores
3. Pull ESPN injury report
4. Analyze NBA schedule for next 3 weeks
5. Score unowned players against roster needs
6. Display top 15 recommendations

Result: Ranked table showing player name, z-scores per category, injury status,
schedule bonus, availability rate, and final adjusted score.

### Example 2: FAAB Bid Suggestion

User says: "How much should I bid on Player X?"

Actions:
1. Fetch all league FAAB transaction history
2. Classify Player X's quality tier based on z-score
3. Analyze historical bids for similar-tier players
4. Apply IQR outlier detection to filter premium bid noise
5. Suggest bid based on selected strategy

Result: Suggested FAAB bid amount with tier context and bid distribution stats.

### Example 3: Submit a Waiver Claim

User says: "Claim Player X and drop Player Y for $15"

Actions:
1. Verify Player X is available on waivers
2. Auto-detect lowest-value roster player as drop candidate (or use manual list)
3. Check IL compliance and weekly transaction limit
4. Submit XML POST to Yahoo Fantasy API
5. Confirm successful claim

Result: Waiver claim submitted with confirmation or dry-run preview.

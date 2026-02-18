# NBA Fantasy Advisor

Nightly waiver wire recommendation engine for Yahoo Fantasy Basketball (9-category H2H leagues).

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Combines **nba_api** (real NBA stats) with **yfpy** (Yahoo Fantasy Sports API) to:
- Scrape current season NBA player stats
- Compute 9-category z-scores (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO)
- Analyze your roster's strengths and weaknesses
- Fetch real-time injury data from ESPN's public API
- Factor in upcoming schedule density (games per week)
- Recommend the best available waiver wire pickups tailored to your team's needs
- Submit waiver claims and FAAB bids directly to Yahoo (with manual fallback when write access is unavailable)
- Auto-resolve IL/IL+ roster moves with smart drop strategies
- Scheduled watch mode with email reports via GitHub Actions
- Streaming mode targeting tomorrow's games (designed for overnight FAAB leagues)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Yahoo Fantasy API (optional for --skip-yahoo mode)

1. Go to [https://developer.yahoo.com/apps/create/](https://developer.yahoo.com/apps/create/) and create an app:
   - **Application Type**: `Installed Application`
   - **Redirect URI**: `https://localhost:8080`
   - **API Permissions**: check `Fantasy Sports` → `Read`

2. Copy `.env.template` to `.env`:
   ```bash
   cp .env.template .env
   ```

3. Paste your **Client ID** and **Client Secret** into `.env`:
   ```
   YAHOO_CONSUMER_KEY=your_client_id_here
   YAHOO_CONSUMER_SECRET=your_client_secret_here
   ```

4. On first run, a browser window will open for OAuth authorization. Allow access and paste the verification code when prompted.

### 3. League Configuration

Update `.env` with your league details:
```
YAHOO_LEAGUE_ID=94443
YAHOO_TEAM_ID=9
YAHOO_GAME_CODE=nba
```

## Usage

### Full Analysis (with Yahoo Fantasy)
```bash
python main.py
```

### NBA Stats Only (no Yahoo setup needed)
```bash
python main.py --skip-yahoo
```

### Additional Options
```bash
python main.py --top 25                    # Show top 25 recommendations
python main.py --days 7                    # Evaluate last 7 days of form
python main.py --claim                     # Submit a waiver claim interactively
python main.py --dry-run                   # Preview a claim without submitting
python main.py --faab-history              # Analyze league FAAB bid history
python main.py --strategy aggressive       # FAAB bidding strategy (value|competitive|aggressive)
python main.py --compact                   # Compact table: Player, Team, Z, Score, Injury, Schedule
python main.py --stream                    # Streaming mode: best pickup with a game tomorrow
python main.py --stream --dry-run          # Preview streaming picks without submitting
python main.py --watch                     # Run full analysis and email the report
python main.py --stream --watch            # Run streaming analysis and email the report
python main.py --list-leagues              # Show all your Yahoo Fantasy NBA leagues
python main.py --list-teams                # Show all teams in your league
python main.py --skip-yahoo --top 30
```

## How It Works

1. **Fetch Stats**: Pulls per-game stats for all NBA players via nba_api (volume-weighted FG%/FT%)
2. **Z-Score Ranking**: Computes z-scores across all 9 categories to create a single value metric
3. **Injury Report**: Fetches real-time injury data from ESPN's public JSON API — penalizes injured players (Out For Season → 0.0 multiplier, Out → 0.10, Day-to-Day → partial)
4. **Schedule Analysis**: Pulls the NBA schedule to weight players with more upcoming games higher (week-decay model)
5. **Roster Analysis**: Connects to Yahoo Fantasy to analyze your team's category strengths/weaknesses
6. **Need-Weighted Scoring**: Boosts waiver recommendations for players who fill your weakest categories, with optional punt-category mode
7. **Hot Pickup Detection**: Fetches recent game logs (last 3 games) and computes z-score deltas to identify breakout performers. Players trending upward get a recency boost in scoring.
8. **Trending Players**: Pulls Yahoo ownership-change data (percent-owned delta) to flag players being widely added across leagues. Trending players get an additional scoring boost.
9. **FAAB Bidding**: Analyzes league bid history (IQR outlier detection) and suggests bids using league-relative tiering, adjusted for roster strength
10. **Color-Coded Output**: ANSI color-coded terminal output — green (Healthy/STRONG), yellow (DTD/Below Avg), red (OUT/WEAK) — with `NO_COLOR` support
11. **Compact Mode**: `--compact` flag shows a condensed table (Player, Team, Z_Value, Adj_Score, Injury, Games_Wk)
12. **Output**: Ranked table of recommended pickups with stats, z-scores, injury status, hot-pickup indicators, and schedule data
13. **Auto-Detect League Settings**: On startup, reads Yahoo API league metadata (stat categories, roster positions, FAAB/waiver type, transaction limits) and auto-overrides config defaults — no manual tuning needed.
14. **League & Team Discovery**: `--list-leagues` shows all Yahoo Fantasy NBA leagues you belong to; `--list-teams` lists every team in the current league with IDs and manager names.
15. **Roster Impact Preview**: Before confirming a waiver claim, shows the per-category z-score delta (ADD vs. DROP) so you can see exactly which categories improve or regress.
16. **Streaming Mode**: `--stream` finds the best available waiver pickup whose team plays *tomorrow* (for overnight FAAB leagues), identifies your weakest roster spot, and shows the roster impact of the swap.
17. **IL/IL+ Smart Resolution**: In claim mode, drops the IL player directly to preserve all droppable players for bids. In streaming mode, compares z-scores — if the recovered IL player is close to (or better than) the worst roster player, keeps the IL player as a roster upgrade instead.
18. **Manual Fallback**: If your Yahoo app lacks write scope (Read/Write), the tool detects the 401 scope error on the first submission attempt and prints a step-by-step **Manual Action Plan** with exact player names, FAAB bids, and Yahoo UI instructions for all queued claims.
19. **Watch Mode & Email Reports**: `--watch` runs the analysis and emails an HTML report (with color-coded injury badges and score highlights). `--stream --watch` does the same for streaming picks. Designed for GitHub Actions nightly automation.

## Project Structure

```
nba-fantasy-advisor/
├── main.py                 # Entry point & CLI
├── config.py               # Settings & environment config
├── requirements.txt
├── .env.template           # Yahoo API credentials template
├── .env                    # Your credentials (git-ignored)
├── src/
│   ├── __init__.py
│   ├── nba_stats.py        # NBA stats scraping (nba_api) + hot-pickup z-delta engine
│   ├── yahoo_fantasy.py    # Yahoo Fantasy integration (yfpy) + auth retry + trending players
│   ├── waiver_advisor.py   # Recommendation engine (need-weighted + recency/trending boosts)
│   ├── injury_news.py      # Injury report via ESPN JSON API
│   ├── schedule_analyzer.py # NBA schedule & games-per-week analysis
│   ├── faab_analyzer.py    # FAAB bid history & suggested bids
│   ├── league_settings.py  # Yahoo league settings, FAAB balance, budget tracking
│   ├── transactions.py     # Waiver claims, FAAB bids & IL smart resolution
│   ├── notifier.py         # HTML email reports for watch/scheduled mode
│   └── colors.py           # ANSI color utilities for terminal output
├── .github/
│   └── workflows/
│       ├── nightly-watch.yml   # Nightly waiver report (11 PM ET)
│       └── daily-stream.yml    # Daily streaming picks (12:30 AM ET)
└── docs/
    ├── methodology.md      # Scoring model & algorithm details
    ├── setup-guide.md      # Installation & configuration
    ├── output-reference.md # Column definitions & output format
    ├── faab-analysis.md    # FAAB bid analysis system
    ├── transactions.md     # Transaction submission flow
    ├── schedule-analysis.md # Schedule scoring & FAAB adjustment
    ├── github-workflows.md # GitHub Actions setup & troubleshooting
    └── example-run.md      # Full annotated example output
```

## 9-Category Scoring

| Category | Stat | Higher is Better |
|----------|------|:----------------:|
| FG% | Field Goal Percentage | ✅ |
| FT% | Free Throw Percentage | ✅ |
| 3PM | Three-Pointers Made | ✅ |
| PTS | Points | ✅ |
| REB | Rebounds | ✅ |
| AST | Assists | ✅ |
| STL | Steals | ✅ |
| BLK | Blocks | ✅ |
| TO | Turnovers | ❌ |

## Data Sources

| Data | Source | Method |
|------|--------|--------|
| Player stats | [nba_api](https://github.com/swar/nba_api) | `LeagueDashPlayerStats` endpoint |
| Injury report | [ESPN](https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries) | Public JSON API (no auth required) |
| NBA schedule | [nba_api](https://github.com/swar/nba_api) | `LeagueGameFinder` / schedule endpoints |
| Fantasy rosters | [Yahoo Fantasy API](https://developer.yahoo.com/fantasysports/) | OAuth 2.0 via yfpy |
| Ownership trends | [Yahoo Fantasy API](https://developer.yahoo.com/fantasysports/) | `PercentOwned` delta via league player batch queries |

## Dependencies

- **nba_api** — NBA stats and schedule data
- **yfpy** — Yahoo Fantasy Sports API wrapper
- **pandas** — Data manipulation
- **requests** — HTTP client (ESPN injury API)
- **tabulate** — Terminal table formatting
- **python-dotenv** — Environment variable management

## Technical Notes

- **Dynamic game_id**: The Yahoo game_id (which changes every season) is auto-resolved via `get_current_game_info()` on each run — no manual config update needed across seasons.
- **OAuth retry**: yfpy's `get_response` refreshes the token on 401 but doesn't retry the request. The tool patches this with automatic re-authentication and back-off (up to 3 retries).
- **Unicode normalization**: Player names with diacritics (Dončić, Nurkić, Porziņģis) are handled via NFKD decomposition for reliable cross-source matching.
- **FAAB tier floors**: Percentile-based tier boundaries are clamped to absolute score minimums (Elite ≥ 4.0, Strong ≥ 2.5, etc.) to prevent weak waiver pools from inflating labels.
- **IQR outlier detection**: Premium/returning-star bids are separated from standard bids using IQR analysis, preventing them from skewing tier bid statistics.
- **Auto-detect droppable players**: When `AUTO_DETECT_DROPPABLE = True`, the tool ranks your roster by z-score and auto-identifies the bottom N players as drop candidates — no manual config edits needed when your roster changes. Use `UNDDROPPABLE_PLAYERS` to protect stashed players.
- **Smart transaction counting**: Multiple bids against the same drop player count as one transaction slot (unique drops, not total bids).
- **Roster-strength-aware FAAB**: Bids are adjusted based on your overall roster strength — weak rosters bid more aggressively, strong rosters bid conservatively.
- **Color-coded terminal output**: ANSI colors for injury status (red=OUT, yellow=DTD, green=Healthy), category assessments, z-scores, and FAAB budget status. Respects `NO_COLOR` env var and non-TTY output. Windows VT processing enabled automatically.
- **Compact display mode**: `--compact` flag reduces the recommendation table to key columns for quick scanning, including Hot (🔥) and Trending (📈) indicators.
- **Hot-pickup detection**: Fetches last N game logs per candidate and z-scores recent performance against season averages. Players with z_delta ≥ 1.0 are flagged as 🔥 Hot. Recency boost = `RECENCY_WEIGHT × z_delta` (additive to Adj_Score).
- **Yahoo trending integration**: Queries Yahoo ownership-change data in batches. Players gaining ≥ 5% ownership are flagged as 📈 Trending. Trending boost = `TRENDING_WEIGHT × min(delta/10, 3.0)` (additive to Adj_Score).
- **Expanded candidate pool**: When hot-pickup is enabled, the candidate pool is expanded to `TOP_N × 3` to ensure breakout performers ranked lower by season z-score are still evaluated.
- **Auto-detect league settings**: On startup, `apply_yahoo_settings()` reads the Yahoo API response and patches `WEEKLY_TRANSACTION_LIMIT`, `FAAB_ENABLED`, validates 9-cat stat categories, and reports roster slot counts — so your config matches your league automatically.
- **Streaming mode**: `--stream` fetches tomorrow's NBA schedule and filters the waiver pool to only players with a game tomorrow (designed for overnight FAAB auction leagues). Ranks them using the same need-weighted scoring. Shows your weakest roster spot and the roster impact of the top suggested swap. Also checks IL/IL+ compliance and may recommend activating a recovered IL player as the day's roster upgrade.
- **IL/IL+ smart resolution**: Two strategies based on context. **Claim flow** (`--claim`/`--dry-run`): drops the IL player directly — clears the violation and frees a roster spot without consuming any droppable players. **Streaming flow** (`--stream`): compares the IL player's z-score with the worst regular roster player — if close enough (`IL_SMART_DROP_Z_THRESHOLD`, default 0.5), drops the regular player and activates the IL player as a roster upgrade.
- **Manual fallback for read-only apps**: Yahoo's Developer Console currently only shows a "Read" toggle for Fantasy Sports. When API writes fail with a scope error, the tool automatically prints a Manual Action Plan with step-by-step Yahoo UI instructions for all queued claims (including IL resolution steps and FAAB bids). No code changes needed when write access is granted later.
- **Watch mode & email**: `--watch` sends an HTML email report after analysis. `--stream --watch` sends a streaming picks email. Uses Gmail SMTP with App Passwords. Designed for GitHub Actions cron automation (see `.github/workflows/`).

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
- Submit waiver claims and FAAB bids directly to Yahoo
- Auto-resolve IL/IL+ roster moves

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
python main.py --skip-yahoo --top 30
```

## How It Works

1. **Fetch Stats**: Pulls per-game stats for all NBA players via nba_api (volume-weighted FG%/FT%)
2. **Z-Score Ranking**: Computes z-scores across all 9 categories to create a single value metric
3. **Injury Report**: Fetches real-time injury data from ESPN's public JSON API — penalizes injured players (Out For Season → 0.0 multiplier, Out → 0.10, Day-to-Day → partial)
4. **Schedule Analysis**: Pulls the NBA schedule to weight players with more upcoming games higher (week-decay model)
5. **Roster Analysis**: Connects to Yahoo Fantasy to analyze your team's category strengths/weaknesses
6. **Need-Weighted Scoring**: Boosts waiver recommendations for players who fill your weakest categories, with optional punt-category mode
7. **FAAB Bidding**: Analyzes league bid history (IQR outlier detection) and suggests bids using league-relative tiering
8. **Output**: Ranked table of recommended pickups with stats, z-scores, injury status, and schedule data

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
│   ├── nba_stats.py        # NBA stats scraping (nba_api)
│   ├── yahoo_fantasy.py    # Yahoo Fantasy integration (yfpy) + auth retry
│   ├── waiver_advisor.py   # Recommendation engine
│   ├── injury_news.py      # Injury report via ESPN JSON API
│   ├── schedule_analyzer.py # NBA schedule & games-per-week analysis
│   ├── faab_analyzer.py    # FAAB bid history & suggested bids
│   ├── league_settings.py  # Yahoo league settings, FAAB balance, budget tracking
│   └── transactions.py     # Waiver claims, FAAB bids & IL moves
└── docs/
    ├── methodology.md      # Scoring model & algorithm details
    ├── setup-guide.md      # Installation & configuration
    ├── output-reference.md # Column definitions & output format
    ├── faab-analysis.md    # FAAB bid analysis system
    ├── transactions.md     # Transaction submission flow
    ├── schedule-analysis.md # Schedule scoring & FAAB adjustment
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

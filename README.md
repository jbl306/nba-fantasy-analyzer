# NBA Fantasy Advisor

Nightly waiver wire recommendation engine for Yahoo Fantasy Basketball (9-category H2H leagues).

Combines **nba_api** (real NBA stats) with **yfpy** (Yahoo Fantasy Sports API) to:
- Scrape current season NBA player stats
- Compute 9-category z-scores (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO)
- Analyze your roster's strengths and weaknesses
- Recommend the best available waiver wire pickups tailored to your team's needs

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
python main.py --top 25          # Show top 25 recommendations
python main.py --days 7           # Evaluate last 7 days of form
python main.py --skip-yahoo --top 30
```

## How It Works

1. **Fetch Stats**: Pulls per-game stats for all NBA players from nba_api
2. **Z-Score Ranking**: Computes z-scores across all 9 categories to create a single value metric
3. **Roster Analysis**: Connects to Yahoo Fantasy to analyze your team's category strengths/weaknesses
4. **Need-Weighted Scoring**: Boosts waiver recommendations for players who fill your weakest categories
5. **Output**: Ranked table of recommended pickups with stats and z-scores

## Project Structure

```
nba-fantasy-advisor/
├── main.py                 # Entry point & CLI
├── config.py               # Settings & environment config
├── requirements.txt
├── .env.template           # Yahoo API credentials template
├── .env                    # Your credentials (git-ignored)
└── src/
    ├── __init__.py
    ├── nba_stats.py        # NBA stats scraping (nba_api)
    ├── yahoo_fantasy.py    # Yahoo Fantasy integration (yfpy)
    └── waiver_advisor.py   # Recommendation engine
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

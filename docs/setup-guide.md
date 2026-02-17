# Setup Guide

This guide covers first-time setup, Yahoo OAuth authentication, and configuration.

---

## Prerequisites

- **Python 3.10+** (tested with 3.13)
- A **Yahoo Developer App** for OAuth2 credentials
- An active **Yahoo Fantasy Basketball** league

---

## 1. Create a Yahoo Developer App

1. Go to [https://developer.yahoo.com/apps/](https://developer.yahoo.com/apps/)
2. Click **Create an App**
3. Fill in:
   - **Application Name**: anything (e.g., "Fantasy Advisor")
   - **Application Type**: Installed Application
   - **API Permissions**: Fantasy Sports — Read
   - **Redirect URI**: `https://localhost:8443`
4. Click **Create App**
5. Copy the **Consumer Key** and **Consumer Secret**

---

## 2. Configure Environment

Copy the template and fill in your credentials:

```bash
cp .env.template .env
```

Edit `.env`:

```env
YAHOO_CONSUMER_KEY=your_consumer_key_here
YAHOO_CONSUMER_SECRET=your_consumer_secret_here
YAHOO_LEAGUE_ID=your_league_id
YAHOO_TEAM_ID=your_team_number
YAHOO_GAME_CODE=nba
```

### Finding Your League ID

1. Go to your Yahoo Fantasy Basketball league page
2. The URL looks like: `https://basketball.fantasysports.yahoo.com/nba/94443`
3. The number at the end (`94443`) is your **League ID**

### Finding Your Team ID

1. Go to your team page in the league
2. The URL looks like: `https://basketball.fantasysports.yahoo.com/nba/94443/9`
3. The last number (`9`) is your **Team ID**

---

## 3. Install Dependencies

Using a virtual environment (recommended):

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Required packages:
- `nba_api` — NBA.com stats API wrapper
- `yfpy` — Yahoo Fantasy Sports API wrapper
- `pandas` — Data manipulation
- `python-dotenv` — .env file loading
- `tabulate` — Pretty table output
- `requests` — HTTP client (ESPN injury API, etc.)

---

## 4. First Run (OAuth Authorization)

The first time you run the tool with Yahoo enabled, it will initiate an OAuth2 flow:

```bash
python main.py
```

1. A browser window opens to Yahoo's authorization page
2. Log in with your Yahoo account and **Allow** the app
3. Yahoo redirects to a page (may show an error — that's OK)
4. Copy the **verification code** from the URL or page
5. Paste it into the terminal when prompted

After successful authorization, the OAuth tokens are saved locally. Subsequent runs will not require re-authorization unless the token expires.

> **Note:** This step must be done interactively in a terminal. It cannot be automated.

---

## 5. Running the Tool

### Full analysis (Yahoo + NBA stats)

```bash
python main.py
```

### Quick mode (NBA stats only, no Yahoo)

```bash
python main.py --skip-yahoo
```

### Show more recommendations

```bash
python main.py --top 25
```

### Combine flags

```bash
python main.py --skip-yahoo --top 30
```

---

## 6. Configuration Reference

All configuration lives in `config.py` and can be adjusted:

### Stat Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| Minimum minutes | 15.0 | Players averaging fewer minutes are excluded |
| Minimum games | 5 | Players with fewer GP are excluded |

### Availability Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| `AVAILABILITY_HEALTHY` | 0.80 | GP rate above this = "Healthy" |
| `AVAILABILITY_MODERATE` | 0.60 | GP rate above this = "Moderate" |
| `AVAILABILITY_RISKY` | 0.40 | GP rate above this = "Risky" |
| Below 0.40 | — | "Fragile" |

### Activity Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| `INACTIVE_DAYS_THRESHOLD` | 10 | Days since last game to flag as "Inactive" |
| Active threshold | 3 days | Hardcoded; ≤3 days = Active |
| Questionable range | 4–10 days | Between active and inactive |

### Output Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `TOP_N_RECOMMENDATIONS` | 15 | Default number of recommendations |
| `DETAILED_LOG_LIMIT` | 50 | Number of candidates to fetch game logs for |

### FAAB Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `FAAB_ENABLED` | `False` | Set to `True` if your league uses FAAB bidding for waivers |
| `DEFAULT_FAAB_BID` | `1` | Fallback bid amount when no historical data is available |
| `FAAB_STRATEGY` | `"competitive"` | Default bid strategy: `"value"`, `"competitive"`, or `"aggressive"` |
| `FAAB_BUDGET_REGULAR_SEASON` | `300` | Total FAAB budget for the regular season |
| `FAAB_BUDGET_PLAYOFFS` | `100` | FAAB budget after playoff reset |
| `FAAB_MAX_BID_PERCENT` | `0.50` | Max percentage of remaining budget allowed on a single bid |

### Transaction & Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `WEEKLY_TRANSACTION_LIMIT` | `3` | Max transactions per week (resets Monday) |
| `SCHEDULE_WEEKS_AHEAD` | `2` | Number of upcoming weeks to analyze for schedule-based scoring |
| `SCHEDULE_WEIGHT` | `0.10` | How strongly schedule affects score multiplier (±10% per game delta) |

See [FAAB Bid Analysis](faab-analysis.md) for a detailed explanation of strategies and how bid suggestions work.
See [Schedule Analysis](schedule-analysis.md) for how schedule data is used in scoring and FAAB bids.

---

## 7. Troubleshooting

### "ModuleNotFoundError: No module named 'pandas'"

Ensure you've activated the virtual environment before running:

```bash
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### OAuth token expired

Delete the saved token file and re-run to re-authenticate:

```bash
python main.py
```

### "No players found" or empty results

- Check that the NBA season is active (stats are only available during the regular season and playoffs)
- Verify your league ID and team ID are correct in `.env`
- Try `--skip-yahoo` to confirm NBA stats are loading

### Rate limiting from nba_api

The NBA.com API can be rate-limited. The tool adds small delays between requests. If you encounter errors, wait a few minutes and retry.

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

> **Note:** You do **not** need to specify a `YAHOO_GAME_ID`. The tool auto-resolves the current season's game ID via the Yahoo API on each run, so it never goes stale across seasons.

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
- `yfpy` — Yahoo Fantasy Sports API wrapper
- `pandas` — Data manipulation
- `python-dotenv` — .env file loading
- `tabulate` — Pretty table output
- `requests` — HTTP client (ESPN APIs, NBA.com CDN)

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

### Streaming mode (best pickup with a game tomorrow)

```bash
python main.py --stream
```

### Watch mode (scheduled email report)

```bash
python main.py --watch
```

Runs the full analysis and emails the top recommendations. Designed for scheduled execution (GitHub Actions, Task Scheduler, cron) — see [Watch Mode Setup](#watch-mode--scheduled-email-reports) below.

### League & team discovery

```bash
python main.py --list-leagues             # Show all your NBA fantasy leagues
python main.py --list-teams               # Show all teams in your configured league
```

### Combine flags

```bash
python main.py --skip-yahoo --top 30
python main.py --compact                  # Condensed table output
python main.py --stream --compact          # Streaming in compact mode
```

> **Auto-detect:** League settings (stat categories, roster slots, FAAB mode, transaction limits) are automatically read from the Yahoo API on each run and override `config.py` defaults. Use `--list-leagues` and `--list-teams` to find the correct IDs for your `.env` file.

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
| `DETAILED_LOG_LIMIT` | 10 | Number of candidates to fetch game logs for |

### Roster Management

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_DETECT_DROPPABLE` | `True` | Auto-identify lowest-value roster players as drop candidates by z-score |
| `AUTO_DROPPABLE_COUNT` | `3` | Number of bottom-ranked players to flag as droppable |
| `UNDDROPPABLE_PLAYERS` | `[]` | Players that should never be auto-flagged (e.g., stashed injured stars) |
| `DROPPABLE_PLAYERS` | `[list]` | Manual droppable list (fallback when auto-detect is off; forced entries when on) |

### FAAB Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `FAAB_ENABLED` | `True` | Set to `True` if your league uses FAAB bidding for waivers |
| `DEFAULT_FAAB_BID` | `1` | Fallback bid amount when no historical data is available |
| `FAAB_BID_OVERRIDE` | `True` | Prompt to override suggested FAAB bid amount (`False` = auto-accept suggested bid) |
| `FAAB_STRATEGY` | `"competitive"` | Default bid strategy: `"value"`, `"competitive"`, or `"aggressive"` |
| `FAAB_BUDGET_REGULAR_SEASON` | `300` | Total FAAB budget for the regular season |
| `FAAB_BUDGET_PLAYOFFS` | `100` | FAAB budget after playoff reset |
| `FAAB_MAX_BID_PERCENT` | `0.50` | Max percentage of remaining budget allowed on a single bid |

### Transaction & Schedule Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `WEEKLY_TRANSACTION_LIMIT` | `3` | Max transactions per week (resets Monday) |
| `SCHEDULE_WEEKS_AHEAD` | `3` | Number of upcoming weeks to analyze for schedule-based scoring |
| `SCHEDULE_WEIGHT` | `0.10` | How strongly schedule affects score multiplier (±10% per game delta) |

### Hot Pickup & Trending Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `HOT_PICKUP_ENABLED` | `True` | Enable hot-pickup detection (recent game z-delta analysis + Yahoo trending) |
| `HOT_PICKUP_RECENT_GAMES` | `3` | Number of recent games to fetch for each candidate |
| `HOT_PICKUP_RECENCY_WEIGHT` | `0.25` | Additive boost per `z_delta` point for improving players |
| `HOT_PICKUP_TRENDING_WEIGHT` | `0.15` | Additive boost for trending players (scaled by ownership delta) |
| `HOT_PICKUP_MIN_DELTA` | `5` | Minimum %-ownership change to flag a player as 📈 Trending |
| `SCHEDULE_WEEK_DECAY` | `0.50` | Exponential decay factor for future week weighting |

### CLI Flags

| Flag | Description |
|------|-------------|
| `--skip-yahoo` | Skip Yahoo API; use NBA stats only |
| `--top N` | Show N recommendations (default: 15) |
| `--compact` | Condensed table output |
| `--claim` | Enter interactive claim submission flow (falls back to manual instructions if write access unavailable) |
| `--dry-run` | Preview claim XML without submitting |
| `--faab-history` | Fetch FAAB bid history for smart suggestions |
| `--strategy S` | FAAB strategy: `value`, `competitive`, `aggressive` |
| `--days N` | Schedule analysis window in days |
| `--stream` | Streaming mode — best pickup with a game tomorrow (overnight FAAB) |
| `--watch` | Run analysis once and email results (for scheduled/cron use) |
| `--list-leagues` | Show all your NBA fantasy leagues and exit |
| `--list-teams` | Show all teams in your league and exit |

See [FAAB Bid Analysis](faab-analysis.md) for a detailed explanation of strategies and how bid suggestions work.
See [Schedule Analysis](schedule-analysis.md) for how schedule data is used in scoring and FAAB bids.

---

## Watch Mode — Scheduled Email Reports

The `--watch` flag runs the full analysis once and emails you the results. Pair it with a scheduler so you wake up to waiver recommendations every morning.

### Email Setup (Gmail)

1. **Enable 2-Factor Authentication** on your Google account
2. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password for "Mail"
4. Add to your `.env`:

```env
NOTIFY_EMAIL_TO=joshua.lee89@gmail.com
NOTIFY_SMTP_PASSWORD=abcd efgh ijkl mnop    # 16-char app password (no spaces in .env)
```

### Option A: GitHub Actions (Recommended)

Runs on GitHub's servers at 11 PM ET every night — your laptop can be off.

1. **Push the repo to GitHub** (private repo is fine — free tier includes 2,000 minutes/month)

2. **Complete Yahoo OAuth locally** (one-time):
   ```bash
   python main.py --list-leagues
   ```
   This creates the OAuth tokens in your `.env` file.

3. **Add secrets** in your GitHub repo → Settings → Secrets and variables → Actions:

   | Secret | Value |
   |--------|-------|
   | `YAHOO_CONSUMER_KEY` | Your Yahoo app key |
   | `YAHOO_CONSUMER_SECRET` | Your Yahoo app secret |
   | `YAHOO_LEAGUE_ID` | Your league ID (e.g., `94443`) |
   | `YAHOO_TEAM_ID` | Your team number (e.g., `9`) |
   | `YAHOO_ACCESS_TOKEN` | From `.env` after OAuth |
   | `YAHOO_REFRESH_TOKEN` | From `.env` after OAuth |
   | `YAHOO_TOKEN_TYPE` | Usually `bearer` |
   | `NOTIFY_EMAIL_TO` | Your email address |
   | `NOTIFY_SMTP_PASSWORD` | Gmail App Password |

4. **Enable the workflow** in the Actions tab

The workflow file is at `.github/workflows/nightly-watch.yml`. It runs at 04:00 UTC (11:00 PM ET) daily and can also be triggered manually from the Actions tab.

> **Token refresh:** Yahoo OAuth tokens expire periodically. If the nightly run fails with an auth error, re-run `python main.py --list-leagues` locally to refresh the token, then update `YAHOO_ACCESS_TOKEN` and `YAHOO_REFRESH_TOKEN` in GitHub Secrets.

### Option B: Windows Task Scheduler

For running directly on your laptop (must be on and awake at the scheduled time):

1. Open **Task Scheduler** → Create Basic Task
2. **Trigger:** Daily at 11:00 PM
3. **Action:** Start a program
   - Program: `C:\Users\joshu\projects\.venv\Scripts\python.exe`
   - Arguments: `main.py --watch`
   - Start in: `C:\Users\joshu\projects\nba-fantasy-advisor`
4. In the task's **Conditions** tab:
   - ✅ Wake the computer to run this task
   - ❌ Start only if on AC power (uncheck to run on battery)
5. In **Settings** tab:
   - ✅ Run task as soon as possible after a scheduled start is missed

### Option C: WSL / Linux cron

```bash
# Edit crontab
crontab -e

# Run at 11 PM ET every day (adjust for your timezone)
0 23 * * * cd /mnt/c/Users/joshu/projects/nba-fantasy-advisor && /mnt/c/Users/joshu/projects/.venv/bin/python main.py --watch >> /tmp/nba-advisor.log 2>&1
```

### Testing

Verify email works before enabling the schedule:

```bash
python main.py --watch
```

This runs the full analysis and sends the email immediately. Check your inbox (and spam folder) for the report.

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

### "You must be logged in to view this league"

This is a known yfpy bug — it refreshes the OAuth token on a 401 but then continues processing the original failed response. The tool includes a retry patch that re-authenticates with back-off (up to 3 retries). If you still see this error persistently, delete the `.env` token fields and re-authenticate:

```bash
python main.py
```

### "No players found" or empty results

- Check that the NBA season is active (stats are only available during the regular season and playoffs)
- Verify your league ID and team ID are correct in `.env`
- Try `--skip-yahoo` to confirm NBA stats are loading

### ESPN API issues

The ESPN public APIs require no authentication and have generous rate limits. If requests fail, check your network connection and retry. The tool adds small delays between requests automatically.

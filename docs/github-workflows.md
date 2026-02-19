# GitHub Actions Workflows

The advisor ships with two GitHub Actions workflows that run automatically in the cloud — no laptop required. Both send results via email and can also be triggered manually from the GitHub Actions tab at any time.

---

## Overview

| Workflow | File | Auto Schedule | Manual | Command | Email Subject |
|----------|------|--------------|--------|---------|---------------|
| Nightly Waiver Report | `nightly-watch.yml` | 11:00 PM ET daily | ✅ | `--watch` | 🏀 Waiver Wire Report [team] |
| Daily Streaming Picks | `daily-stream.yml` | 12:30 AM ET daily | ✅ | `--stream --watch` | 🏀 Streaming Picks [team] |
| League Advisor | `league-advisor.yml` | — (on-demand only) | ✅ | `--team N --watch` | 🏀 Waiver Wire Report [team] |

All workflow files live in `.github/workflows/`.

> **League Advisor email:** League members just type their email in the workflow input — no secrets setup needed on their end. The repo owner's SMTP credentials (already configured as secrets) handle delivery.

---

## One-Time Setup

### 1. Complete Yahoo OAuth locally

The workflows authenticate with Yahoo using OAuth tokens stored as GitHub Secrets. You must generate these tokens locally first — the OAuth flow requires an interactive browser session that GitHub's servers can't complete.

```bash
python main.py --list-leagues
```

This will open a browser, ask you to authorize the app, and save the tokens to your `.env` file. You only need to do this once (tokens persist via refresh).

### 2. Push the repo to GitHub

A private repo works fine. Free tier includes 2,000 minutes/month — more than enough for two daily runs.

```bash
git remote add origin https://github.com/your-username/nba-fantasy-advisor.git
git push -u origin v2
```

### 3. Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add each of the following:

| Secret Name | Where to get it |
|-------------|----------------|
| `YAHOO_CONSUMER_KEY` | Your Yahoo Developer App |
| `YAHOO_CONSUMER_SECRET` | Your Yahoo Developer App |
| `YAHOO_LEAGUE_ID` | Your league URL, or `--list-leagues` output |
| `YAHOO_TEAM_ID` | Your team URL, or `--list-teams` output |
| `YAHOO_ACCESS_TOKEN` | Your `.env` file after local OAuth run |
| `YAHOO_REFRESH_TOKEN` | Your `.env` file after local OAuth run |
| `YAHOO_TOKEN_TYPE` | Your `.env` file — usually `bearer` |
| `NOTIFY_EMAIL_TO` | Your Gmail address |
| `NOTIFY_SMTP_PASSWORD` | Gmail App Password (see below) |

**Gmail App Password setup:**
1. Enable 2-Factor Authentication on your Google account
2. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password for "Mail"
4. Paste the 16-character password as the `NOTIFY_SMTP_PASSWORD` secret

### 4. Enable the workflows

Go to the **Actions** tab in your GitHub repo. If workflows are disabled, click **"I understand my workflows, go ahead and enable them"**.

Both workflows will now run on their automatic schedules and are available for manual dispatch.

---

## Workflow 1 — Nightly Waiver Report

**File:** `.github/workflows/nightly-watch.yml`

Runs the full waiver wire analysis and emails your top recommendations every night.

### Schedule

| Time Zone | Time |
|-----------|------|
| ET (EST) | 11:00 PM |
| ET (EDT) | 11:00 PM (03:00 UTC) |
| UTC | 04:00 |

### What it does

1. Checks out the repo and installs dependencies
2. Builds a `.env` from GitHub Secrets
3. Runs `python main.py --watch`:
   - Fetches your Yahoo league rosters
   - Pulls NBA stats and computes 9-category z-scores
   - Applies team-need weighting, injury multipliers, and schedule context
   - Sends an HTML email with the top waiver recommendations
4. Uploads CSV output as a run artifact (kept 7 days)

### Email format

Subject: **🏀 Waiver Wire Report — Feb 18**

The email includes:
- Ranked table: Player, Team, `Z_Value`, `Adj_Score`, Games this week, Injury status
- 🔥 Hot pickup and 📈 Trending flags
- Schedule context (current week dates and avg games/team)
- Color-coded scores (green = strong, grey = marginal)

### Manual trigger

Run it anytime from the Actions tab:

1. Go to **Actions** → **Nightly Waiver Report**
2. Click **Run workflow** → **Run workflow**

Useful for mid-week checks or after a major injury news.

---

## Workflow 2 — Daily Streaming Picks

**File:** `.github/workflows/daily-stream.yml`

Finds the best available player with a game **tomorrow** and emails streaming recommendations. Designed for overnight FAAB auction leagues where same-day pickups are not possible.

### Schedule

| Time Zone | Time |
|-----------|------|
| ET (EST) | 12:30 AM |
| ET (EDT) | 12:30 AM (04:30 UTC) |
| UTC | 05:30 |

Running after midnight allows overnight FAAB processing — the streaming picks target tomorrow's game slate so your claims are ready for the next day.

### What it does

1. Checks out the repo and installs dependencies
2. Builds a `.env` from GitHub Secrets
3. Runs `python main.py --stream --watch`:
   - Fetches tomorrow's NBA schedule
   - Filters the waiver pool to only players on teams playing tomorrow
   - Checks IL/IL+ compliance and evaluates smart drop strategies
   - Ranks candidates against your roster's weakest spot
   - Sends an HTML email with tomorrow's best streaming pickups
4. Uploads CSV output as a run artifact (kept 7 days)

### Email format

Subject: **🏀 Streaming Picks — Feb 18**

The email includes:
- Ranked table of available players with games tomorrow
- IL/IL+ action banner (if applicable) — activate a recovered IL player or drop to clear violation
- Roster impact preview for the top pick
- Injury and z-score context

### Manual trigger

The most common use case — trigger it manually during the day when you want to make a streaming add:

1. Go to **Actions** → **Daily Streaming Picks**
2. Click **Run workflow** → **Run workflow**
3. Check your email in ~2 minutes

---

## Artifacts

Both workflows upload their CSV outputs as run artifacts. To access them:

1. Go to **Actions** → click a completed run
2. Scroll to **Artifacts** at the bottom
3. Download `waiver-report-N` or `streaming-report-N`

Artifacts are kept for **7 days** before automatic deletion.

---

## Workflow 3 — League Advisor (on-demand, any team)

**File:** `.github/workflows/league-advisor.yml`

An on-demand workflow any league member can use. Pick your team from a dropdown, optionally enter an email address, and get a personalised waiver report. League members don't need to configure any secrets — the email is sent using the repo owner's SMTP credentials.

### Additional setup (repo owner)

Beyond the secrets listed above, add **one repository variable** for the League Advisor email feature:

1. Go to **Settings** → **Secrets and variables** → **Actions** → **Variables** tab
2. Add `NOTIFY_EMAIL_FROM` = your Gmail address (the one with the App Password)

This lets the workflow send reports *to* any league member's email *from* your account.

### Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| **team** | choice | ✅ | — | Your fantasy team (see reference table below) |
| **top_n** | string | ❌ | `10` | Number of recommendations |
| **email** | string | ❌ | — | Email address to receive the report (leave blank to skip) |

### How to use

1. Go to **Actions** → **League Advisor (pick your team)**
2. Click **Run workflow**
3. Select your team from the dropdown
4. Optionally enter your email address
5. Click **Run workflow**
6. When complete, download the artifact or check your inbox

### Team Reference Table

| ID | Team Name |
|----|-----------|
| 1 | the profeshunals |
| 2 | RAYNAUD's phenomenon |
| 3 | MeLO iN ThE TrAp |
| 4 | Dabham |
| 5 | Cool Cats |
| 6 | Rookie |
| 7 | Da Young OG |
| 8 | Old School Legends |
| 9 | jbl |
| 10 | Tanking for tanking's sake |
| 11 | Big Kalk |
| 12 | Kailash Gupta's Boss Team |

> **Note:** Team names may change during the season. Run `python main.py --list-teams` locally to see the current names, or check the dropdown in the workflow dispatch UI.

---

## Troubleshooting

### Workflow fails with "You must be logged in"

The Yahoo OAuth tokens have expired. Refresh them locally:

```bash
python main.py --list-leagues
```

Then update `YAHOO_ACCESS_TOKEN` and `YAHOO_REFRESH_TOKEN` in GitHub Secrets with the new values from your `.env`.

### "SMTP Authentication Error"

Your Gmail App Password is wrong or has been revoked. Generate a new one at [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) and update the `NOTIFY_SMTP_PASSWORD` secret.

### Email lands in spam

Add your GitHub Actions sender address to your Gmail contacts or mark as "Not spam" once. Gmail will learn.

### Workflow doesn't appear in Actions tab

Check that the YAML files exist on the branch GitHub is tracking and that workflows are enabled for the repo (Settings → Actions → General → Allow all actions).

### Running locally to test

Both commands work interactively on your machine:

```bash
# Test nightly report
python main.py --watch

# Test streaming picks
python main.py --stream --watch
```

These use your local `.env` and are the fastest way to verify email delivery before relying on the scheduled runs.

---

## UTC Offset Reference

GitHub Actions cron runs on UTC. Key conversions:

| ET Offset | Season | UTC Formula |
|-----------|--------|-------------|
| UTC-5 (EST) | Nov – Mar | ET + 5h |
| UTC-4 (EDT) | Mar – Nov | ET + 4h |

Both workflow comments include both EST and EDT equivalents so you can adjust the cron if needed.

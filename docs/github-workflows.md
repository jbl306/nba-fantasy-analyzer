# GitHub Actions Workflows

The advisor ships with two GitHub Actions workflows that run in the cloud — no laptop required.

| Workflow | Purpose |
|----------|---------|
| **Nightly Waiver Report** | Automated nightly run for the repo owner’s team |
| **League Advisor** | On-demand run for any league member (pick your team) |

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

### 3. Add GitHub Secrets & Variables

Go to your repo → **Settings** → **Secrets and variables** → **Actions**.

#### Secrets

Click **New repository secret** and add each of the following:

| Secret Name | Where to get it |
|-------------|----------------|
| `YAHOO_CONSUMER_KEY` | Your Yahoo Developer App |
| `YAHOO_CONSUMER_SECRET` | Your Yahoo Developer App |
| `YAHOO_ACCESS_TOKEN` | Your `.env` file after local OAuth run |
| `YAHOO_REFRESH_TOKEN` | Your `.env` file after local OAuth run |
| `YAHOO_TOKEN_TYPE` | Your `.env` file — usually `bearer` |
| `NOTIFY_SMTP_PASSWORD` | Gmail App Password (see below) |

#### Variables

Switch to the **Variables** tab and add:

| Variable Name | Value |
|---------------|-------|
| `YAHOO_LEAGUE_ID` | Your league ID (from `--list-leagues` output) |
| `NOTIFY_EMAIL_FROM` | Your Gmail address (the one with the App Password) |

`NOTIFY_EMAIL_FROM` is used by both workflows as the SMTP sender. For the League Advisor, league members type their own email in the workflow input — the report is sent from your account to their address.

**Gmail App Password setup:**
1. Enable 2-Factor Authentication on your Google account
2. Go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password for "Mail"
4. Paste the 16-character password as the `NOTIFY_SMTP_PASSWORD` secret

### 4. Enable the workflows

Go to the **Actions** tab in your GitHub repo. If workflows are disabled, click **"I understand my workflows, go ahead and enable them"**.

The Nightly Waiver Report will run on its automatic schedule; the League Advisor is always available for manual dispatch.

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

## Artifacts

Both workflows upload their outputs as run artifacts. To access them:

1. Go to **Actions** → click a completed run
2. Scroll to **Artifacts** at the bottom
3. Download `waiver-report-N` or `waiver-report-team-N`

Artifacts are kept for **7 days** before automatic deletion.

---

## Workflow 2 — League Advisor (on-demand, any team)

**File:** `.github/workflows/league-advisor.yml`

An on-demand workflow any league member can use. Pick your team from a dropdown, optionally enter an email address, and get a personalised waiver report. League members don’t need to configure any secrets — the email is sent from the repo owner’s Gmail using the `NOTIFY_EMAIL_FROM` variable and `NOTIFY_SMTP_PASSWORD` secret already configured above.

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

```bash
# Test nightly report (your team)
python main.py --watch

# Test for another team
python main.py --team 3 --watch
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

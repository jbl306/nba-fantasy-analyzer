# Methodology

This document describes how the NBA Fantasy Advisor generates waiver wire recommendations for 9-category head-to-head Yahoo Fantasy Basketball leagues.

## Pipeline Overview

The recommendation engine runs a multi-step pipeline, with optional FAAB analysis and transaction submission:

```
┌──────────────────────────────────────────────────┐
│  1. Connect to Yahoo Fantasy                     │
│     Authenticate via OAuth2 and query the league │
├──────────────────────────────────────────────────┤
│  1b. Auto-detect league settings                 │
│     Read stat categories, roster slots, FAAB,    │
│     transaction limits from Yahoo API            │
├──────────────────────────────────────────────────┤
│  2. Scan all league rosters                      │
│     Fetch every team's roster → owned player set │
├──────────────────────────────────────────────────┤
│  3. Fetch player stats from Yahoo Fantasy API    │
│     Season per-game stats for all NBA players    │
│     via batched game-level stat queries           │
├──────────────────────────────────────────────────┤
│  4. Filter to available players only             │
│     Remove all owned players from the stats pool │
├──────────────────────────────────────────────────┤
│  5a. Check recent game activity                  │
│     DataFrame-based availability analysis        │
├──────────────────────────────────────────────────┤
│  5a-i. Hot-pickup analysis                       │
│     Recent-game z-delta breakout detection (🔥)   │
├──────────────────────────────────────────────────┤
│  5a-ii. Yahoo trending / ownership data          │
│     Ownership-change delta for trending (📈)      │
├──────────────────────────────────────────────────┤
│  5b. Fetch injury report (ESPN JSON API)         │
│     Injuries, suspensions + news blurbs          │
├──────────────────────────────────────────────────┤
│  5b-ii. Player news analysis                     │
│     ESPN blurbs + Yahoo notes + ESPN scoreboard  │
│     → role/performance keywords → news_mult      │
├──────────────────────────────────────────────────┤
│  5c. Fetch NBA schedule                          │
│     Remaining games per team this week + future  │
├──────────────────────────────────────────────────┤
│  6. Score, rank, and output recommendations      │
│     Z × needs × avail × injury × sched × news   │
│     + recency boost + trending boost             │
├──────────────────────────────────────────────────┤
│  7. FAAB bid analysis (optional, --faab-history) │
│     Fetch league transactions → bid suggestions  │
├──────────────────────────────────────────────────┤
│  8. Transaction submission (optional, --claim)   │
│     Multi-bid add/drop with roster impact preview│
├──────────────────────────────────────────────────┤
│  D. League discovery (--list-leagues/--list-teams)│
│     Show leagues, teams, IDs                     │
└──────────────────────────────────────────────────┘
```

Steps 7, 8, and D are optional modes. See [FAAB Bid Analysis](faab-analysis.md) and [Transactions](transactions.md) for details.

## Step 1 — Yahoo Fantasy Connection

Uses the [yfpy](https://github.com/uberfastman/yfpy) library to authenticate with the Yahoo Fantasy Sports API via OAuth2. On first run, a browser window opens for authorization. Subsequent runs use a saved refresh token stored in the `.env` file.

## Step 1b — Auto-Detect League Settings

Immediately after connecting, the tool reads the league's metadata from the Yahoo API and auto-overrides config defaults:

| Setting | Source | Config Override |
|---------|--------|----------------|
| Transaction limit | `max_adds` | `WEEKLY_TRANSACTION_LIMIT` |
| FAAB mode | `waiver_type` / `uses_faab` | `FAAB_ENABLED` |
| Stat categories | `stat_categories.stats` | Validated against expected 9-cat |
| Roster positions | `roster_positions` | Reports active/bench/IL slot counts |
| Team count | `num_teams` | Informational |

The stat category validation maps Yahoo stat IDs (e.g., `5` = FG%, `12` = PTS, `19` = TO) to the expected 9-category set and warns if any are missing or extra. This ensures the tool's z-score model matches your league's actual scoring categories.

## Step 2 — League Roster Scanning

Rather than relying on Yahoo's free agent endpoint (which can be slow and imprecise), the tool iterates through **every team** in the league and pulls their full roster. This produces a definitive set of owned player names so that recommendations only include truly available players.

The player name matching uses normalization (lowercase, strip punctuation, remove periods/hyphens) to handle differences between Yahoo and NBA.com name formats.

## Step 3 — Player Stats Fetching (Yahoo Fantasy API)

Pulls current-season per-game stats for all NBA players from the **Yahoo Fantasy Sports API** via batched game-level stat queries. The Yahoo API returns stats for all ~700+ NBA players using the league's actual stat category configuration, ensuring perfect alignment with your league's scoring.

Stats are fetched in batches of 25 player keys per API call, with each batch returning per-game averages for all configured stat categories (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO). Players are filtered to those with:

- **≥ 15.0 minutes per game** — excludes end-of-bench players with unreliable small-sample stats
- **≥ 5 games played** — ensures a minimum baseline of data

During this phase, the tool also captures Yahoo player metadata at zero additional API cost:
- **`has_recent_player_notes`** — flag for players with recent Yahoo news
- **`injury_note`** — Yahoo's injury designation if present
- **Player status** — roster status (e.g., IL, IL+, Active)

> **Why Yahoo + ESPN?** Yahoo's API is authenticated via OAuth2 and works reliably from any environment, including GitHub Actions. ESPN's public APIs provide boxscores, injuries, and news with no auth required. This combination avoids any dependency on `stats.nba.com` which aggressively blocks cloud/CI IP ranges.

## Step 4 — Availability Filtering

Cross-references the NBA stats pool against the owned player name set from Step 2. Any player whose normalized name matches an owned player is excluded. The remaining players are the **available waiver pool**.

## Step 5 — Recent Activity Check

Availability is now determined directly from the player stats DataFrame using season-long availability rate (`GP / Team GP`), eliminating the need for per-player game log API calls.

| Flag | Availability Rate | Meaning |
|------|-------------------|--------|
| **Healthy** | ≥ 80% | Durable, reliable starter |
| **Moderate** | 60–80% | Some missed time |
| **Risky** | 40–60% | Significant injury history |
| **Fragile** | < 40% | Rarely available |

This catches players who have great per-game averages but miss significant time due to injuries, suspensions, or G-League assignments. See the [Availability & Injury Risk](#availability--injury-risk) section for how this affects scoring.

> **API efficiency:** This step uses **0 API calls** — all data comes from the DataFrame already built in Step 3.

## Step 5b-ii — Player News Analysis

After fetching the injury report, the tool performs **keyword-based news analysis** to detect role/performance signals that affect a player's future fantasy value beyond raw stats. This analysis combines three data sources:

### Data Sources

| Source | API Calls | What It Provides |
|--------|-----------|------------------|
| ESPN injury blurbs | 0 (reuses injury data) | Role changes, return timelines, extended absences |
| Yahoo player notes flag | 0 (captured in Step 3) | `has_recent_player_notes` boolean |
| ESPN general news feed | 1 | Trade impacts, breakout articles, waiver buzz |
| ESPN boxscores | ~5 per day (3 days) | Full stat lines, starter flags, standout detection |

### Keyword Categories

**Positive signals** (multiplier > 1.0):

| Label | Example Pattern | Multiplier | Signal |
|-------|----------------|------------|--------|
| Starting | "step into the starting role" | ×1.15 | Lineup promotion |
| Will Start | "will start", "in the starting lineup" | ×1.12 | Confirmed start tomorrow |
| Next Man Up | "next man up" | ×1.12 | Teammate injury opens role |
| Career High | "career-high 38 points" | ×1.12 | Breakout performance |
| Cleared | "cleared to play" | ×1.12 | Returning from injury |
| Expected Starter | "expected to start", "projected starter" | ×1.10 | Likely starting tomorrow |
| Expanded Role | "bigger opportunity" | ×1.10 | More usage expected |
| Returning | "returning to action" | ×1.10 | Back from absence |
| No Restrictions | "no minutes restriction" | ×1.10 | Full workload |
| Waiver Buzz | "must-add", "waiver wire" | ×1.10 | Fantasy analyst recommendation |
| Breakout | "breakout season" | ×1.10 | Emerging talent |
| Near Return | "trending towards a return" | ×1.08 | Coming back soon |
| Debut | "making his debut" | ×1.08 | First game opportunity |
| 30+ PTS | Scoreboard: 32 PTS | ×1.08 | Recent dominant scoring |
| Double-Double | "double-double" | ×1.05 | Strong all-around game |
| Recent Starter | ESPN boxscore starter flag | ×1.08 | Started most recent game |

**Negative signals** (multiplier < 1.0):

| Label | Example Pattern | Multiplier | Signal |
|-------|----------------|------------|--------|
| Season-Ending | "season-ending surgery" | ×0.00 | Done for the year |
| Suspended | "arrested", "suspended" | ×0.60 | Legal/disciplinary |
| Indefinite | "indefinitely" | ×0.65 | No return timeline |
| G-League | "assigned to G-League" | ×0.70 | Sent down |
| No Timeline | "no timetable" | ×0.72 | Extended absence |
| Re-Injury | "re-aggravated" | ×0.75 | Setback |
| Week-to-Week | "week-to-week" | ×0.78 | Multi-week absence |
| DNP | "DNP" | ×0.80 | Not playing |
| Sitting Tomorrow | "sitting tomorrow", "out tomorrow" | ×0.78–0.80 | Confirmed miss |
| Re-Evaluation | "re-evaluated in 2 weeks" | ×0.82 | Extended absence |
| Ruled Out | "ruled out" | ×0.75 | Officially out |
| Benched | "moved to bench" | ×0.85 | Lineup demotion |
| Bench Role | "coming off the bench" | ×0.88 | Reduced minutes |
| Mins Restriction | "minutes restriction" | ×0.90 | Capped workload |
| Load Mgmt | "load management" | ×0.90 | Rest days expected |
| Traded | "traded to" | ×0.92 | Role uncertainty |

### ESPN Boxscore Standouts

The tool fetches ESPN game summaries (full boxscores) for the last 3 game-days, extracting per-player stat lines with starter/bench flags. Stat lines are evaluated against **waiver-calibrated thresholds** designed for the 8–14 PPG population typical of waiver candidates:

| Category | Tier 1 | Boost | Tier 2 | Boost | Tier 3 | Boost |
|----------|--------|-------|--------|-------|--------|-------|
| PTS | 15+ | ×1.03 | 22+ | ×1.05 | 30+ | ×1.08 |
| REB | 8+ | ×1.04 | 12+ | ×1.06 | — | — |
| AST | 6+ | ×1.04 | 10+ | ×1.06 | — | — |
| STL | 3+ | ×1.04 | 4+ | ×1.06 | — | — |
| BLK | 3+ | ×1.04 | 4+ | ×1.06 | — | — |
| 3PM | 4+ | ×1.04 | 6+ | ×1.06 | — | — |

Boxscore data also powers **hot-pickup analysis**: recent stat lines are converted to the same format as Yahoo game logs and z-scored against season averages, replacing per-date Yahoo API calls with free ESPN data.

Players who **started their most recent game** get a "Recent Starter" ×1.08 boost — a strong indicator they'll start tomorrow (relevant since pickups are for next day only).

### Combined News Multiplier

All matched keyword multipliers for a player are combined multiplicatively:

$$
M_{news} = \prod_{k \in \text{matched keywords}} m_k
$$

**Example:** A player whose ESPN blurb says "stepping into the starting role" (×1.15) and who also posted 31 PTS as a game leader (×1.08) receives $M_{news} = 1.15 \times 1.08 = 1.24$.

---

## Step 6 — Scoring & Ranking

The final score for each player combines multiple factors:

```
Adj_Score = (Z_Total + Need_Boost) × M_avail × M_injury × M_schedule × M_news
            + B_recency + B_trending
```

Each component is described below.

---

## 9-Category Z-Score Model

### What are z-scores?

A z-score measures how many **standard deviations** a player's stat is above or below the league average. A z-score of +1.5 in assists means the player averages 1.5 standard deviations more assists than the typical NBA player.

### Categories

The standard 9-category head-to-head format uses:

| Category | Stat | Direction |
|----------|------|-----------|
| FG% | Field Goal Percentage | Higher is better |
| FT% | Free Throw Percentage | Higher is better |
| 3PM | Three-Pointers Made per game | Higher is better |
| PTS | Points per game | Higher is better |
| REB | Rebounds per game | Higher is better |
| AST | Assists per game | Higher is better |
| STL | Steals per game | Higher is better |
| BLK | Blocks per game | Higher is better |
| TO | Turnovers per game | **Lower** is better |

### Calculation

#### Counting Stats (3PM, PTS, REB, AST, STL, BLK, TO)

For each counting-stat category, a standard z-score is computed:

$$
z_i = \frac{x_i - \mu}{\sigma}
$$

Where:
- $x_i$ = player's per-game stat
- $\mu$ = league average for that stat
- $\sigma$ = standard deviation across all qualifying players

For turnovers, the z-score is **inverted** (multiplied by -1) since fewer turnovers are better.

#### Percentage Stats — Volume-Weighted Impact (FG%, FT%)

Raw shooting percentages are misleading in H2H because a player's contribution to your team's FG% or FT% depends on both **accuracy** and **attempt volume**. In H2H matchups, your team's FG% is calculated as:

$$
\text{Team FG} = \frac{\sum \text{FGM}}{\sum \text{FGA}}
$$

A player shooting .650 on 2 FGA/game barely moves the needle, while a player shooting .520 on 16 FGA/game dominates the denominator. To capture this, FG% and FT% use **impact-based z-scores**:

$$
\textit{impact}_i = \text{FGA}_i \times (\text{FG}_i - \overline{\text{FG}})
$$

$$
z_{\text{FG}} = \frac{\textit{impact}_i - \mu_{\textit{impact}}}{\sigma_{\textit{impact}}}
$$

The same approach applies to FT% using FTA as the volume weight. This ensures that high-volume efficient shooters are properly rewarded and low-volume outliers are not overvalued.

**Example:** A center shooting .680 FG% on 3.5 FGA/game has an impact of $3.5 \times (0.680 - 0.475) = 0.72$. A wing shooting .490 FG% on 16 FGA/game has an impact of $16 \times (0.490 - 0.475) = 0.24$. Despite the wing having a lower FG%, the center's z-score is higher because his efficiency edge × volume produces more impact — but both are relatively modest. Compare to a star shooting .550 on 20 FGA: impact = $20 \times 0.075 = 1.50$ — clearly the most valuable for your team's FG%.

### Total Z-Score (Z_Value)

The raw player value is the **sum** of all non-punted category z-scores:

$$
Z\_Total = \sum_{c \notin \text{punt}} z_c
$$

A higher `Z_Total` means the player contributes positively across more categories. If no categories are punted, this is the sum of all 9 z-scores.

---

## Punt-Category Mode

In competitive 9-cat H2H leagues, many managers intentionally **punt** (give up) 1–2 weak categories to dominate the remaining 7. For example, a roster built around guards might punt blocks and rebounds to stack assists, steals, 3PM, and FT%.

The tool supports this via the `PUNT_CATEGORIES` config setting:

```python
# config.py
PUNT_CATEGORIES = ["BLK", "REB"]  # example: punt blocks and boards
```

When punt mode is active:

1. `Z_Total` excludes punted categories — a big man's block value won't inflate rankings if you're punting blocks.
2. **Team needs analysis** ignores punted categories — they won't appear as "weaknesses" you should address.
3. **Need-weighted boost** only considers non-punted categories — recommendations focus on your actual competitive categories.
4. **Individual z-score columns are still computed** — you can still see what a player does in punted cats, they just don't affect rankings.

Leave `PUNT_CATEGORIES = []` for a balanced build that optimizes across all 9 categories.

---

## Team Needs Analysis

### Roster Profiling

Your roster is matched against the NBA stats pool and each player's z-scores are computed. The tool then calculates the **average z-score per category** across your roster:

| Assessment | Team Avg Z-Score |
|------------|-----------------|
| **STRONG** | ≥ +0.50 |
| Average | 0.00 to +0.50 |
| Below Avg | -0.50 to 0.00 |
| **WEAK** | ≤ -0.50 |

### Need-Weighted Boost

The 3 weakest **non-punted** categories on your roster receive a **50% bonus weight** when scoring waiver candidates:

$$
Need\_Boost = \sum_{w \in \text{3 weakest}} z_w \times 0.5
$$

This means a player who is strong in your weak categories will rank higher than a generically good player who duplicates your existing strengths.

**Example:** If your team is weak in blocks and steals, a player with $z_{BLK}$ = +2.0 and $z_{STL}$ = +1.5 gets a bonus of `(2.0 + 1.5) × 0.5 = 1.75` added to their base score.

---

## Availability & Injury Risk

Player availability is evaluated on two dimensions:

### Season-Long Availability Rate

Measures what percentage of their team's games a player has actually appeared in:

$$
Avail\% = \frac{\text{Player GP}}{\text{Team GP}}
$$

| Flag | Avail% | Multiplier | Meaning |
|------|--------|------------|---------|
| **Healthy** | ≥ 80% | 1.00 (no penalty) | Durable, reliable starter |
| **Moderate** | 60–80% | 0.85 (15% penalty) | Some missed time |
| **Risky** | 40–60% | 0.65 (35% penalty) | Significant injury history |
| **Fragile** | < 40% | 0.45 (55% penalty) | Rarely available |

### Recent Activity (Last 10 Days)

Fetched from individual game logs for the top 10 candidates:

| Flag | Days Since Last Game | Additional Multiplier |
|------|---------------------|----------------------|
| **Active** | ≤ 3 days | 1.00 (no penalty) |
| **Questionable** | 4–10 days | 0.75 (25% penalty) |
| **Inactive** | > 10 days | 0.30 (70% penalty) |

### Combined Effect

The multipliers stack multiplicatively. A player who is "Risky" season-long AND currently "Inactive" receives:

$$
\text{Combined Multiplier} = 0.65 \times 0.30 = 0.195
$$

This means their adjusted score is only ~20% of their raw talent value, effectively dropping them far down the rankings.

---

## Injury Report (ESPN API)

The tool fetches the current NBA injury report from [ESPN's public JSON API](https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries) — a structured endpoint that requires no authentication and returns comprehensive injury data for all 30 teams. This provides **real injury designations** and **detailed news blurbs** that override the game-log heuristics.

ESPN's API returns structured fields per player including `fantasyStatus` (OFS, OUT, GTD), injury type, body part, side, and projected return date. These are mapped to severity classifications:

| ESPN Status | Maps To | Meaning |
|-------------|---------|--------|
| `OFS` | Out For Season | Season-ending injury or surgery |
| `OUT` + extended keywords | Out (extended) | Multi-week absence |
| `OUT` | Out | Currently out, timeline varies |
| `GTD` + status "Out" | Out (game-time) | Listed out but day-to-day evaluation |
| `GTD` | Day-To-Day | Could play any game |

This is critical because a player like Jaren Jackson Jr. may have an 80%+ GP rate (looks "Healthy") but was just declared out for the season with knee surgery. The game log check might flag him as "Inactive" eventually, but the injury report catches it immediately with context.

### Injury Severity Classification

| Status | Label | Base Multiplier | Meaning |
|--------|-------|----------------|--------|
| Out For Season | `OUT-SEASON` | 0.00 | **Hard exclusion** — removed from recommendations entirely |
| Suspended | `SUSP` | Dynamic (see below) | Computed from suspension length vs. remaining fantasy games |
| Out | `OUT` | 0.10 | Near-elimination; still visible for IL stash |
| Day To Day | `DTD` | 0.90 | Minor penalty; could play any game |

**Hard exclusion:** Players with a multiplier of exactly 0.0 (OUT-SEASON, long suspensions) are completely removed from the recommendation list — they are not just penalized, they are skipped. Additive boosts (recency, trending) cannot rescue a hard-excluded player.

**Near-elimination guard:** Players with a multiplier ≤ 0.05 have their additive boosts (recency, trending) zeroed out to prevent small positive signals from keeping a long-term-absent player on the list.

### Suspension Multiplier (Dynamic)

Suspended players receive a context-aware multiplier based on their team's remaining fantasy-season games rather than a static penalty. The suspension game count is parsed from the ESPN blurb text (e.g., "25-game suspension").

$$
\textit{availFrac} = \frac{\max(\textit{remainingGames} - \textit{suspensionGames},\; 0)}{\textit{remainingGames}}
$$

| Games Available / Remaining | Multiplier | Meaning |
|-----------------------------|------------|---------|
| 0% (misses all remaining games) | 0.00 (excluded) | Season-ending suspension |
| ≤ 15% | 0.03 | Nearly season-ending |
| ≤ 35% | 0.10 | Misses most remaining games |
| ≤ 60% | 0.30 | Misses a significant chunk |
| ≤ 85% | 0.60 | Moderate miss |
| > 85% | 0.85 | Minor miss (1-2 games) |

**Example:** A 25-game suspension with 20 remaining fantasy games → 0 games available → ×0.00 (hard exclusion). The same suspension with 80 remaining games → 55 available (69%) → ×0.30.

When schedule data is unavailable, the tool falls back to static thresholds: ≥10 games = 0.0, ≥5 = 0.03, ≥2 = 0.15, 1 = 0.85.

### Contextual Adjustments

The news blurb text is analyzed for keywords that refine the multiplier:

| Blurb Contains | Adjustment | Example |
|---------------|------------|--------|
| "rest of the season", "season-ending", "surgery", "no timetable", "torn ACL" | OUT → 0.05 | "Antetokounmpo has no timetable for a return" |
| "return after the all-star break", "progressed to", "on-court workouts" | OUT → 0.40 | "Curry won't return before the All-Star break" (implying return after) |
| Return-soon keywords + DTD | DTD → 0.95 | "Expected to return for Friday's game" |

This means two "Out" players can receive very different penalties based on their actual prognosis.

---

## Final Score Formula

Putting it all together:

$$
Adj\_Score = \left( Z\_Total + \sum_{w \in \text{3 weakest}} z_w \times 0.5 \right) \times M_{avail} \times M_{injury} \times M_{schedule} \times M_{news} + B_{recency} + B_{trending}
$$

Where:
- $Z\_Total$ = sum of 9 category z-scores (raw talent)
- $z_w$ = z-score in each of the team's 3 weakest categories (need boost)
- $M_{avail}$ = season availability multiplier (based on GP / Team GP ratio)
- $M_{injury}$ = injury/suspension report multiplier (0.0 to 1.0; 1.0 if not on report)
- $M_{schedule}$ = schedule multiplier based on team games vs league average (see [Schedule Analysis](schedule-analysis.md))
- $M_{news}$ = player news multiplier from keyword analysis (see [Step 5b-ii](#step-5b-ii--player-news-analysis))
- $B_{recency}$ = `HOT_PICKUP_RECENCY_WEIGHT` × `z_delta` (only when positive; 0 otherwise)
- $B_{trending}$ = `HOT_PICKUP_TRENDING_WEIGHT` × min(Δ%Own / 10, 3.0) (only when 📈 trending)

### Multiplicative Core

All multipliers stack multiplicatively. A player who is "Moderate" season-long, "Inactive" recently, and "Out" on the injury report:

$$
\text{Combined} = 0.85 \times 0.30 \times 0.10 = 0.0255
$$

### Additive Boosts

The recency and trending boosts are **additive** — they are applied after the multiplicative core. This means a breakout performer (🔥) or trending player (📈) gets a fixed signal bonus regardless of schedule multiplier.

However, for near-eliminated players ($M_{injury} \leq 0.05$), additive boosts are zeroed out to prevent small positive signals from keeping a long-term-absent player on the list. Players with $M_{injury} = 0.0$ are hard-excluded entirely.

### Hard Exclusion

Players with `OUT-SEASON` status or long suspensions ($M_{injury} = 0.0$) are completely removed from the recommendation list before scoring. They cannot appear in the output regardless of their raw z-score, trending status, or hot-pickup signal.

Players are sorted by `Adj_Score` descending. The top N (default: 15) are displayed as recommendations.

---

## Roster Impact Preview

Before confirming a waiver claim (in `--claim` or `--dry-run` mode), a roster impact preview shows the per-category z-score delta:

$$
\Delta z_c = z_{\text{add},c} - z_{\text{drop},c}
$$

for each non-punted category $c$. The net z-score change is the sum across all categories:

$$
\text{net} = \sum_c \Delta z_c
$$

Deltas ≥ +0.3 are highlighted green (improvement), ≤ −0.3 red (regression). This shows exactly which categories improve or worsen from a swap, so you can make informed decisions.

---

## League & Team Discovery

The discovery commands (`--list-leagues`, `--list-teams`) help you find the correct league and team IDs for your `.env` configuration:

- **`--list-leagues`** queries the Yahoo API for all NBA Fantasy leagues you belong to in the current season and displays their IDs, names, team counts, and scoring types.
- **`--list-teams`** lists all teams in your configured league with team IDs, manager names, and a marker for your own team.

Both commands run and exit without performing full analysis.

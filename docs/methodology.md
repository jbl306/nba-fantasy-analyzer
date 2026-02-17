# Methodology

This document describes how the NBA Fantasy Advisor generates waiver wire recommendations for 9-category head-to-head Yahoo Fantasy Basketball leagues.

## Pipeline Overview

The recommendation engine runs a six-step pipeline, with optional FAAB analysis and transaction submission:

```
┌──────────────────────────────────────────────────┐
│  1. Connect to Yahoo Fantasy                     │
│     Authenticate via OAuth2 and query the league │
├──────────────────────────────────────────────────┤
│  2. Scan all league rosters                      │
│     Fetch every team's roster → owned player set │
├──────────────────────────────────────────────────┤
│  3. Fetch NBA stats from nba_api                 │
│     Season per-game stats for all NBA players    │
├──────────────────────────────────────────────────┤
│  4. Filter to available players only             │
│     Remove all owned players from the stats pool │
├──────────────────────────────────────────────────┤
│  5a. Check recent game activity (top 50)         │
│     Game logs to detect injuries / inactivity    │
├──────────────────────────────────────────────────┤
│  5b. Fetch injury report (ESPN JSON API)         │
│     Real injury designations + news blurbs       │
├──────────────────────────────────────────────────┤
│  6. Score, rank, and output recommendations      │
│     Z-scores × team needs × avail × injury       │
├──────────────────────────────────────────────────┤
│  7. FAAB bid analysis (optional, --faab-history) │
│     Fetch league transactions → bid suggestions  │
├──────────────────────────────────────────────────┤
│  8. Transaction submission (optional, --claim)   │
│     Multi-bid add/drop claims via Yahoo API      │
└──────────────────────────────────────────────────┘
```

Steps 7 and 8 are optional post-analysis actions. See [FAAB Bid Analysis](faab-analysis.md) and [Transactions](transactions.md) for details.

## Step 1 — Yahoo Fantasy Connection

Uses the [yfpy](https://github.com/uberfastman/yfpy) library to authenticate with the Yahoo Fantasy Sports API via OAuth2. On first run, a browser window opens for authorization. Subsequent runs use a saved refresh token stored in the `.env` file.

## Step 2 — League Roster Scanning

Rather than relying on Yahoo's free agent endpoint (which can be slow and imprecise), the tool iterates through **every team** in the league and pulls their full roster. This produces a definitive set of owned player names so that recommendations only include truly available players.

The player name matching uses normalization (lowercase, strip punctuation, remove periods/hyphens) to handle differences between Yahoo and NBA.com name formats.

## Step 3 — NBA Stats Fetching

Pulls current-season per-game stats for all qualifying NBA players from the [nba_api](https://github.com/swar/nba_api) library via the `LeagueDashPlayerStats` endpoint. Players are filtered to those with:

- **≥ 15.0 minutes per game** — excludes end-of-bench players with unreliable small-sample stats
- **≥ 5 games played** — ensures a minimum baseline of data

## Step 4 — Availability Filtering

Cross-references the NBA stats pool against the owned player name set from Step 2. Any player whose normalized name matches an owned player is excluded. The remaining players are the **available waiver pool**.

## Step 5 — Recent Activity Check

For the top 50 waiver candidates (by raw z-score), the tool fetches individual game logs from `nba_api` to determine:

- **Last game date** — when the player last appeared in an NBA game
- **Days since last game** — how long they've been absent
- **Games in last 14 days** — recent volume of play

This catches players who have great season averages but are currently injured, suspended, or in the G-League. See the [Availability & Injury Risk](#availability--injury-risk) section for how this affects scoring.

## Step 6 — Scoring & Ranking

The final score for each player combines three factors:

```
Adj_Score = (Z_Total + Need_Boost) × Availability_Multiplier × Schedule_Multiplier
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
\text{Team FG\%} = \frac{\sum \text{FGM}}{\sum \text{FGA}}
$$

A player shooting .650 on 2 FGA/game barely moves the needle, while a player shooting .520 on 16 FGA/game dominates the denominator. To capture this, FG% and FT% use **impact-based z-scores**:

$$
\text{impact}_i = \text{FGA}_i \times (\text{FG\%}_i - \overline{\text{FG\%}})
$$

$$
z_{FG\%} = \frac{\text{impact}_i - \mu_{\text{impact}}}{\sigma_{\text{impact}}}
$$

The same approach applies to FT% using FTA as the volume weight. This ensures that high-volume efficient shooters are properly rewarded and low-volume outliers are not overvalued.

**Example:** A center shooting .680 FG% on 3.5 FGA/game has an impact of $3.5 \times (0.680 - 0.475) = 0.72$. A wing shooting .490 FG% on 16 FGA/game has an impact of $16 \times (0.490 - 0.475) = 0.24$. Despite the wing having a lower FG%, the center's z-score is higher because his efficiency edge × volume produces more impact — but both are relatively modest. Compare to a star shooting .550 on 20 FGA: impact = $20 \times 0.075 = 1.50$ — clearly the most valuable for your team's FG%.

### Total Z-Score (Z_Value)

The raw player value is the **sum** of all non-punted category z-scores:

$$
Z\_Total = \sum_{c \notin \text{punt}} z_c
$$

A higher Z_Total means the player contributes positively across more categories. If no categories are punted, this is the sum of all 9 z-scores.

---

## Punt-Category Mode

In competitive 9-cat H2H leagues, many managers intentionally **punt** (give up) 1–2 weak categories to dominate the remaining 7. For example, a roster built around guards might punt blocks and rebounds to stack assists, steals, 3PM, and FT%.

The tool supports this via the `PUNT_CATEGORIES` config setting:

```python
# config.py
PUNT_CATEGORIES = ["BLK", "REB"]  # example: punt blocks and boards
```

When punt mode is active:

1. **Z_Total** excludes punted categories — a big man's block value won't inflate rankings if you're punting blocks.
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

**Example:** If your team is weak in blocks and steals, a player with z_BLK = +2.0 and z_STL = +1.5 gets a bonus of `(2.0 + 1.5) × 0.5 = 1.75` added to their base score.

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

Fetched from individual game logs for the top 50 candidates:

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
| Out For Season | `OUT-SEASON` | 0.00 | Eliminated from recommendations entirely |
| Out | `OUT` | 0.10 | Near-elimination; still visible for IL stash |
| Day To Day | `DTD` | 0.90 | Minor penalty; could play any game |

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
Adj\_Score = \left( Z\_Total + \sum_{w \in \text{3 weakest}} z_w \times 0.5 \right) \times M_{avail} \times M_{recent} \times M_{injury} \times M_{schedule}
$$

Where:
- $Z\_Total$ = sum of 9 category z-scores (raw talent)
- $z_w$ = z-score in each of the team's 3 weakest categories (need boost)
- $M_{avail}$ = season availability multiplier (1.0 / 0.85 / 0.65 / 0.45)
- $M_{recent}$ = recent activity multiplier (1.0 / 0.75 / 0.30)
- $M_{injury}$ = injury report multiplier (0.0 to 1.0; 1.0 if not on injury report)
- $M_{schedule}$ = schedule multiplier based on team games vs league average (see [Schedule Analysis](schedule-analysis.md))

All multipliers stack multiplicatively. A player who is "Moderate" season-long, "Inactive" recently, and "Out" on the injury report:

$$
\text{Combined} = 0.85 \times 0.30 \times 0.10 = 0.0255
$$

Players are sorted by `Adj_Score` descending. The top N (default: 15) are displayed as recommendations.

# Schedule Analysis

This document covers the NBA schedule analysis system — how it fetches the league schedule, computes upcoming game counts per team, and integrates schedule data into waiver scoring and FAAB bid suggestions.

---

## Overview

In fantasy basketball, not all weeks are equal. Some teams play 4–5 games in a week while others play only 2–3. A player on a team with more games provides more stat production opportunities, making them more valuable for that specific week.

The schedule analyzer:

1. **Fetches the full NBA schedule** from NBA.com's CDN (with per-day fallback via nba_api)
2. **Computes game counts per team** for each upcoming fantasy week (Monday–Sunday)
3. **Applies a schedule multiplier** to waiver candidate scores based on games vs. league average
4. **Compares waiver targets vs. droppable players** by projected weekly production
5. **Adjusts FAAB bids** based on how many games the player's team has this week

---

## Schedule Data Sources

### Primary: NBA.com CDN JSON

The tool fetches the full season schedule from:

```
https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
```

This is a single HTTP request that returns every game for the entire season with dates, teams, and game IDs.

### Fallback: nba_api Scoreboardv2

If the CDN request fails, the tool falls back to querying `scoreboardv2` from `nba_api` for each day in the target range. This requires 7 API calls per week but provides the same data.

---

## Fantasy Week Definition

Fantasy weeks run **Monday through Sunday**. The tool computes upcoming weeks relative to the current date:

- If today is Monday–Saturday, "this week" starts on the most recent Monday
- "Next week" starts on the following Monday
- The `SCHEDULE_WEEKS_AHEAD` setting (default: 2) controls how many weeks to analyze

Example output:

```
Week 1: Feb 16 – Feb 22
Week 2: Feb 23 – Mar 01
```

---

## Game Count Analysis

For each upcoming week, the tool counts how many games each NBA team plays. **For the current week, only remaining games from today onward are counted** — games that have already been played are excluded, since they don't help a new pickup:", "oldString": "For each upcoming week, the tool counts how many games each NBA team plays:

```
────────────────────────────────────────
TEAM GAME COUNTS — Week 1: Feb 16 – Feb 22
────────────────────────────────────────
ATL: 4  BOS: 3  BKN: 4  CHA: 3  CHI: 4
CLE: 3  DAL: 4  DEN: 3  DET: 4  GSW: 3
HOU: 4  IND: 3  LAC: 3  LAL: 4  MEM: 3
MIA: 4  MIL: 3  MIN: 4  NOP: 3  NYK: 4
OKC: 3  ORL: 4  PHI: 3  PHX: 4  POR: 3
SAC: 4  SAS: 3  TOR: 4  UTA: 3  WAS: 4
────────────────────────────────────────
Average: 3.5 games | Range: 3 – 4
```

Key metrics computed:
- **Average games per team** across the league
- **Min / Max** game counts
- Per-team game dates for detailed scheduling

---

## Schedule Multiplier

The schedule multiplier adjusts a player's `Adj_Score` based on their team's game count relative to the league average.

### Multi-Week Decay Weighting

When multiple weeks of schedule data are available, the multiplier uses an **exponential decay** so the current week matters most and future weeks matter progressively less:

$$
\textit{weightedDelta} = \frac{\sum_{i=0}^{N-1} \lambda^{i} \cdot (g_i - \bar{g}_i)}{\sum_{i=0}^{N-1} \lambda^{i}}
$$

Where $\lambda$ = `SCHEDULE_WEEK_DECAY` (default 0.5), $g_i$ is the team's game count for week $i$, and $\bar{g}_i$ is the league average for that week.

**Example with 2 weeks:**

| Week | Games | Avg | Delta | Decay Weight | Contribution |
|------|-------|-----|-------|--------------|--------------|
| 0 (current) | 4 | 3.5 | +0.5 | 1.00 | +0.500 |
| 1 (next) | 2 | 3.5 | -1.5 | 0.50 | -0.750 |
| | | | | **Sum = 1.50** | **-0.250** |

$$
\textit{weightedDelta} = -0.250 / 1.50 = -0.167
$$

The final multiplier is then:

$$
\textit{scheduleMult} = 1.0 + \textit{scheduleWeight} \times \textit{weightedDelta}
$$

### Single-Week Fallback

When only one week is available, the formula simplifies to the original:

$$
\textit{scheduleMult} = 1.0 + \textit{scheduleWeight} \times (\textit{games} - \textit{avgGames})
$$

With `SCHEDULE_WEIGHT = 0.10` (default):

| Team Games | League Avg | Delta | Multiplier | Effect |
|-----------|------------|-------|------------|--------|
| 5 | 3.5 | +1.5 | 1.15× | +15% score boost |
| 4 | 3.5 | +0.5 | 1.05× | +5% score boost |
| 3 | 3.5 | -0.5 | 0.95× | -5% score penalty |
| 2 | 3.5 | -1.5 | 0.85× | -15% score penalty |

This is applied multiplicatively with all other score factors (needs, availability, injury):

$$
\textit{AdjScore} = \textit{NeedScore} \times M_{\text{avail}} \times M_{\text{injury}} \times M_{\text{schedule}}
$$

---

## Waiver vs. Droppable Comparison

The schedule report includes a head-to-head comparison of waiver targets against your droppable players, using projected weekly z-value:

$$
\textit{WeeklyValue} = \textit{ZperGame} \times \textit{gamesThisWeek}
$$

Where `Z_per_game = Z_Value / GP * team_GP_rate` is the player's per-game z-score contribution.

### Example Output

```
────────────────────────────────────────
WAIVER TARGETS: Projected Weekly Value
────────────────────────────────────────
  Player              Team  Games  Z/Game  Wk_Value
  De'Anthony Melton   DET     4    +0.87    +3.48
  Caris LeVert        CLE     3    +0.75    +2.25
  Bruce Brown         DEN     3    +0.52    +1.56

────────────────────────────────────────
DROPPABLE PLAYERS: Current Weekly Value
────────────────────────────────────────
  Player                    Team  Games  Z/Game  Wk_Value
  Sandro Mamukelashvili     MIN     4    +0.31    +1.24
  Justin Champagnie         IND     3    +0.28    +0.84

────────────────────────────────────────
NET VALUE: Waiver – Best Droppable
────────────────────────────────────────
  Waiver              Pick Up  Drop                      Net Gain
  De'Anthony Melton   +3.48    Sandro Mamukelashvili     +2.24
  Caris LeVert        +2.25    Sandro Mamukelashvili     +1.01
```

This helps answer the question: "Is this waiver pickup actually better than my worst player *this week*?"

---

## FAAB Bid Schedule Adjustment

Beyond the score multiplier, the schedule also directly influences FAAB bid amounts:

$$
\textit{scheduleFactor} = 1.0 + 0.15 \times (\textit{games} - \textit{avgGames})
$$

This is a stronger adjustment than the score multiplier (±15% per game vs. ±10%) because FAAB bids should more aggressively account for immediate weekly value.

See [FAAB Bid Analysis](faab-analysis.md#schedule-aware-bidding) for full details.

---

## Team Abbreviation Normalization

Yahoo Fantasy and NBA.com use different team abbreviations. The tool normalizes them automatically:

| Yahoo | NBA.com | Team |
|-------|---------|------|
| GS | GSW | Golden State Warriors |
| NO | NOP | New Orleans Pelicans |
| NY | NYK | New York Knicks |
| SA | SAS | San Antonio Spurs |
| WSH | WAS | Washington Wizards |
| PHO | PHX | Phoenix Suns |

All other abbreviations match between Yahoo and NBA.com.

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `SCHEDULE_WEEKS_AHEAD` | `3` | Number of upcoming weeks to analyze |
| `SCHEDULE_WEIGHT` | `0.10` | How strongly schedule affects the score multiplier (±10% per game delta) |
| `SCHEDULE_WEEK_DECAY` | `0.50` | Exponential decay factor for future weeks (1.0 = equal weight, 0.0 = current week only) |

---

## Architecture

```
src/schedule_analyzer.py
├── Data Fetching
│   ├── fetch_nba_schedule()              # Full season from NBA.com CDN
│   └── _fetch_schedule_per_day()         # Fallback: nba_api per day
├── Week Computation
│   └── get_upcoming_weeks()              # Mon–Sun ranges for N weeks
├── Game Counting
│   ├── get_team_game_counts()            # {team: count} in date range
│   └── get_team_game_dates()             # {team: [dates]} in date range
├── Analysis
│   ├── build_schedule_analysis()         # Multi-week analysis dict
│   └── compute_schedule_multiplier()     # Score multiplier from games vs avg
├── Comparison
│   ├── get_player_weekly_value()         # Z/game × games → weekly value
│   └── compare_waiver_vs_droppable()     # Head-to-head net value table
├── Display
│   └── format_schedule_report()          # Full formatted report
├── Runner
│   └── run_schedule_analysis()           # Top-level pipeline
└── Helpers
    └── normalize_team_abbr()             # Yahoo → NBA abbreviation mapping
```

---

## Limitations

- **Schedule changes:** NBA games can be postponed or rescheduled. The tool uses the latest available data but cannot predict future changes.
- **Back-to-back impact:** The tool counts total games but doesn't account for rest/fatigue from back-to-back games, which can reduce per-game production.
- **Playoff schedule:** NBA playoff schedule is not available until matchups are set, so late-season analysis may have limited forward visibility.
- **CDN availability:** The NBA.com CDN endpoint may occasionally be unavailable; the fallback to nba_api scoreboardv2 handles this automatically.

# Output Reference

This document describes every column and section in the waiver wire recommendation output.

---

## 1. Team Analysis (Yahoo Mode Only)

When connected to Yahoo, a team analysis section is printed first showing your roster's category strengths and weaknesses.

### Team Category Summary

```
=== YOUR TEAM'S CATEGORY ANALYSIS ===

Category      Team Avg Z    Assessment
──────────    ──────────    ──────────
FG%               +0.42    Average
FT%               +0.81    STRONG ↑
3PM               -0.15    Below Avg
PTS               +0.63    STRONG ↑
REB               -0.62    WEAK ↓
AST               +0.28    Average
STL               -0.71    WEAK ↓
BLK               -0.44    Below Avg
TO                +0.19    Average
```

| Column | Description |
|--------|-------------|
| **Category** | One of the 9 fantasy categories |
| **Team Avg Z** | Average z-score for that category across all players on your roster |
| **Assessment** | Qualitative label based on average z-score |

Assessment thresholds:

| Label | Z-Score Range |
|-------|---------------|
| STRONG ↑ | ≥ +0.50 |
| Average | +0.00 to +0.50 |
| Below Avg | -0.50 to +0.00 |
| WEAK ↓ | ≤ -0.50 |

### Priority Needs

After the category table, the top 3 weakest categories are listed as your **priority needs**. These categories receive the 0.5× bonus weight during scoring.

```
Priority needs: STL, REB, BLK
```

---

## 2. Recommendation Table

The main output is a ranked table of available waiver wire players.

### Example Output

```
=== TOP 15 WAIVER WIRE RECOMMENDATIONS ===

 Rank  Player             Team    GP  MIN  Avail%  Health    Recent       G/14d  FG%    FT%    3PM   PTS    REB    AST    STL   BLK   TO    Z_Value  Z_Delta  Hot  %Own  Δ%Own  Trending  Adj_Score
─────  ─────────────────  ─────  ───  ───  ──────  ────────  ───────────  ─────  ─────  ─────  ────  ─────  ─────  ─────  ────  ────  ────  ───────  ───────  ───  ────  ─────  ────────  ─────────
    1  Paul Reed           PHI     30  22   0.68    Moderate  Active(0d)      5   0.524  0.712  0.2   12.1    8.3    1.5   1.1   1.4   1.2    +3.82    +3.10  🔥    18    +12   📈         +6.44
    2  Nikola Jokic        DEN     55  34   0.92    Healthy   Active(1d)      6   0.567  0.831  1.0   26.8   12.7   10.2   1.3   0.8   3.5   +12.41    +0.45        92           +14.28
```

### Column Definitions

| Column | Source | Description |
|--------|--------|-------------|
| **Rank** | Computed | Position in the sorted recommendation list (1 = best pickup) |
| **Player** | nba_api | Full player name |
| **Team** | nba_api | NBA team abbreviation (e.g., DEN, PHI, LAL) |
| **GP** | nba_api | Games Played this season |
| **MIN** | nba_api | Average minutes per game |
| **Avail%** | Computed | Season availability rate: `GP / Team_GP`. Higher is better. |
| **Health** | Computed | Season durability flag (see table below) |
| **Injury** | ESPN API | Injury report status from ESPN (see table below) |
| **Recent** | Game Log | Recent activity status with days since last game (see table below) |
| **G/14d** | Game Log | Number of games played in the last 14 days. 0 likely means injured/out. |
| **FG%** | nba_api | Field Goal Percentage (per game) |
| **FT%** | nba_api | Free Throw Percentage (per game) |
| **3PM** | nba_api | Three-Pointers Made per game |
| **PTS** | nba_api | Points per game |
| **REB** | nba_api | Total rebounds per game |
| **AST** | nba_api | Assists per game |
| **STL** | nba_api | Steals per game |
| **BLK** | nba_api | Blocks per game |
| **TO** | nba_api | Turnovers per game |
| **Z_Value** | Computed | Sum of z-scores across all 9 categories. Raw talent ranking without adjustments. |
| **Z_Delta** | Computed | Difference between recent-game z-score and season z-score. Positive = improving, negative = declining. Color-coded: green (≥ 1.0), red (≤ -1.0). |
| **Hot** | Computed | 🔥 when Z_Delta ≥ 1.0 — player is performing significantly above their season average in recent games. |
| **%Own** | Yahoo API | Percentage of Yahoo leagues where the player is rostered (0–100). |
| **Δ%Own** | Yahoo API | Change in ownership percentage over the last week. Positive = rising demand. |
| **Trending** | Computed | 📈 when Δ%Own ≥ `HOT_PICKUP_MIN_DELTA` (default: 5) — player is being widely added across leagues. |
| **Adj_Score** | Computed | Final adjusted score factoring in team needs, availability, recent activity, schedule, recency boost, and trending boost. **This is the primary sort column.** |
| **Games_Wk** | Schedule | Remaining games this fantasy week (Mon–Sun). Games already played are excluded. More remaining games = more stat opportunity. |

### Health Flag

Based on season-long games played vs. team games played:

| Value | Avail% | Score Multiplier |
|-------|--------|-----------------|
| `Healthy` | ≥ 80% | ×1.00 |
| `Moderate` | 60–80% | ×0.85 |
| `Risky` | 40–60% | ×0.65 |
| `Fragile` | < 40% | ×0.45 |

### Injury Flag

Fetched from ESPN's public NBA injury API:

| Value | Meaning | Base Score Multiplier |
|-------|---------|----------------------|
| `OUT-SEASON` | Confirmed out for the remainder of the season | ×0.00 (removed from list) |
| `SUSP` | Suspended — multiplier computed from suspension games vs. remaining fantasy schedule | ×0.0 to ×0.85 (dynamic, see below) |
| `OUT` | Currently out, timeline varies | ×0.10 to ×0.40 (contextual) |
| `DTD` | Day-to-day, could play any game | ×0.90 to ×0.95 |
| `-` | Not on the injury report | ×1.00 (no penalty) |

The actual multiplier is adjusted based on keywords in the news blurb (e.g., "no timetable" makes it harsher, "return after break" makes it lighter). Players with a ×0.00 multiplier (OUT-SEASON, long suspensions) are fully excluded from the recommendation list.

#### Suspension Multiplier (Dynamic)

Suspension severity is computed relative to the team's remaining fantasy-season games, not just the raw game count:

| Games Available / Games Remaining | Multiplier | Meaning |
|-----------------------------------|------------|---------|
| 0% (misses entire remaining schedule) | ×0.00 (excluded) | Season-ending suspension |
| ≤ 15% | ×0.03 | Nearly season-ending |
| ≤ 35% | ×0.10 | Misses most remaining games |
| ≤ 60% | ×0.30 | Misses a significant chunk |
| ≤ 85% | ×0.60 | Moderate miss |
| > 85% | ×0.85 | Minor miss (1-2 games) |

For example, a 25-game suspension with only 20 remaining games → 0 games available → ×0.00 (excluded). The same 25-game suspension with 80 remaining games → 55 available (69%) → ×0.30.

### Recent Flag

Based on when the player last appeared in an NBA game:

| Value | Days Since Game | Score Multiplier |
|-------|----------------|-----------------|
| `Active(Nd)` | ≤ 3 days | ×1.00 |
| `Quest.(Nd)` | 4–10 days | ×0.75 |
| `INACTIVE(Nd!)` | > 10 days | ×0.30 |
| `N/A` | No game log data | ×0.30 |

`N` = number of days since their last game.

### Interpreting the Output

- **High Z_Value but low Adj_Score**: The player is talented but penalized for poor availability or current inactivity. They may be injured. Stash candidate for IR if your league supports it.
- **Adj_Score close to Z_Value**: The player is healthy, recently active, and may also address your team needs. This is an ideal pickup.
- **Adj_Score higher than Z_Value**: The player's stats align with your team's weakest categories, giving them a need-weighted bonus on top of raw talent.
- **High Games_Wk**: Players with more remaining games this week provide more stat opportunities. Combined with a high Adj_Score, these are premium pickups for the current week.
- **🔥 Hot indicator**: The player's last few games are significantly better than their season average (z_delta ≥ 1.0). This is a breakout signal — they may be emerging into a larger role or finding their rhythm.
- **📈 Trending indicator**: The player's ownership is rising rapidly across Yahoo leagues. Other managers are picking them up, so acting quickly is important before they're unavailable.
- **Positive Z_Delta but no 🔥**: The player is improving recently but not dramatically enough to qualify as "hot" (z_delta between 0 and 1.0). Still a mild positive signal.

---

## 2.4 League Settings & Constraints

When connected to Yahoo, a league settings report is displayed showing league rules and your current constraints:

```
======================================================================
  LEAGUE SETTINGS & CONSTRAINTS
======================================================================

  League:           My Fantasy League
  Scoring:          head
  Waiver type:      FAAB
  Current week:     14
  Playoff starts:   Week 20

  ────────────────────────────────────────
  FAAB BUDGET
  ────────────────────────────────────────
  Remaining:        $250
  Total budget:     $300
  Weeks left:       6
  Weekly budget:    $41.7
  Max single bid:   $125
  Budget status:    MODERATE

  ────────────────────────────────────────
  WEEKLY TRANSACTIONS
  ────────────────────────────────────────
  1 transaction remaining this week (2/3)
```

| Field | Description |
|-------|-------------|
| **Remaining** | Current FAAB balance from Yahoo |
| **Total budget** | $300 regular season or $100 playoffs |
| **Weeks left** | Weeks remaining in current phase |
| **Weekly budget** | Remaining ÷ weeks left |
| **Max single bid** | 50% of remaining budget |
| **Budget status** | FLEXIBLE (≥ 1.3×), COMFORTABLE (≥ 0.9×), MODERATE (≥ 0.6×), or CONSERVE (< 0.6×) |
| **Transactions** | Used vs. limit this week (resets Monday) |

---

## 2.5 Injury Report Notes

After the recommendation table, a separate section lists the detailed injury blurbs for any recommended player who appears on the injury report:

```
====================================================================================================
INJURY REPORT NOTES (source: ESPN)
====================================================================================================
  Walker Kessler            OUT-SEASON (Shoulder) - Kessler will undergo left shoulder surgery...
  Stephen Curry             OUT (Knee) - The Warriors said Curry won't return before the All-Star break...
  Trey Murphy III           DTD (Shoulder) - Murphy III did not return to Wednesday's game...
```

These blurbs provide the context needed to make informed pickup decisions — whether an injury is minor, multi-week, or season-ending.

---

## 2.6 Color-Coded Output

The tool uses ANSI color codes to highlight key information at a glance:

| Color | Used For |
|-------|----------|
| **Green** | Healthy status, STRONG assessment, positive z-scores, FLEXIBLE/COMFORTABLE budget |
| **Yellow** | DTD (Day-To-Day), Below Avg assessment, MODERATE budget |
| **Red** | OUT / OUT-SEASON / SUSP, WEAK assessment, negative z-scores, CONSERVE budget |
| **Cyan** | Section headers and titles |
| **Magenta** | Elite tier label |

Color output is automatically disabled when:
- The `NO_COLOR` environment variable is set (per [no-color.org](https://no-color.org/))
- Output is piped to a file or non-TTY stream

On Windows, the tool enables Virtual Terminal Processing so ANSI escape sequences render correctly in PowerShell and CMD.

---

## 2.7 Compact Display Mode

Use `--compact` to show a condensed recommendation table with only the most essential columns:

```bash
python main.py --compact
```

| Column | Description |
|--------|-------------|
| **Player** | Player name |
| **Team** | NBA team abbreviation |
| **Games_Wk** | Remaining games this week |
| **Injury** | Injury status (color-coded) |
| **Z_Value** | Raw 9-cat z-score |
| **Adj_Score** | Final adjusted score |
| **Hot** | 🔥 if breakout performer (z_delta ≥ 1.0) |
| **Trending** | 📈 if ownership rising rapidly |

All other columns (GP, MIN, Avail%, Health, Recent, G/14d, individual stat lines, Z_Delta, %Own, Δ%Own) are hidden in compact mode. The legend is also shortened.

---

## 3. Skip-Yahoo Mode

When running with `--skip-yahoo`, the tool cannot determine your team's roster or needs. In this mode:

- No team analysis section is printed
- Need-weighted boost is **not applied** (all candidates scored equally)
- All players meeting the minimum stat thresholds are considered "available" (no roster filtering)
- **Trending data is unavailable** — Yahoo ownership deltas require a Yahoo connection, so the Trending (📈), %Own, and Δ%Own columns will be empty
- Hot-pickup detection (🔥) still works since it uses NBA game log data only
- Output shows the same columns, but Adj_Score = Z_Value × availability multipliers + recency boost only
- Useful for a quick overview of the best unowned NBA performers regardless of league context

### Usage

```bash
python main.py --skip-yahoo
python main.py --skip-yahoo --top 25
```

---

## 4. CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--skip-yahoo` | off | Run without Yahoo connection; shows all qualifying NBA players ranked by z-score with availability adjustments |
| `--top N` | 15 | Number of recommendations to display |
| `--days N` | (season) | Currently reserved for future per-range stat window functionality |
| `--claim` | off | After analysis, enter interactive multi-bid transaction flow |
| `--dry-run` | off | Preview transactions without submitting (implies `--claim`) |
| `--compact` | off | Show condensed table: Player, Team, Games_Wk, Injury, Z_Value, Adj_Score only |
| `--faab-history` | off | Analyze league FAAB bid history and show suggested bids for all strategies |
| `--strategy` | `competitive` | Override FAAB bidding strategy: `value`, `competitive`, or `aggressive` |
| `--stream` | off | Streaming mode: find the best available player with a game today for your weakest roster spot |
| `--list-leagues` | off | Show all Yahoo Fantasy NBA leagues you belong to and exit |
| `--list-teams` | off | Show all teams in your league with IDs and managers, then exit |

---

## 5. FAAB Analysis Output

When running with `--faab-history`, additional output sections appear after the recommendation table:

### League Bid Summary

Overall FAAB bidding statistics (total transactions, mean/median/max bid, standard deviation).

### Bids by Player Quality Tier

A table showing bid distribution for each quality tier (Elite, Strong, Solid, Streamer, Dart) — including count, mean, median, min, max, P25, and P75 values.

### Spending by Team

Per-team spending breakdown (total spent, number of bids, average bid, max bid), sorted by total spending.

### Top 10 Biggest FAAB Bids

The largest individual bids placed in your league this season.

### Suggested FAAB Bids

Three tables (one per strategy: value, competitive, aggressive) showing suggested bid amounts for the top 10 waiver candidates, with tier classification, confidence level, remaining games this week, and reasoning. Bids are adjusted for:

- **Budget health** — scaled by budget factor (FLUSH/HEALTHY/TIGHT/CRITICAL)
- **Schedule value** — scaled by upcoming games vs. league average (±15% per game)
- **Safety caps** — never exceeds 50% of remaining budget or total remaining

See [FAAB Bid Analysis](faab-analysis.md) and [Schedule Analysis](schedule-analysis.md) for full details.

---

## 6. Schedule Analysis Output

When schedule data is available, a schedule comparison report is printed after the recommendations:

### Team Game Grid

Shows how many games each NBA team plays in the upcoming week(s).

### Waiver Targets: Projected Weekly Value

Shows each recommended waiver target with their team, remaining games this week, z-score per game, and projected weekly value (z/game × remaining games).

### Droppable Players: Current Weekly Value

Same metrics for your droppable players, allowing direct comparison.

### Net Value: Waiver – Best Droppable

Head-to-head comparison showing the net gain from picking up each waiver target vs. your best droppable player.

See [Schedule Analysis](schedule-analysis.md) for the complete methodology.

---

## 7. Auto-Detect League Settings

On startup (when Yahoo is connected), the tool reads your league's metadata via the Yahoo API and automatically overrides config defaults:

- **Transaction limit**: `WEEKLY_TRANSACTION_LIMIT` is set from the league's `max_adds` setting.
- **FAAB mode**: `FAAB_ENABLED` is set based on the league's waiver type (`FAAB` vs. waiver priority).
- **Stat categories**: Validates that the league uses the expected 9 scoring categories and warns if any are missing or extra.
- **Roster positions**: Reports active, bench, and IL slot counts from the league roster structure.
- **Team count**: Reports the number of teams in the league.

Example output:
```
  Auto-detected league settings:
    Transaction limit: 4 adds/week (from Yahoo)
    FAAB bidding: enabled (waiver_type=FAAB)
    Stat categories: 9/9 expected categories confirmed
    Roster: 10 active + 3 bench + 2 IL slots
    League size: 12 teams
```

---

## 8. League & Team Discovery

### `--list-leagues`

Shows all Yahoo Fantasy NBA leagues you belong to:

```
  Your NBA Fantasy Leagues (2):
  ID       Name                                Season   Teams   Scoring
  ──────── ─────────────────────────────────── ──────── ─────── ───────────────
  94443    My H2H League                        2024     12      head
  88712    Office Pool                          2024     10      roto
```

### `--list-teams`

Shows all teams in your current league with IDs and managers:

```
  Teams in League 94443 (12):
  ID    Team Name                      Manager              Yours
  ───── ────────────────────────────── ──────────────────── ─────
  1     Giannis Gang                   Mike                 
  9     Court Crushers                 Josh                  ←
  12    Block Party                    Sarah                
```

Use these to find the correct `YAHOO_LEAGUE_ID` and `YAHOO_TEAM_ID` for your `.env` file.

---

## 9. Roster Impact Preview

When submitting a waiver claim (`--claim` or `--dry-run`), a roster impact preview is shown before confirming:

```
  Roster Impact: ADD Nikola Jović / DROP Kevin Love
    FG% +0.3, FT% -0.1, 3PM +0.2, PTS +1.4, REB -0.5, AST +0.3, STL +0.1, BLK +0.2, TO -0.1  →  net +1.8 z-score
```

- Each category shows the z-score change (add_z − drop_z).
- Green values (≥ +0.3) indicate meaningful improvement; red (≤ −0.3) indicate regression.
- The net z-score summarises the total impact of the swap across all non-punt categories.

---

## 10. Streaming Mode (`--stream`)

Streaming mode finds the best available player with a game **today** and recommends them as a daily add/drop:

```bash
python main.py --stream
```

### How it works

1. Fetches today's NBA schedule to identify which teams play.
2. Filters the waiver pool to only players on teams with a game today.
3. Analyzes your roster to identify your weakest spot (lowest z-score player).
4. Scores streaming candidates using the same need-weighted algorithm.
5. Shows the top picks with a roster impact preview for the #1 recommendation.

### Example output

```
======================================================================
  STREAMING ADVISOR — Wednesday January 15, 2025
======================================================================

  8 games today — 16 teams playing
  42 available players with a game today

  Weakest roster spot: Kevin Love (z-score: -1.24)
  Target categories: STL, REB, BLK

==========================================================================================
BEST STREAMING PICKUPS FOR TODAY (Jan 15)
==========================================================================================

 Rank  Player            Team  Injury  FG%    FT%    3PM   PTS   REB   AST   STL  BLK  TO   Z_Value  Adj_Score
─────  ────────────────  ────  ──────  ─────  ─────  ────  ────  ────  ────  ───  ───  ───  ───────  ─────────
    1  Paul Reed         PHI   -       0.524  0.712  0.2   12.1  8.3   1.5   1.1  1.4  1.2    +3.82     +5.14
    ...

  Suggested move: ADD Paul Reed / DROP Kevin Love
  Roster impact:  FG% +0.1, REB +1.2, STL +0.3, BLK +0.8  →  net +2.1 z-score
```

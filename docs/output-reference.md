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

 Rank  Player             Team    GP  MIN  Avail%  Health    Recent       G/14d  FG%    FT%    3PM   PTS    REB    AST    STL   BLK   TO    Z_Value  Adj_Score
─────  ─────────────────  ─────  ───  ───  ──────  ────────  ───────────  ─────  ─────  ─────  ────  ─────  ─────  ─────  ────  ────  ────  ───────  ─────────
    1  Nikola Jokic       DEN     55  34   0.92    Healthy   Active(1d)      6   0.567  0.831  1.0   26.8   12.7   10.2   1.3   0.8   3.5   +12.41     +14.28
    2  Tyrese Maxey       PHI     40  38   0.71    Moderate  Active(0d)      7   0.451  0.874  3.6   27.1    3.8    6.2   1.0   0.5   2.4    +8.15      +9.87
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
| **Injury** | Scraped | Injury report status from Basketball-Reference (see table below) |
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
| **Adj_Score** | Computed | Final adjusted score factoring in team needs, availability, and recent activity. **This is the primary sort column.** |

### Health Flag

Based on season-long games played vs. team games played:

| Value | Avail% | Score Multiplier |
|-------|--------|-----------------|
| `Healthy` | ≥ 80% | ×1.00 |
| `Moderate` | 60–80% | ×0.85 |
| `Risky` | 40–60% | ×0.65 |
| `Fragile` | < 40% | ×0.45 |

### Injury Flag

Scraped from Basketball-Reference's injury report:

| Value | Meaning | Base Score Multiplier |
|-------|---------|----------------------|
| `OUT-SEASON` | Confirmed out for the remainder of the season | ×0.00 (removed) |
| `OUT` | Currently out, timeline varies | ×0.05 to ×0.40 (contextual) |
| `DTD` | Day-to-day, could play any game | ×0.90 to ×0.95 |
| `-` | Not on the injury report | ×1.00 (no penalty) |

The actual multiplier is adjusted based on keywords in the news blurb (e.g., "no timetable" makes it harsher, "return after break" makes it lighter).

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

---

## 2.5 Injury Report Notes

After the recommendation table, a separate section lists the detailed injury blurbs for any recommended player who appears on the injury report:

```
====================================================================================================
INJURY REPORT NOTES (source: Basketball-Reference)
====================================================================================================
  Walker Kessler            OUT-SEASON (Shoulder) - Kessler will undergo left shoulder surgery...
  Stephen Curry             OUT (Knee) - The Warriors said Curry won't return before the All-Star break...
  Trey Murphy III           DTD (Shoulder) - Murphy III did not return to Wednesday's game...
```

These blurbs provide the context needed to make informed pickup decisions — whether an injury is minor, multi-week, or season-ending.

---

## 3. Skip-Yahoo Mode

When running with `--skip-yahoo`, the tool cannot determine your team's roster or needs. In this mode:

- No team analysis section is printed
- Need-weighted boost is **not applied** (all candidates scored equally)
- All players meeting the minimum stat thresholds are considered "available" (no roster filtering)
- Output shows the same columns, but Adj_Score = Z_Value × availability multipliers only
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

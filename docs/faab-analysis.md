# FAAB Bid Analysis

This document covers the FAAB (Free Agent Acquisition Budget) bid analysis system — how it fetches historical league bidding data, classifies player quality into tiers, and suggests optimal bid amounts based on your league's spending patterns.

---

## Overview

In FAAB leagues, every manager starts the season with a fixed dollar budget and submits blind bids on waiver players. Winning the bid means getting the player, but overspending depletes your budget for the rest of the season.

This league uses a **$300 regular season budget** that **resets to $100 for the playoffs**.

The FAAB analyzer solves this problem by:

1. **Fetching all league transactions** from Yahoo Fantasy
2. **Classifying each pickup** into a quality tier based on the player's Adj_Score
3. **Computing bid statistics** per tier, per team, and league-wide
4. **Suggesting smart bid amounts** based on historical patterns and your chosen strategy
5. **Adjusting bids for budget health** — scales bids based on remaining budget vs. ideal weekly spend
6. **Adjusting bids for schedule value** — scales bids based on the player's team game count in the upcoming week

---

## Quality Tiers

Every player (both historical pickups and current waiver candidates) is assigned a quality tier based on their Adj_Score:

| Tier | Adj_Score Range | Description |
|------|----------------|-------------|
| **Elite** | ≥ 6.0 | Top-tier fantasy contributor across multiple categories |
| **Strong** | 4.0 – 5.99 | Well above average; likely starter value |
| **Solid** | 2.5 – 3.99 | Reliable contributor; fills a role |
| **Streamer** | 1.0 – 2.49 | Short-term value; good for weekly streaming |
| **Dart** | < 1.0 | Speculative; high-upside but inconsistent |

These tiers are used both for analyzing historical bid distribution and for generating new bid suggestions.

---

## Bid History Analysis

### Transaction Fetching

The analyzer calls `query.get_league_transactions()` via yfpy to retrieve every add/drop transaction that has occurred in your league this season. Each transaction is parsed to extract:

- **Player added** (name and player key)
- **Player dropped** (if add/drop swap)
- **FAAB bid amount** ($0 for free agent pickups)
- **Team** that made the transaction
- **Transaction type** (add or add/drop)

### Three Reports

The analysis produces three statistical breakdowns:

#### 1. League-Wide Summary

Overall bidding behavior across all teams:

```
Total transactions:  87
FAAB bids:           52
Free pickups ($0):   35

League bid mean:     $8.7
League bid median:   $5.0
Highest bid:         $47
Lowest bid:          $1
Bid std deviation:   $9.3
```

#### 2. Bids by Player Quality Tier

Bid distribution bucketed by what quality of player was picked up:

| Tier | Count | Mean | Median | Min | Max | P25 | P75 |
|------|-------|------|--------|-----|-----|-----|-----|
| Elite | 8 | $22.5 | $19 | $8 | $47 | $12 | $31 |
| Strong | 14 | $11.3 | $9 | $3 | $28 | $5 | $15 |
| Solid | 18 | $5.1 | $4 | $1 | $14 | $2 | $7 |
| Streamer | 9 | $2.4 | $2 | $1 | $6 | $1 | $3 |
| Dart | 3 | $1.3 | $1 | $1 | $2 | $1 | $2 |

This is the most important table — it tells you exactly what your league pays for each quality of player.

#### 3. Spending by Team

Shows which teams are aggressive spenders and which are conservative:

| Team | Total Spent | # Bids | Avg Bid | Max Bid |
|------|-------------|---------|---------|---------|
| Team A | $89 | 12 | $7.4 | $28 |
| Team B | $65 | 8 | $8.1 | $47 |
| ... | | | | |

Also shows the **Top 10 Biggest FAAB Bids** — the largest individual bids placed in your league.

---

## Bid Suggestion Strategies

When suggesting a bid for a waiver candidate, the analyzer maps the player's Adj_Score to a quality tier and then looks up that tier's historical bid distribution. Three strategies are available:

| Strategy | Percentile Used | Goal |
|----------|----------------|------|
| **value** | 25th percentile (P25) | Bargain hunting — win when competition is light |
| **competitive** | Median (P50) | Market rate — win about half the time |
| **aggressive** | 75th percentile (P75) | Maximize win rate — outbid most managers |

### How Suggestions Work

1. The player's Adj_Score determines their quality tier (e.g., `Adj_Score = 4.5` → Strong)
2. The tier's historical bid distribution is looked up (e.g., Strong tier: median = $9, P25 = $5, P75 = $15)
3. Based on your strategy, the corresponding percentile is selected as the base bid
4. Elite tier players get a small bump (+10%) to account for higher competition
5. If a tier has fewer than 2 historical bids, the system falls back to a score-based heuristic using the league median
6. **Budget factor** scales the bid based on your remaining budget health (see below)
7. **Schedule factor** scales the bid based on the player's upcoming game count (see below)
8. A hard cap ensures the bid never exceeds `max_single_bid` (50% of remaining budget) or total remaining budget

### Budget-Aware Bidding

The analyzer computes a **budget factor** based on your remaining FAAB balance:

$$
\text{budget\_factor} = \frac{\text{weekly\_budget}}{\text{ideal\_weekly\_budget}}
$$

Where `weekly_budget = remaining / weeks_remaining` and `ideal_weekly_budget = total_budget / total_weeks`.

The factor is clamped to [0.5, 2.0] to prevent extreme scaling:

| Budget Status | Budget Factor | Effect |
|---------------|---------------|--------|
| **FLUSH** | ≥ 1.30 | Bids scaled up — you can afford to be aggressive |
| **HEALTHY** | 0.90 – 1.29 | Bids near normal |
| **TIGHT** | 0.60 – 0.89 | Bids scaled down — conserve budget |
| **CRITICAL** | < 0.60 | Bids significantly reduced — survival mode |

The bid is multiplied by the budget factor, so a $10 base bid with a TIGHT budget (factor 0.75) becomes $8.

### Schedule-Aware Bidding

The analyzer also adjusts bids based on how many games the player's team plays in the upcoming fantasy week:

$$
\text{schedule\_factor} = 1.0 + 0.15 \times (\text{games} - \text{avg\_games})
$$

This provides a ±15% adjustment per game above or below the league average:

| Games This Week | Avg = 3.5 | Schedule Factor | Effect |
|----------------|-----------|-----------------|--------|
| 5 | +1.5 above | 1.225 | Bid up ~23% |
| 4 | +0.5 above | 1.075 | Bid up ~8% |
| 3 | -0.5 below | 0.925 | Bid down ~8% |
| 2 | -1.5 below | 0.775 | Bid down ~23% |

Players with more games this week provide more stat production opportunity, justifying a higher bid.

### Safety Caps

- **Max single bid:** 50% of remaining budget (`FAAB_MAX_BID_PERCENT = 0.50`)
- **Hard cap:** Never exceeds remaining budget
- Both caps are applied after all scaling factors

### Confidence Levels

Each suggestion includes a confidence rating:

| Confidence | Criteria | Meaning |
|------------|----------|---------|
| **high** | ≥ 5 bids in tier | Reliable — enough historical data |
| **medium** | 2–4 bids in tier | Reasonable estimate, limited sample |
| **low** | 0–1 bids in tier | Heuristic-based fallback |

### Example Output

```
======================================================================
  SUGGESTED FAAB BIDS (strategy: competitive)
======================================================================

   Player                    Adj_Score  Tier       Bid    Confidence  Reason
0  De'Anthony Melton            5.42    Strong     $9     high        Median bid for Strong tier (market rate)
1  Caris LeVert                 4.87    Strong     $9     high        Median bid for Strong tier (market rate)
2  Bruce Brown                  3.21    Solid      $4     high        Median bid for Solid tier (market rate)
3  Jalen Williams               2.18    Streamer   $2     medium      Median bid for Streamer tier (market rate)

Strategies: value (bargain) | competitive (market rate) | aggressive (ensure win)
```

When running `--faab-history`, all three strategies are displayed side by side so you can compare.

---

## CLI Usage

### Analyze FAAB history

```bash
python main.py --faab-history
```

Runs the full waiver analysis, then fetches and analyzes all league FAAB transactions. Prints the league summary, tier breakdown, team spending, top bids, and bid suggestions for all three strategies.

### Override bidding strategy

```bash
python main.py --faab-history --strategy aggressive
```

Sets the strategy used in the interactive claim flow (`--claim`). When viewing FAAB history, all three strategies are always shown regardless of this flag.

### Combine with claim mode

```bash
python main.py --claim --faab-history
```

Runs FAAB analysis first, then enters the interactive claim flow where each recommendation shows an inline bid suggestion (e.g., `~$9`) and the FAAB bid prompt pre-fills with the suggested amount.

### Preview without submitting

```bash
python main.py --claim --dry-run --faab-history
```

---

## Configuration

All FAAB settings are in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `FAAB_ENABLED` | `False` | Set to `True` if your league uses FAAB bidding |
| `DEFAULT_FAAB_BID` | `1` | Fallback bid when no historical data is available |
| `FAAB_STRATEGY` | `"competitive"` | Default strategy: `"value"`, `"competitive"`, or `"aggressive"` |
| `FAAB_BUDGET_REGULAR_SEASON` | `300` | Total FAAB budget for the regular season |
| `FAAB_BUDGET_PLAYOFFS` | `100` | FAAB budget after playoff reset |
| `FAAB_MAX_BID_PERCENT` | `0.50` | Max percentage of remaining budget allowed on a single bid |

The `--strategy` CLI flag overrides `FAAB_STRATEGY` at runtime.

> **Note:** `FAAB_ENABLED` controls whether the interactive claim flow (`--claim`) prompts for bid amounts and shows inline bid hints. The `--faab-history` flag works independently — you can analyze bid history even without `FAAB_ENABLED = True`.

### Budget Tracking

The system reads your remaining FAAB balance from Yahoo and computes budget health automatically. It displays:

- **Remaining budget** and **total budget** (regular season vs. playoffs)
- **Weeks remaining** in the current phase
- **Weekly budget** (remaining ÷ weeks left)
- **Budget status** (FLUSH / HEALTHY / TIGHT / CRITICAL)
- **Max single bid** (50% of remaining)

---

## Architecture

```
src/faab_analyzer.py
├── Constants
│   └── TIER_THRESHOLDS           # Quality tier definitions
├── Tier Classification
│   └── score_to_tier()           # Adj_Score → tier label
├── Data Fetching
│   └── fetch_league_transactions()  # Yahoo API → parsed transaction list
├── Analysis
│   ├── analyze_bid_history()     # Stats: overall, by_tier, by_team
│   ├── suggest_bid()             # Single player → bid recommendation
│   └── suggest_bids_for_recommendations()  # Batch bid suggestions
├── Display
│   ├── format_faab_report()      # Printable analysis report
│   └── format_bid_suggestions()  # Printable suggestion table
├── Runner
│   └── run_faab_analysis()       # Full pipeline: fetch → analyze → print → save
└── Helpers
    ├── _get_attr()               # Safe attribute access for yfpy objects
    ├── _get_faab_bid()           # Extract FAAB bid from transaction
    └── _extract_name()           # Parse player name from various shapes
```

### Output File

FAAB bid history is saved to `output/faab_analysis.csv` with columns: `transaction_id`, `timestamp`, `type`, `faab_bid`, `add_player_name`, `add_player_key`, `drop_player_name`, `drop_player_key`, `team_name`, `team_key`, `status`.

---

## Limitations

- **Tier accuracy for historical pickups:** Players who were picked up weeks ago may not appear in the current recommendation data. Their tier is marked as "Unknown" unless they show up in the current `rec_df`.
- **Bid competition is hidden:** Yahoo FAAB uses blind bidding — you only see the winning bid, not the losing bids. The analyzer can only learn from winning amounts.
- **Season progression:** Early-season bid patterns may differ from late-season (when budgets are depleted). The analyzer treats all bids equally.
- **Schedule changes:** NBA schedule can change due to postponements; the tool uses the most recent data from NBA.com but cannot predict future changes.

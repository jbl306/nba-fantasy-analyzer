# NBA Fantasy Advisor — Scoring Methodology

## Z-Score Calculation

For each stat category, the z-score measures how many standard deviations a
player is above or below the league average:

$$z = \frac{x - \mu}{\sigma}$$

### Volume-Weighted Categories (FG%, FT%)

Raw percentages are misleading — a player shooting 60% on 2 attempts per game
is less valuable than one shooting 50% on 15 attempts. Volume-weighted impact
z-scores solve this:

$$z_{FG\%} = z_{FGA} \times z_{FG\%_{raw}}$$

This credits both accuracy and volume.

### Turnovers (Inverted)

Lower turnovers are better, so the z-score is inverted:

$$z_{TO} = -1 \times \frac{TO - \mu_{TO}}{\sigma_{TO}}$$

## Composite Score

$$Z_{TOTAL} = \sum_{cat \notin PUNT} z_{cat}$$

## Roster Need Weighting

1. Compute your roster's average z-score per category
2. Identify weak categories (below roster mean)
3. Apply a multiplier (1.0 to 2.0) that boosts candidates who fill weak spots

## Injury Multipliers

| Status | Multiplier | Notes |
|--------|:----------:|-------|
| Out For Season | 0.00 | Player excluded |
| Out | 0.10 | Extended absence keywords → 0.05 |
| Day-to-Day | 0.90 | Return-soon keywords → 0.95 |
| Healthy | 1.00 | No injury listed |

## Availability Rate

$$availability = \frac{GP_{player}}{GP_{team}}$$

| Tier | Threshold | Penalty |
|------|:---------:|:-------:|
| Healthy | >= 85% | 0% |
| Moderate | >= 70% | 15% |
| Risky | >= 50% | 35% |
| Fragile | < 50% | 55% |

## Schedule Bonus

$$bonus = (games\_per\_week - league\_avg) \times SCHEDULE\_WEIGHT$$

Applied per week with decay: wk1 = 1.0, wk2 = 0.5, wk3 = 0.25.

## FAAB Tier Classification

| Tier | Criteria | Typical Bid Range |
|------|----------|:-----------------:|
| Elite | Top 5% z-score + score floor | $40–$80+ |
| Strong | Top 15% | $20–$40 |
| Solid | Top 35% | $8–$20 |
| Streamer | Top 60% | $3–$8 |
| Dart | Below 60% | $1–$3 |

IQR outlier detection separates premium bids (returning injured stars) from
standard bids to avoid inflating tier medians.

## Final Adjusted Score

$$Adj\_Score = Z_{TOTAL} \times need\_weight \times injury\_mult \times availability\_mult + schedule\_bonus$$

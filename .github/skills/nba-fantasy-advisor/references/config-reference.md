# NBA Fantasy Advisor — Configuration Reference

## Environment Variables (.env)

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `YAHOO_CONSUMER_KEY` | Yes | `""` | Yahoo Developer app Client ID |
| `YAHOO_CONSUMER_SECRET` | Yes | `""` | Yahoo Developer app Client Secret |
| `YAHOO_LEAGUE_ID` | No | `"94443"` | Yahoo Fantasy league ID |
| `YAHOO_TEAM_ID` | No | `9` | Your team number in the league |
| `YAHOO_GAME_CODE` | No | `"nba"` | Yahoo game code |

## config.py Settings

### Core Analysis

| Setting | Default | Description |
|---------|---------|-------------|
| `TOP_N_RECOMMENDATIONS` | `15` | Number of recommendations to display |
| `RECENT_GAMES_WINDOW` | `14` | Days to evaluate recent player form |
| `PUNT_CATEGORIES` | `[]` | Categories to exclude from scoring |
| `DROPPABLE_PLAYERS` | `[list]` | Players eligible for drop in claims |

### FAAB Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `FAAB_ENABLED` | `True` | Whether league uses FAAB bidding |
| `FAAB_STRATEGY` | `"competitive"` | Bid strategy: value/competitive/aggressive |
| `FAAB_BUDGET_REGULAR_SEASON` | `300` | Starting regular season FAAB budget |
| `FAAB_BUDGET_PLAYOFFS` | `100` | Playoff FAAB budget after reset |
| `FAAB_MAX_BID_PERCENT` | `0.50` | Max fraction of budget for one bid |
| `FAAB_BID_OVERRIDE` | `None` | Override suggested bid with fixed amount |

### Schedule Analysis

| Setting | Default | Description |
|---------|---------|-------------|
| `SCHEDULE_WEEKS_AHEAD` | `3` | Weeks of schedule to analyze |
| `SCHEDULE_WEIGHT` | `0.10` | Per-game delta impact on Adj_Score |
| `SCHEDULE_WEEK_DECAY` | `0.5` | Weight decay per future week |

### Availability Thresholds

| Setting | Default | Description |
|---------|---------|-------------|
| `AVAILABILITY_HEALTHY` | `0.85` | Threshold for "Healthy" flag |
| `AVAILABILITY_MODERATE` | `0.70` | Threshold for "Moderate" flag |
| `AVAILABILITY_RISKY` | `0.50` | Threshold for "Risky" flag |

### Stat Categories (9-Cat)

FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO

- FG% and FT%: Volume-weighted (accuracy × attempts)
- TO: Inverted (lower is better)

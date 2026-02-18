# NBA Fantasy Advisor — API Patterns

## External API Dependencies

### NBA.com (nba_api)

- **Stats endpoint**: `LeagueDashPlayerStats` — per-game averages for all players
- **Game logs**: `PlayerGameLog` — recent game-by-game stats
- **Schedule**: `cdn.nba.com/static/json/staticData/scheduleLeagueV2.json`
- **Fallback**: `ScoreboardV2` if CDN schedule unavailable
- **Auth**: None required
- **Rate limiting**: Respect 1-2 second delays between `nba_api` calls
- **Headers**: `nba_api` requires a valid `Referer` and `User-Agent`

### ESPN Injury API

- **Endpoint**: `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`
- **Auth**: None required
- **Format**: JSON array of teams with nested athlete injury entries
- **Key fields**: `athlete.displayName`, `status` (Out, Day-To-Day), `details.detail`
- **Failure mode**: Returns empty gracefully — analysis continues without injury data

### Yahoo Fantasy API (yfpy)

- **Auth**: OAuth2 (consumer key + secret → browser-based token flow)
- **Base**: `fantasysports.yahooapis.com/fantasy/v2/`
- **Key endpoints**:
  - `league/{game_key}.l.{league_id}/teams/roster` — all rosters
  - `league/{game_key}.l.{league_id}/settings` — league rules
  - `league/{game_key}.l.{league_id}/transactions` — FAAB history
  - `team/{game_key}.l.{league_id}.t.{team_id}/roster/players` — your roster
- **Transaction submission**: XML POST to Yahoo Fantasy API
- **Token refresh**: yfpy has a bug where 401 doesn't retry — patched in `yahoo_fantasy.py`
- **Rate limiting**: Yahoo may throttle; built-in retry with exponential back-off (3 attempts)

## Error Handling Patterns

### Common Error Codes

| Code | Source | Meaning | Handling |
|------|--------|---------|----------|
| 401 | Yahoo | Token expired | Auto-retry with re-auth (up to 3x) |
| 403 | NBA.com | Rate limited | Wait and retry |
| 404 | Yahoo | Invalid league/team ID | Check config |
| 500 | ESPN | Server error | Graceful fallback (skip injury data) |

### Retry Strategy

```python
# Exponential back-off pattern used throughout
for attempt in range(max_retries):
    try:
        result = api_call()
        break
    except AuthError:
        sleep(2 ** attempt)
        refresh_token()
```

## Data Flow

```
NBA.com Stats → Z-Scores → ┐
ESPN Injuries → Multipliers → ├→ Waiver Advisor → Ranked Recommendations
Yahoo Rosters → Owned Set   → ┤
NBA Schedule  → Game Density → ┘
```

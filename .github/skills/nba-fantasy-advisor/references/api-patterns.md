# NBA Fantasy Advisor — API Patterns

## External API Dependencies

### ESPN Public APIs

- **Injuries**: `site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries` — player injury reports with blurbs
- **News**: `site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=25` — general NBA news articles
- **Scoreboard**: `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD` — daily game list
- **Game Summary**: `site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}` — full boxscores with starter flags
- **Auth**: None required
- **Rate limiting**: Generous — small delays added between calls as a courtesy

### NBA.com CDN

- **Schedule**: `cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` — full-season schedule
- **Auth**: None required
- **Fallback**: ESPN scoreboard per-day lookup if CDN unavailable

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
Yahoo Stats   → Z-Scores → ┐
ESPN Boxscores→ Hot Pickup → ├→ Waiver Advisor → Ranked Recommendations
ESPN Injuries → Multipliers → ┤
Yahoo Rosters → Owned Set   → ┤
NBA Schedule  → Game Density → ┘
```

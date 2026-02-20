"""Yahoo Fantasy Sports integration using yfpy.

Connects to your Yahoo Fantasy Basketball league to retrieve roster info,
all teams' rosters, free agents, and league settings.
"""

import logging
import os
import time
import unicodedata
from pathlib import Path

from yfpy.query import YahooFantasySportsQuery

import config

_AUTH_RETRIES = 3
_AUTH_BACKOFF = 1.0  # seconds; doubles each retry
_AUTH_ERROR_PHRASES = ("logged in", "token_expired", "invalid_token", "oauth_problem")


def _patch_get_response(query: YahooFantasySportsQuery) -> None:
    """Patch yfpy's get_response to retry after 401 re-authentication.

    yfpy's ``get_response`` refreshes the OAuth token on a 401, but then
    continues processing the *original* failed response instead of
    retrying the request with the new token.  It logs the error at
    ERROR level before raising — producing noisy "You must be logged in"
    messages even when the retry will succeed.

    This wrapper:
    1. Suppresses yfpy's ERROR logs during retried attempts so the user
       doesn't see misleading error lines for transient auth failures.
    2. Forces a fresh ``_authenticate()`` with back-off between retries.
    3. Re-raises the last exception only if *all* retries fail.
    """
    _original = query.get_response
    _yfpy_logger = logging.getLogger("yfpy.query")

    def _get_response_with_retry(url: str):
        last_exc: Exception | None = None
        for attempt in range(_AUTH_RETRIES):
            # Suppress yfpy's ERROR logs for the expected "You must be
            # logged in" message that yfpy emits internally *before*
            # our retry logic can kick in.  We restore the level in the
            # finally block so normal errors still appear.
            prev_level = _yfpy_logger.level
            _yfpy_logger.setLevel(logging.CRITICAL)
            try:
                result = _original(url)
                return result
            except Exception as exc:
                exc_lower = str(exc).lower()
                if not any(phrase in exc_lower for phrase in _AUTH_ERROR_PHRASES):
                    # Not an auth error — restore logging and re-raise
                    _yfpy_logger.setLevel(prev_level)
                    raise
                last_exc = exc
                wait = _AUTH_BACKOFF * (attempt + 1)
                if attempt == 0:
                    print(
                        f"  Yahoo auth error ({type(exc).__name__}) — refreshing token "
                        f"(retry {attempt + 1}/{_AUTH_RETRIES})…"
                    )
                time.sleep(wait)
                query._authenticate()
            finally:
                _yfpy_logger.setLevel(prev_level)
        raise last_exc  # type: ignore[misc]

    query.get_response = _get_response_with_retry


def create_yahoo_query() -> YahooFantasySportsQuery:
    """Create and return an authenticated YahooFantasySportsQuery instance.

    Uses environment variables for authentication. On first run, a browser
    window will open for OAuth2 authorization.  The Yahoo game_id (which
    changes every season) is resolved automatically via the API.

    Returns:
        Configured YahooFantasySportsQuery for your NBA fantasy league.
    """
    # Temporarily suppress yfpy's "No game id" warning while we resolve it.
    yfpy_logger = logging.getLogger("yfpy.query")
    prev_level = yfpy_logger.level
    yfpy_logger.setLevel(logging.ERROR)

    query = YahooFantasySportsQuery(
        league_id=config.YAHOO_LEAGUE_ID,
        game_code=config.YAHOO_GAME_CODE,
        yahoo_consumer_key=config.YAHOO_CONSUMER_KEY,
        yahoo_consumer_secret=config.YAHOO_CONSUMER_SECRET,
        env_file_location=config.PROJECT_DIR,
        save_token_data_to_env_file=True,
    )

    # Auto-resolve game_id for the current season so it never goes stale.
    game_info = query.get_current_game_info()
    query.game_id = game_info.game_id

    yfpy_logger.setLevel(prev_level)

    # Work around yfpy bug: on 401 it refreshes the token but doesn't
    # retry the request, so the caller sees "You must be logged in".
    _patch_get_response(query)

    return query


def list_user_leagues(query: YahooFantasySportsQuery) -> list[dict]:
    """List all fantasy basketball leagues the user belongs to.

    Useful after first OAuth to discover league and team IDs without
    digging through Yahoo URLs.

    Returns:
        List of dicts with league_id, league_key, name, season, num_teams,
        scoring_type.
    """
    leagues: list[dict] = []
    try:
        game_info = query.get_current_game_info()
        game_key = str(game_info.game_id)
    except Exception as e:
        print(f"  Error resolving game key: {e}")
        return leagues

    try:
        user_leagues = query.get_user_leagues_by_game_key([game_key])
    except Exception as e:
        print(f"  Error fetching user leagues: {e}")
        return leagues

    if not user_leagues:
        return leagues

    for league_obj in user_leagues:
        game = league_obj
        if hasattr(league_obj, "game"):
            game = league_obj.game
        league_list = getattr(game, "leagues", None)
        if not league_list:
            continue
        for lg_wrapper in league_list:
            lg = lg_wrapper.league if hasattr(lg_wrapper, "league") else lg_wrapper
            league_key = str(getattr(lg, "league_key", ""))
            lid = league_key.split(".")[-1] if "." in league_key else ""
            leagues.append({
                "league_id": lid,
                "league_key": league_key,
                "name": str(getattr(lg, "name", "Unknown")),
                "season": str(getattr(lg, "season", "")),
                "num_teams": getattr(lg, "num_teams", "?"),
                "scoring_type": str(getattr(lg, "scoring_type", "?")),
            })

    return leagues


def list_league_teams(query: YahooFantasySportsQuery) -> list[dict]:
    """List all teams in the current league with their IDs and managers.

    Helps new users find their ``YAHOO_TEAM_ID`` without navigating Yahoo.

    Returns:
        List of dicts with team_id, name, manager, is_my_team.
    """
    teams_out: list[dict] = []
    try:
        teams = query.get_league_teams()
    except Exception as e:
        print(f"  Error fetching league teams: {e}")
        return teams_out

    for team_obj in teams:
        team = team_obj.team if hasattr(team_obj, "team") else team_obj
        team_id = getattr(team, "team_id", None)
        raw_name = getattr(team, "name", "Unknown")
        name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)

        # Extract manager info
        managers = getattr(team, "managers", None)
        manager_name = ""
        if managers:
            for m_wrapper in managers:
                mgr = m_wrapper.manager if hasattr(m_wrapper, "manager") else m_wrapper
                nickname = getattr(mgr, "nickname", "")
                if nickname:
                    manager_name = str(nickname)
                    break

        is_mine = (int(team_id) == config.YAHOO_TEAM_ID) if team_id is not None else False

        teams_out.append({
            "team_id": int(team_id) if team_id is not None else 0,
            "name": name,
            "manager": manager_name,
            "is_my_team": is_mine,
        })

    return teams_out


def get_team_name(query: YahooFantasySportsQuery, team_id: int | None = None) -> str:
    """Return the fantasy team name for *team_id* (defaults to ``config.YAHOO_TEAM_ID``).

    Returns an empty string on failure so callers can safely use
    ``team_name or ""``.
    """
    tid = team_id if team_id is not None else config.YAHOO_TEAM_ID
    try:
        for t in list_league_teams(query):
            if t["team_id"] == tid:
                return t["name"]
    except Exception:
        pass
    return ""


def get_league_teams(query: YahooFantasySportsQuery) -> list:
    """Get all teams in the league."""
    return query.get_league_teams()


def get_all_team_rosters(query: YahooFantasySportsQuery) -> tuple[dict, set]:
    """Fetch rosters for every team in the league.

    Iterates through all league teams and pulls each roster so we have
    a definitive list of which players are owned (and by whom).

    Returns:
        Tuple of:
          - dict mapping team_name -> list of player detail dicts
          - set of normalized owned player names (for fast lookup)
    """
    teams = get_league_teams(query)
    all_rosters: dict[str, list[dict]] = {}
    owned_player_names: set[str] = set()

    for team_obj in teams:
        team = team_obj
        if hasattr(team_obj, "team"):
            team = team_obj.team

        team_name = "Unknown"
        team_id = None
        if hasattr(team, "name"):
            raw = team.name
            team_name = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if hasattr(team, "team_id"):
            team_id = int(team.team_id)

        if team_id is None:
            continue

        try:
            roster = query.get_team_roster_player_info_by_date(team_id)
            player_details = []
            for p in roster:
                details = extract_player_details(p)
                player_details.append(details)
                owned_player_names.add(normalize_name(details["name"]))
            all_rosters[team_name] = player_details
            print(f"    {team_name}: {len(roster)} players")
        except Exception as e:
            print(f"    Warning: could not fetch roster for {team_name} (ID {team_id}): {e}")

    return all_rosters, owned_player_names


def get_my_team_roster(
    query: YahooFantasySportsQuery,
    team_id: int | None = None,
) -> list:
    """Get the current roster for your team.

    Args:
        query: Authenticated YFPY query instance.
        team_id: Your team ID. Defaults to config.YAHOO_TEAM_ID.

    Returns:
        List of player objects on your roster.
    """
    if team_id is None:
        team_id = config.YAHOO_TEAM_ID

    roster = query.get_team_roster_player_info_by_date(team_id)
    return roster


def normalize_name(name: str) -> str:
    """Normalize a player name for matching.

    Strips diacritics (Dončić → Doncic), punctuation, and casing so that
    names from Yahoo Fantasy and NBA API reliably match even when one source
    uses Unicode and the other uses ASCII transliterations.
    """
    # Decompose Unicode characters and drop combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")


def extract_player_name(player_obj) -> str:
    """Extract the player's full name from a yfpy player object."""
    player = player_obj
    if hasattr(player_obj, "player"):
        player = player_obj.player

    if hasattr(player, "name"):
        name = player.name
        if hasattr(name, "full"):
            return name.full
        if hasattr(name, "first") and hasattr(name, "last"):
            return f"{name.first} {name.last}"

    if hasattr(player, "player_key"):
        return str(player.player_key)

    return "Unknown"


def extract_player_details(player_obj) -> dict:
    """Extract key details from a yfpy player object.

    Returns:
        Dict with 'name', 'team', 'position', 'player_key', 'status',
        'percent_owned', 'percent_owned_delta'.
    """
    player = player_obj
    if hasattr(player_obj, "player"):
        player = player_obj.player

    details = {
        "name": extract_player_name(player_obj),
        "team": "",
        "position": "",
        "player_key": "",
        "status": "",
        "selected_position": "",
        "percent_owned": 0.0,
        "percent_owned_delta": 0.0,
    }

    if hasattr(player, "editorial_team_abbr"):
        details["team"] = str(player.editorial_team_abbr or "")
    if hasattr(player, "display_position"):
        details["position"] = str(player.display_position or "")
    if hasattr(player, "player_key"):
        details["player_key"] = str(player.player_key or "")
    if hasattr(player, "status"):
        details["status"] = str(player.status or "")
    if hasattr(player, "selected_position"):
        sp = player.selected_position
        if hasattr(sp, "position"):
            details["selected_position"] = str(sp.position or "")
        elif hasattr(sp, "selected_position"):
            inner = sp.selected_position
            if hasattr(inner, "position"):
                details["selected_position"] = str(inner.position or "")
        elif isinstance(sp, dict):
            details["selected_position"] = str(sp.get("position", ""))
        elif isinstance(sp, str):
            details["selected_position"] = sp
    if hasattr(player, "percent_owned"):
        po = player.percent_owned
        if hasattr(po, "value"):
            details["percent_owned"] = float(po.value or 0)
        elif isinstance(po, (int, float)):
            details["percent_owned"] = float(po)
        # Capture ownership delta (week-over-week change)
        if hasattr(po, "delta"):
            try:
                details["percent_owned_delta"] = float(po.delta or 0)
            except (ValueError, TypeError):
                pass

    return details


def fetch_trending_players(
    query: YahooFantasySportsQuery,
    player_names: list[str],
    owned_names: set[str] | None = None,
) -> dict[str, dict]:
    """Fetch percent-owned and ownership delta for waiver candidates.

    Queries Yahoo's ``get_player_percent_owned_by_week`` for each candidate
    that has a discoverable player_key.  This reveals which free agents are
    being added across all Yahoo leagues — a strong "grab before it's too
    late" signal.

    Strategy:
      1. Fetch a batch of league players from Yahoo (free agents first).
      2. Match them by normalized name to our candidate list.
      3. Extract percent_owned value + delta.

    Args:
        query: Authenticated YFPY query instance.
        player_names: List of player names to look up trending data for.
        owned_names: Set of owned player names (to skip).

    Returns:
        Dict mapping normalized player name → {
            percent_owned: float,
            percent_owned_delta: float,
            is_trending: bool,
        }
    """
    import config

    trending: dict[str, dict] = {}
    target_names = {normalize_name(n) for n in player_names}
    if owned_names:
        target_names -= owned_names

    if not target_names:
        return trending

    # Fetch league players in batches to find our candidates
    # Yahoo returns ~25 players per call; fetch enough to cover free agents
    print("  Fetching Yahoo ownership trends for waiver candidates...")
    seen_names: set[str] = set()
    batch_size = 25
    max_fetched = 250  # Don't over-fetch — just need the top trending FAs

    for start in range(0, max_fetched, batch_size):
        if not target_names - seen_names:
            break  # Found all candidates
        try:
            players = query.get_league_players(
                player_count_limit=batch_size,
                player_count_start=start,
            )
            if not players:
                break

            for p_obj in players:
                details = extract_player_details(p_obj)
                norm = normalize_name(details["name"])
                seen_names.add(norm)

                if norm in target_names:
                    pct = details.get("percent_owned", 0)
                    delta = details.get("percent_owned_delta", 0)
                    is_trending = delta >= config.HOT_PICKUP_MIN_DELTA
                    trending[norm] = {
                        "percent_owned": pct,
                        "percent_owned_delta": delta,
                        "is_trending": is_trending,
                    }
            time.sleep(0.3)
        except Exception as e:
            print(f"  Warning: trending data batch at {start} failed: {e}")
            break

    found = len(trending)
    trending_count = sum(1 for v in trending.values() if v["is_trending"])
    print(f"  Found ownership data for {found} candidates, {trending_count} trending\n")

    return trending

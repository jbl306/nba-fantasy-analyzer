"""Yahoo Fantasy Sports integration using yfpy.

Connects to your Yahoo Fantasy Basketball league to retrieve roster info,
all teams' rosters, free agents, and league settings.
"""

import os
from pathlib import Path

from yfpy.query import YahooFantasySportsQuery

import config


def create_yahoo_query() -> YahooFantasySportsQuery:
    """Create and return an authenticated YahooFantasySportsQuery instance.

    Uses environment variables for authentication. On first run, a browser
    window will open for OAuth2 authorization.

    Returns:
        Configured YahooFantasySportsQuery for your NBA fantasy league.
    """
    query = YahooFantasySportsQuery(
        league_id=config.YAHOO_LEAGUE_ID,
        game_code=config.YAHOO_GAME_CODE,
        yahoo_consumer_key=config.YAHOO_CONSUMER_KEY,
        yahoo_consumer_secret=config.YAHOO_CONSUMER_SECRET,
        env_file_location=config.PROJECT_DIR,
        save_token_data_to_env_file=True,
    )
    return query


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
            team_name = str(team.name)
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
    """Normalize a player name for matching."""
    return name.strip().lower().replace(".", "").replace("'", "").replace("-", " ")


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
        Dict with 'name', 'team', 'position', 'player_key', 'status'.
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

    return details

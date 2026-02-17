"""Yahoo Fantasy Sports transaction module.

Submits add/drop waiver claims directly through the Yahoo Fantasy API
by leveraging yfpy's authenticated OAuth session to POST transaction XML.

Yahoo API transactions endpoint:
  POST https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/transactions

Requirements:
  - Yahoo Developer App with Fantasy Sports API access
  - Authenticated yfpy session (token must be valid)
  - You must be the manager of the team you're transacting for
"""

import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import pandas as pd

import config
from src.yahoo_fantasy import (
    create_yahoo_query,
    extract_player_details,
    get_my_team_roster,
    normalize_name,
)
from src.faab_analyzer import (
    analyze_bid_history,
    fetch_league_transactions,
    format_bid_suggestions,
    suggest_bid,
    suggest_bids_for_recommendations,
)


# ---------------------------------------------------------------------------
# IL/IL+ roster compliance check
# ---------------------------------------------------------------------------

def check_il_compliance(query) -> list[dict]:
    """Check if any players on IL/IL+ slots have invalid injury statuses.

    Yahoo Fantasy rules:
      - IL slot: Player must have INJ, O, or SUSP status
      - IL+ slot: Player must have INJ, O, GTD, DTD, or SUSP status

    If a player on an IL slot no longer has an eligible status (e.g., they
    recovered), Yahoo BLOCKS ALL roster transactions until that player is
    moved off the IL slot. You must drop or move the player first.

    Returns:
        List of violation dicts with player name, slot, status, and eligible
        statuses. Empty list means roster is IL-compliant.
    """
    roster = get_my_team_roster(query)
    violations = []

    for player_obj in roster:
        details = extract_player_details(player_obj)
        slot = details.get("selected_position", "")
        status = details.get("status", "").strip().upper()
        player_name = details.get("name", "Unknown")
        player_key = details.get("player_key", "")

        if slot == "IL":
            if status not in config.IL_ELIGIBLE_STATUSES:
                violations.append({
                    "player": player_name,
                    "player_key": player_key,
                    "slot": "IL",
                    "status": status or "Healthy",
                    "eligible_statuses": ", ".join(sorted(config.IL_ELIGIBLE_STATUSES)),
                })
        elif slot == "IL+":
            if status not in config.IL_PLUS_ELIGIBLE_STATUSES:
                violations.append({
                    "player": player_name,
                    "player_key": player_key,
                    "slot": "IL+",
                    "status": status or "Healthy",
                    "eligible_statuses": ", ".join(sorted(config.IL_PLUS_ELIGIBLE_STATUSES)),
                })

    return violations


# ---------------------------------------------------------------------------
# Player key resolution helpers
# ---------------------------------------------------------------------------

def get_league_key(query) -> str:
    """Get the league key (e.g. '418.l.94443') from the authenticated query."""
    return query.get_league_key()


def get_team_key(query) -> str:
    """Get your team key (e.g. '418.l.94443.t.9') from the authenticated query."""
    league_key = get_league_key(query)
    return f"{league_key}.t.{config.YAHOO_TEAM_ID}"


def find_player_key_on_roster(query, player_name: str) -> str | None:
    """Find the Yahoo player_key for a player on your roster by name.

    Args:
        query: Authenticated yfpy query instance.
        player_name: Player name to search for (fuzzy matching).

    Returns:
        Player key string (e.g. '418.p.6047') or None if not found.
    """
    roster = get_my_team_roster(query)
    norm_target = normalize_name(player_name)

    for player_obj in roster:
        details = extract_player_details(player_obj)
        if normalize_name(details["name"]) == norm_target:
            return details["player_key"]

    # Partial match fallback (last name + first initial)
    target_parts = norm_target.split()
    if len(target_parts) >= 2:
        target_last = target_parts[-1]
        target_first_initial = target_parts[0][0] if target_parts[0] else ""
        for player_obj in roster:
            details = extract_player_details(player_obj)
            parts = normalize_name(details["name"]).split()
            if len(parts) >= 2:
                if parts[-1] == target_last and parts[0][0] == target_first_initial:
                    return details["player_key"]

    return None


def find_player_key_from_recommendations(
    rec_df: pd.DataFrame,
    player_name: str,
    query=None,
) -> str | None:
    """Find the Yahoo player_key for a recommended waiver pickup.

    First searches the recommendations DataFrame. If not found there,
    falls back to searching the full league player pool via the Yahoo API.

    Args:
        rec_df: Recommendations DataFrame (must have 'Player' column).
        player_name: Player name to look up.
        query: Optional yfpy query instance for league player search fallback.

    Returns:
        Player key string or None if not found.
    """
    norm_target = normalize_name(player_name)

    # Check if we stored player_key in the recommendations
    if "player_key" in rec_df.columns:
        for _, row in rec_df.iterrows():
            if normalize_name(str(row.get("Player", ""))) == norm_target:
                pk = row.get("player_key", "")
                if pk:
                    return str(pk)

    # Fallback: search via Yahoo API league players
    if query:
        return _search_league_for_player_key(query, player_name)

    return None


def _search_league_for_player_key(query, player_name: str) -> str | None:
    """Search the Yahoo league player pool for a player's key.

    Uses Yahoo's ``search=`` API parameter for a targeted name search first,
    then falls back to paginating through the full player list.
    """
    norm_target = normalize_name(player_name)

    # ------------------------------------------------------------------
    # Approach 1: Yahoo search= API (fast, targeted)
    # ------------------------------------------------------------------
    # Try searching by last name first (most specific), then full name.
    search_terms = []
    parts = player_name.strip().split()
    if len(parts) >= 2:
        search_terms.append(parts[-1])       # last name
    search_terms.append(player_name.strip())  # full name

    for term in search_terms:
        try:
            league_key = query.get_league_key()
            url = (
                f"https://fantasysports.yahooapis.com/fantasy/v2/league/"
                f"{league_key}/players;search={term}"
            )
            results = query.query(url, ["league", "players"])
            if results:
                player_list = results if isinstance(results, list) else [results]
                for p in player_list:
                    # query.query() may return a dict wrapping a Player,
                    # e.g. {'player': Player(...)}.  Unwrap it.
                    player_obj = p
                    if isinstance(p, dict) and "player" in p:
                        player_obj = p["player"]
                    details = extract_player_details(player_obj)
                    if normalize_name(details["name"]) == norm_target:
                        return details["player_key"]
        except Exception:
            pass  # search endpoint may return empty / error — fall through

    # ------------------------------------------------------------------
    # Approach 2: Paginate through league players (slow fallback)
    # ------------------------------------------------------------------
    try:
        for start in range(0, 250, 25):
            players = query.get_league_players(
                player_count_limit=25,
                player_count_start=start,
            )
            if not players:
                break
            for p in players:
                details = extract_player_details(p)
                if normalize_name(details["name"]) == norm_target:
                    return details["player_key"]
    except Exception as e:
        print(f"  Warning: league player search failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Transaction XML builders
# ---------------------------------------------------------------------------

def build_add_drop_xml(
    add_player_key: str,
    drop_player_key: str,
    team_key: str,
    faab_bid: int | None = None,
) -> str:
    """Build the XML payload for an add/drop transaction.

    Args:
        add_player_key: Yahoo player key for the player to add.
        drop_player_key: Yahoo player key for the player to drop.
        team_key: Your team key.
        faab_bid: FAAB bid amount (None for non-FAAB / standard waiver leagues).

    Returns:
        XML string for the Yahoo Fantasy API POST body.
    """
    root = ET.Element("fantasy_content")
    transaction = ET.SubElement(root, "transaction")
    ET.SubElement(transaction, "type").text = "add/drop"

    if faab_bid is not None:
        ET.SubElement(transaction, "faab_bid").text = str(faab_bid)

    players = ET.SubElement(transaction, "players")

    # Player to ADD
    add_player = ET.SubElement(players, "player")
    ET.SubElement(add_player, "player_key").text = add_player_key
    add_data = ET.SubElement(add_player, "transaction_data")
    ET.SubElement(add_data, "type").text = "add"
    ET.SubElement(add_data, "destination_team_key").text = team_key

    # Player to DROP
    drop_player = ET.SubElement(players, "player")
    ET.SubElement(drop_player, "player_key").text = drop_player_key
    drop_data = ET.SubElement(drop_player, "transaction_data")
    ET.SubElement(drop_data, "type").text = "drop"
    ET.SubElement(drop_data, "source_team_key").text = team_key

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def build_add_only_xml(
    add_player_key: str,
    team_key: str,
    faab_bid: int | None = None,
) -> str:
    """Build the XML payload for an add-only transaction (no drop).

    Args:
        add_player_key: Yahoo player key for the player to add.
        team_key: Your team key.
        faab_bid: FAAB bid amount (None for non-FAAB leagues).

    Returns:
        XML string for the Yahoo Fantasy API POST body.
    """
    root = ET.Element("fantasy_content")
    transaction = ET.SubElement(root, "transaction")
    ET.SubElement(transaction, "type").text = "add"

    if faab_bid is not None:
        ET.SubElement(transaction, "faab_bid").text = str(faab_bid)

    players = ET.SubElement(transaction, "players")

    add_player = ET.SubElement(players, "player")
    ET.SubElement(add_player, "player_key").text = add_player_key
    add_data = ET.SubElement(add_player, "transaction_data")
    ET.SubElement(add_data, "type").text = "add"
    ET.SubElement(add_data, "destination_team_key").text = team_key

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def build_drop_only_xml(drop_player_key: str, team_key: str) -> str:
    """Build the XML payload for a drop-only transaction.

    Used to free a roster spot (e.g., before moving a player off IL).

    Args:
        drop_player_key: Yahoo player key for the player to drop.
        team_key: Your team key.

    Returns:
        XML string for the Yahoo Fantasy API POST body.
    """
    root = ET.Element("fantasy_content")
    transaction = ET.SubElement(root, "transaction")
    ET.SubElement(transaction, "type").text = "drop"

    players = ET.SubElement(transaction, "players")
    drop_player = ET.SubElement(players, "player")
    ET.SubElement(drop_player, "player_key").text = drop_player_key
    drop_data = ET.SubElement(drop_player, "transaction_data")
    ET.SubElement(drop_data, "type").text = "drop"
    ET.SubElement(drop_data, "source_team_key").text = team_key

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def build_roster_move_xml(player_key: str, new_position: str) -> str:
    """Build the XML payload for a roster position change (e.g., IL → BN).

    Sent via PUT to the team roster endpoint, not the transactions endpoint.

    Args:
        player_key: Yahoo player key for the player to move.
        new_position: Target roster position (e.g., 'BN', 'Util', 'PG').

    Returns:
        XML string for the Yahoo Fantasy API PUT body.
    """
    root = ET.Element("fantasy_content")
    roster = ET.SubElement(root, "roster")
    ET.SubElement(roster, "coverage_type").text = "date"
    ET.SubElement(roster, "date").text = date.today().isoformat()

    players = ET.SubElement(roster, "players")
    player = ET.SubElement(players, "player")
    ET.SubElement(player, "player_key").text = player_key
    position = ET.SubElement(player, "position")
    position.text = new_position

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# Transaction submission
# ---------------------------------------------------------------------------

def submit_transaction(query, xml_payload: str) -> dict[str, Any]:
    """Submit a transaction to the Yahoo Fantasy API.

    Uses yfpy's internal OAuth session to POST transaction XML.

    Args:
        query: Authenticated yfpy query instance.
        xml_payload: XML string for the transaction.

    Returns:
        Dict with 'success' (bool), 'message' (str), and optional 'response' data.
    """
    league_key = get_league_key(query)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/transactions"

    headers = {"Content-Type": "application/xml"}

    try:
        # Access yfpy's internal OAuth session (yahoo-oauth)
        oauth_session = query._yahoo_fantasy_api
        response = oauth_session.session.post(url, data=xml_payload, headers=headers)

        if response.status_code in (200, 201):
            return {
                "success": True,
                "message": "Transaction submitted successfully!",
                "status_code": response.status_code,
                "response_text": response.text[:500],
            }
        else:
            return {
                "success": False,
                "message": f"Yahoo API returned HTTP {response.status_code}",
                "status_code": response.status_code,
                "response_text": response.text[:1000],
            }

    except AttributeError:
        # yfpy internal structure may vary — try alternative access
        try:
            oauth_session = query._yahoo_fantasy_api
            # Attempt using the requests session directly
            response = oauth_session.session.post(url, data=xml_payload, headers=headers)
            if response.status_code in (200, 201):
                return {
                    "success": True,
                    "message": "Transaction submitted successfully!",
                    "status_code": response.status_code,
                    "response_text": response.text[:500],
                }
            else:
                return {
                    "success": False,
                    "message": f"Yahoo API returned HTTP {response.status_code}",
                    "status_code": response.status_code,
                    "response_text": response.text[:1000],
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Could not access yfpy OAuth session: {e}",
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"Transaction failed: {e}",
        }


def submit_roster_move(query, player_key: str, new_position: str) -> dict[str, Any]:
    """Submit a roster position change via the Yahoo Fantasy API.

    Moves a player to a different roster slot (e.g., IL → BN).
    Uses PUT to the team roster endpoint.

    Args:
        query: Authenticated yfpy query instance.
        player_key: Yahoo player key for the player to move.
        new_position: Target position (e.g., 'BN').

    Returns:
        Dict with 'success' (bool) and 'message' (str).
    """
    team_key = get_team_key(query)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster"
    xml_payload = build_roster_move_xml(player_key, new_position)
    headers = {"Content-Type": "application/xml"}

    try:
        oauth_session = query._yahoo_fantasy_api
        response = oauth_session.session.put(url, data=xml_payload, headers=headers)

        if response.status_code in (200, 201):
            return {
                "success": True,
                "message": f"Moved {player_key} to {new_position}",
                "status_code": response.status_code,
            }
        else:
            return {
                "success": False,
                "message": f"Yahoo API returned HTTP {response.status_code}",
                "status_code": response.status_code,
                "response_text": response.text[:1000],
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Roster move failed: {e}",
        }


# ---------------------------------------------------------------------------
# IL/IL+ auto-resolution
# ---------------------------------------------------------------------------

def resolve_il_violations(
    query,
    violations: list[dict],
    available_droppable: list[str],
    dry_run: bool = False,
) -> tuple[bool, list[str]]:
    """Auto-resolve IL/IL+ violations by dropping a player and moving the
    non-compliant IL player to the bench.

    For each violation the flow is:
      1. Select the first available droppable player
      2. Drop that player (frees a roster spot)
      3. Move the non-compliant IL/IL+ player to BN (bench)

    Args:
        query: Authenticated yfpy query instance.
        violations: List from check_il_compliance() (must include player_key).
        available_droppable: Droppable player names still available.
        dry_run: If True, preview without submitting.

    Returns:
        Tuple of (all_resolved: bool, names_consumed: list[str]).
        names_consumed lists the droppable players that were used up.
    """
    consumed: list[str] = []
    remaining = list(available_droppable)  # work on a copy

    for v in violations:
        il_player = v["player"]
        il_key = v["player_key"]
        slot = v["slot"]

        if not remaining:
            print(f"\n  ✗ No droppable players left to resolve {il_player} in {slot}")
            print(f"    Add more players to DROPPABLE_PLAYERS in config.py")
            return False, consumed

        # Pick the first available droppable player
        drop_name = remaining.pop(0)

        print(f"\n  Resolving: {il_player} in {slot} (status: {v['status']})")
        print(f"    Step 1 → Drop {drop_name} to free a roster spot")

        # Resolve the droppable player's key
        drop_key = find_player_key_on_roster(query, drop_name)
        if not drop_key:
            print(f"    ✗ Could not find {drop_name} on roster!")
            return False, consumed

        team_key = get_team_key(query)
        drop_xml = build_drop_only_xml(drop_key, team_key)

        if dry_run:
            print(f"    [DRY RUN] Would drop {drop_name} ({drop_key})")
        else:
            result = submit_transaction(query, drop_xml)
            if not result["success"]:
                print(f"    ✗ Drop failed: {result['message']}")
                if "response_text" in result:
                    print(f"      {result['response_text'][:200]}")
                return False, consumed
            print(f"    ✓ Dropped {drop_name}")

        consumed.append(drop_name)

        # Move the IL player to bench
        print(f"    Step 2 → Move {il_player} from {slot} to BN")

        if dry_run:
            print(f"    [DRY RUN] Would move {il_player} ({il_key}) → BN")
        else:
            move_result = submit_roster_move(query, il_key, "BN")
            if not move_result["success"]:
                print(f"    ✗ Roster move failed: {move_result['message']}")
                if "response_text" in move_result:
                    print(f"      {move_result['response_text'][:200]}")
                return False, consumed
            print(f"    ✓ Moved {il_player} to bench")

    return True, consumed


# ---------------------------------------------------------------------------
# High-level transaction functions
# ---------------------------------------------------------------------------

def submit_add_drop(
    query,
    add_player_name: str,
    drop_player_name: str,
    faab_bid: int | None = None,
    rec_df: pd.DataFrame | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit an add/drop waiver claim.

    Resolves player names to Yahoo player keys, builds the transaction
    XML, and submits it to the Yahoo Fantasy API.

    Args:
        query: Authenticated yfpy query instance.
        add_player_name: Full name of the player to pick up.
        drop_player_name: Full name of the player to drop (must be on your roster).
        faab_bid: FAAB bid amount (None for non-FAAB leagues).
        rec_df: Optional recommendations DataFrame (helps find add player's key).
        dry_run: If True, show what would happen without actually submitting.

    Returns:
        Dict with 'success', 'message', and transaction details.
    """
    team_key = get_team_key(query)

    # Resolve DROPPING player key (must be on your roster)
    print(f"\n  Resolving drop player: {drop_player_name}...")
    drop_key = find_player_key_on_roster(query, drop_player_name)
    if not drop_key:
        return {
            "success": False,
            "message": f"Could not find '{drop_player_name}' on your roster. "
                       f"Check spelling or update DROPPABLE_PLAYERS in config.py.",
        }
    print(f"    Found: {drop_player_name} -> {drop_key}")

    # Resolve ADDING player key (from recs or league search)
    print(f"  Resolving add player: {add_player_name}...")
    add_key = None
    if rec_df is not None:
        add_key = find_player_key_from_recommendations(rec_df, add_player_name, query)
    if not add_key:
        add_key = _search_league_for_player_key(query, add_player_name)
    if not add_key:
        return {
            "success": False,
            "message": f"Could not find player key for '{add_player_name}'. "
                       f"Check spelling — the player may not exist in Yahoo.",
        }
    print(f"    Found: {add_player_name} -> {add_key}")

    # Build XML
    xml_payload = build_add_drop_xml(add_key, drop_key, team_key, faab_bid)

    if dry_run:
        print(f"\n  [DRY RUN] Would submit add/drop transaction:")
        print(f"    ADD:  {add_player_name} ({add_key})")
        print(f"    DROP: {drop_player_name} ({drop_key})")
        if faab_bid is not None:
            print(f"    FAAB Bid: ${faab_bid}")
        print(f"    Team: {team_key}")
        print(f"\n  XML payload:\n{xml_payload}")
        return {
            "success": True,
            "message": "[DRY RUN] Transaction prepared but not submitted.",
            "add_player": add_player_name,
            "add_key": add_key,
            "drop_player": drop_player_name,
            "drop_key": drop_key,
            "faab_bid": faab_bid,
        }

    # Submit
    print(f"\n  Submitting add/drop transaction to Yahoo...")
    result = submit_transaction(query, xml_payload)
    result["add_player"] = add_player_name
    result["add_key"] = add_key
    result["drop_player"] = drop_player_name
    result["drop_key"] = drop_key
    result["faab_bid"] = faab_bid
    return result


# ---------------------------------------------------------------------------
# Interactive transaction flow
# ---------------------------------------------------------------------------

def run_transaction_flow(
    query=None,
    rec_df: pd.DataFrame | None = None,
    dry_run: bool = False,
    faab_analysis: dict | None = None,
    budget_status: dict | None = None,
    schedule_analysis: dict | None = None,
    nba_stats=None,
) -> None:
    """Interactive flow to select and submit add/drop transactions.

    Supports submitting multiple bids in one session. You can drop the
    same player multiple times to bid on different add targets (Yahoo
    processes them in priority order — if the first wins, the rest are
    voided automatically).

    Enforces:
      - Weekly transaction limit (config.WEEKLY_TRANSACTION_LIMIT)
      - FAAB budget cap (config.FAAB_MAX_BID_PERCENT of remaining)
      - IL/IL+ auto-resolution

    Args:
        query: Authenticated yfpy query instance (creates one if None).
        rec_df: Pre-computed recommendations DataFrame (runs analysis if None).
        dry_run: If True, preview transactions without submitting.
        faab_analysis: Pre-computed FAAB analysis for bid suggestions.
        budget_status: Pre-computed budget health dict.
        schedule_analysis: Pre-computed schedule analysis dict.
        nba_stats: Full NBA stats DataFrame (for schedule comparison).
    """
    print()
    print("=" * 70)
    print("  WAIVER CLAIM TRANSACTION")
    if dry_run:
        print("  [DRY RUN MODE — no transactions will be submitted]")
    print("=" * 70)

    # Authenticate
    if query is None:
        print("\nConnecting to Yahoo Fantasy Sports...")
        query = create_yahoo_query()

    # ---------------------------------------------------------------
    # Weekly transaction limit check
    # ---------------------------------------------------------------
    txn_limit_info = None
    try:
        from src.league_settings import (
            count_transactions_this_week, check_transaction_limit,
            fetch_game_weeks, get_current_week_start,
        )
        transactions_raw = fetch_league_transactions(query)

        # Use actual Yahoo fantasy week boundaries (handles All-Star week)
        game_weeks = fetch_game_weeks(query)
        current_week = None
        try:
            meta = query.get_league_metadata()
            current_week = int(meta.current_week) if hasattr(meta, 'current_week') else None
        except Exception:
            pass
        week_start = get_current_week_start(game_weeks, current_week)

        used = count_transactions_this_week(transactions_raw, week_start=week_start)
        txn_limit_info = check_transaction_limit(used)
        print(f"\n  {txn_limit_info['message']}")

        if txn_limit_info["at_limit"]:
            print("\n  Cannot submit any more transactions this week.")
            print("  The weekly limit resets on Monday.")
            return
    except Exception as e:
        print(f"\n  Warning: could not check transaction limit: {e}")

    # ---------------------------------------------------------------
    # Budget status display
    # ---------------------------------------------------------------
    if budget_status and config.FAAB_ENABLED:
        print(f"\n  FAAB Budget: ${budget_status['remaining_budget']} remaining"
              f" | ${budget_status['weekly_budget']}/wk"
              f" | Status: {budget_status['status']}"
              f" | Max bid: ${budget_status['max_single_bid']}")

    # Build the working droppable list
    droppable = list(config.DROPPABLE_PLAYERS)  # mutable copy
    if not droppable:
        print("\nERROR: No droppable players configured.")
        print("Add player names to DROPPABLE_PLAYERS in config.py")
        return

    # Check IL/IL+ roster compliance
    print("\nChecking IL/IL+ roster compliance...")
    il_violations = check_il_compliance(query)
    if il_violations:
        print()
        print("  \u26a0  IL/IL+ ROSTER COMPLIANCE ISSUE")
        print("  Yahoo blocks ALL transactions when IL slots have ineligible players.")
        print()
        for v in il_violations:
            print(f"  \u2022 {v['player']} is in {v['slot']} slot with status: {v['status']}")
            print(f"    Required: {v['eligible_statuses']}")

        # Check if we have enough droppable players for IL resolution + bids
        needed = len(il_violations)
        if needed > len(droppable):
            print(f"\n  ✗ Need {needed} droppable players for IL resolution but only "
                  f"{len(droppable)} configured.")
            print(f"    Add more players to DROPPABLE_PLAYERS in config.py.")
            return

        remaining_after = len(droppable) - needed
        print(f"\n  Auto-resolving {needed} IL violation(s)...")
        print(f"  Will use {needed} droppable player(s), leaving {remaining_after} for bids.")

        success, consumed = resolve_il_violations(
            query, il_violations, droppable, dry_run=dry_run,
        )
        if not success:
            print("\n  ✗ IL resolution failed. Cannot proceed with transactions.")
            return

        # Remove consumed players from the droppable list
        for name in consumed:
            if name in droppable:
                droppable.remove(name)

        print(f"\n  ✓ IL/IL+ compliance resolved")

        if not droppable:
            print("\n  \u26a0  All droppable players were used for IL resolution.")
            print("  No players left to drop for waiver bids.")
            print("  Add more players to DROPPABLE_PLAYERS in config.py.")
            return
    else:
        print("  \u2713 IL/IL+ slots are compliant")

    print(f"\nYour droppable players ({len(droppable)}):")
    for i, name in enumerate(droppable, 1):
        key = find_player_key_on_roster(query, name)
        status = f"({key})" if key else "(NOT FOUND on roster!)"
        print(f"  {i}. {name:<30} {status}")

    # Show top recommendations (with bid suggestions if FAAB)
    if rec_df is None or rec_df.empty:
        print("\nNo recommendation data available. Run the full analysis first")
        print("(python main.py) then use --claim to submit transactions.")
        return

    top_n = min(10, len(rec_df))

    # Load or compute FAAB analysis for bid suggestions
    if config.FAAB_ENABLED and faab_analysis is None:
        print("\nLoading FAAB bid history for suggestions...")
        try:
            transactions = fetch_league_transactions(query)
            faab_analysis = analyze_bid_history(transactions, rec_df)
            print(f"  Analyzed {len(transactions)} historical transactions")
        except Exception as e:
            print(f"  Warning: could not load FAAB history: {e}")
            faab_analysis = None

    # Determine schedule context for bid suggestions
    schedule_game_counts = None
    avg_games = 3.5
    if schedule_analysis and schedule_analysis.get("weeks"):
        schedule_game_counts = schedule_analysis["weeks"][0]["game_counts"]
        avg_games = schedule_analysis.get("avg_games_per_week", 3.5)

    print(f"\nTop {top_n} waiver recommendations:")
    for i in range(top_n):
        row = rec_df.iloc[i]
        player = row.get("Player", "Unknown")
        team = row.get("Team", "")
        score = row.get("Adj_Score", 0)
        injury = row.get("Injury", "-")
        games_wk = row.get("Games_Wk", "-")
        injury_str = f" [{injury}]" if injury != "-" else ""
        games_str = f"  {games_wk}G" if games_wk != "-" else ""

        # Show suggested bid if FAAB
        bid_hint = ""
        if config.FAAB_ENABLED and faab_analysis:
            # Get schedule games for this player
            sched_games = None
            if schedule_game_counts:
                from src.schedule_analyzer import normalize_team_abbr
                nba_team = normalize_team_abbr(str(team))
                sched_games = schedule_game_counts.get(nba_team)

            sug = suggest_bid(
                player, float(score), faab_analysis, config.FAAB_STRATEGY,
                budget_status=budget_status,
                schedule_games=sched_games,
                avg_games=avg_games,
            )
            bid_hint = f"  ~${sug['suggested_bid']}"
            premium_range = sug.get("premium_range")
            if premium_range and float(score) >= 6.0:
                bid_hint += f" (premium: ${premium_range['min']}-${premium_range['max']})"

        print(f"  {i+1:>2}. {player:<28} {team:<5} Score: {score:>6.2f}{games_str}{injury_str}{bid_hint}")

    # ---------------------------------------------------------------
    # Multi-bid loop: submit multiple claims in one session
    # ---------------------------------------------------------------
    submitted_claims: list[dict] = []
    bid_number = 0

    # Track how many transactions we can still make
    txn_remaining = txn_limit_info["remaining"] if txn_limit_info else 999

    while True:
        # Check if we've hit the weekly limit
        if txn_remaining <= 0:
            print(f"\n  Weekly transaction limit reached. Cannot add more bids.")
            break

        bid_number += 1
        if bid_number > 1:
            print(f"\n{'─'*50}")
            print(f"  Bid #{bid_number} (enter 'q' to finish)"
                  f"  [{txn_remaining} transaction(s) remaining this week]")
            print(f"{'─'*50}")
        else:
            print()

        try:
            drop_choice = input(
                f"Select player to DROP (1-{len(droppable)}, or 'q' to finish): "
            ).strip()
            if drop_choice.lower() == 'q':
                break
            drop_idx = int(drop_choice) - 1
            if drop_idx < 0 or drop_idx >= len(droppable):
                print(f"Invalid choice. Must be 1-{len(droppable)}.")
                continue
            drop_name = droppable[drop_idx]

            add_choice = input(
                f"Select player to ADD (1-{top_n}, or 'q' to finish): "
            ).strip()
            if add_choice.lower() == 'q':
                break
            add_idx = int(add_choice) - 1
            if add_idx < 0 or add_idx >= top_n:
                print(f"Invalid choice. Must be 1-{top_n}.")
                continue
            add_name = rec_df.iloc[add_idx].get("Player", "")
            add_score = float(rec_df.iloc[add_idx].get("Adj_Score", 0))

            # FAAB bid with smart suggestion
            faab_bid = None
            if config.FAAB_ENABLED:
                suggested = config.DEFAULT_FAAB_BID
                if faab_analysis:
                    # Get schedule games for add player
                    add_team = str(rec_df.iloc[add_idx].get("Team", ""))
                    sched_games = None
                    if schedule_game_counts:
                        from src.schedule_analyzer import normalize_team_abbr
                        sched_games = schedule_game_counts.get(
                            normalize_team_abbr(add_team)
                        )

                    sug = suggest_bid(
                        add_name, add_score, faab_analysis, config.FAAB_STRATEGY,
                        budget_status=budget_status,
                        schedule_games=sched_games,
                        avg_games=avg_games,
                    )
                    suggested = sug["suggested_bid"]
                    print(f"  Suggested bid: ${suggested} ({sug['reason']})")
                    premium_range = sug.get("premium_range")
                    if premium_range:
                        print(f"  Premium range: ${premium_range['min']}-${premium_range['max']}"
                              f" ({premium_range['count']} returning-star bids in history)")
                    if budget_status:
                        print(f"  Budget: ${budget_status['remaining_budget']} remaining"
                              f" | Max bid: ${budget_status['max_single_bid']}")

                bid_input = input(
                    f"  FAAB bid amount (${suggested} suggested, or enter amount): "
                ).strip()
                if bid_input:
                    faab_bid = int(bid_input)
                else:
                    faab_bid = suggested

                # Enforce budget cap
                if budget_status and faab_bid > budget_status.get("max_single_bid", faab_bid):
                    max_bid = budget_status["max_single_bid"]
                    print(f"  ⚠  Bid ${faab_bid} exceeds max single bid ${max_bid}. Capping.")
                    faab_bid = max_bid
                if budget_status and faab_bid > budget_status.get("remaining_budget", faab_bid):
                    rem = budget_status["remaining_budget"]
                    print(f"  ⚠  Bid ${faab_bid} exceeds remaining budget ${rem}. Capping.")
                    faab_bid = rem

        except (ValueError, KeyboardInterrupt):
            print("\nFinished.")
            break

        # Add to queue
        submitted_claims.append({
            "add_name": add_name,
            "drop_name": drop_name,
            "faab_bid": faab_bid,
        })
        txn_remaining -= 1
        print(f"  ✓ Queued: ADD {add_name} / DROP {drop_name}"
              + (f" / ${faab_bid}" if faab_bid is not None else ""))

        if txn_remaining <= 0:
            print(f"\n  Weekly transaction limit reached after this bid.")
            break

        # Ask if they want to add another bid
        another = input("\nAdd another bid? (y/n): ").strip().lower()
        if another not in ("y", "yes"):
            break

    # ---------------------------------------------------------------
    # Review and confirm all queued claims
    # ---------------------------------------------------------------
    if not submitted_claims:
        print("\nNo claims queued. Cancelled.")
        return

    print(f"\n{'='*60}")
    print(f"  QUEUED CLAIMS ({len(submitted_claims)} total)")
    print(f"{'='*60}")
    for i, claim in enumerate(submitted_claims, 1):
        bid_str = f"  FAAB: ${claim['faab_bid']}" if claim["faab_bid"] is not None else ""
        print(f"  {i}. ADD: {claim['add_name']:<25} DROP: {claim['drop_name']}{bid_str}")
    print(f"{'='*60}")

    if not dry_run:
        confirm = input("\nSubmit all claims? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("Cancelled.")
            return

    # Submit each claim
    results = []
    for i, claim in enumerate(submitted_claims, 1):
        print(f"\n  [{i}/{len(submitted_claims)}] Processing...")
        result = submit_add_drop(
            query=query,
            add_player_name=claim["add_name"],
            drop_player_name=claim["drop_name"],
            faab_bid=claim["faab_bid"],
            rec_df=rec_df,
            dry_run=dry_run,
        )
        results.append(result)

        if result["success"]:
            print(f"  ✓ {result['message']}")
        else:
            print(f"  ✗ {result['message']}")
            if "response_text" in result:
                print(f"    Details: {result['response_text'][:200]}")

    # Summary
    successes = sum(1 for r in results if r["success"])
    failures = len(results) - successes
    print(f"\n{'='*50}")
    print(f"  Done: {successes} succeeded, {failures} failed")
    print(f"{'='*50}")

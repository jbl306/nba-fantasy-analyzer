"""Injury news fetcher using ESPN's public NBA injury API.

Fetches the current NBA injury report from ESPN's API and parses
player injury statuses, body parts, and detailed news blurbs. This data is
used to override the availability scoring for players who are confirmed
injured, even if their season GP rate looks healthy.

Source: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
"""

from datetime import datetime

import requests

import config


# ESPN public injury API (JSON, no auth required)
INJURY_REPORT_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

# Severity classifications based on status text
INJURY_SEVERITY = {
    "Out For Season": {
        "multiplier": 0.0,   # completely eliminate from recommendations
        "label": "OUT-SEASON",
        "priority": 1,
    },
    "Out": {
        "multiplier": 0.10,  # near-elimination, but allows IR stash visibility
        "label": "OUT",
        "priority": 2,
    },
    "Day To Day": {
        "multiplier": 0.90,  # minor penalty — could play any game
        "label": "DTD",
        "priority": 3,
    },
}

# Keywords in blurbs that indicate extended absence
EXTENDED_ABSENCE_KEYWORDS = [
    "rest of the season",
    "season-ending",
    "remainder of the season",
    "torn acl",
    "torn achilles",
    "surgery",
    "no timetable",
    "indefinitely",
]

# Keywords that suggest a player is close to returning
RETURN_SOON_KEYWORDS = [
    "return after the all-star break",
    "return to action",
    "progressed to",
    "on-court workouts",
    "scrimmages",
    "expected to return",
    "nearing a return",
    "day-to-day",
    "game-time decision",
]


def fetch_injury_report() -> list[dict]:
    """Fetch and parse the NBA injury report from ESPN's public API.

    Returns:
        List of dicts, each containing:
            - name: Player full name
            - team: NBA team name
            - update_date: Date string of the injury update
            - status: 'Out For Season', 'Out', or 'Day To Day'
            - body_part: Injured body part (e.g., 'Left Knee', 'Achilles')
            - description: Full news blurb text
            - severity_label: Short label (OUT-SEASON, OUT, DTD)
            - severity_multiplier: Score multiplier (0.0 to 0.9)
            - extended_absence: bool, True if blurb suggests long-term absence
            - return_soon: bool, True if blurb suggests near-term return
    """
    print("  Fetching NBA injury report from ESPN...")

    try:
        response = requests.get(INJURY_REPORT_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"  WARNING: Could not fetch injury report: {e}")
        return []
    except ValueError:
        print("  WARNING: Invalid JSON response from ESPN injury API")
        return []

    injuries = []

    for team_data in data.get("injuries", []):
        team_name = team_data.get("displayName", "Unknown")

        for entry in team_data.get("injuries", []):
            athlete = entry.get("athlete", {})
            player_name = athlete.get("displayName", "")
            if not player_name:
                continue

            # Get structured injury details
            details = entry.get("details", {})
            fantasy_status = details.get("fantasyStatus", {})
            fantasy_abbr = fantasy_status.get("abbreviation", "")
            injury_type = details.get("type", "Unknown")
            injury_detail = details.get("detail", "")
            injury_side = details.get("side", "")
            return_date_str = details.get("returnDate", "")

            # Get status and comments
            raw_status = entry.get("status", "Out")
            short_comment = entry.get("shortComment", "")
            long_comment = entry.get("longComment", "")
            date_str = entry.get("date", "")
            type_abbr = entry.get("type", {}).get("abbreviation", "")

            # --- Map ESPN fantasy status to our severity classifications ---
            if fantasy_abbr == "OFS":
                status = "Out For Season"
            elif raw_status == "Suspension" or type_abbr == "SUSP":
                status = "Out"  # Treat suspensions as Out
            elif raw_status.lower().startswith("day"):
                status = "Day To Day"
            else:
                status = "Out"

            # Build body part string with side for clarity
            body_part = injury_type
            if injury_side and injury_side != "Not Specified":
                body_part = f"{injury_side} {injury_type}"

            # Use the most detailed blurb available
            blurb = long_comment or short_comment or ""

            # Format update date
            update_date = ""
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    update_date = dt.strftime("%a, %b %d, %Y")
                except ValueError:
                    update_date = date_str

            # Determine base severity
            severity = INJURY_SEVERITY.get(status, INJURY_SEVERITY["Out"])

            # Check for extended absence or return-soon keywords in blurb
            desc_lower = blurb.lower()
            extended = any(kw in desc_lower for kw in EXTENDED_ABSENCE_KEYWORDS)
            returning = any(kw in desc_lower for kw in RETURN_SOON_KEYWORDS)

            # ESPN "OFS" / "OUT" fantasy tags are authoritative signals
            if fantasy_abbr in ("OFS", "OUT"):
                extended = True

            # Adjust multiplier for nuanced cases
            multiplier = severity["multiplier"]
            if status == "Out" and extended:
                multiplier = 0.05  # even harsher for confirmed long-term
            elif status == "Out" and returning:
                multiplier = 0.40  # less penalty if return is imminent
            elif status == "Day To Day" and returning:
                multiplier = 0.95  # barely any penalty

            injuries.append({
                "name": player_name,
                "team": team_name,
                "update_date": update_date,
                "status": status,
                "body_part": body_part,
                "description": blurb,
                "severity_label": severity["label"],
                "severity_multiplier": multiplier,
                "extended_absence": extended,
                "return_soon": returning,
            })

    print(f"  Found {len(injuries)} players on the injury report")
    return injuries


def build_injury_lookup(injuries: list[dict]) -> dict[str, dict]:
    """Build a normalized-name lookup dict from the injury report.

    Args:
        injuries: List of injury dicts from fetch_injury_report().

    Returns:
        Dict mapping normalized player names to their injury info.
        If a player appears multiple times, the most severe entry wins.
    """
    from src.yahoo_fantasy import normalize_name

    lookup: dict[str, dict] = {}

    for entry in injuries:
        norm = normalize_name(entry["name"])
        # Keep the most severe (lowest multiplier) if duplicates
        if norm in lookup:
            if entry["severity_multiplier"] < lookup[norm]["severity_multiplier"]:
                lookup[norm] = entry
        else:
            lookup[norm] = entry

    return lookup


def get_player_injury_status(
    player_name: str,
    injury_lookup: dict[str, dict],
) -> dict | None:
    """Look up a player's injury status from the injury report.

    Args:
        player_name: Player name (will be normalized).
        injury_lookup: Dict from build_injury_lookup().

    Returns:
        Injury info dict if the player is injured, or None if healthy.
    """
    from src.yahoo_fantasy import normalize_name

    norm = normalize_name(player_name)

    # Direct match
    if norm in injury_lookup:
        return injury_lookup[norm]

    # Partial match: try last name + first initial
    parts = norm.split()
    if len(parts) >= 2:
        last = parts[-1]
        first_initial = parts[0][0] if parts[0] else ""
        for key, info in injury_lookup.items():
            key_parts = key.split()
            if len(key_parts) >= 2:
                if key_parts[-1] == last and key_parts[0] and key_parts[0][0] == first_initial:
                    return info

    return None


def format_injury_note(injury_info: dict, max_blurb_len: int = 80) -> str:
    """Format an injury entry as a concise one-line note.

    Args:
        injury_info: Injury dict from the lookup.
        max_blurb_len: Max characters for the blurb portion.

    Returns:
        Formatted string like "OUT-SEASON (Knee) - Will miss rest of season..."
    """
    label = injury_info.get("severity_label", "?")
    body = injury_info.get("body_part", "?")
    blurb = injury_info.get("description", "")

    if len(blurb) > max_blurb_len:
        blurb = blurb[:max_blurb_len - 3] + "..."

    return f"{label} ({body}) - {blurb}"

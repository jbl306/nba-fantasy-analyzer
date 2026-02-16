"""Injury news scraper using Basketball-Reference.

Fetches the current NBA injury report from Basketball-Reference and parses
player injury statuses, body parts, and detailed news blurbs. This data is
used to override the availability scoring for players who are confirmed
injured, even if their season GP rate looks healthy.

Source: https://www.basketball-reference.com/friv/injuries.fcgi
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config


# URL for the Basketball-Reference injury report
INJURY_REPORT_URL = "https://www.basketball-reference.com/friv/injuries.fcgi"

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
    """Fetch and parse the NBA injury report from Basketball-Reference.

    Returns:
        List of dicts, each containing:
            - name: Player full name
            - team: NBA team name
            - update_date: Date string of the injury update
            - status: 'Out For Season', 'Out', or 'Day To Day'
            - body_part: Injured body part (e.g., 'Knee', 'Achilles')
            - description: Full news blurb text
            - severity_label: Short label (OUT-SEASON, OUT, DTD)
            - severity_multiplier: Score multiplier (0.0 to 0.9)
            - extended_absence: bool, True if blurb suggests long-term absence
            - return_soon: bool, True if blurb suggests near-term return
    """
    print("  Fetching NBA injury report from Basketball-Reference...")

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        session = requests.Session()
        # First hit the main page to get cookies
        session.get("https://www.basketball-reference.com", headers=headers, timeout=15)
        time.sleep(1.5)
        response = session.get(INJURY_REPORT_URL, headers=headers, timeout=30)
        # Basketball-Reference may return 403 but still include the data
        # Only fail if we genuinely couldn't connect
        if response.status_code >= 500:
            response.raise_for_status()
        time.sleep(1.0)  # respect rate limits
    except requests.RequestException as e:
        print(f"  WARNING: Could not fetch injury report: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # The injury table is in a <table> with id "injuries"
    table = soup.find("table", {"id": "injuries"})
    if table is None:
        # Fallback: try to find any table with injury data
        table = soup.find("table")
        if table is None:
            print("  WARNING: Could not find injury table in page")
            return []

    injuries = []
    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")

    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        # Extract cell text
        player_name = cells[0].get_text(strip=True)
        team = cells[1].get_text(strip=True)
        update_date = cells[2].get_text(strip=True)
        description_raw = cells[3].get_text(strip=True)

        if not player_name or player_name == "Player":
            continue

        # Parse description: "Status (Body Part) - Blurb text"
        status, body_part, blurb = _parse_description(description_raw)

        # Determine severity
        severity = INJURY_SEVERITY.get(status, INJURY_SEVERITY["Out"])

        # Check for extended absence or return-soon keywords
        desc_lower = description_raw.lower()
        extended = any(kw in desc_lower for kw in EXTENDED_ABSENCE_KEYWORDS)
        returning = any(kw in desc_lower for kw in RETURN_SOON_KEYWORDS)

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
            "team": team,
            "update_date": update_date,
            "status": status,
            "body_part": body_part,
            "description": blurb or description_raw,
            "severity_label": severity["label"],
            "severity_multiplier": multiplier,
            "extended_absence": extended,
            "return_soon": returning,
        })

    print(f"  Found {len(injuries)} players on the injury report")
    return injuries


def _parse_description(description: str) -> tuple[str, str, str]:
    """Parse a description string into (status, body_part, blurb).

    Examples:
        "Out For Season (Knee) - The Jazz said..." -> ("Out For Season", "Knee", "The Jazz said...")
        "Day To Day (Hip) - Claxton did not..." -> ("Day To Day", "Hip", "Claxton did not...")
        "Out (Achilles) - Tatum has..." -> ("Out", "Achilles", "Tatum has...")
    """
    pattern = r"^(Out For Season|Out|Day To Day)\s*\(([^)]+)\)\s*-\s*(.+)$"
    match = re.match(pattern, description, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2).strip(), match.group(3).strip()

    # Fallback: try to at least get the status
    if description.lower().startswith("out for season"):
        return "Out For Season", "Unknown", description
    elif description.lower().startswith("out"):
        return "Out", "Unknown", description
    elif description.lower().startswith("day to day"):
        return "Day To Day", "Unknown", description

    return "Unknown", "Unknown", description


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

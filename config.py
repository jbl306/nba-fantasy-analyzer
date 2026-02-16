"""Configuration settings for the NBA Fantasy Advisor."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
PROJECT_DIR = Path(__file__).parent
ENV_FILE = PROJECT_DIR / ".env"
load_dotenv(ENV_FILE)

# Yahoo Fantasy Sports settings
YAHOO_CONSUMER_KEY = os.environ.get("YAHOO_CONSUMER_KEY", "")
YAHOO_CONSUMER_SECRET = os.environ.get("YAHOO_CONSUMER_SECRET", "")
YAHOO_LEAGUE_ID = os.environ.get("YAHOO_LEAGUE_ID", "94443")
YAHOO_TEAM_ID = int(os.environ.get("YAHOO_TEAM_ID", "9"))
YAHOO_GAME_CODE = os.environ.get("YAHOO_GAME_CODE", "nba")

# nba_api settings
# Number of recent games to evaluate player performance
RECENT_GAMES_WINDOW = 14  # last 14 days
TOP_N_RECOMMENDATIONS = 15  # number of waiver recommendations to show

# Availability & injury risk settings
# Games played rate thresholds (GP / team games played)
AVAILABILITY_HEALTHY = 0.80   # >= 80% GP rate = no penalty
AVAILABILITY_MODERATE = 0.60  # 60-80% = moderate discount
AVAILABILITY_RISKY = 0.40     # 40-60% = heavy discount
# Below 40% = very heavy discount

# Number of days without a game to flag as "inactive"
INACTIVE_DAYS_THRESHOLD = 10

# How many top waiver candidates to fetch detailed game logs for
DETAILED_LOG_LIMIT = 50

# Injury report settings
# Source: Basketball-Reference injury report
INJURY_REPORT_ENABLED = True  # set to False to skip injury scraping
# Max characters of injury blurb to show in output
INJURY_BLURB_MAX_LENGTH = 80

# 9-Category league stat categories
# Standard 9-cat: FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO
STAT_CATEGORIES = {
    "FG_PCT": {"name": "FG%", "higher_is_better": True},
    "FT_PCT": {"name": "FT%", "higher_is_better": True},
    "FG3M": {"name": "3PM", "higher_is_better": True},
    "PTS": {"name": "PTS", "higher_is_better": True},
    "REB": {"name": "REB", "higher_is_better": True},
    "AST": {"name": "AST", "higher_is_better": True},
    "STL": {"name": "STL", "higher_is_better": True},
    "BLK": {"name": "BLK", "higher_is_better": True},
    "TOV": {"name": "TO", "higher_is_better": False},
}

# Output directory for saved data
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

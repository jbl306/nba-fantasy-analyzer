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

# Roster management settings
# Only these players on your roster are eligible to be dropped.
# Everyone else is considered untouchable.
DROPPABLE_PLAYERS = [
    "Sandro Mamukelashvili",
    "Justin Champagnie",
    "Kristaps Porziņģis",
]

# FAAB (Free Agent Acquisition Budget) settings
# Set FAAB_ENABLED = True if your league uses FAAB bidding for waivers.
# Set to False for standard rolling waiver priority leagues.
FAAB_ENABLED = False
DEFAULT_FAAB_BID = 1  # default bid amount when FAAB is enabled
# Bidding strategy for suggestions: "value", "competitive", or "aggressive"
#   value:       Bid at 25th percentile (bargain hunting)
#   competitive: Bid at median (market rate) — DEFAULT
#   aggressive:  Bid at 75th percentile (maximize win rate)
FAAB_STRATEGY = "competitive"

# FAAB budget — your league's starting budget per phase.
# Regular season budget resets to FAAB_BUDGET_PLAYOFFS when playoffs begin.
FAAB_BUDGET_REGULAR_SEASON = 300   # Total FAAB $ for the regular season
FAAB_BUDGET_PLAYOFFS = 100         # FAAB $ after playoff reset
FAAB_MAX_BID_PERCENT = 0.50        # Max fraction of remaining budget on one bid

# FAAB outlier detection — separates standard waiver bids from premium
# (returning star) bids so outliers don't inflate regular bid suggestions.
# E.g., Paul George or Jayson Tatum returning from injury command huge bids
# that would skew the averages for normal waiver pickups.
PREMIUM_BID_FLOOR = 15     # Minimum bid to be classified as "premium"
OUTLIER_IQR_FACTOR = 1.5   # IQR multiplier for outlier detection

# Transaction limits
# Number of add/drop transactions allowed per fantasy week (Mon-Sun).
# Resets at the start of each Monday.
WEEKLY_TRANSACTION_LIMIT = 3

# Schedule analysis settings
# Analyze upcoming games to value waiver targets by playing time opportunity.
SCHEDULE_WEEKS_AHEAD = 2       # Number of upcoming weeks to analyze
SCHEDULE_WEIGHT = 0.10         # How much each game delta from avg impacts Adj_Score

# IL/IL+ roster compliance
# Valid injury statuses for each IL slot type. If a player on an IL slot
# doesn't have an eligible status, Yahoo blocks ALL transactions.
IL_ELIGIBLE_STATUSES = {"INJ", "O", "SUSP"}
IL_PLUS_ELIGIBLE_STATUSES = {"INJ", "O", "GTD", "DTD", "SUSP"}

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
DETAILED_LOG_LIMIT = 10

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

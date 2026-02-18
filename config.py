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
# AUTO_DETECT_DROPPABLE: When True, automatically identify the lowest-value
# players on your roster by z-score and offer them as drop candidates.
# When False, fall back to the manual DROPPABLE_PLAYERS list below.
AUTO_DETECT_DROPPABLE = True

# Number of bottom-ranked roster players to flag as droppable.
AUTO_DROPPABLE_COUNT = 3

# Players that should NEVER be auto-detected as droppable, even if their
# z-score is low (e.g. injured stars you're stashing).
UNDDROPPABLE_PLAYERS: list[str] = []

# Manual droppable list — used when AUTO_DETECT_DROPPABLE = False,
# or as additional forced-droppable entries when AUTO_DETECT_DROPPABLE = True.
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
FAAB_ENABLED = True
DEFAULT_FAAB_BID = 1  # default bid amount when FAAB is enabled
FAAB_BID_OVERRIDE = True  # Prompt to override suggested FAAB bid amount (False = auto-accept)
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
# Default weekly add/drop limit (auto-detected from Yahoo when connected).
WEEKLY_TRANSACTION_LIMIT = 3

# Schedule analysis settings
# Analyze upcoming games to value waiver targets by playing time opportunity.
SCHEDULE_WEEKS_AHEAD = 3       # Number of upcoming weeks to analyze
SCHEDULE_WEIGHT = 0.10         # How much each game delta from avg impacts Adj_Score
SCHEDULE_WEEK_DECAY = 0.5      # Weight decay per future week (wk1=1.0, wk2=0.5, wk3=0.25)

# IL/IL+ roster compliance
# Valid injury statuses for each IL slot type. If a player on an IL slot
# doesn't have an eligible status, Yahoo blocks ALL transactions.
IL_ELIGIBLE_STATUSES = {"INJ", "O", "SUSP"}
IL_PLUS_ELIGIBLE_STATUSES = {"INJ", "O", "GTD", "DTD", "SUSP"}
# When an IL player recovers and the roster is full, two drops are needed:
# one to resolve the IL violation and one for the waiver claim.
# In streaming mode, if the worst regular roster player's z-score is within
# this threshold of the IL player's z-score, just drop the regular player
# and move the IL player to bench (roster upgrade, saves a transaction).
IL_SMART_DROP_Z_THRESHOLD = 0.5

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

# Hot-pickup / trending detection
# Weights recent performance and ownership trends to catch breakout players
# before rivals claim them.
HOT_PICKUP_ENABLED = True          # Enable trending/hot-pickup boost
HOT_PICKUP_RECENT_GAMES = 3       # Number of recent games to evaluate
HOT_PICKUP_RECENCY_WEIGHT = 0.25  # Weight for recent-game z-score boost
HOT_PICKUP_TRENDING_WEIGHT = 0.15 # Weight for ownership-trend (% owned delta) boost
HOT_PICKUP_MIN_DELTA = 5          # Min % owned increase to trigger trending flag

# Injury report settings
# Source: Basketball-Reference injury report
INJURY_REPORT_ENABLED = True  # set to False to skip injury scraping
# Max characters of injury blurb to show in output
INJURY_BLURB_MAX_LENGTH = 80

# Punt categories — leave empty for a balanced build.
# List category *names* (e.g. "FT%", "TO") you intentionally punt.
# Punted categories are excluded from Z_TOTAL, team-needs analysis,
# and the need-weighted boost so they don't influence recommendations.
# Examples: PUNT_CATEGORIES = ["FT%", "TO"]   # punt FT% and turnovers
PUNT_CATEGORIES: list[str] = []

# 9-Category league stat categories
# Standard 9-cat: FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO
#
# FG% and FT% use volume-weighted z-scores: a player's "impact" on your
# team's shooting percentage is proportional to both their accuracy AND
# their attempt volume (FGA / FTA per game).  This prevents low-volume
# shooters from inflating FG%/FT% value.
#
# The volume_col key tells the z-score engine which column to use as the
# weighting factor.  Categories without volume_col use a standard z-score.
STAT_CATEGORIES = {
    "FG_PCT": {"name": "FG%", "higher_is_better": True, "volume_col": "FGA"},
    "FT_PCT": {"name": "FT%", "higher_is_better": True, "volume_col": "FTA"},
    "FG3M": {"name": "3PM", "higher_is_better": True},
    "PTS": {"name": "PTS", "higher_is_better": True},
    "REB": {"name": "REB", "higher_is_better": True},
    "AST": {"name": "AST", "higher_is_better": True},
    "STL": {"name": "STL", "higher_is_better": True},
    "BLK": {"name": "BLK", "higher_is_better": True},
    "TOV": {"name": "TO", "higher_is_better": False},
}

# Output directory for saved data
OUTPUT_DIR = Path("/mnt/c/Users/joshu/projects/nba-fantasy-advisor/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Yahoo NBA stat_id → config STAT_CATEGORIES key mapping.
# Used to validate that your Yahoo league's scoring categories match
# the 9-cat model this tool expects.  Auto-detected on connection.
YAHOO_STAT_ID_MAP: dict[int, str] = {
    5:  "FG_PCT",   # FG%
    8:  "FT_PCT",   # FT%
    10: "FG3M",     # 3PTM
    12: "PTS",      # Points
    15: "REB",      # Rebounds
    16: "AST",      # Assists
    17: "STL",      # Steals
    18: "BLK",      # Blocks
    19: "TOV",      # Turnovers
}

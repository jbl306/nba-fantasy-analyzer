"""NBA Fantasy Advisor - Nightly waiver wire recommendations.

Uses nba_api to scrape real NBA stats and yfpy to connect to your
Yahoo Fantasy Basketball league, then recommends the best available
waiver pickups based on 9-category z-score analysis.

Usage:
    python main.py                  # Full analysis with Yahoo Fantasy
    python main.py --skip-yahoo     # NBA stats only (no Yahoo auth needed)
    python main.py --top 25         # Show top 25 recommendations
"""

import argparse
import sys

import config
from src.waiver_advisor import run_waiver_analysis


def main():
    parser = argparse.ArgumentParser(
        description="NBA Fantasy Basketball Waiver Wire Advisor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                     Full analysis (requires Yahoo API setup)
  python main.py --skip-yahoo        Show top NBA players by z-score only
  python main.py --top 25            Show top 25 recommendations
  python main.py --days 7            Use last 7 days for recent form
        """,
    )
    parser.add_argument(
        "--skip-yahoo",
        action="store_true",
        help="Skip Yahoo Fantasy integration (show NBA stats rankings only)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help=f"Number of recommendations to show (default: {config.TOP_N_RECOMMENDATIONS})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"Number of recent days to evaluate (default: {config.RECENT_GAMES_WINDOW})",
    )

    args = parser.parse_args()

    # Override config if args provided
    if args.top:
        config.TOP_N_RECOMMENDATIONS = args.top
    if args.days:
        config.RECENT_GAMES_WINDOW = args.days

    # Validate Yahoo credentials if not skipping
    if not args.skip_yahoo:
        if not config.YAHOO_CONSUMER_KEY or config.YAHOO_CONSUMER_KEY == "your_consumer_key_here":
            print("ERROR: Yahoo API credentials not configured.")
            print()
            print("To set up Yahoo Fantasy integration:")
            print("  1. Copy .env.template to .env")
            print("  2. Create an app at https://developer.yahoo.com/apps/create/")
            print("  3. Paste your Client ID and Client Secret into .env")
            print()
            print("Or run with --skip-yahoo to see NBA stats rankings without Yahoo.")
            sys.exit(1)

    print()
    print("=" * 70)
    print("  NBA FANTASY ADVISOR - Waiver Wire Recommendations")
    print(f"  League: {config.YAHOO_LEAGUE_ID} | Team: {config.YAHOO_TEAM_ID}")
    print(f"  Scoring: 9-Category H2H")
    print("=" * 70)
    print()

    run_waiver_analysis(skip_yahoo=args.skip_yahoo)


if __name__ == "__main__":
    main()

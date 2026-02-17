"""NBA Fantasy Advisor - Nightly waiver wire recommendations.

Uses nba_api to scrape real NBA stats and yfpy to connect to your
Yahoo Fantasy Basketball league, then recommends the best available
waiver pickups based on 9-category z-score analysis.

Usage:
    python main.py                  # Full analysis with Yahoo Fantasy
    python main.py --skip-yahoo     # NBA stats only (no Yahoo auth needed)
    python main.py --top 25         # Show top 25 recommendations
    python main.py --claim          # Run analysis then submit a waiver claim
    python main.py --dry-run        # Preview a waiver claim without submitting
    python main.py --faab-history   # Analyze league FAAB bid history
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
  python main.py --claim             Run analysis then submit add/drop claim
  python main.py --dry-run           Preview add/drop without submitting
  python main.py --faab-history      Show FAAB bid history and suggestions
  python main.py --strategy aggressive  Use aggressive bidding strategy
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
    parser.add_argument(
        "--claim",
        action="store_true",
        help="After analysis, interactively submit an add/drop waiver claim",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview a waiver claim without actually submitting it",
    )
    parser.add_argument(
        "--faab-history",
        action="store_true",
        help="Analyze league FAAB bid history and show suggested bids",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["value", "competitive", "aggressive"],
        default=None,
        help="FAAB bidding strategy: value (bargain), competitive (median), aggressive (ensure win)",
    )

    args = parser.parse_args()

    # Override config if args provided
    if args.top:
        config.TOP_N_RECOMMENDATIONS = args.top
    if args.days:
        config.RECENT_GAMES_WINDOW = args.days
    if args.strategy:
        config.FAAB_STRATEGY = args.strategy

    # --dry-run implies --claim
    if args.dry_run:
        args.claim = True

    # --claim and --faab-history require Yahoo
    if (args.claim or args.faab_history) and args.skip_yahoo:
        print("ERROR: --claim/--dry-run/--faab-history requires Yahoo integration (cannot use --skip-yahoo)")
        sys.exit(1)

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

    # Run analysis — returns (query, rec_df, nba_stats, schedule_analysis) when claim/faab mode is requested
    need_data = args.claim or args.faab_history
    result = run_waiver_analysis(skip_yahoo=args.skip_yahoo, return_data=need_data)

    # Unpack the expanded return tuple
    query = None
    rec_df = None
    nba_stats = None
    schedule_analysis = None
    if result is not None and isinstance(result, tuple):
        if len(result) == 4:
            query, rec_df, nba_stats, schedule_analysis = result
        elif len(result) == 2:
            query, rec_df = result

    # Compute budget status and schedule context for FAAB suggestions
    budget_status = None
    schedule_game_counts = None
    avg_games = 3.5

    if query is not None and config.FAAB_ENABLED:
        try:
            from src.league_settings import (
                fetch_league_settings, get_faab_balance, compute_budget_status,
            )
            settings = fetch_league_settings(query)
            faab_balance = get_faab_balance(query)
            if faab_balance is None:
                # Estimate from FAAB history if Yahoo doesn't expose the balance
                faab_balance = config.FAAB_BUDGET_REGULAR_SEASON
            budget_status = compute_budget_status(
                remaining_budget=faab_balance,
                current_week=settings.get("current_week"),
                end_week=settings.get("end_week"),
                playoff_start_week=settings.get("playoff_start_week"),
            )
        except Exception as e:
            print(f"  Warning: budget computation failed: {e}")

    if schedule_analysis and schedule_analysis.get("weeks"):
        schedule_game_counts = schedule_analysis["weeks"][0]["game_counts"]
        avg_games = schedule_analysis.get("avg_games_per_week", 3.5)

    # FAAB history analysis
    faab_analysis = None
    if args.faab_history and query is not None:
        from src.faab_analyzer import run_faab_analysis
        faab_analysis = run_faab_analysis(
            query=query, rec_df=rec_df,
            budget_status=budget_status,
            schedule_game_counts=schedule_game_counts,
            avg_games=avg_games,
        )

    # If claim mode, launch the transaction flow
    if args.claim and query is not None:
        from src.transactions import run_transaction_flow
        run_transaction_flow(
            query=query, rec_df=rec_df, dry_run=args.dry_run,
            faab_analysis=faab_analysis,
            budget_status=budget_status,
            schedule_analysis=schedule_analysis,
            nba_stats=nba_stats,
        )


if __name__ == "__main__":
    main()

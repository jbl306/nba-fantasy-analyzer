"""NBA Fantasy Advisor - Nightly waiver wire recommendations.

Uses Yahoo Fantasy API (via yfpy) for player stats and league data,
ESPN public APIs for injury reports, news, and boxscores, and NBA.com
CDN for scheduling. Recommends the best available waiver pickups
based on 9-category z-score analysis.

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

# Ensure Unicode output works on Windows (cp1252 can't encode diacritics
# in player names like Dončić, Vučević, Nurkić).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
        "--compact",
        action="store_true",
        help="Compact display: show only Player, Team, Z_Value, Adj_Score, Injury, Games_Wk",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["value", "competitive", "aggressive"],
        default=None,
        help="FAAB bidding strategy: value (bargain), competitive (median), aggressive (ensure win)",
    )
    parser.add_argument(
        "--list-leagues",
        action="store_true",
        help="Show all Yahoo Fantasy NBA leagues you belong to and exit",
    )
    parser.add_argument(
        "--list-teams",
        action="store_true",
        help="Show all teams in your league with IDs and managers, then exit",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Streaming mode: find the best available player with a game today for your weakest roster spot",
    )
    parser.add_argument(
        "--team",
        type=int,
        default=None,
        help="Override YAHOO_TEAM_ID for this run (e.g. --team 3 to analyze team #3)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run analysis once and send results via email notification (designed for scheduled/cron use)",
    )
    parser.add_argument(
        "--notify",
        type=str,
        choices=["email"],
        default=None,
        help="Notification method for --watch mode (default: email)",
    )

    args = parser.parse_args()

    # Override config if args provided
    if args.team:
        config.YAHOO_TEAM_ID = args.team
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

    # --stream requires Yahoo
    if args.stream and args.skip_yahoo:
        print("ERROR: --stream requires Yahoo integration (cannot use --skip-yahoo)")
        sys.exit(1)

    # --watch requires Yahoo and email config
    if args.watch and args.skip_yahoo:
        print("ERROR: --watch requires Yahoo integration (cannot use --skip-yahoo)")
        sys.exit(1)
    if args.watch:
        from src.notifier import email_configured
        if not email_configured():
            print("ERROR: --watch requires email configuration in .env")
            print("  Set NOTIFY_EMAIL_TO and NOTIFY_SMTP_PASSWORD")
            print("  See docs/setup-guide.md for Gmail App Password instructions.")
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

    # ---------------------------------------------------------------
    # Discovery commands (--list-leagues, --list-teams) — run and exit
    # ---------------------------------------------------------------
    if args.list_leagues or args.list_teams:
        from src.yahoo_fantasy import create_yahoo_query
        print("\nConnecting to Yahoo Fantasy Sports...")
        query = create_yahoo_query()

        if args.list_leagues:
            from src.yahoo_fantasy import list_user_leagues
            leagues = list_user_leagues(query)
            if not leagues:
                print("\n  No NBA fantasy leagues found for this account.")
            else:
                print(f"\n  Your NBA Fantasy Leagues ({len(leagues)}):")
                print(f"  {'ID':<8} {'Name':<35} {'Season':<8} {'Teams':<7} {'Scoring'}")
                print(f"  {'─'*8} {'─'*35} {'─'*8} {'─'*7} {'─'*15}")
                for lg in leagues:
                    print(f"  {lg['league_id']:<8} {lg['name']:<35} {lg['season']:<8} {lg['num_teams']:<7} {lg['scoring_type']}")
                print(f"\n  Set YAHOO_LEAGUE_ID in .env to use a league.")

        if args.list_teams:
            from src.yahoo_fantasy import list_league_teams
            teams = list_league_teams(query)
            if not teams:
                print("\n  No teams found in this league.")
            else:
                print(f"\n  Teams in League {config.YAHOO_LEAGUE_ID} ({len(teams)}):")
                print(f"  {'ID':<5} {'Team Name':<30} {'Manager':<20} {'Yours'}")
                print(f"  {'─'*5} {'─'*30} {'─'*20} {'─'*5}")
                for t in teams:
                    marker = " ←" if t["is_my_team"] else ""
                    print(f"  {t['team_id']:<5} {t['name']:<30} {t['manager']:<20}{marker}")
                print(f"\n  Set YAHOO_TEAM_ID in .env to your team number.")
        return

    # ---------------------------------------------------------------
    # Watch mode (--watch) — run analysis, email results, and exit
    # ---------------------------------------------------------------
    # Streaming + Watch mode (--stream --watch) — run streaming analysis and email
    # Must be checked BEFORE the standalone --watch block.
    # ---------------------------------------------------------------
    if args.stream and args.watch:
        from src.waiver_advisor import run_streaming_analysis
        from src.notifier import send_email_report
        from src.yahoo_fantasy import create_yahoo_query, get_team_name
        team_name = get_team_name(create_yahoo_query())
        rec_df = run_streaming_analysis(return_data=True)
        if rec_df is not None and not rec_df.empty:
            top_n = config.TOP_N_RECOMMENDATIONS
            print(f"\n  Sending streaming report via email (top {top_n})...")
            send_email_report(rec_df, top_n=top_n, mode="stream", team_name=team_name)
        else:
            print("  No streaming recommendations to send.")
        return

    # ---------------------------------------------------------------
    # Watch mode (--watch) — run analysis, email results, and exit
    # ---------------------------------------------------------------
    if args.watch:
        from src.notifier import send_email_report
        from src.yahoo_fantasy import get_team_name, create_yahoo_query
        team_name = get_team_name(create_yahoo_query())
        print()
        print("=" * 70)
        print("  NBA FANTASY ADVISOR - Watch Mode")
        print(f"  League: {config.YAHOO_LEAGUE_ID} | Team: {config.YAHOO_TEAM_ID} ({team_name})")
        print("=" * 70)
        print()

        result = run_waiver_analysis(
            skip_yahoo=False,
            return_data=True,
            compact=False,
        )

        if result is not None and isinstance(result, tuple) and len(result) >= 2:
            _query, rec_df = result[0], result[1]
            schedule_analysis = result[3] if len(result) >= 4 else None
            if rec_df is not None and not rec_df.empty:
                top_n = config.TOP_N_RECOMMENDATIONS
                print(f"\n  Sending email report (top {top_n} recommendations)...")
                send_email_report(rec_df, schedule_analysis=schedule_analysis, top_n=top_n, team_name=team_name)
            else:
                print("  No recommendations to send.")
        else:
            print("  Analysis returned no data — cannot send report.")
        return

    # ---------------------------------------------------------------
    # Streaming mode (--stream) — run and exit
    # ---------------------------------------------------------------
    if args.stream:
        from src.waiver_advisor import run_streaming_analysis
        run_streaming_analysis()
        return

    print()
    print("=" * 70)
    print("  NBA FANTASY ADVISOR - Waiver Wire Recommendations")
    print(f"  League: {config.YAHOO_LEAGUE_ID} | Team: {config.YAHOO_TEAM_ID}")
    print(f"  Scoring: 9-Category H2H")
    print("=" * 70)
    print()

    # Run analysis — returns (query, rec_df, nba_stats, schedule_analysis) when claim/faab mode is requested
    need_data = args.claim or args.faab_history
    result = run_waiver_analysis(
        skip_yahoo=args.skip_yahoo,
        return_data=need_data,
        compact=args.compact,
    )

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
                fetch_league_settings, get_faab_balance,
                get_all_faab_balances, compute_budget_status,
            )
            settings = fetch_league_settings(query)
            faab_balance = get_faab_balance(query)
            if faab_balance is None:
                # Estimate from FAAB history if Yahoo doesn't expose the balance
                faab_balance = config.FAAB_BUDGET_REGULAR_SEASON

            # Fetch league-wide FAAB balances for relative ranking
            league_balances: list[int] | None = None
            try:
                all_balances = get_all_faab_balances(query)
                if all_balances:
                    league_balances = [b["faab_balance"] for b in all_balances]
            except Exception as e:
                print(f"  Warning: could not fetch league FAAB balances: {e}")

            budget_status = compute_budget_status(
                remaining_budget=faab_balance,
                current_week=settings.get("current_week"),
                end_week=settings.get("end_week"),
                playoff_start_week=settings.get("playoff_start_week"),
                start_week=settings.get("start_week"),
                league_balances=league_balances,
            )
        except Exception as e:
            print(f"  Warning: budget computation failed: {e}")

    if schedule_analysis and schedule_analysis.get("weeks"):
        schedule_game_counts = schedule_analysis["weeks"][0]["game_counts"]
        avg_games = schedule_analysis.get("avg_games_per_week", 3.5)

    # Compute roster strength for FAAB bid adjustments
    roster_strength = None
    if rec_df is not None and nba_stats is not None:
        try:
            from src.waiver_advisor import (
                analyze_roster, identify_team_needs, compute_roster_strength,
            )
            from src.yahoo_fantasy import get_my_team_roster
            my_roster = get_my_team_roster(query)
            roster_df = analyze_roster(my_roster, nba_stats)
            team_needs = identify_team_needs(roster_df)
            roster_strength = compute_roster_strength(team_needs)
        except Exception as e:
            print(f"  Warning: roster strength computation failed: {e}")

    # FAAB history analysis
    faab_analysis = None
    if args.faab_history and query is not None:
        from src.faab_analyzer import run_faab_analysis
        faab_analysis = run_faab_analysis(
            query=query, rec_df=rec_df,
            budget_status=budget_status,
            schedule_game_counts=schedule_game_counts,
            avg_games=avg_games,
            roster_strength=roster_strength,
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
            roster_strength=roster_strength,
        )


if __name__ == "__main__":
    main()

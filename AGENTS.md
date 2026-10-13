# NBA Fantasy Advisor

This repository implements a Python CLI for Yahoo NBA 9-category head-to-head
waiver analysis, FAAB suggestions, and optional transactions. Shared workflow
and testing policy live in `/home/jbl/.codex/AGENTS.md`.

## Entry points and references

- `main.py` owns CLI modes; `config.py` owns defaults and environment loading.
- `src/yahoo_stats.py` owns player statistics and z-scores;
  `src/waiver_advisor.py` owns roster needs and recommendation scoring.
- `src/transactions.py` owns claims and roster moves; `src/league_settings.py`
  owns detected league constraints and budgets.
- [Methodology](docs/methodology.md), [FAAB analysis](docs/faab-analysis.md),
  [schedule analysis](docs/schedule-analysis.md), and
  [output reference](docs/output-reference.md) explain domain behavior.
- [Setup](docs/setup-guide.md), [transactions](docs/transactions.md), and
  [scheduled workflows](docs/github-workflows.md) explain operation.

Use source and `config.py` to resolve stale documentation or default values.
The retired `.github/skills/nba-fantasy-advisor` package is replaced by this
repository guidance and the existing domain documentation.

## Domain and authorization boundaries

- Preserve all nine categories: FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO.
  Shooting z-scores standardize `attempts * (percentage - mean_percentage)`;
  they are not the product of separate percentage and attempt z-scores.
  Invert turnovers. Exclude punted categories from totals and roster needs
  while retaining individual category scores.
- Preserve Unicode name normalization, owned-player exclusion, injury and
  availability handling, schedule decay, news/recency/trending adjustments,
  and FAAB tier floors/IQR separation. Follow the implementation's order of
  scoring operations; do not replace it with a simplified formula.
- Preserve protected/droppable player rules, IL/IL+ eligibility checks,
  unique-drop transaction counting, budget limits, roster-impact previews,
  confirmation, and manual fallback when Yahoo write scope is unavailable.
  Analysis does not authorize claims, drops, roster moves, or email delivery.
  `--claim` can write to Yahoo; `--watch` sends email. Require explicit task
  authority for these operations and retain the application's confirmations.
- Keep OAuth credentials, cached tokens, SMTP credentials, private roster
  exports, and provider responses out of output, commits, and instructions.
  Do not delete authentication state as a routine troubleshooting step.
  Follow the global credential workflow when credentials are needed.

## Setup, commands, and checks

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py --help
```

The CLI supports `--top`, `--days`, `--compact`, `--faab-history`, `--strategy`,
`--stream`, `--team`, `--list-leagues`, and `--list-teams`. Running analysis
requires Yahoo authentication and network access. `--skip-yahoo` currently
prints an error because statistics come from Yahoo; it is not an offline
verification path. `--dry-run` implies `--claim` and suppresses transaction
submission, but still authenticates, reads live providers, and produces output.

Importing `config.py` loads `.env` and creates the configured `OUTPUT_DIR`,
currently an absolute Windows-mounted path. Inspect it before executing even
`--help`; do not change paths, credentials, or scheduled workflows implicitly.

No automated test suite is currently checked in. For instruction-only edits,
review links and command definitions without importing the application. For
behavior changes, use focused disposable numerical/transaction checks with
external services mocked at their boundary. Claims, email, and live provider
acceptance require separately authorized verification.

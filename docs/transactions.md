# Transactions

This document describes how the NBA Fantasy Advisor submits waiver wire transactions (add/drop claims) through the Yahoo Fantasy Sports API.

## Overview

After the recommendation engine identifies the best available waiver pickups, you can optionally submit **add/drop transactions** directly from the command line. This drops a player from your configurable droppable list and picks up a recommended waiver target — all without leaving the terminal.

The flow supports **multiple bids per session** — you can queue several add/drop claims and submit them all at once. Yahoo processes them in priority order.

```
┌─────────────────────────────────────┐
│  1. Run full waiver analysis        │
│     (same pipeline as main.py)      │
├─────────────────────────────────────┤
│  2. Check IL/IL+ compliance         │
│     Auto-resolve if non-compliant   │
│     (drop player → move IL to BN)   │
├─────────────────────────────────────┤
│  3. Load FAAB analysis (optional)   │
│     Historical bids for suggestions │
├─────────────────────────────────────┤
│  4. Display droppable players       │
│     (minus any used for IL fix)     │
├─────────────────────────────────────┤
│  5. Display top recommendations     │
│     Top 10 with inline bid hints    │
├─────────────────────────────────────┤
│  6. Multi-bid loop                  │
│     Select drop/add + FAAB bid      │
│     Repeat for additional claims    │
├─────────────────────────────────────┤
│  7. Review & confirm queued claims  │
│     Summary of all pending bids     │
├─────────────────────────────────────┤
│  8. Resolve keys & submit XML       │
│     POST each claim to Yahoo API    │
└─────────────────────────────────────┘
```

## Usage

### Preview a transaction (dry run)

```bash
python main.py --dry-run
```

Runs the full analysis, shows the interactive selection menu, resolves player keys, and prints the XML payload — but does **not** submit anything to Yahoo. Use this to verify everything works before making a real claim.

### Submit a waiver claim

```bash
python main.py --claim
```

Runs the full analysis, then enters the interactive transaction flow. After you select players and confirm, it submits the add/drop to Yahoo's API.

> **Tip:** `--dry-run` implies `--claim`, so you don't need both flags.

### Combined with FAAB analysis

```bash
python main.py --claim --faab-history       # FAAB analysis + claim with smart bids
python main.py --claim --strategy aggressive # Use aggressive bid suggestions
python main.py --dry-run --faab-history      # Preview claims with FAAB suggestions
```

### Combined with other flags

```bash
python main.py --claim --top 25        # Show top 25 recs, then claim
python main.py --dry-run --days 7      # Use 7-day window, preview claim
```

`--claim` and `--dry-run` require Yahoo integration and cannot be used with `--skip-yahoo`.

## Configuration

### Droppable players (`config.py`)

```python
DROPPABLE_PLAYERS = [
    "Sandro Mamukelashvili",
    "Justin Champagnie",
    "Kristaps Porziņģis",
]
```

Only players in this list can be dropped. Everyone else on your roster is treated as untouchable. Update this list as your roster changes.

### FAAB settings (`config.py`)

```python
FAAB_ENABLED = True              # Set to True if your league uses FAAB bidding
DEFAULT_FAAB_BID = 1            # Fallback bid when no historical data available
FAAB_BID_OVERRIDE = True         # Prompt to override suggested bid (False = auto-accept)
FAAB_STRATEGY = "competitive"    # "value", "competitive", or "aggressive"
FAAB_BUDGET_REGULAR_SEASON = 300 # Total regular season FAAB budget
FAAB_BUDGET_PLAYOFFS = 100       # FAAB budget after playoff reset
FAAB_MAX_BID_PERCENT = 0.50      # Max % of remaining budget on a single bid
```

### Transaction limits (`config.py`)

```python
WEEKLY_TRANSACTION_LIMIT = 3     # Max transactions per week (resets Monday)
```

The tool checks your transactions since the start of the current fantasy week and enforces this limit. If you've already used all 3 transactions this week, the claim flow exits early with a message.

**Smart transaction counting:** Multiple bids against the **same drop player** only count as one transaction slot. Yahoo processes claims in priority order — if you queue 3 bids all dropping the same player, they consume only 1 of your 3 weekly slots (since at most one will actually execute). The tool counts *unique drop players* rather than total queued bids.

If `FAAB_ENABLED` is `True`, the transaction flow will:

- Show inline bid suggestions next to each recommendation (e.g., `~$9`)
- Pre-fill the bid prompt with the suggested amount based on your strategy
- Include the bid in the transaction XML as a `<faab_bid>` element

The `--strategy` CLI flag overrides `FAAB_STRATEGY` at runtime. See [FAAB Bid Analysis](faab-analysis.md) for details on how suggestions are computed.

For standard rolling waiver priority leagues, leave `FAAB_ENABLED = False`.

## How It Works

### 0. IL/IL+ auto-resolution

Before any transaction can be submitted, the tool checks your IL and IL+ roster slots for compliance. Yahoo Fantasy rules:

| Slot | Eligible Statuses |
|------|-------------------|
| **IL** | INJ, O, SUSP |
| **IL+** | INJ, O, GTD, DTD, SUSP |

If a player in an IL slot has recovered (no longer has an eligible status), Yahoo **blocks all transactions** for your team. The tool detects this and auto-resolves it in two steps:

1. **Drop a player** from your `DROPPABLE_PLAYERS` list to free a roster spot
2. **Move the non-compliant IL player** to the bench (BN) via a roster position PUT

This happens automatically — no manual intervention on the Yahoo website needed. The consumed droppable player(s) are then removed from the available list for the subsequent waiver bids.

**Example:** If you have 3 droppable players and 1 IL violation, the tool drops player #1 to resolve IL, then shows the remaining 2 players as options for your FAAB bid.

If there aren't enough droppable players to cover both IL resolution AND at least one waiver bid, the tool will warn you and stop.

### 1. Player key resolution

Yahoo's API identifies players by **player keys** (e.g., `418.p.6047`), not names. The module resolves names in two ways:

- **Drop player:** Fetches your current roster via `get_team_roster_player_info_by_date()` and matches by normalized name. Falls back to last-name + first-initial partial matching.
- **Add player:** First checks the recommendations DataFrame, then falls back to searching the league player pool via `get_league_players()` in 25-player batches.

### 2. Transaction XML

Yahoo's Fantasy API expects an XML payload for write operations. The module builds these with Python's `xml.etree.ElementTree`.

**Add/drop claim** (standard waiver bid):

```xml
<?xml version='1.0' encoding='utf-8'?>
<fantasy_content>
  <transaction>
    <type>add/drop</type>
    <faab_bid>5</faab_bid>          <!-- only if FAAB league -->
    <players>
      <player>
        <player_key>418.p.1234</player_key>
        <transaction_data>
          <type>add</type>
          <destination_team_key>418.l.94443.t.9</destination_team_key>
        </transaction_data>
      </player>
      <player>
        <player_key>418.p.5678</player_key>
        <transaction_data>
          <type>drop</type>
          <source_team_key>418.l.94443.t.9</source_team_key>
        </transaction_data>
      </player>
    </players>
  </transaction>
</fantasy_content>
```

**Drop-only transaction** (used during IL resolution to free a roster spot):

```xml
<?xml version='1.0' encoding='utf-8'?>
<fantasy_content>
  <transaction>
    <type>drop</type>
    <players>
      <player>
        <player_key>418.p.5678</player_key>
        <transaction_data>
          <type>drop</type>
          <source_team_key>418.l.94443.t.9</source_team_key>
        </transaction_data>
      </player>
    </players>
  </transaction>
</fantasy_content>
```

**Roster position change** (used during IL resolution to move a player from IL/IL+ to bench):

```xml
<?xml version='1.0' encoding='utf-8'?>
<fantasy_content>
  <roster>
    <coverage_type>date</coverage_type>
    <date>2026-02-17</date>
    <players>
      <player>
        <player_key>418.p.1234</player_key>
        <position>BN</position>
      </player>
    </players>
  </roster>
</fantasy_content>
```

### 3. API submission

The module reuses **yfpy's authenticated OAuth session** for all API calls:

**Transactions** (add/drop, drop-only):

```
POST https://fantasysports.yahooapis.com/fantasy/v2/league/{league_key}/transactions
Content-Type: application/xml
```

**Roster moves** (IL → BN position change):

```
PUT https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster
Content-Type: application/xml
```

Both avoid needing separate OAuth token management — yfpy handles token refresh automatically.

### 4. Safety guards

Several safeguards prevent accidental transactions:

| Guard | Description |
|-------|-------------|
| **Weekly transaction limit** | Enforces 3/week cap; counts unique drop players (multiple bids against same drop = 1 slot) |
| **FAAB budget caps** | Max single bid = 50% of remaining; hard cap at remaining budget |
| **IL/IL+ compliance** | Auto-checks IL slots and resolves non-compliance before proceeding |
| **Droppable list** | Only players in `DROPPABLE_PLAYERS` can be dropped |
| **Roster verification** | Confirms the drop player is actually on your roster |
| **Player key validation** | Both add and drop player keys must resolve before proceeding |
| **Explicit confirmation** | Prompts "Submit all claims? (yes/no)" before submitting any queued claims |
| **Dry-run mode** | `--dry-run` shows the full XML without sending it |
| **Queue review** | All queued claims are displayed in a summary table before confirmation |

## Error handling

| Error | Cause | Fix |
|-------|-------|-----|
| "IL resolution failed" | Drop or roster move was rejected by Yahoo | Check the error details; the player may already be in a valid state |
| "Could not find X on your roster" | Drop player name doesn't match any roster player | Check spelling in `DROPPABLE_PLAYERS`; names must match Yahoo's format |
| "Could not find player key for X" | Add player not found in Yahoo's player pool | Verify the player name matches Yahoo's listing |
| HTTP 401 | OAuth token expired or invalid | Delete `token.json` in project root and re-authenticate |
| HTTP 403 | Insufficient API permissions | Verify your Yahoo Developer App has Fantasy Sports checked |
| HTTP 400 | Invalid transaction (player on waivers, roster full, etc.) | Check the response body for Yahoo's specific error message |

## Architecture

```
src/transactions.py
├── IL/IL+ compliance
│   ├── check_il_compliance()            # Scan roster for IL violations
│   └── resolve_il_violations()          # Auto-drop + move IL player to BN
├── Player key resolution
│   ├── find_player_key_on_roster()      # Drop player → key
│   ├── find_player_key_from_recommendations()  # Add player → key
│   └── _search_league_for_player_key()  # Fallback Yahoo search
├── XML builders
│   ├── build_add_drop_xml()             # Add/drop payload
│   ├── build_add_only_xml()             # Add-only payload
│   ├── build_drop_only_xml()            # Drop-only payload (IL resolution)
│   └── build_roster_move_xml()          # Roster position change (IL → BN)
├── API submission
│   ├── submit_transaction()             # POST via yfpy OAuth
│   └── submit_roster_move()             # PUT via yfpy OAuth
├── High-level flow
│   ├── submit_add_drop()                # Resolve + build + submit
│   └── run_transaction_flow()           # Interactive multi-bid menu
│       ├── IL auto-resolution           # Pre-flight fix for IL violations
│       ├── FAAB analysis integration    # Inline bid suggestions
│       ├── _unique_drops_used()         # Count unique drop players in queue
│       ├── Multi-bid queue loop         # Queue multiple claims
│       └── Batch submission             # Submit all claims sequentially
├── FAAB integration (imported from src/faab_analyzer.py)
│   ├── fetch_league_transactions()      # Load bid history
│   ├── analyze_bid_history()            # Compute tier/team stats
│   └── suggest_bid()                    # Per-player bid suggestion
└── Helpers
    ├── get_league_key()
    └── get_team_key()
```

## Limitations

- **Read vs Write scope:** Yahoo's Fantasy Sports Developer App settings show only a "Read" toggle. Despite the label, the Fantasy Sports OAuth scope covers both read and write operations as long as you are the team manager.
- **yfpy is read-only:** yfpy itself has no write methods. This module works around that by directly accessing yfpy's internal OAuth session for POST requests.
- **Waiver processing:** Submitting a claim doesn't guarantee the pickup. Yahoo processes waivers on its normal schedule (typically overnight). The claim enters the waiver queue.
- **Multiple bids, same drop player:** You can drop the same player for different add targets. Yahoo processes claims in priority order — if the first claim wins, the rest are automatically voided. The tool correctly counts unique drop players rather than total bids when tracking your weekly transaction limit.
- **Budget tracking:** The claim flow reads your remaining FAAB balance from Yahoo, displays budget status (FLUSH/HEALTHY/TIGHT/CRITICAL), and enforces bid caps based on remaining budget.

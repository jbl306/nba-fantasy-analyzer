# Example Run

Full output of `python main.py --claim --dry-run --faab-history` — a combined analysis + dry-run waiver claim session with FAAB bid history.

This run demonstrates:

- Yahoo Fantasy league connection and roster scanning
- 9-category z-score analysis with team need weighting
- ESPN injury report integration
- NBA schedule analysis (3 weeks ahead)
- FAAB bid history analysis with IQR outlier detection
- Interactive waiver claim flow (dry-run mode)

---

## Command

```
$ python main.py --claim --dry-run --faab-history
```

## Output

### 1. Startup & League Connection

```
======================================================================
  NBA FANTASY ADVISOR - Waiver Wire Recommendations
  League: 94443 | Team: 9
  Scoring: 9-Category H2H
======================================================================

Connecting to Yahoo Fantasy Sports...
  Fetching league settings from Yahoo...
======================================================================
  LEAGUE SETTINGS & CONSTRAINTS
======================================================================

  League:           b'Milltown Fantasy Ball'
  Scoring:          head
  Waiver type:      FR
  Uses FAAB:        1
  Max season adds:  ?
  Current week:     17
  End week:         21
  Playoff starts:   Week 19

  Roster positions: [RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "PG",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "SG",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "G",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "SF",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "PF",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "F",
  "position_type": "P"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 1,
  "position": "C",
  "position_type": "P"
}), RosterPosition({
  "count": 2,
  "is_starting_position": 1,
  "position": "Util",
  "position_type": "P"
}), RosterPosition({
  "count": 3,
  "is_starting_position": 0,
  "position": "BN"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 0,
  "position": "IL"
}), RosterPosition({
  "count": 1,
  "is_starting_position": 0,
  "position": "IL+"
})]


Fetching all team rosters in the league...
    b'the profeshunals': 14 players
    b'cool CADE': 14 players
    b'MeLO iN ThE TrAp': 14 players
    b'Dabham': 14 players
    b'Cool Cats': 14 players
    b'Rookie': 14 players
    b'Da Young OG': 14 players
    b'Old School Legends': 14 players
    b'jbl': 14 players
    b"Tanking for tanking's sake": 14 players
    b'Big Kalk': 14 players
    b"Kailash Gupta's Boss Team": 12 players

  12 teams, 166 total owned players

Your roster (14 players):
    De'Aaron Fox              PG,SG      SAS
    Bennedict Mathurin        SG,SF      LAC
    Tyrese Maxey              PG         PHI
    Jaylen Brown              SG,SF      BOS
    Mikal Bridges             SG,SF,PF   NYK
    Saddiq Bey                SF,PF      NOP
    Jusuf Nurkić              C          UTA
    Jarrett Allen             C          CLE
    Isaiah Hartenstein        C          OKC
    Zion Williamson           SF,PF,C    NOP
    Sandro Mamukelashvili     PF,C       TOR
    Justin Champagnie         SF,PF      WAS
    Kristaps Porziņģis        PF,C       GSW
    Ivica Zubac               C          IND

Fetching NBA player stats...
  Fetching league-wide player stats for 2025-26 (PerGame)...
  Computing availability rates...
  Loaded stats for 335 NBA players

  163 players owned in your league
  172 players available on waivers

Analyzing your roster's 9-cat profile...
======================================================================
YOUR TEAM CATEGORY ANALYSIS
======================================================================

Category       Team Avg Z      Assessment
------------------------------------------
TO                  -0.37       Below Avg
3PM                 -0.13       Below Avg
FT%                 -0.09       Below Avg
BLK                  0.23         Average
AST                  0.31         Average
STL                  0.39         Average
PTS                  0.71          STRONG
FG%                  0.78          STRONG
REB                  0.85          STRONG

Strengths: AST, STL, PTS, FG%, REB
Weaknesses: TO
  -> Target waiver pickups strong in: TO

Checking recent game activity for top 10 candidates...
  0 active, 6 inactive/injured

  Fetching NBA injury report from ESPN...
  Found 114 players on the injury report
  114 players on injury report, 47 available but injured

  Fetching NBA schedule from NBA.com...
  Loaded 1309 games from NBA schedule
Ranking available players (need + availability + injury + schedule adjusted)...
====================================================================================================
TOP WAIVER WIRE RECOMMENDATIONS
====================================================================================================

  Rank  Player             Team      GP    MIN    Games_Wk  Avail%    Health    Injury    Recent        G/14d      FG%    FT%    3PM    PTS    REB    AST    STL    BLK    TO    Z_Value    Adj_Score
------  -----------------  ------  ----  -----  ----------  --------  --------  --------  ------------  -------  -----  -----  -----  -----  -----  -----  -----  -----  ----  ---------  -----------
     1  Sam Merrill        CLE       31   25.3           5  55%       Risky     -         -             -        0.484  0.878    3.5   13.6    2.3    2.3    0.6    0.2   0.9        1.1         1.95
     2  Julian Champagnie  SAS       54   27.9           4  96%       Healthy   -         -             -        0.422  0.846    2.4   11.1    5.9    1.4    0.8    0.4   0.9       0.64          1.8
     3  Max Christie       DAL       50   29.7           4  89%       Healthy   -         -             -        0.467  0.869    2.5   13.3    3.4    2.3    0.6    0.4   1.1       0.53         1.72
     4  Jay Huff           IND       55     20           5  98%       Healthy   -         Questionable  4        0.469  0.845    1.4    8.7    3.8    1.3    0.6    1.9   0.8       1.67          1.7
     5  Reed Sheppard      HOU       53   24.7           4  95%       Healthy   -         Questionable  5        0.426  0.776    2.4   12.7    2.6      3    1.4    0.6   1.3       1.33          1.5
     6  Royce O'Neale      PHX       55   29.3           5  98%       Healthy   -         -             -        0.424  0.679    2.8   10.3    4.8    2.9    1.2    0.3   1.5       0.78         1.45
     7  Moses Moody        GSW       53   25.1           4  95%       Healthy   -         -             -        0.437  0.779    2.4   11.5    3.3    1.5    0.9    0.6   0.9        0.1         0.97
     8  Neemias Queta      BOS       51   25.1           3  91%       Healthy   -         Questionable  4        0.639   0.67      0    9.7    8.3    1.5    0.9    1.3   1.1        2.2         0.84
     9  Al Horford         GSW       34   20.6           4  61%       Moderate  -         -             -        0.429  0.895    1.4    7.6    4.9    2.3    0.8    1.1     1       0.49         0.72
    10  Derrick Jones Jr.  LAC       22   24.8           5  39%       Fragile   -         -             -        0.541  0.775    1.3     10    2.5    1.2    0.9    1.1   0.8       0.72         0.48
    11  Duncan Robinson    DET       51   28.2           4  91%       Healthy   -         -             -        0.441   0.74    2.9   12.3    2.7    1.9    0.6    0.3   0.7      -0.73         0.48
    12  Isaiah Joe         OKC       47   21.1           5  84%       Healthy   -         -             -        0.441  0.882    2.4   10.5    2.5    1.4    0.6    0.2   0.6      -1.04          0.4
    13  AJ Green           MIL       49   30.2           5  88%       Healthy   -         -             -         0.44  0.794    3.1   10.7    2.6      2    0.6    0.1   0.8      -1.04         0.34
    14  Tim Hardaway Jr.   DEN       54   27.5           5  96%       Healthy   OUT       -             -        0.453  0.859    2.9   14.1    2.6    1.3    0.5    0.1   0.5      -0.16         0.17
    15  Cameron Johnson    DEN       31   30.4           5  55%       Risky     -         -             -         0.47   0.81    1.9   11.5    3.6    2.2    0.7    0.3   0.9       -0.5         0.15

Z_Value   = Raw 9-cat z-score (higher = better all-around)
Adj_Score = Z_Value weighted by team needs, availability, injury, AND schedule
Games_Wk  = Games this upcoming week (more games = more stat production)
Avail%    = Games Played / Team Games (season durability)
Health    = Healthy (>=80%) | Moderate (60-80%) | Risky (40-60%) | Fragile (<40%)
Injury    = OUT-SEASON | OUT | DTD (Day-To-Day) | - (not on injury report)
Recent    = Active (played <3d ago) | Questionable (3-10d) | Inactive (>10d)

====================================================================================================
INJURY REPORT NOTES (source: ESPN)
====================================================================================================
  Tim Hardaway Jr.          OUT (Left Foot) - Minnesota won't play again until Feb. 20 against the Mavericks after heading ...

======================================================================
  UPCOMING SCHEDULE: Week 17: Feb 09 – Feb 22
======================================================================

Team      Games  Dates
------  -------  -----------------------------------------------------
ATL           5  Mon 02/09, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
BKN           5  Mon 02/09, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
CHA           5  Mon 02/09, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
CHI           5  Mon 02/09, Wed 02/11, Thu 02/19, Sat 02/21, Sun 02/22
CLE           5  Mon 02/09, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
DEN           5  Mon 02/09, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
IND           5  Tue 02/10, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
LAC           5  Tue 02/10, Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
LAL           5  Mon 02/09, Tue 02/10, Thu 02/12, Fri 02/20, Sun 02/22
MIL           5  Mon 02/09, Wed 02/11, Thu 02/12, Fri 02/20, Sun 02/22
NYK           5  Tue 02/10, Wed 02/11, Thu 02/19, Sat 02/21, Sun 02/22
OKC           5  Mon 02/09, Wed 02/11, Thu 02/12, Fri 02/20, Sun 02/22
ORL           5  Mon 02/09, Wed 02/11, Thu 02/19, Sat 02/21, Sun 02/22
PHI           5  Mon 02/09, Wed 02/11, Thu 02/19, Sat 02/21, Sun 02/22
PHX           5  Tue 02/10, Wed 02/11, Thu 02/19, Sat 02/21, Sun 02/22
POR           5  Mon 02/09, Wed 02/11, Thu 02/12, Fri 02/20, Sun 02/22
DAL           4  Tue 02/10, Thu 02/12, Fri 02/20, Sun 02/22
DET           4  Mon 02/09, Wed 02/11, Thu 02/19, Sat 02/21
GSW           4  Mon 02/09, Wed 02/11, Thu 02/19, Sun 02/22
HOU           4  Tue 02/10, Wed 02/11, Thu 02/19, Sat 02/21
MEM           4  Mon 02/09, Wed 02/11, Fri 02/20, Sat 02/21
MIA           4  Mon 02/09, Wed 02/11, Fri 02/20, Sat 02/21
MIN           4  Mon 02/09, Wed 02/11, Fri 02/20, Sun 02/22
NOP           4  Mon 02/09, Wed 02/11, Fri 02/20, Sat 02/21
SAC           4  Mon 02/09, Wed 02/11, Thu 02/19, Sat 02/21
SAS           4  Tue 02/10, Wed 02/11, Thu 02/19, Sat 02/21
UTA           4  Mon 02/09, Wed 02/11, Thu 02/12, Fri 02/20
WAS           4  Wed 02/11, Thu 02/19, Fri 02/20, Sun 02/22
BOS           3  Wed 02/11, Thu 02/19, Sun 02/22
STP           3  Sun 02/15, Sun 02/15, Sun 02/15
STR           3  Sun 02/15, Sun 02/15, Sun 02/15
TOR           3  Wed 02/11, Thu 02/19, Sun 02/22
MEL           2  Fri 02/13, Fri 02/13
VIN           2  Fri 02/13, Fri 02/13
WLD           2  Sun 02/15, Sun 02/15
AUS           1  Fri 02/13
TMC           1  Fri 02/13

  Average: 4.0 games/team  |  Range: 1–5

======================================================================
  UPCOMING SCHEDULE: Week 18: Feb 23 – Mar 01
======================================================================

Team      Games  Dates
------  -------  ------------------------------------------
BKN           4  Tue 02/24, Thu 02/26, Fri 02/27, Sun 03/01
BOS           4  Tue 02/24, Wed 02/25, Fri 02/27, Sun 03/01
CLE           4  Tue 02/24, Wed 02/25, Fri 02/27, Sun 03/01
DAL           4  Tue 02/24, Thu 02/26, Fri 02/27, Sun 03/01
DET           4  Mon 02/23, Wed 02/25, Fri 02/27, Sun 03/01
HOU           4  Mon 02/23, Wed 02/25, Thu 02/26, Sat 02/28
LAL           4  Tue 02/24, Thu 02/26, Sat 02/28, Sun 03/01
MEM           4  Mon 02/23, Wed 02/25, Fri 02/27, Sun 03/01
MIL           4  Tue 02/24, Wed 02/25, Fri 02/27, Sun 03/01
NOP           4  Tue 02/24, Thu 02/26, Sat 02/28, Sun 03/01
OKC           4  Tue 02/24, Wed 02/25, Fri 02/27, Sun 03/01
POR           4  Tue 02/24, Thu 02/26, Sat 02/28, Sun 03/01
SAC           4  Mon 02/23, Wed 02/25, Thu 02/26, Sun 03/01
SAS           4  Mon 02/23, Wed 02/25, Thu 02/26, Sun 03/01
ATL           3  Tue 02/24, Thu 02/26, Sun 03/01
CHA           3  Tue 02/24, Thu 02/26, Sat 02/28
CHI           3  Tue 02/24, Thu 02/26, Sun 03/01
DEN           3  Wed 02/25, Fri 02/27, Sun 03/01
GSW           3  Tue 02/24, Wed 02/25, Sat 02/28
IND           3  Tue 02/24, Thu 02/26, Sun 03/01
MIA           3  Tue 02/24, Thu 02/26, Sat 02/28
MIN           3  Tue 02/24, Thu 02/26, Sun 03/01
NYK           3  Tue 02/24, Fri 02/27, Sun 03/01
ORL           3  Tue 02/24, Thu 02/26, Sun 03/01
PHI           3  Tue 02/24, Thu 02/26, Sun 03/01
TOR           3  Tue 02/24, Wed 02/25, Sat 02/28
UTA           3  Mon 02/23, Thu 02/26, Sat 02/28
WAS           3  Tue 02/24, Thu 02/26, Sat 02/28
LAC           2  Thu 02/26, Sun 03/01
PHX           2  Tue 02/24, Thu 02/26

  Average: 3.4 games/team  |  Range: 2–4

======================================================================
  UPCOMING SCHEDULE: Week 19: Mar 02 – Mar 08
======================================================================

Team      Games  Dates
------  -------  ------------------------------------------
BOS           4  Mon 03/02, Wed 03/04, Fri 03/06, Sun 03/08
CHA           4  Tue 03/03, Wed 03/04, Fri 03/06, Sun 03/08
DAL           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
DET           4  Tue 03/03, Thu 03/05, Sat 03/07, Sun 03/08
HOU           4  Mon 03/02, Thu 03/05, Fri 03/06, Sun 03/08
LAC           4  Mon 03/02, Wed 03/04, Fri 03/06, Sat 03/07
LAL           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
MIA           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
MIL           4  Mon 03/02, Wed 03/04, Sat 03/07, Sun 03/08
NOP           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
NYK           4  Tue 03/03, Wed 03/04, Fri 03/06, Sun 03/08
ORL           4  Tue 03/03, Thu 03/05, Sat 03/07, Sun 03/08
PHX           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
SAS           4  Tue 03/03, Thu 03/05, Fri 03/06, Sun 03/08
UTA           4  Mon 03/02, Wed 03/04, Thu 03/05, Sat 03/07
WAS           4  Mon 03/02, Tue 03/03, Thu 03/05, Sun 03/08
BKN           3  Tue 03/03, Thu 03/05, Sat 03/07
CHI           3  Tue 03/03, Thu 03/05, Sun 03/08
DEN           3  Mon 03/02, Thu 03/05, Fri 03/06
GSW           3  Mon 03/02, Thu 03/05, Sat 03/07
IND           3  Wed 03/04, Fri 03/06, Sun 03/08
MEM           3  Tue 03/03, Wed 03/04, Sat 03/07
MIN           3  Tue 03/03, Thu 03/05, Sat 03/07
OKC           3  Tue 03/03, Wed 03/04, Sat 03/07
PHI           3  Tue 03/03, Wed 03/04, Sat 03/07
POR           3  Wed 03/04, Fri 03/06, Sun 03/08
SAC           3  Tue 03/03, Thu 03/05, Sun 03/08
TOR           3  Tue 03/03, Thu 03/05, Sun 03/08
ATL           2  Wed 03/04, Sat 03/07
CLE           2  Tue 03/03, Sun 03/08

  Average: 3.5 games/team  |  Range: 2–4

======================================================================
  WAIVER TARGET SCHEDULE VALUE (Week 17: Feb 09 – Feb 22)
======================================================================

  #  Player             Team      Games    Z/Game    Week_Z    Sched×
---  -----------------  ------  -------  --------  --------  --------
  1  Sam Merrill        CLE           5      1.1       5.5        1.1
  2  Julian Champagnie  SAS           4      0.64      2.56       1
  3  Max Christie       DAL           4      0.53      2.12       1
  4  Jay Huff           IND           5      1.67      8.35       1.1
  5  Reed Sheppard      HOU           4      1.33      5.32       1
  6  Royce O'Neale      PHX           5      0.78      3.9        1.1
  7  Moses Moody        GSW           4      0.1       0.4        1
  8  Neemias Queta      BOS           3      2.2       6.6        0.9
  9  Al Horford         GSW           4      0.49      1.96       1
 10  Derrick Jones Jr.  LAC           5      0.72      3.6        1.1
 11  Duncan Robinson    DET           4     -0.73     -2.92       1
 12  Isaiah Joe         OKC           5     -1.04     -5.2        1.1
 13  AJ Green           MIL           5     -1.04     -5.2        1.1
 14  Tim Hardaway Jr.   DEN           5     -0.16     -0.8        1.1
 15  Cameron Johnson    DEN           5     -0.5      -2.5        1.1

======================================================================
  DROPPABLE PLAYERS SCHEDULE (Week 17: Feb 09 – Feb 22)
======================================================================

Player                 Team      Games    Z/Game    Week_Z
---------------------  ------  -------  --------  --------
Sandro Mamukelashvili  TOR           3      0.85      2.55
Justin Champagnie      WAS           4     -0.74     -2.98
Kristaps Porziņģis     GSW           4      3.55     14.2

======================================================================
  NET VALUE: WAIVER TARGETS vs DROPPABLE PLAYERS
  (Week 17: Feb 09 – Feb 22)
======================================================================

  #  Add Player           Add(G)    Add Wk_Z  Drop Player              Drop(G)    Drop Wk_Z     Net
---  -----------------  --------  ----------  ---------------------  ---------  -----------  ------
  1  Sam Merrill               5        5.5   Sandro Mamukelashvili          3         2.55    2.95
  1  Sam Merrill               5        5.5   Justin Champagnie              4        -2.98    8.48
  1  Sam Merrill               5        5.5   Kristaps Porziņģis             4        14.2    -8.7
  2  Julian Champagnie         4        2.56  Sandro Mamukelashvili          3         2.55    0.01
  2  Julian Champagnie         4        2.56  Justin Champagnie              4        -2.98    5.54
  2  Julian Champagnie         4        2.56  Kristaps Porziņģis             4        14.2   -11.64
  3  Max Christie              4        2.12  Sandro Mamukelashvili          3         2.55   -0.43
  3  Max Christie              4        2.12  Justin Champagnie              4        -2.98    5.1
  3  Max Christie              4        2.12  Kristaps Porziņģis             4        14.2   -12.08
  4  Jay Huff                  5        8.35  Sandro Mamukelashvili          3         2.55    5.8
  4  Jay Huff                  5        8.35  Justin Champagnie              4        -2.98   11.33
  4  Jay Huff                  5        8.35  Kristaps Porziņģis             4        14.2    -5.85
  5  Reed Sheppard             4        5.32  Sandro Mamukelashvili          3         2.55    2.77
  5  Reed Sheppard             4        5.32  Justin Champagnie              4        -2.98    8.3
  5  Reed Sheppard             4        5.32  Kristaps Porziņģis             4        14.2    -8.88
  6  Royce O'Neale             5        3.9   Sandro Mamukelashvili          3         2.55    1.35
  6  Royce O'Neale             5        3.9   Justin Champagnie              4        -2.98    6.88
  6  Royce O'Neale             5        3.9   Kristaps Porziņģis             4        14.2   -10.3
  7  Moses Moody               4        0.4   Sandro Mamukelashvili          3         2.55   -2.15
  7  Moses Moody               4        0.4   Justin Champagnie              4        -2.98    3.38
  7  Moses Moody               4        0.4   Kristaps Porziņģis             4        14.2   -13.8
  8  Neemias Queta             3        6.6   Sandro Mamukelashvili          3         2.55    4.05
  8  Neemias Queta             3        6.6   Justin Champagnie              4        -2.98    9.58
  8  Neemias Queta             3        6.6   Kristaps Porziņģis             4        14.2    -7.6
  9  Al Horford                4        1.96  Sandro Mamukelashvili          3         2.55   -0.59
  9  Al Horford                4        1.96  Justin Champagnie              4        -2.98    4.94
  9  Al Horford                4        1.96  Kristaps Porziņģis             4        14.2   -12.24
 10  Derrick Jones Jr.         5        3.6   Sandro Mamukelashvili          3         2.55    1.05
 10  Derrick Jones Jr.         5        3.6   Justin Champagnie              4        -2.98    6.58
 10  Derrick Jones Jr.         5        3.6   Kristaps Porziņģis             4        14.2   -10.6

  Net = Add_Weekly_Z − Drop_Weekly_Z  (positive = upgrade)

Results saved to /home/jbl/projects/nba-fantasy-advisor/output/waiver_recommendations.csv
  Fetching league settings from Yahoo...
  Warning: could not fetch FAAB balance from Yahoo: YahooFantasySportsQuery.get_team_info() missing 1 required positional argument: 'team_id'

Fetching league transaction history...
  Found 207 add/drop transactions
Analyzing FAAB bid patterns...
======================================================================
  FAAB BID HISTORY ANALYSIS
======================================================================

  Total transactions:  207
  FAAB bids:           127
  Free pickups ($0):   80
  Standard bids:       121
  Premium bids:        6  (outlier threshold: $23)

  Standard bid mean:   $6.8
  Standard bid median: $6
  Standard bid max:    $21
  Standard bid min:    $1
  Bid std deviation:   $5.2
  Raw mean (all bids): $9.4  (includes premium)

======================================================================
  PREMIUM PICKUPS (returning stars / outlier bids)
======================================================================

  These bids are statistical outliers (>= $23) and are
  excluded from standard tier statistics to prevent inflation.

  Premium bid count:   6
  Premium bid mean:    $60.8
  Premium bid median:  $44.5
  Premium bid range:   $31 - $113

Player             Bid    Team              Tier     Dropped
-----------------  -----  ----------------  -------  -----------------
Marvin Bagley III  $113   Dabham            Dart     Rui Hachimura
Paul George        $101   Da Young OG       Dart     Malik Monk
Kel'el Ware        $53    MeLO iN ThE TrAp  Unknown  Aaron Nesmith
Ace Bailey         $36    MeLO iN ThE TrAp  Unknown  Jaren Jackson Jr.
Jayson Tatum       $31    the profeshunals  Unknown  Neemias Queta
Will Riley         $31    the profeshunals  Unknown  Ace Bailey

======================================================================
  STANDARD BIDS BY PLAYER QUALITY TIER
======================================================================
  (premium outliers excluded for accurate bid suggestions)

Tier        Count  Mean    Median    Min    Max    P25    P75
--------  -------  ------  --------  -----  -----  -----  -----
Solid           5  $5      $3        $2     $13    $3     $4
Streamer        2  $4.5    $4.5      $1     $8     $-     $-
Dart           48  $5.7    $5.0      $1     $21    $2     $7
Unknown        66  $7.9    $7.0      $1     $21    $3     $13

======================================================================
  SPENDING BY TEAM (all bids)
======================================================================

Team                Total Spent      # Bids  Avg Bid    Max Bid
------------------  -------------  --------  ---------  ---------
Da Young OG         $223                 24  $9.3       $101
Dabham              $205                  8  $25.6      $113
the profeshunals    $192                 16  $12.0      $31
Big Kalk            $179                 20  $8.9       $21
MeLO iN ThE TrAp    $170                 19  $8.9       $53
cool CADE           $128                 17  $7.5       $16
Old School Legends  $45                   5  $9.0       $15
jbl                 $31                  15  $2.1       $7
Rookie              $10                   1  $10.0      $10
Cool Cats           $8                    2  $4.0       $5

======================================================================
  TOP 10 BIGGEST FAAB BIDS
======================================================================

Player                    Bid    Category    Team              Dropped
------------------------  -----  ----------  ----------------  -----------------
Marvin Bagley III         $113   PREMIUM     Dabham            Rui Hachimura
Paul George               $101   PREMIUM     Da Young OG       Malik Monk
Kel'el Ware               $53    PREMIUM     MeLO iN ThE TrAp  Aaron Nesmith
Ace Bailey                $36    PREMIUM     MeLO iN ThE TrAp  Jaren Jackson Jr.
Jayson Tatum              $31    PREMIUM     the profeshunals  Neemias Queta
Will Riley                $31    PREMIUM     the profeshunals  Ace Bailey
Zach LaVine               $21    standard    Big Kalk          P.J. Washington
Nic Claxton               $21    standard    the profeshunals  Kon Knueppel
Nickeil Alexander-Walker  $21    standard    the profeshunals  Reed Sheppard
Jonathan Kuminga          $18    standard    Dabham            -

======================================================================
  SUGGESTED FAAB BIDS (strategy: value)
======================================================================

    Player               Adj_Score  Tier        Games  Bid    Premium    Confidence    Reason
--  -----------------  -----------  --------  -------  -----  ---------  ------------  -------------------------------------------------------------------------
 0  Sam Merrill               1.95  Solid           5  $3     $31-$113   high          P25 for Solid tier (bargain, std bids) (Budget: HEALTHY, 5G this week)
 1  Julian Champagnie         1.8   Solid           4  $3     $31-$113   high          P25 for Solid tier (bargain, std bids) (Budget: HEALTHY, 4G this week)
 2  Max Christie              1.72  Solid           4  $3     $31-$113   high          P25 for Solid tier (bargain, std bids) (Budget: HEALTHY, 4G this week)
 3  Jay Huff                  1.7   Solid           5  $3     $31-$113   high          P25 for Solid tier (bargain, std bids) (Budget: HEALTHY, 5G this week)
 4  Reed Sheppard             1.5   Solid           4  $3     $31-$113   high          P25 for Solid tier (bargain, std bids) (Budget: HEALTHY, 4G this week)
 5  Royce O'Neale             1.45  Streamer        5  $1     $31-$113   medium        P25 for Streamer tier (bargain, std bids) (Budget: HEALTHY, 5G this week)
 6  Moses Moody               0.97  Streamer        4  $1     $31-$113   medium        P25 for Streamer tier (bargain, std bids) (Budget: HEALTHY, 4G this week)
 7  Neemias Queta             0.84  Streamer        3  $1     $31-$113   medium        P25 for Streamer tier (bargain, std bids) (Budget: HEALTHY, 3G this week)
 8  Al Horford                0.72  Streamer        4  $1     $31-$113   medium        P25 for Streamer tier (bargain, std bids) (Budget: HEALTHY, 4G this week)
 9  Derrick Jones Jr.         0.48  Dart            5  $2     $31-$113   high          P25 for Dart tier (bargain, std bids) (Budget: HEALTHY, 5G this week)

Strategies: value (bargain) | competitive (market rate) | aggressive (ensure win)
Premium column shows the historical range for returning-star / outlier bids.

======================================================================
  SUGGESTED FAAB BIDS (strategy: competitive)
======================================================================

    Player               Adj_Score  Tier        Games  Bid    Premium    Confidence    Reason
--  -----------------  -----------  --------  -------  -----  ---------  ------------  --------------------------------------------------------------------------------
 0  Sam Merrill               1.95  Solid           5  $3     $31-$113   high          Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 5G this week)
 1  Julian Champagnie         1.8   Solid           4  $3     $31-$113   high          Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 4G this week)
 2  Max Christie              1.72  Solid           4  $3     $31-$113   high          Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 4G this week)
 3  Jay Huff                  1.7   Solid           5  $3     $31-$113   high          Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 5G this week)
 4  Reed Sheppard             1.5   Solid           4  $3     $31-$113   high          Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 4G this week)
 5  Royce O'Neale             1.45  Streamer        5  $5     $31-$113   medium        Median for Streamer tier (market rate, std bids) (Budget: HEALTHY, 5G this week)
 6  Moses Moody               0.97  Streamer        4  $4     $31-$113   medium        Median for Streamer tier (market rate, std bids) (Budget: HEALTHY, 4G this week)
 7  Neemias Queta             0.84  Streamer        3  $3     $31-$113   medium        Median for Streamer tier (market rate, std bids) (Budget: HEALTHY, 3G this week)
 8  Al Horford                0.72  Streamer        4  $4     $31-$113   medium        Median for Streamer tier (market rate, std bids) (Budget: HEALTHY, 4G this week)
 9  Derrick Jones Jr.         0.48  Dart            5  $6     $31-$113   high          Median for Dart tier (market rate, std bids) (Budget: HEALTHY, 5G this week)

Strategies: value (bargain) | competitive (market rate) | aggressive (ensure win)
Premium column shows the historical range for returning-star / outlier bids.

======================================================================
  SUGGESTED FAAB BIDS (strategy: aggressive)
======================================================================

    Player               Adj_Score  Tier        Games  Bid    Premium    Confidence    Reason
--  -----------------  -----------  --------  -------  -----  ---------  ------------  ---------------------------------------------------------------------------------
 0  Sam Merrill               1.95  Solid           5  $5     $31-$113   high          P75 for Solid tier (higher win rate, std bids) (Budget: HEALTHY, 5G this week)
 1  Julian Champagnie         1.8   Solid           4  $4     $31-$113   high          P75 for Solid tier (higher win rate, std bids) (Budget: HEALTHY, 4G this week)
 2  Max Christie              1.72  Solid           4  $4     $31-$113   high          P75 for Solid tier (higher win rate, std bids) (Budget: HEALTHY, 4G this week)
 3  Jay Huff                  1.7   Solid           5  $5     $31-$113   high          P75 for Solid tier (higher win rate, std bids) (Budget: HEALTHY, 5G this week)
 4  Reed Sheppard             1.5   Solid           4  $4     $31-$113   high          P75 for Solid tier (higher win rate, std bids) (Budget: HEALTHY, 4G this week)
 5  Royce O'Neale             1.45  Streamer        5  $10    $31-$113   medium        P75 for Streamer tier (higher win rate, std bids) (Budget: HEALTHY, 5G this week)
 6  Moses Moody               0.97  Streamer        4  $8     $31-$113   medium        P75 for Streamer tier (higher win rate, std bids) (Budget: HEALTHY, 4G this week)
 7  Neemias Queta             0.84  Streamer        3  $7     $31-$113   medium        P75 for Streamer tier (higher win rate, std bids) (Budget: HEALTHY, 3G this week)
 8  Al Horford                0.72  Streamer        4  $8     $31-$113   medium        P75 for Streamer tier (higher win rate, std bids) (Budget: HEALTHY, 4G this week)
 9  Derrick Jones Jr.         0.48  Dart            5  $8     $31-$113   high          P75 for Dart tier (higher win rate, std bids) (Budget: HEALTHY, 5G this week)

Strategies: value (bargain) | competitive (market rate) | aggressive (ensure win)
Premium column shows the historical range for returning-star / outlier bids.

FAAB history saved to /home/jbl/projects/nba-fantasy-advisor/output/faab_analysis.csv

======================================================================
  WAIVER CLAIM TRANSACTION
  [DRY RUN MODE — no transactions will be submitted]
======================================================================

  2 transactions remaining this week (1/3)

  FAAB Budget: $300 remaining | $150.0/wk | Status: HEALTHY | Max bid: $150

Checking IL/IL+ roster compliance...
  ✓ IL/IL+ slots are compliant

Your droppable players (3):
  1. Sandro Mamukelashvili          (466.p.6596)
  2. Justin Champagnie              (466.p.6632)
  3. Kristaps Porziņģis             (466.p.5464)

Top 10 waiver recommendations:
   1. Sam Merrill                  CLE   Score:   1.95  5G  ~$3
   2. Julian Champagnie            SAS   Score:   1.80  4G  ~$3
   3. Max Christie                 DAL   Score:   1.72  4G  ~$3
   4. Jay Huff                     IND   Score:   1.70  5G  ~$3
   5. Reed Sheppard                HOU   Score:   1.50  4G  ~$3
   6. Royce O'Neale                PHX   Score:   1.45  5G  ~$5
   7. Moses Moody                  GSW   Score:   0.97  4G  ~$4
   8. Neemias Queta                BOS   Score:   0.84  3G  ~$3
   9. Al Horford                   GSW   Score:   0.72  4G  ~$4
  10. Derrick Jones Jr.            LAC   Score:   0.48  5G  ~$6

Select player to DROP (1-3, or 'q' to finish): 2
Select player to ADD (1-10, or 'q' to finish): 1
  Suggested bid: $3 (Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 5G this week))
  Premium range: $31-$113 (6 returning-star bids in history)
  Budget: $300 remaining | Max bid: $150
  FAAB bid amount ($3 suggested, or enter amount): 3
  ✓ Queued: ADD Sam Merrill / DROP Justin Champagnie / $3

Add another bid? (y/n): y

──────────────────────────────────────────────────
  Bid #2 (enter 'q' to finish)  [1 transaction(s) remaining this week]
──────────────────────────────────────────────────
Select player to DROP (1-3, or 'q' to finish): 2
Select player to ADD (1-10, or 'q' to finish): 3
  Suggested bid: $3 (Median for Solid tier (market rate, std bids) (Budget: HEALTHY, 4G this week))
  Premium range: $31-$113 (6 returning-star bids in history)
  Budget: $300 remaining | Max bid: $150
  FAAB bid amount ($3 suggested, or enter amount):
  ✓ Queued: ADD Max Christie / DROP Justin Champagnie / $3

Add another bid? (y/n): n

============================================================
  QUEUED CLAIMS (2 total)
============================================================
  1. ADD: Sam Merrill               DROP: Justin Champagnie  FAAB: $3
  2. ADD: Max Christie              DROP: Justin Champagnie  FAAB: $3
============================================================

  [1/2] Processing...

  Resolving drop player: Justin Champagnie...
    Found: Justin Champagnie -> 466.p.6632
  Resolving add player: Sam Merrill...
    Found: Sam Merrill -> 466.p.6452

  [DRY RUN] Would submit add/drop transaction:
    ADD:  Sam Merrill (466.p.6452)
    DROP: Justin Champagnie (466.p.6632)
    FAAB Bid: $3
    Team: 466.l.94443.t.9

  XML payload:
<?xml version='1.0' encoding='utf-8'?>
<fantasy_content><transaction><type>add/drop</type><faab_bid>3</faab_bid><players><player><player_key>466.p.6452</player_key><transaction_data><type>add</type><destination_team_key>466.l.94443.t.9</destination_team_key></transaction_data></player><player><player_key>466.p.6632</player_key><transaction_data><type>drop</type><source_team_key>466.l.94443.t.9</source_team_key></transaction_data></player></players></transaction></fantasy_content>
  ✓ [DRY RUN] Transaction prepared but not submitted.

  [2/2] Processing...

  Resolving drop player: Justin Champagnie...
    Found: Justin Champagnie -> 466.p.6632
  Resolving add player: Max Christie...
    Found: Max Christie -> 466.p.6725

  [DRY RUN] Would submit add/drop transaction:
    ADD:  Max Christie (466.p.6725)
    DROP: Justin Champagnie (466.p.6632)
    FAAB Bid: $3
    Team: 466.l.94443.t.9

  XML payload:
<?xml version='1.0' encoding='utf-8'?>
<fantasy_content><transaction><type>add/drop</type><faab_bid>3</faab_bid><players><player><player_key>466.p.6725</player_key><transaction_data><type>add</type><destination_team_key>466.l.94443.t.9</destination_team_key></transaction_data></player><player><player_key>466.p.6632</player_key><transaction_data><type>drop</type><source_team_key>466.l.94443.t.9</source_team_key></transaction_data></player></players></transaction></fantasy_content>
  ✓ [DRY RUN] Transaction prepared but not submitted.

==================================================
  Done: 2 succeeded, 0 failed
==================================================
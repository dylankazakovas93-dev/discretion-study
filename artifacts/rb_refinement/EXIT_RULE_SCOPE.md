# Exit-rule scoping study — RB-K1 (development 2018-2025)

Diagnostic run on 5,347 RB-K1 trades simulated with a -1R stop and NO target,
bar by bar on real OHLC, stop-first on same-bar ambiguity.

## Headline

Holding without a target loses: **83.1% of trades eventually hit the -1R stop.**

### Give-back — trades that reached +XR and STILL stopped out at -1R

| Reached | Then stopped out | n |
|---|---|---|
| +0.5R | 76.8% | 3,899 |
| +0.7R | 74.3% | 3,520 |
| +1.0R | 69.3% | 2,940 |
| +1.5R | 61.8% | 2,355 |
| +2.0R | 54.8% | 1,954 |

The edge is in taking profit, not in the entry. This is the mechanism behind the
monotonic fixed-target result (0.5R/0.7R beating the structural target).

### Reach rates

| Level | Share reaching |
|---|---|
| >=0.3R | 82.6% |
| >=0.5R | 72.9% |
| >=0.7R | 65.8% |
| >=1.0R | 55.0% |
| >=1.5R | 44.0% |
| >=2.0R | 36.5% |
| >=3.0R | 28.0% |

### Continuation once moving

0.5R -> 0.7R 90.3% | 0.5R -> 1.0R 75.4% | 0.7R -> 1.0R 83.5%
1.0R -> 1.5R 80.1% | 1.0R -> 2.0R 66.5% | 1.5R -> 2.0R 83.0%

### Heat before reaching +1R (breakeven-rule viability)

p10 -0.803R | p25 -0.552R | p50 -0.280R | p75 -0.106R | p90 -0.029R
Only 28.9% of eventual 1R-runners first dip beyond -0.5R.
A breakeven / stop-tighten rule would kill relatively few genuine winners.

### Speed

Time to +0.5R: median 0 min (entry bar itself), p75 2 min.
Time to +1.0R: median 2 min, p75 6 min.

## Pre-registered rule set (12 rules, declared before evaluation)

A. Fixed target (already run, benchmark): 0.5R, 0.7R, 1.0R
B. Breakeven move: stop -> entry after +0.3R / +0.5R / +0.7R, then structural target
C. Partial profit: half at +0.5R run to 1.0R / half at +0.5R run to 1.5R /
   half at +0.7R run to 1.5R
D. Trail after trigger: trail 0.5R after +0.5R / trail 0.5R after +1.0R /
   trail 1.0R after +1.0R

Scoring: bar-by-bar simulation, stop-first, occupancy re-run per rule,
gross/1pt/2pt, per-year breakdown. Judged on within-family monotonicity, not
best-cell selection. No continuous parameter fitting.

## Declared cautions

1. EXECUTION RISK. Median 0 minutes to +0.5R means the entry bar's own high
   often reaches target. Tight-target configurations depend on capturing a
   ~6-point move inside the first minute or two with a resting order. Real fill
   quality on moves that fast is unverified and this risk falls hardest on
   exactly the configurations that score best.
2. FAMILY C SCORING. Partial profits change position size mid-trade, so R is no
   longer one clean unit. Scored as 0.5 x (first exit R) + 0.5 x (second exit R).
   Not directly comparable to single-exit rules.

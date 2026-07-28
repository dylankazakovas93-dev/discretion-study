# RB-K1 target sweep (development 2018-2025)

Stop UNCHANGED throughout (structural invalidation, ATR(24) 1m floored, >=12pt).
Only the target moves. entry_price = open of entry bar, outcomes re-simulated
from bars, stop-first on same-bar ambiguity, occupancy re-run per target.

| Target | Trades | /wk | PF@1pt | Net@1pt | Pos yrs | PF@2pt | Net@2pt | Pos yrs | MDD@2pt | Win% |
|---|---|---|---|---|---|---|---|---|---|---|
| STRUCTURAL (frozen) | 2150 | 5.21 | 1.3515 | +349.5 | 8/8 | 1.2296 | +239.6 | 8/8 | -26.1 | 56.0 |
| fixed 0.5R | 3208 | 7.77 | **1.6236** | +437.7 | 8/8 | **1.3716** | +273.4 | 8/8 | **-15.6** | 79.2 |
| fixed 0.7R | 2698 | 6.53 | 1.5500 | **+443.6** | 8/8 | 1.3599 | **+304.2** | 8/8 | -17.4 | 71.5 |
| fixed 1.0R | 2266 | 5.49 | 1.3759 | +354.2 | 8/8 | 1.2405 | +237.4 | 8/8 | -18.4 | 60.4 |
| fixed 1.5R | 1900 | 4.60 | 1.2219 | +234.4 | 8/8 | 1.1237 | +136.9 | 7/8 | -29.7 | 46.9 |
| fixed 2.0R | 1774 | 4.30 | 1.1596 | +182.3 | 8/8 | 1.0765 | +91.6 | 6/8 | -53.6 | 38.5 |

## Reading

Performance is MONOTONIC in target size: PF falls steadily from 0.5R to 2.0R at
both cost levels. That is a clean gradient across an ordered parameter, not an
isolated spike, which is the main reason to take it seriously.

0.7R is the best on net R after 2pt (+304.2 vs +239.6 structural, +27%).
0.5R is the best on PF, drawdown and frequency.
Both keep 8/8 positive years at BOTH cost levels.

Tighter targets also RAISE frequency (7.77/wk at 0.5R vs 5.21 structural)
because faster exits release the single position sooner.

## Caution

A 0.5R target with a 1R stop needs a >66.7% win rate to break even. Observed
79.2% at 2pt cost leaves real but not enormous margin. Any execution slippage
that converts wins to losses attacks this configuration harder than a wide one.

The 2026 OOS already run used the STRUCTURAL target. Changing the target means
that result no longer describes the candidate rule, and the clean 2026 window
has now been looked at once.

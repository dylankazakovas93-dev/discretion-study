# FROZEN OOS SHORTLIST v1.0.0 — broad standalone setups

Frozen on development data 2018-2025 ONLY. Untouched years not accessed.
Search: 2,817 configurations, 1,406 evaluated (>=200 trades), 27 8/8 survivors.

## K1 (PRIMARY) — "NY morning, price near fair value"

Session          NY_AM
Market state     |price - VWAP(anchored 09:30 ET)| < 1.0 anchored weighted SD,
                 measured on the last COMPLETED 1m bar before the decision bar
Structure        any existing causal structural entry variant (unrestricted)
Stop             existing structural stop, ATR(24) 1m floored, >= 12.0 pts
Target           existing nearest opposing valid structure, ATR(24) 5m gated
Occupancy        one global position, earliest-actionable, (entry_ts, fkey)

Development results (standalone occupancy rerun, NOT an Option 3 slice):
  trades 3,036 | 7.3/wk | PF@1pt 1.3620 | PF@2pt 1.2369
  net@1pt +489.0R | net@2pt +335.8R | MDD@1pt -33.0R
  positive years 8/8 at 1pt AND 8/8 at 2pt
  best year share of net@2pt: 23% (2022 +77.1 of +335.8)

## K3 (SECONDARY) — lower frequency variant

Session          NY_AM
Market state     |price - VWAP(anchored 03:00 ET)| < 1.0 anchored weighted SD
Confirmation     price on the trade side of completed-bar EMA21(1m)
Structure/stop/target/occupancy: as K1

  trades 1,197 | 2.9/wk | PF@1pt 1.6633 | PF@2pt 1.5138
  net@1pt +290.5R | net@2pt +235.2R | MDD@1pt -15.4R
  positive years 8/8 at 1pt AND 8/8 at 2pt

## Pre-registered OOS criteria (declared before any untouched-year access)

PASS      PF > 1.10 after 2pt full round trip AND net R > 0
MARGINAL  PF 1.00-1.10 after 2pt
FAIL      PF < 1.00 after 2pt or net R <= 0

## Recorded contamination

Jan-Jun 2026 was evaluated for frozen Option 3 in a prior session and the result
disclosed. That window CANNOT serve as pristine holdout. 2026-06-08 onward has
never been ingested and remains clean.

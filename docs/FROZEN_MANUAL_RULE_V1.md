# FROZEN MANUAL RULE v1.0.0

Locked 2026-07-26 BEFORE any evaluation on 2026 data.
Selected on in-sample evidence only (2018-2025). 2026 is holdout.

## Rule (all conditions required)

1. SESSION in {NY_AM, LONDON, NY_PM}
2. ENTRY_VARIANT in {
     ENTRY_ON_IMMEDIATE_DISPLACEMENT,
     ENTRY_ON_MINIMAL_WICK_REJECTION,
     ENTRY_ON_STRONG_REJECTION,
     ENTRY_ON_FIRST_CLOSE_OUTSIDE,
     ENTRY_ON_NEW_FVG
   }
3. EFFECTIVE STOP DISTANCE >= 12.0 points
   (effective = max(structural, ATR(24) of last completed 1m candle))
4. Target = nearest opposing valid structure, gated at >= ATR(24) of last
   completed 5m candle. Unchanged from frozen engine v2.0.0.
5. ONE POSITION AT A TIME globally, earliest-actionable: take the earliest
   qualifying entry; ignore all others until its exit.
6. NO playbook / prior-record admission filter of any kind. The v2 study
   showed the admission layer performs no better than taking every setup.

## Cost basis

Primary basis for this rule is NET at 1.0 point round turn, not gross.

## Pre-registered in-sample results (2018-2025)

trades            9,771
trades/week        23.5
PF gross         1.2411
PF @1.0pt        1.1466
expectancy @1.0  0.0801R
win rate         47.2%
net @1.0pt      +782.7R
max drawdown     -82.8R
positive years      8/8

per-year net R @1.0pt:
  2018  +2.5    2019 +24.0    2020 +51.8    2021 +115.9
  2022 +279.7   2023 +28.4    2024 +51.5    2025 +228.8

## Pre-registered success criteria for the 2026 holdout

Evaluated on 2026 data ONLY, at 1.0pt cost:
  PASS       PF >= 1.10 AND net R > 0
  MARGINAL   PF 1.00-1.10
  FAIL       PF < 1.00 or net R <= 0

Declared before running. No post-hoc adjustment of thresholds is permitted.

## Known caveats recorded at lock time

- Rule selected after inspecting in-sample results across ~15 candidates.
  The stop-distance floor has a mechanical justification (a fixed point cost
  is a larger fraction of R on smaller stops); the session and variant
  selections do not, and are exactly what this holdout tests.
- 2022 contributes 36% of in-sample net R. Single-regime dependence is a
  live risk.
- 2018 (+2.5R) is close enough to zero that the 8/8 year record is fragile.
- Fills assume exact stop price; gap-through is not modelled.

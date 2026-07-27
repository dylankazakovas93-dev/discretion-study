# AMD / TPO / RB refinement — direct verdict

1. Was the AMD detector fully implemented?  **NO.** Not built in this run.
2. Was a causal TPO engine fully implemented?  **YES.** 30-minute brackets,
   each price bin counted once per bracket, bin sizes 1/2/4 points, developing
   and prior-session profiles, POC with deterministic tie-break, 70% TPO value
   area, all read at the last completed bar before the decision bar.
3. Did AMD improve RB-K1 or RB-K3?  **UNTESTED.**
4. Did TPO improve RB-K1 or RB-K3?  **NO.**
5. Did VWAP + TPO combine for incremental value?  **NO.**
6. Did one supporting FVG/iFVG improve the setup?  **UNTESTED.**
7. Which RB timeframes contributed?  1m/3m/5m together; established previously.
8. Harmful reaction type?  Not re-tested this run.
9-13. Best configuration remains RB-K1 unchanged.
14. Freeze RB-K1 and RB-K3 as previously specified. No TPO challenger qualifies.

## Benchmark reproduction (Part 1 gate — PASSED)

| Strategy | Trades | /wk | PF@1 | PF@2 | Net@2 | MDD@2 | Pos yrs @2 |
|---|---|---|---|---|---|---|---|
| K1 frozen (any structure) | 3,036 | 7.29 | 1.3620 | 1.2369 | +335.8 | -41.8 | 8/8 |
| K3 frozen (any structure) | 1,197 | 2.88 | 1.6633 | 1.5138 | +235.2 | -16.9 | 8/8 |
| RB-K1 | 2,150 | 5.16 | 1.3515 | 1.2296 | +239.6 | -26.1 | 8/8 |
| RB-K3 | 928 | 2.23 | 1.6540 | 1.5080 | +185.0 | -13.3 | 7/8 |
| RB only, no state | 6,141 | 14.75 | 1.2208 | 1.1266 | +426.2 | -53.2 | 6/8 |
| Option 3 | 9,771 | 23.47 | 1.1466 | 1.0602 | +336.0 | -146.2 | 4/8 |

## TPO result — no incremental value

| Config | /wk | PF@1 | PF@2 | Net@2 | MDD@2 | Pos yrs @2 |
|---|---|---|---|---|---|---|
| RB-K1 benchmark | 5.16 | 1.3515 | 1.2296 | +239.6 | -26.1 | 8/8 |
| TPO prior bin1 >1ATR from POC + VWAP | 4.20 | 1.3581 | 1.2360 | +205.4 | -22.9 | 8/8 |
| TPO prior bin4 >1ATR from POC + VWAP | 4.16 | 1.3574 | 1.2354 | +203.1 | -25.6 | 8/8 |
| TPO prior bin2 below POC + VWAP | 2.63 | 1.3673 | 1.2498 | +133.8 | -21.0 | 7/8 |

Every TPO state cuts frequency while leaving PF within ~0.02 of the benchmark
and surrendering 15-45% of net R. TPO location relative to POC or value area
carries no information about RB trade quality that the VWAP state does not
already capture.

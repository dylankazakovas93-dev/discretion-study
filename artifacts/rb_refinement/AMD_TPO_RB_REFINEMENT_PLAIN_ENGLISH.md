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

---

# AMD addendum (run 2)

**1. Was the AMD detector fully implemented?  YES.** Causal state machine:
accumulation range unknown until its final bar closes (activation), manipulation
must follow activation, re-entry must follow manipulation, distribution
confirmation must follow re-entry. 288 configurations across timeframes
(1/3/5m), lengths (12/18/24), range widths (<=1.0/1.5 ATR), excursions
(any/0.25 ATR), manipulation windows (6/12), distribution confirmations
(midpoint/opposite side) and RB windows (6/12). 259,490 AMD instances detected.

**3. Did AMD improve RB-K1 or RB-K3?  CANNOT BE ANSWERED — sample too small.**

576 AMD+RB configurations were run. **Zero reached the 300-trade minimum.**

    matched RB trades per AMD config: max 36, median 0, over eight years
    configs producing any matched trade at all: 284 of 576
    AMD instances per config: median 155 over eight years (~19/year)

The binding constraint is the specified accumulation test: range width divided
by completed Wilder ATR(24). A 12-24 bar range is compared against a ONE-bar
ATR, and under normal price behaviour a multi-bar range is several times a
single-bar ATR. Requiring <=1.0-1.5x therefore selects only extremely coiled
conditions, which are rare. That is what the specification asks for, and it was
implemented as written; the consequence is that AMD-confirmed rejection-block
trades occur at most 36 times in eight years (~0.09/week).

AMD as specified is not falsified. It is untestable at the required sample size
because the events almost never coincide with an eligible RB trigger.

**Verdict unchanged: RB-K1 remains the best manually definable rule.**

---

# AMD v2 addendum — operator-revised definitions

Revised per operator specification: duration-based accumulation (>=20 min,
>=60 min on 15m), timeframe-scaled width (1m <=3.0 ATR, 3m <=2.0, 5m <=1.5,
15m <=1.0), SUSTAINED manipulation (>=5 consecutive completed 1m closes beyond
the range boundary, >=15 on 15m), optional gate requiring the sweep extreme to
reach a VWAP SD band or EMA21, distribution = first opposite-direction RB
trigger within 30 or 60 minutes.

**AMD is now testable.** 59 of 65 configurations reached the 300-trade minimum,
against 1 of 577 under the v1 width-only definition.

## Results vs benchmarks

| Config | /wk | PF@1 | PF@2 | Net@2 | Pos yrs @1 | Pos yrs @2 |
|---|---|---|---|---|---|---|
| RB-K1 benchmark | 5.16 | 1.3515 | 1.2296 | +239.6 | 8/8 | 8/8 |
| RB-K3 benchmark | 2.23 | 1.6540 | 1.5080 | +185.0 | 8/8 | 7/8 |
| V02 AMD 1m w3.0 no-gate 30m | 4.76 | 1.3653 | 1.2642 | +264.1 | 8/8 | 7/8 |
| V00 AMD 1m w3.0 gate 30m | 4.01 | 1.3616 | 1.2629 | +220.4 | 8/8 | 7/8 |
| V03_K1 AMD 1m w3.0 no-gate 60m + K1 VWAP | 1.85 | 1.6722 | 1.5241 | +174.0 | 8/8 | 8/8 |

## Direct answers

**Did AMD improve RB-K1?** Marginally, on PF and net R, at slightly lower
frequency. V02 beats RB-K1 on PF@2 (1.2642 vs 1.2296) and net@2 (+264.1 vs
+239.6) but drops to 7/8 positive years at 2pt where RB-K1 holds 8/8.

**Did the "manipulation ran into a level" gate help?** NO. Gate-off beats
gate-on at every timeframe (V03 1.5241 vs V01 1.4433; V02 1.2642 vs V00
1.2629). The gate cuts instances to 33% and does not improve quality.
Caveat: the gate covers VWAP SD bands and EMA21 only, not FVG or RB zones.

**Best 3-8 trades/week config:** V02, 4.76/wk, PF 1.3653 @1pt and 1.2642 @2pt.

## Known implementation caveat

Accumulations are detected on a sliding window, so a single consolidation is
counted once per qualifying end-bar. Raw instance counts (7.5M across 32
configs) are therefore heavily overlapping and are NOT distinct AMD events.
This does not bias the RB pairing, because overlapping distribution windows
merge into the same eligibility mask, but the instance counts must not be read
as event frequency.

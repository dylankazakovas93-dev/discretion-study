# SPEC_LOCKED — NQ macro-surprise reaction (generation 2)

Frozen 2026-08-02 on development data only: **2021, 2022, 2024, 2026-to-Jun**.
Holdout **2023 and 2025** has never been read by any analysis of this hypothesis.

This is a separate hypothesis from the earnings rule (generation 1, which failed its
holdout). Different event family, different mechanism, independently registered.

## Event selection

- Instrument: **NQ front month** (highest-volume outright per session).
- Event days: **CPI, NFP and PPI releases** (08:30 ET). PCE days excluded — by the time PCE
  prints, CPI and PPI have already revealed most of it weeks earlier.
- CPI/Core CPI, PPI/Core PPI and NFP/unemployment-rate share a release minute; the panel
  keeps **one event per release minute**, the one with the larger standardized surprise.
- **Filter: |z| >= 0.75**, where z is the surprise divided by a strictly trailing standard
  deviation of that series' own past surprises (12 obs, min 6, shift(1)).
  0.75 is a floor, not a tuned value: every band below it is negative on dev data
  (0.5-0.75 = -0.242%, PF 0.24), every band above it is positive.

## Entry

Enter at the **close of the first completed 1-minute bar at or after the release**, in that
bar's direction (long if it closed above its open, short if below). The surprise sign is
NOT used for direction — only price. Trading the print direction was tested and loses.

## Exit

- **Stop: 1.5x the 30-minute ATR (14-period) measured at entry.** Median distance 41 pts
  (p10 25, p90 84). Fires on 29% of trades.
- **No target.** Nine target constructions tested across both generations; all rejected.
- **Hard time exit at +30 minutes**, whether the trade is up or down.

## One position at a time

Structural: all releases are 08:30 ET, one event per release minute, flat 30 minutes later.
Verified — 80 trades on 80 distinct sessions, zero overlap, minimum gap 1 day.

## Development results (NOT a forecast)

| | value |
|---|---|
| trades | 80 (20.0/yr) |
| mean | +0.1253% |
| win rate | 59% |
| profit factor | 2.57 |
| RR | 1.80 |
| t | +2.91 |
| worst loss | 94 pts (vs 201 unstopped) |

Per year: 2021 +0.061% PF 1.69 · 2022 +0.320% PF 4.49 · 2024 +0.026% PF 1.33 ·
2026 +0.087% PF 2.62. All four positive.

## Confirmatory test — ONE run, no redesign afterwards

Run this exact rule on **2023 and 2025**.

- **PASS**: mean > 0 AND t > 1.5 AND win rate >= 55%
- **FAIL**: mean <= 0 OR win rate < 50%
- otherwise INCONCLUSIVE

## Search history and caveats

- **~53 trials** on this hypothesis (NEW-0001..0006), versus ~285 on generation 1.
- Costs not applied (~7% of the mean at these sizes).
- 2018 and 2020 produce no events: the trailing sigma needs 6 prior surprises per series
  and the macro data starts 2020-06. Effective dev window is 4 years.
- 2022 contributes a disproportionate share of the return.
- Consensus data is a single unverified source (Forex Factory paste).
- Unemployment claims were never ingested.

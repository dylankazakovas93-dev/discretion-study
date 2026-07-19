# Data Feasibility

## Supplied immutable archives

All five archives describe Databento `GLBX.MDP3`, schema `ohlcv-1m`, parent `NQ.FUT`, requested as individual instrument IDs. CSV timestamps are UTC bar-open timestamps and the schema is `ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol`. Raw symbols include outright contracts and calendar spreads; canonical loader selects the ET-day dominant-volume front month, collapses duplicate UTC timestamps after that selection, and starts a new absolute segment at each selected contract change. This roll policy is causal only to the extent that daily dominant-volume selection is accepted as a fixed operational convention; Stage 1 must preserve the source rows and exclusions.

| Archive | UTC coverage observed | Rows | Archive SHA-256 | Size | Condition nonavailable days |
| --- | --- | ---: | --- | ---: | ---: |
| `nq2018.zip` | 2018-01-01 23:00 to 2019-12-30 23:59 | 942,559 | `910fcd9faf31ea1a9a485398e6771e9e44eb3314f0ebbff84ed40b6bf2545203` | 13,301,345 B | 5 |
| `nq2020.zip` | 2020-01-01 23:00 to 2020-12-30 23:59 | 487,719 | `d96a1379b1ff7ed057a4b749739f4474197be479ca39d260ace4e59131576213` | 7,312,131 B | 4 |
| `nq2021.zip` | 2021-01-03 23:00 to 2022-12-30 21:59 | 1,028,959 | `0336cfac5fe804a4c756ff9372a0bad314e526c389e5dd8da3774883a29b2f62` | 15,503,090 B | 2 |
| `nq2023.zip` | 2023-01-02 23:00 to 2024-12-30 23:59 | 1,025,448 | `c982860543d8db5d18d9cbe751d9655f8e46bf76ae5513b7fd7a9dcd7b740773` | 15,487,024 B | 0 |
| `nq2025.zip` | 2025-01-01 23:00 to 2026-06-07 23:59 | 741,444 | `b4fcf58ff5db70d2a8d45d605ce5a2742ab003a1cf694ef2721a04562b6608e2` | 11,606,889 B | 7 |

The source package manifests retain per-member hashes, including compressed CSV hashes. Data inspection was limited to metadata, condition calendars, headers, coverage, row counts, archive hashes, and source-symbol inventory; it did not inspect returns, candidate outcomes, or strategy performance. The exact input archives remain outside the repository at `/Users/mariusvidziunas/Downloads/quant-data-upload/NQ/`.

## Integrity and availability findings

The coverage is sufficient for chronological partitions, including DST transitions and early-close/holiday observations. It is not sufficient to claim zero missing 10:00 observations until Stage 1 builds a non-performance integrity ledger after front-month selection: required fields are ET session date, expected/observed 10:00 bar, duplicate count, selected contract, segment ID, holiday/early-close status, and exclusion reason. No news calendar exists in the repository; a later `H10-NEWS-001` test needs an external scheduled-release dataset.

Known repository contamination: July 6–10, 2025 is explicitly contaminated development/visual-validation data; phase1 contains exploratory/replay material including 2026. Treat 2025-07-06 through 2025-07-10 and all phase1-exposed 2026 windows as unavailable for this project's untouched final holdout. Existing repository work does not document a prior 10:00-specific empirical study, but the presence of `open_1000` primitives and generic artifact rows does not establish an untouched period.

## Feasible partition recommendation (coverage/contamination only)

Provisional chronological allocation, to be frozen before any Stage 2 results:

- engineering fixtures only: a small, hand-selected non-result fixture; do not use outcomes;
- development/specification: 2018-01-01 through 2022-12-30;
- validation: 2023-01-01 through 2024-12-30;
- final untouched holdout: 2025-01-01 through 2026-06-07, excluding already-exposed July 6–10, 2025 and every known phase1-exposed 2026 date; alternatively acquire a clean post-2026-06 dataset for a contiguous untouched final test.

This is a feasibility recommendation only, not a selection based on returns. The fragmented nature of the proposed final period is a limitation; the cleanest design is a newly acquired, documented post-exposure period.

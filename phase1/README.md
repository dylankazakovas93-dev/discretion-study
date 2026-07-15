# Phase 1 — NQ 1-Minute OHLCV Primitive Audit

Deterministic, causal implementation of the frozen Phase-1 primitives for the
NQ one-minute OHLCV research trial. **Definition + implementation audit only** —
no setup discovery, no trade evaluation, no profitability.

## Layout

```
core.py         loader, audit, ET tz, CAUSAL contract selection, continuity
                segments, segment-aware HTF aggregation (daily = 18:00->16:59)
primitives.py   FVG, iFVG, liquidity refs, rejection-block candidates,
                displacement; segment-restricted trailing percentiles + validity
run.py          driver -> all ledgers + roll/segment/validity ledgers + report
charts.py       deterministic human-audit examples + annotated PNG charts
tests.py        114 invariant checks (causality, continuity, counts)
REPORT.md       human-readable Phase-1 report (read this first)
outputs/
  data_quality_report.json         includes warmup, seam, validity summary
  reproducibility_manifest.json
  nq_1m_et_normalized.csv           ET frame (segment_id, selected contract)
  htf_candles_<tf>.csv              HTF candles w/ complete, availability, segment
  ledgers/                          primitive + roll_decisions + continuity_segments
                                    + trailing_validity_table (CSV; JSON for small)
  charts/                           37 annotated audit charts
  examples/audit_examples.json      machine index of the audit examples
```

## Reproduce

```
pip install pandas numpy pytz zstandard matplotlib
# decompress both delivered .zst files to CSV first
python3 run.py  discovery.csv <discovery.csv.zst>  warmup.csv <warmup.csv.zst>
python3 charts.py
python3 tests.py     # 114/114 invariant checks
```

(Omit the two warm-up arguments to run discovery-only.)
Deterministic: no randomness, no seeds. Identical inputs → identical outputs.

## Key facts

- **Discovery week** (`glbx-mdp3-20260706-20260712`): 2026-07-05 20:00 →
  2026-07-12 19:59 ET, front month **NQU6**. Clean; one continuity segment.
- **Causal contract selection:** each session's contract is decided from the
  **previous** session's outright volume (no intra-session look-ahead). Only two
  disclosed bootstraps (data start, post-seam). See `roll_decisions.csv`.
- **Continuity segments (26):** new segment after each roll, the seam, and any
  >60-min non-calendar gap. No HTF candle spans a boundary. Discovery = segment 25.
- **Warm-up is NOT fully resolved for setup discovery.** Older sessions exist,
  but trailing 10/20/40 require same-segment complete predecessors, and the
  28-day seam isolates July. **daily (all N) and 4h prev40 stay null all week;**
  15m/30m/1h become valid partway through — see `trailing_validity_table.csv`.

See `REPORT.md` §0. Parameter version: `phase1-v1.0.0`.

# Phase 1 — NQ 1-Minute OHLCV Primitive Audit

Deterministic, causal implementation of the frozen Phase-1 primitives for the
NQ one-minute OHLCV research trial. **Definition + implementation audit only** —
no setup discovery, no trade evaluation, no profitability.

## Layout

```
core.py         loader, audit, ET tz, FROZEN quarterly roll, dual (absolute/
                normalization) segments, segment-aware HTF agg (daily=18:00->16:59)
primitives.py   FVG, iFVG, liquidity refs, rejection-block candidates,
                displacement; norm-segment trailing percentiles + validity
run.py          driver -> all ledgers + roll_schedule/segments/validity + report
charts.py       deterministic human-audit examples + annotated PNG charts
tests.py        119 invariant checks (frozen roll, dual segments, counts)
REPORT.md       human-readable Phase-1 report (read this first)
outputs/
  data_quality_report.json         includes warmup, seam, validity summary
  reproducibility_manifest.json
  nq_1m_et_normalized.csv           ET frame (segment_id, selected contract)
  htf_candles_<tf>.csv              HTF candles w/ complete, availability, segment
  ledgers/                          primitive + roll_schedule + continuity_segments
                                    + trailing_validity_table (CSV; JSON for small)
  charts/                           37 annotated audit charts
  examples/audit_examples.json      machine index of the audit examples
```

## Reproduce

```
pip install pandas numpy pytz zstandard matplotlib
# decompress the three delivered .zst files to CSV first
python3 run.py  discovery.csv <discovery.zst>  warmup.csv <warmup.zst>  gap.csv <gap.zst>
python3 charts.py
python3 tests.py     # 119/119 invariant checks
```

(Extra files are passed as `csv hash` pairs; omit them to run discovery-only.)
Deterministic: no randomness, no seeds. Identical inputs → identical outputs.

## Key facts

- **Three contiguous files** stitch 2025-01-01 → 2026-07-12 with no gap:
  warm-up (2025-01→2026-06-07) + gap-fill (2026-06-08→07-05) + discovery
  (2026-07-06→07-12). All SHA-256-verified.
- **Frozen quarterly roll** (not volume): Globex open on the Monday of the
  third-Friday expiry week. June 2026 → **NQM6 → NQU6 at `2026-06-15 18:00 ET`**
  (`roll_schedule.csv`).
- **Dual segments.** *Absolute* segments reset at every roll + >4-day outage
  (7 segments, one per contract); no absolute structure (FVG/liquidity/rejection/
  displacement) spans a roll — discovery = NQU6 segment 6. *Normalization*
  segments reset only at a >4-day outage, so scale-invariant trailing percentiles
  cross contracts — the whole history is one norm segment (id 0).
- **Every trailing 10/20/40 percentile is valid in July** (0 null, incl. daily
  prev40) — see `trailing_validity_table.csv`.

See `REPORT.md` §0. Parameter version: `phase1-v1.0.0`.

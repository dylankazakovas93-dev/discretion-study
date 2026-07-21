# Primitive reset — NQU6 timestamp audit

Narrow primitive reset only (FVG, iFVG, rejection blocks). No strategy
testing, no adaptive evidence, no historical rerun. See
`primitive_reset_report.md` for the full write-up.

## Files

- `data_coverage.json` — exact NQU6 coverage vs. the requested window.
- `fvg_candidates.csv` — every detected FVG, all 6 governing timeframes.
- `fvg_atr_bin_summary.csv` — FVG counts by timeframe x size bin.
- `ifvg_candidates.csv` — every detected iFVG.
- `rb_confirmed_candidates.csv` — every RB candidate that reached 1.5x-ATR
  confirmation.
- `rb_rejected_candidates.csv` — every RB candidate that did not confirm
  (with a mechanical `rejection_reason`).
- `fvg_doji_blocked.csv` — geometry-valid FVG triples excluded because an
  A/B/C candle was an exact doji (`open == close`); diagnostic only, never
  an active FVG or iFVG parent.
- `rb_equal_wick_ambiguous.csv` — source candles with exactly equal-length
  wicks; diagnostic only, never an active RB.
- `rb_precedence_suppressed.csv` — reaction candles that merely tapped an
  already-active same-direction RB, suppressed from becoming a duplicate
  overlapping RB.
- `structure_lifecycle_events.csv` — every FVG/iFVG/RB lifecycle timestamp
  (formed/touched/inverted/expired/deactivated), one row per event.
- `reproducibility.json` — counts and provenance for this run.
- `primitive_reset_report.md` — exact logic implemented, audit output,
  test results, and the honest verdict.

## How to reproduce

```
PYTHONPATH=src python3 scripts/primitive_reset_audit.py
PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
```

## Code

New, isolated package: `src/discretion/primitive_reset/` (never imported by
`discretion.primitives.*`, `branch_engine`, `materializer`, or `pipeline` —
this reset does not touch or feature-gate the existing candidate/evidence
pipeline; it simply does not participate in it).

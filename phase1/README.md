# Phase 1 — NQ 1-Minute OHLCV Primitive Audit

Deterministic, causal implementation of the frozen Phase-1 primitives for the
NQ one-minute OHLCV research trial. **Definition + implementation audit only** —
no setup discovery, no trade evaluation, no profitability.

## Layout

```
core.py         loader, data audit, ET tz conversion, causal HTF aggregation
primitives.py   FVG, iFVG, liquidity refs, rejection-block candidates, displacement
run.py          driver -> writes all ledgers + audit report + HTF candles
charts.py       deterministic human-audit examples + annotated PNG charts
REPORT.md       human-readable Phase-1 report (read this first)
outputs/
  data_quality_report.json
  reproducibility_manifest.json
  nq_1m_et_normalized.csv          ET-normalized 1m frame (session-tagged)
  htf_candles_<tf>.csv             completed HTF candle ledgers
  ledgers/                         primitive ledgers (CSV canonical; JSON for small)
  charts/                          37 annotated audit charts
  examples/audit_examples.json     machine index of the audit examples
```

## Reproduce

```
pip install pandas numpy pytz zstandard matplotlib
# decompress the delivered .zst to data.csv first
python3 core.py  data.csv <original.csv.zst>
python3 run.py   data.csv <original.csv.zst>
python3 charts.py
```

Deterministic: no randomness, no seeds. Identical inputs → identical outputs.

## Key finding

The delivered dataset covers **2026-07-05 20:00 → 2026-07-12 19:59 ET** only —
the discovery week is complete but the required **≥ 40 warm-up sessions before
Jul 6 are absent** (1 partial session present). Warm-up-dependent statistics
(trailing 10/20/40 percentiles, previous-RTH references) are therefore
under-supported and marked `null` where history is insufficient, never
fabricated. See `REPORT.md` §0.

Parameter version: `phase1-v1.0.0`.

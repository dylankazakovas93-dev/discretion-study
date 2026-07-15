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
# decompress both delivered .zst files to CSV first
python3 run.py  discovery.csv <discovery.csv.zst>  warmup.csv <warmup.csv.zst>
python3 charts.py
```

(Omit the two warm-up arguments to run discovery-only.)
Deterministic: no randomness, no seeds. Identical inputs → identical outputs.

## Key facts

- **Discovery week** (`glbx-mdp3-20260706-20260712`): 2026-07-05 20:00 →
  2026-07-12 19:59 ET, front month **NQU6**. Complete, clean (0 dupes / 0
  malformed / 0 OHLC violations; missing minutes = maintenance + weekend only).
- **Warm-up** (`glbx-mdp3-20250101-20260607`): **371 Globex sessions**,
  stitched into a continuous front-month series (per-day volume roll, 6
  quarterly rolls). Requirement **met**.
- **Seam caveat:** warm-up ends Jun 7 on NQM6; discovery starts Jul 5 on NQU6,
  with a ~28-day gap. Warm-up is used **only for relative trailing size
  percentiles**; structural detection is confined to the post-seam discovery
  series. All prev-10/20/40 percentiles are now fully populated (0 null).

See `REPORT.md` §0. Parameter version: `phase1-v1.0.0`.

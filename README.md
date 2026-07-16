# discretion-study

Formalizing coded ICT-style discretion on NQ 1-minute OHLCV as a **causal
grammar of deterministic primitives**. A setup is a causally coherent path
through primitives — continuation *or* fade — with a frozen 0.5R–1R execution
policy. Everything is computed on completed bars only; no future information,
no post-outcome construction.

## Layout

- `src/discretion/data/` — Databento GLBX.MDP3 loader, front-month/roll
  segmentation, UTC→ET conversion, causal Wilder ATR.
- `src/discretion/primitives/` — FVG, iFVG, rejection blocks, displacement,
  time anchors, historical/liquidity levels, session VWAP + bands, structure
  (swings, equal clusters, compression/expansion). Permanent IDs; occurrences
  are never deleted.
- `src/discretion/setups/` — path builders, entry modes, frozen RR policy,
  interaction-episode deduplication, separate outcome evaluation.
- `src/discretion/pipeline/` — dev-window run, coverage table, ledgers, counts.
- `src/discretion/review/` — candlestick charts and the 25-category review pack.
- `tests/` — 57 unit + integration tests.

## Run

```bash
pip install -r requirements.txt
# unit tests
PYTHONPATH=src:tests python -m pytest -q
# full dev run (July 2025) -> artifacts/
PYTHONPATH=src python -m discretion.pipeline.run
# charts + review pack -> artifacts/
PYTHONPATH=src python -m discretion.review.review_pack
```

Raw data lives under `data/raw/` (gitignored; licensed Databento data).

See **[REPORT.md](REPORT.md)** for the full deliverables report, coverage
summary, counts, and the ten direct answers.

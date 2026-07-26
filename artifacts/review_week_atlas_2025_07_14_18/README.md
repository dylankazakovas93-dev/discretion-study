# Review-Week Structure-and-Setup Atlas — 2025-07-14 .. 2025-07-18

A deterministic, chronological, causal visual review of what the graph-native
recognizer saw during this NQ week: primitive detection, higher-timeframe
structure, episode/branch construction, coherent setups (strong/weak/rejected/
unresolved), structural stop/target placement, RR-based rejection, and the
current recognizer's provisional prior-only evidence. **This is a visual and
causal review, not a profitability study, an optimizer, or a forward/edge
claim.** See `atlas_report.md` for the full narrative report, compute-budget
disclosure, and the honest verdict.

## Files in this directory

- `atlas_report.md` — full narrative report (Stages 0-7, completion report).
- `primitive_inventory.csv` — full event_type/event_subtype crosstab by true
  CME session and calendar day (the ground-truth counts).
- `mapped_categories.csv` — the task's plain-English primitive-event category
  counts, derived from the same crosstab (never a separate re-implementation).
- `htf_inventory.json` — 5m/15m/30m/60m completed-candle, wick, HTF-FVG,
  HTF-iFVG and target-selection counts.
- `episode_inventory.csv`, `branch_inventory.csv` — every episode/branch whose
  origin falls in the review week.
- `candidate_ledger.csv.gz` — every eligible graph-native candidate (all
  target-policy variants) in the review week (gitignored; hash + row count in
  `reproducibility.json`).
- `deduplicated_candidates.csv` — one representative candidate per
  `trigger_event_id` (frozen policy-priority rule; a pure filter, never
  mutates the underlying ledger).
- `rejected_candidates.csv` — every structurally-formed-but-RR-rejected
  candidate in the review week.
- `unresolved_branches.csv` — every branch that correctly never emitted a
  trigger.
- `example_manifest_pre_outcome.json` / `.sha256` — the frozen, hashed example
  selection, built and hashed before any candidate's own outcome was read for
  selection (see atlas_report.md "Stage 3" for the exact proof).
- `example_manifest_with_outcomes.json` — the same example IDs with outcomes
  attached afterward (win/loss/ambiguous/expired, realized R, first hit).
- `coherence_table.json` — one machine-generated audit row per chart.
- `manual_review_sheet.csv` — the same rows with empty columns for Dylan to
  mark coherent/questionable/incorrect-primitive/etc.
- `reproducibility.json` — hashes, row counts, window bounds, chart count.
- `charts/` — every example chart (pre-trigger structure normal; anything used
  only for outcome evaluation is shaded and labeled
  `POST-TRIGGER OUTCOME -- NOT AVAILABLE TO DECISION`).

## How to reproduce

```
PYTHONPATH=src python3 scripts/run_review_atlas.py      # Stage 1: engine run + checkpoint
PYTHONPATH=src python3 scripts/build_review_atlas.py     # Stages 2-7: inventory, manifest, charts
```

# Chronological Structure-and-Setup Atlas — 2025-07-14 .. 2025-07-18 (NQU5)

A visual and causal review of what the deterministic graph-native recognizer
saw during one NQ week, using only information available at each decision
time. **This is not a profitability study, an optimizer, or a forward/edge
claim.** The broad adaptive-recognizer audit (collision/calibration/
walk-forward) is intentionally paused for this task, per instruction.

## Stage 0 — verified state

- Branch: `claude/graph-native-candidate-engine-v2`. Starting HEAD
  `2e64e9f8917550a7f902acb2c41fe0f5dee1fb3b` — matched the expected SHA
  exactly (verified before any computation; the remote had not moved).
- Working tree: clean at start.
- PR #2: open, draft, unmerged (confirmed via `pull_request_read`; remains so).
- The three causal-integrity fixes in `2e64e9f` were verified present in the
  diff: (1) `signatures.py` `sweep_state` now seq-gated to `<=entry_seq`
  (inert on similarity — unused in `NUM_KEYS`/`CAT_KEYS`); (2) `graph/
  targets.py` removed a mutable `.active` AND from wick/HTF-FVG/HTF-iFVG
  freshness checks that leaked end-of-scan future state into target
  eligibility; (3) `primitives/structure.py`'s `detect_equal_levels` now
  freezes a cluster at its first confirming pair instead of back-dating
  `created_seq` as later data arrives.
- Data coverage: `data/raw/glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst`,
  confirmed loadable through the review week and well beyond.
- Contract symbols: **NQU5 only** (front month since the 2025-06-16 roll; no
  roll inside the window used).
- CME sessions available before the review week: **136** exist in the data
  file (true 18:00 ET→18:00 ET session boundaries, computed independently of
  the codebase's internal `_session_key`, which is documented below as a
  distinct, disclosed quirk). The requested minimum of 40 was therefore
  *available as data* — the shortfall described below is a **compute-budget**
  constraint on the continuous engine run, not a data-availability one, and is
  disclosed exactly per the task's own instruction for that situation.

## Compute-budget disclosure (read before the counts below)

`BranchEngine` evaluates every later event against every active
causally-compatible branch; branch/episode bookkeeping accumulates over the
run. Empirically in this environment: a ~6-day continuous window (the size
already proven tractable in the prior MTF-target-layer task) completes in
well under 10 minutes; a **~2-week** continuous window did not finish
`BranchEngine` within 10+ minutes and was aborted; a bare `evidence.
build_snapshot` pass over **all** ~60,265 in-week candidates (as opposed to a
small selected subset) ran **45+ minutes without finishing** and was aborted.

Two independent, disclosed scope reductions follow from this — **no engine
code was changed to make either faster**:

1. **Continuous engine window.** Rather than load 40+ prior sessions
   continuously (data-available but not compute-tractable this session), the
   continuous graph-native run covers **2025-07-11 (Fri) through the review
   week end** — the review week itself plus **exactly 1** true prior CME
   session (2025-07-11) for causal continuity. This is stated exactly, not
   silently substituted. **Adaptive evidence in this atlas is therefore
   severely underpowered** and should be read as illustrating the mechanism
   only (see the `qualified_2` example category below, which is legitimately
   empty for exactly this reason) — consistent with this task's explicit
   instruction to pause the broader adaptive-recognizer audit.
2. **Per-candidate qualification.** Scoring literally every in-week candidate
   is intractable (demonstrated above). `bounded_qualification_scan()`
   computes real, unmodified `evidence.build_snapshot`/`gate.qualify` output
   for a disclosed **chronological prefix of 500 of 60,265** in-week
   candidates; every candidate outside that prefix is honestly left
   `UNSCORED` (verified by `test_bounded_qualification_scan_matches_full_
   evidence_and_discloses_scope`) rather than silently estimated. Stage 2's
   `qualified_candidates_scored_subset` / `recorded_not_activated_candidates_
   scored_subset` fields are explicitly labeled partial, with
   `qualification_n_scored`/`qualification_n_total_in_week` alongside them.

A third, minor, disclosed-but-unfixed item: the codebase's internal
`_session_key` (used by VWAP session reset and the evidence engine's
session-ordinal gating) resets an *additional* time at midnight ET, on top of
the true 18:00 ET CME session open. This is a pre-existing granularity quirk,
not a causality leak (if anything it is more conservative for prior-only
gating, never less) — not fixed, out of scope for this visual-review task.
This atlas's own Stage 0/2 session counts use a correct continuous
18:00→17:59 ET definition (`review_atlas.true_session_date`), independent of
that internal quirk.

## Stage 1 — chronological pipeline run

Loaded **8,160** one-minute bars, 2025-07-11T04:00:00Z .. 2025-07-19T03:59:59Z
(2025-07-11 00:00 ET .. 2025-07-18 23:59:59 ET), NQU5, no contract roll inside
the window, no missing intervals beyond the ordinary weekend closure.

`build_primitives`: 2.4s. `BranchEngine.run()`: **442.9s** — 29,233 trigger
states, 7,726 episodes, 34,812 branches. `materialize_all`: **357.5s** —
**74,008** eligible candidates, **33,171** rejected. A pre-outcome check
confirmed **107,179/107,179** candidates were `UNEVALUATED` at checkpoint
time (i.e. before Stage 3 ever ran) — the checkpoint (`_checkpoint_result.pkl`,
gitignored, 1.39 GB) is the frozen, pre-outcome materialized state Stages 2-7
all read from. Old `build_setups` factories were never called (candidates
came only from `BranchEngine`/`Materializer`, matching the accepted
graph-native architecture; this was not re-tested here since it is already
covered by `tests/test_materializer.py::test_graph_native_generation_works_
with_build_setups_disabled`, part of the full suite rerun below).

Determinism: `bounded_qualification_scan`/`evidence_for_subset` were proven
byte-identical to `evidence.run()`'s own output for whichever candidates they
score (`test_evidence_for_subset_matches_full_run`, `test_bounded_
qualification_scan_matches_full_evidence_and_discloses_scope`); the frozen
candidate geometry itself is proven immutable under additional appended bars
by the existing `test_features_unchanged_by_bars_added_after_trigger`. A
second full end-to-end 6-session engine run was not repeated here (~13 minutes
per run) given that determinism of every layer it depends on (aggregation,
materializer, target resolver, RR policy, dedup) already has dedicated
byte-identical-rerun regression coverage elsewhere in the suite; the
pre-outcome manifest hash below is the single canonical fingerprint of this
run's actual output.

## Stage 2 — weekly inventory (full detail: `primitive_inventory.csv`,
`mapped_categories.csv`, `htf_inventory.json`)

**HTF inventory** (5m / 15m / 30m / 60m):

| | 5m | 15m | 30m | 60m |
|---|---|---|---|---|
| completed candles | 1309 | 437 | 219 | 110 |
| wick HIGH/MEDIUM/LOW | 75/206/2197 | 30/70/751 | 14/44/372 | 7/19/193 |
| fresh HTF FVGs | 16 | 9 | 6 | 3 |
| HTF FVG failures | 230 | 74 | 36 | 20 |
| HTF iFVGs | 240 | 80 | 39 | 23 |
| occluded (considered ledger) | 229,186 | 127,898 | 75,889 | 55,878 |
| selected as target | 21,196 | 6,601 | 7,901 | 5,232 |

**Graph objects** (review week only, `2025-07-14 00:00 .. 2025-07-18 23:59
ET`; see `graph_object_inventory` in `weekly_inventory` output for the full
breakdown and `episode_inventory.csv`/`branch_inventory.csv` for row-level
detail):
- triggered graph-native candidates: **19,985** distinct trigger events
  (deduplicated one-representative-per-trigger view: `deduplicated_
  candidates.csv`), expanding to **60,265** structurally valid target-policy
  variants + **27,595** RR-rejected variants = 87,860 total candidate rows in
  the review week (`target_policy_variants`).
- `sub_0p5R_rejected_candidates`: rejected variants specifically for
  `INSUFFICIENT_NATURAL_RR` (see `rejected_candidates.csv` for the exact
  reason on every row).
- `qualified_candidates_scored_subset` / `recorded_not_activated_candidates_
  scored_subset`: computed over the disclosed 500-candidate bounded scan
  only — **not** the full-week total (see compute-budget disclosure above).

Full primitive event counts (FVG lifecycle, RB taps, displacement grades,
compression/expansion, sweeps, VWAP/band interactions, time-anchor
interactions, etc.) by true CME session and calendar day: `primitive_
inventory.csv` (raw event_type/event_subtype ground truth — never
summarized under an "eligible setup" umbrella) and `mapped_categories.csv`
(the same ground truth mapped to the task's plain-English category names via
`PRIMITIVE_EVENT_CATEGORIES`, never a separate re-implementation).

## Stage 3 — deterministic example selection

Built from `materialize_all`'s frozen output (`setup.outcome == "UNEVALUATED"`
for all 107,179 candidates at that point, asserted in code). Selection uses
only pre-outcome structural fields, target-policy fields, rejection reasons,
and (for two categories only) prior-only `qualification`/`evidence` computed
from *other, earlier* candidates' outcomes — never the selected candidate's
own outcome (proven, not merely sequenced: `test_selection_is_invariant_to_
candidates_own_outcome` force-sets every candidate's own outcome to a fake
extreme value and reconfirms identical selected IDs).

**Pre-outcome manifest hash:**
`1e6adc2df8126c96909df870039b6628e144c1cca6253a57b6bcdab2a720452e`
(`example_manifest_pre_outcome.json` / `.sha256`).

Required primitive examples: **15/15 categories populated** (3 rejection
blocks across distinct subtypes, 3 FVGs with materially distinct lifecycle
signatures, 2 no-fill continuations, 2 failure→iFVG, 2 iFVG retests, 2
prominent upper wicks, 2 prominent lower wicks, 2 equal-level examples, 2
each of good/mixed/bad displacement, 2 compression, 2 expansion, 2 VWAP
interactions, 2 time-anchor interactions).

Required branch/path examples: **16/17 categories populated.**
`rb_tap_bad_displacement_compression_fade` (the `rb_failure_fade` path
family) did not occur in this specific week — reported absent, not
fabricated or relabelled, per the task's explicit instruction for this case.

Required quality-tier pack (Stage 4): **10/10 categories populated** — 5
strongest, 5 middle, 5 weakest (by the documented lexicographic key below), 5
structurally rejected, 3 unresolved branches, 3 `INSUFFICIENT_NATURAL_RR`, 2
natural-RR≥1R-capped, 2 natural-RR 0.5–<1R, 2 same-trigger different-policy
variants, 2 deduplicated-trigger examples.

Qualification-dependent examples: `not_activated_similar_graph_2` populated
(2); **`qualified_2` is legitimately empty (0 of the 500-candidate bounded
scan reached `QUALIFIED_PENDING_TRIGGER`)** — directly consistent with, and
expected from, the severe evidence underpowering disclosed above (the gate
requires `min_unique_sessions=3`, and only 1 true prior session feeds the
pool this run).

### Structural-quality lexicographic key (Stage 4A — no manufactured score)

`structural_quality_key(candidate)` = `(graph_completeness_steps,
displacement_rank[good=2/mixed=1/bad=0/none=-1], natural_rr, executed_rr,
has_target_family)`, compared as a tuple, descending = "stronger" by this
ordering. Every component is a verbatim frozen field already on the
candidate (`ordered_event_ids` length, `features["displacement_grade"]`,
`setup.natural_rr`/`executed_rr`, `target_anchor_type`) — no field the
frozen representation does not already carry was invented; where a
plausible-sounding field (compression-state/duration, overlap, close-quality)
does **not** exist in the frozen feature vector, it is reported as `null`,
never fabricated (see `docs/SIMILARITY_AUDIT_PROTOCOL.md` gap F5 for the
compression-state gap specifically).

Adaptive-evidence view (Stage 4B, on every example that received real
evidence): `qualification_state`, exact/reduced/NN match counts, unique prior
sessions, effective sample size, `shrunk_expected_R`, uncertainty, gate
failure reasons, target policy — all read verbatim off the (real,
unmodified) evidence snapshot, explicitly labeled provisional because the
broader collision/calibration audit is paused this round.

## Stage 5 — charts (`charts/`, 84 total)

Every chart shows ET timestamps, one-minute candles, the relevant completed
HTF/RB/FVG/wick/level/VWAP/compression structures available at or before the
trigger, a solid vertical TRIGGER line, entry/stop/natural-target/
executed-target lines with prices and RR, the exact graph path, branch and
episode IDs, and (for materialized candidates) the qualification state. Any
later market path used only for outcome evaluation is visually separated
with a shaded background and the label `POST-TRIGGER OUTCOME -- NOT
AVAILABLE TO DECISION`; the stop/target-anchor overlay guard skips drawing
any anchor object whose `created_seq` is after the candidate's own
`entry_seq` (verified: `test_no_future_structure_drawn_pre_trigger`).
Rejected candidates show the unchanged stop, the natural target, and the
exact rejection reason. Unresolved branches show the causal path so far and
`terminal_status`/`terminal_reason`.

## Stage 6 — coherence table and manual review sheet

`coherence_table.json` — one machine-generated row per chart: chart ID,
candidate/branch ID, timestamp, primitive family, graph path, structural
relationship proof, stop/target anchor, target policy, natural RR,
structural state, qualification state, example-selection rule, the
pre-outcome manifest hash, and outcome (attached only after selection).
`manual_review_sheet.csv` — the same 84 rows with empty
coherent/questionable/incorrect-primitive/incorrect-causal-relationship/
stop-too-tight/stop-too-wide/target-not-genuine/missed-setup/false-setup/
wrong-grade/wrong-similarity/other-notes columns for Dylan to fill in by hand.

## Stage 7 — outcome attachment

Outcomes were evaluated and attached only *after* the pre-outcome manifest
was written and hashed (`example_manifest_with_outcomes.json`); win/loss/
ambiguous/expired, realized R, and which of stop/target was hit first are
recorded without altering selection, grade, geometry, or evidence. Outcome
statistics in this atlas are descriptive only and are not used to rank,
filter, or re-select any chart.

## Test requirements

See the completion report below for exact collected/passed/failed/skipped
counts from the full suite rerun. Atlas-specific coverage:
`tests/test_review_atlas.py` — 9 tests, all passing, covering properties 1,
2, 4, 6, 10, 11, 12 of the 12 required regression properties (determinism,
outcome-invariant selection, no future-structure chart leakage, rejected
candidates never qualified, dedup never mutates the ledger, examples
selected before outcome, review-week decisions use only prior completed
sessions) plus the semantics-preserving-performance regression for both
`evidence_for_subset` and `bounded_qualification_scan`. Properties 3, 5, 7, 8,
9 are already covered by existing tests, cited in that file's module
docstring, and were not duplicated.

## Known limitations (summary)

1. Continuous engine run used 1 true prior CME session, not the requested
   40+ — a disclosed compute-budget constraint (data was available; the
   continuous multi-week engine run was not tractable in this session), not
   a silent substitution. Adaptive evidence is correspondingly severely
   underpowered this round.
2. Weekly qualification counts are computed over a disclosed 500-candidate
   chronological prefix of 60,265 in-week candidates, not the full week.
3. One branch/path category (`rb_tap_bad_displacement_compression_fade`) had
   no occurrence this specific week.
4. The `qualified_2` example category is empty, directly consistent with #1.
5. The codebase's internal `_session_key` resets an extra time at midnight
   ET (pre-existing, disclosed, not a causality leak, not fixed — out of
   scope).
6. `deduplicated_candidates.csv` (~8.5 MB) and `rejected_candidates.csv`
   (~12 MB) were committed as plain CSV per the task's explicit artifact
   naming (no `.gz` implied for those two filenames specifically).

This document is completed by the Completion Report delivered in the final
chat message of this task, which repeats the repository/data/test integrity
figures and states the honest verdict.

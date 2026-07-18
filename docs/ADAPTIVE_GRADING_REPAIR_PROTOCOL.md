# Adaptive Grading Repair Protocol (frozen before implementation)

This freezes the corrected contract for the recognizer's grading model before
any repair code is written. It supersedes the informal structural-quality
ranking used by the first review-week atlas (`docs/MULTITIMEFRAME_TARGET_
REPORT.md`'s downstream consumer, `artifacts/review_week_atlas_2025_07_14_18/`
commit `905d091`), which is disclosed as defective and superseded, not deleted.

**The governing principle, restated exactly as given:** a setup is not graded
by whether it visually resembles an idealized pattern. A setup is graded by
how profitable that exact branch, or genuinely similar prior branches, has
been across frozen recent-history lookbacks. Displacement quality,
compression, immediate vs. retest entry, and similar descriptive branch
states are **identity/similarity features**, never universal positive or
negative grades.

## 1. True CME-session identity

One canonical function, `discretion.data.cme_session.session_date(ts_et) ->
date`: a session opens at **18:00:00 ET** and runs through **17:59:59 ET the
next calendar day**. A timestamp's session date is the calendar date on which
its session *opened if before 18:00 local time, else the following day's
date* — equivalently: `ts.date()` if `ts.time() < 18:00`, else `ts.date() +
1 day`. Sunday 22:00 ET and Monday 00:05 ET and Monday 17:59 ET all resolve
to the same session date (labelled by the Monday date); Monday 18:00 ET opens
the next session. Comparing local wall-clock hour:minute on an already
tz-aware `America/New_York` timestamp is DST-transparent: the 18:00 boundary
never shifts in local time, so a DST-transition day is never split or
duplicated. Session **ordinals** are the rank of the sorted distinct session
dates seen in a run (0-based, chronological).

This is the **only** session-identity function used for evidence gating
(candidate entry session, outcome completion session, historical comparable
admission, lookback horizon boundaries, unique-session counts, current-session
exclusion). It is intentionally **separate** from `primitives/vwap.py`'s
`_session_key`, which resets VWAP at 18:00 for its own purpose (detecting a
session *boundary* between adjacent bars) and is not touched by this repair —
VWAP reset behavior is out of scope and unchanged.

## 2. Comparable-admission rule

A historical comparable may inform a candidate only when:

```
comparable.completion_session_ordinal < candidate.entry_session_ordinal
```

Strict `<` on **session ordinal**, never calendar date, never raw clock time,
never "did it complete earlier today." A comparable that completes *later in
the same session* than a candidate's entry, or *earlier in the same session*,
is equally inadmissible — the whole session is a wall, not a wall reduced to
midnight. A candidate can never be its own comparable.

## 3. Structural validity (binary, not graded)

Every candidate/branch is exactly one of:

- `STRUCTURALLY_VALID` — the frozen branch grammar completed; every required
  causal relationship is proven; the entry mode is valid for that branch; the
  stop is the branch's frozen invalidation contract (§4); the target is the
  branch's frozen target-policy selection (§5); stop and target existed
  causally at entry; stop and target are each on the geometrically correct
  side of entry; natural RR ≥ 0.5; no blocking rejection applies.
- `STRUCTURALLY_REJECTED` — missing required lineage, wrong-side stop,
  wrong-side target, unavailable target at entry, invalid target under the
  selected policy, invalid branch relationship, natural RR < 0.5, geometry
  requiring stop-tightening or target-stretching, or any future-dependent
  geometry.
- `UNRESOLVED` — the grammar has not yet produced a trigger or a measurable
  invalidation. Never converted into a graded candidate.

No `HIGH`/`MEDIUM`/`LOW` structural tier exists anywhere in the repaired
codebase. This binary label is implemented as a pure function of existing
frozen fields (`Setup.eligible`/`rejected`/`rejection_reason` for candidates,
`BranchState.terminal_status` for branches) — it does not change how those
fields are computed, only how they are surfaced.

## 4. Branch-specific stop contracts (existing, documented here — unchanged
by this repair unless a defect is found)

The resolver lives in `src/discretion/graph/anchors.py::resolve_anchors`,
keyed by `trigger.trigger_family`. Per family (`fam|stop=<rule_id>`):

| family | stop rule id | source object | direction | buffer |
|---|---|---|---|---|
| `fvg_formation`/`fvg_fill`/`fvg_no_fill` | `fvg_boundary` | the origin FVG | beyond `lo` (long) / `hi` (short) | 2 ticks |
| `ifvg_activation`/`ifvg_retest` | `ifvg_invalidation_boundary` | the origin iFVG | beyond `lo`/`hi` | 2 ticks |
| `rb_reaction`/`rb_fvg_fill` | `rb_invalidation_boundary` | the origin RB | beyond `lo`/`hi` | 2 ticks |
| `rb_failure_fade` | `failure_region_boundary` | the focus compression/failure zone | beyond `band_lo`/`band_hi` | 2 ticks |
| `sweep_fade`/`sweep_reclaim_fade` | `swept_extreme` | the swept level + trigger-bar extreme | beyond `min(lo,bar.low)`/`max(hi,bar.high)` | 2 ticks |
| `break_accept_cont` | `accepted_boundary` | the accepted level | beyond `price` | 2 ticks |
| `break_failed_fade` | `failed_break_boundary` | the failed level + trigger-bar extreme | beyond `min(price,bar.low)`/`max(price,bar.high)` | 2 ticks |
| `anchor_reclaim` | `anchor_boundary` | the time anchor | beyond `price` | 2 ticks |
| `compression_expansion` | `compression_region` | the origin compression zone | beyond `band_lo`/`band_hi` | 2 ticks |
| `compression_false_expansion` | `compression_region` | the focus compression zone | beyond `band_lo`/`band_hi` | 2 ticks |
| `vwap_band_fade` | `vwap_band` | the rejected band's reference price | beyond that price | 2 ticks |
| `vwap_bounce`/`vwap_reclaim`/`vwap_break_accept` | `vwap` | the live VWAP value | beyond VWAP | 2 ticks |

**Fallback** (`structural_extreme_fallback`): used only when no
family-specific rule matched *and* is clearly named as a fallback in the
stored `stop_anchor_type`; it is never substituted for a family that has a
dedicated rule above. If the required source object is unavailable, the
candidate is `STRUCTURALLY_REJECTED` (`resolve_anchors` returns a stop only
when a valid boundary exists — see the fallback branch itself, which still
requires `focus`/`origin`/`bar0`, all guaranteed present at a materialized
trigger).

Invalidation meaning: crossing the stop price disproves the specific branch
hypothesis that produced the candidate — not a generic risk distance. Stop
resolution reads only branch-native objects and the frozen tick buffer; it
never reads the target or target distance (§6, tested).

## 5. Branch-specific target contracts (existing, documented here)

`src/discretion/graph/targets.py` builds the typed `TargetCandidate` universe
and `select_target` applies one of four frozen policies:

- **`BRANCH_SEMANTIC`** — the branch's own frozen objective (from
  `anchors.resolve_anchors`'s target half — e.g. VWAP/band for VWAP paths,
  `nearest_level_above/below` fallback otherwise), tagged `branch:<family>`.
- **`NEAREST_VALID_STRUCTURE`** — nearest fresh, frontmost, eligible target
  from any non-branch family ahead of price.
- **`NEAREST_PROMINENT_WICK`** — nearest fresh MEDIUM/HIGH-grade
  5/15/30/60m wick-liquidity target only.
- **`NEAREST_OPPOSING_HTF_FVG`** — nearest fresh opposing 5/15/30/60m HTF
  FVG target only, `PROXIMAL_EDGE` surface by default (MIDPOINT/DISTAL_EDGE
  are separate, never-retrospectively-chosen research surface variants
  exposed on the zone object itself).

Universe membership per candidate (`TargetInventory._raw`, gated by
`available_seq <= entry_seq`, same segment): prominent wicks (5/15/30/60m),
HTF FVGs/iFVGs, rejection blocks, swings, historical/session/time-anchor
levels, VWAP + bands, compression boundaries. Direction filter: target must
be strictly ahead of entry in the trade direction (`WRONG_SIDE_OF_ENTRY`
otherwise) and, where directional, on the opposing side
(`WRONG_DIRECTION` otherwise). Freshness: `fresh_at(entry_seq)` per object
family (`STALE` otherwise). Prominence: wick targets below `MEDIUM` are
`LOW_PROMINENCE`-excluded from eligibility. Occlusion: `frontmost`/
`occluded_by_object_id` recorded on every candidate row, never deleted.
Tie-break: nearest `distance_points` wins within a policy's eligible subset
(`select_target`). No valid target under a policy ⇒ that policy simply
produces no variant for that trigger (never a fabricated target).

Target surface is fixed at selection time and never switched after RR is
known (`TargetCandidate.target_surface` is set once in `build_target_
candidates` and read, never rewritten, by `apply_rr_policy`).

## 6. RR is an executability filter, not a grade

```
risk           = |entry - structural_stop|
natural_reward = |structural_target - entry|
natural_RR     = natural_reward / risk
```
`natural_RR < 0.5` → `INSUFFICIENT_NATURAL_RR`, permanent rejection, no
stop-tighten, no farther target, no later-bar search. `0.5 ≤ natural_RR < 1`
→ execute at the natural target. `natural_RR ≥ 1` → execute at exactly 1.0R,
natural target/RR retained as a diagnostic field only. This is
`setups/model.py::apply_rr_policy`, unchanged by this repair. **After the
0.5R gate, `natural_rr`/`executed_rr` remain diagnostic features in the
comparability/similarity vector — they must never drive qualification beyond
that one binary feasibility gate.** A 0.55R branch with strong prior
profitability may qualify; a 3R-natural (1R-executed) branch with poor prior
profitability may not.

## 7. Exact / reduced / nearest-neighbour identity

**Exact tier**: identical `exact_graph` string. This already encodes path
family, ordered event subtypes and the terminal trigger token
(`{ENTRY_MODE}_{DIRECTION}_TRIGGER`), so an exact match already implies
identical path family, direction-normalized mechanism, and entry mode.

**Reduced tier**: identical `reduce_graph(exact_graph)` (generalizes event
*subtypes* to structural roles — e.g. any FVG fill state collapses to
`GAP_FILL`, any RB interaction collapses to `STRUCTURAL_ZONE_INTERACTION` —
while preserving the ordered sequence of structural roles) **plus hard
compatibility** (below). Fields deliberately generalized from exact to
reduced: displacement grade distinctions within a reduced token (GOOD/BAD
distinctions are *retained* — `STRONG_DISPLACEMENT` vs `WEAK_DISPLACEMENT`
remain distinct reduced tokens; only the finer per-event subtype detail like
exact FVG lifecycle state is collapsed). The reduced graph never merges a
continuation-family mechanism with a fade-family mechanism (hard
compatibility enforces this independently).

**Hard compatibility** (`recognizer/similarity.py::hard_compatible`), gate
for both the reduced tier and NN admission:
`path_family` (exact) · `continuation_or_fade` (exact) · `entry_mode` (exact
— this subsumes "immediate vs. retest state" since `entry_mode`'s literal
values already distinguish `first_touch`/`retest`/`midpoint`/`full_fill`
from `formation_close`/`next_bar`) · `origin_family` (exact) ·
`target_policy_id` (exact). "Direction-normalized mechanism" requires no
separate field: the feature vector itself is already direction-normalized
(§ signatures.py docstring) so comparing raw feature values across long/short
candidates is already apples-to-apples. "Required lineage class" is
subsumed by `origin_family` (an iFVG's parent-FVG lineage is a different
`origin_family` state than a bare FVG). **Repair**: `path_family` was
missing from `hard_compatible` prior to this task — added (previously an
`rb_reaction` candidate could NN-match a `sweep_fade` candidate if the other
four fields coincided; this is exactly the "fundamentally different
mechanisms mixing" defect Stage 7 prohibits). `entry_mode` was previously
compared only at the coarse `entry_mode_class` (immediate/delayed) level —
upgraded to exact-value comparison.

**NN tier**: hard-compatible pool only, Gower distance (`similarity.gower`)
over `NUM_KEYS`/`CAT_KEYS`, prior-pool-only numeric ranges, `NN_MAX_DISTANCE
= 0.35`, `NN_MAX_NEIGHBORS = 50`, nearest-first tie-break, missing values
excluded from that feature's contribution (never imputed) — all unchanged
constants, frozen before this task and not re-tuned here.

## 8. Fixed evidence lookback horizons

`HORIZONS = [1, 3, 5, 10, 20, 40, "ALL"]` (sessions), unchanged. For every
tier × horizon: occurrences, unique sessions, wins/losses/ambiguous/expired
(unresolved/OPEN excluded from realized-R statistics but not from
`occurrences`), mean/median realized R, win/loss/favorable rate, outcome
variance, recency-weighted mean R (half-life 10 sessions), effective sample
size (unique sessions with a resolved outcome), standard error
(`pstdev/sqrt(ess)`), average executed-winner R, session bounds (min/max
completion ordinal in the horizon subset), per-session contribution share
(largest single session's occurrence share of the subset), and a
sufficiency flag (`unique_sessions >= gate.DEFAULT_POLICY.min_unique_
sessions`). A compact hierarchical-shrinkage estimate (exact ← reduced ← NN
← global, `K_SHRINK = 5.0`) remains available as a *summary*, but the
underlying horizon-by-horizon table is always retrievable and displayed.

## 9. Qualification semantics

Unchanged gate mechanics (`recognizer/gate.py::GatePolicy`/`qualify`), not
re-tuned against review-week outcomes: `min_effective_sample=4`,
`min_unique_sessions=3`, `min_shrunk_expected_R=0.05`, `max_uncertainty=0.6`,
`require_level_agreement=True`, `recency_required=True`. States:
`QUALIFIED_PENDING_TRIGGER`, `RECORDED_NOT_ACTIVATED`, `UNSCORED`.
`UNSCORED` is reserved for a documented mechanical failure (e.g. a candidate
whose features could not be built), never a routine compute shortcut — the
repaired evidence engine scores every one-trigger/one-policy candidate in the
review week. Every scored candidate carries `gate_fails` (the exact list of
failing field ids) and the full evidence snapshot that produced the decision.

## 10. Deduplication semantics (two distinct, both preserved)

- **`one-trigger/one-policy`** (evidence universe): key
  `(trigger_event_id, target_policy_id)`. When a trigger legitimately
  produces multiple mechanically-duplicate rows under the same policy (can
  occur only from re-materialization; not expected in a single run), the
  representative is chosen by the frozen key `min(candidate_id)`. This is
  the unit of an "independent historical observation" for evidence
  purposes — never the raw variant-row count.
- **`one-trigger` overall** (diagnostic only): key `trigger_event_id`,
  representative chosen by `TARGET_POLICIES` priority order then
  `candidate_id` (existing `review_atlas.dedup_by_trigger`, unchanged). Used
  only for trigger-count diagnostics, never as an evidence pool.

Neither form mutates or removes rows from the underlying candidate ledger.

## 11. Atlas selection rules (Stage 12 sections)

**A. Primitive examples** — deterministic, first-qualifying-occurrence,
unchanged mechanism, corrected lifecycle predicates (§ below).
**B. Branch-mechanism examples** — descriptive, not ranked; one
representative per existing path family/label, selected by strict predicates
proving the graph conditions the label claims (not merely a matching
`path_family` string).
**C. Evidence-ranked examples** — selected by frozen, pre-outcome
evidence/qualification fields only (never the candidate's own outcome):
strongest positive recent exact/reduced evidence, strongest qualified,
conflicting short-vs-medium horizon, positive-short/negative-long,
negative-recent, insufficient-sample, high-uncertainty, exact-unavailable-
reduced-present, reduced-unavailable-NN-present, recorded-not-activated,
qualified/not-activated pairs sharing a reduced graph (only when they
genuinely exist — no fallback substitution), same-trigger different-policy
pairs.
**D. Structurally rejected examples** — by exact rejection reason; never
described as "low quality."

A missing category is reported as **absent**, never backfilled with an
unrelated example under the same label (Problem 6's exact defect).

## 12. Forbidden outcome usage (restated)

No candidate's own outcome may influence its own selection, grade,
qualification, or geometry. No same-CME-session outcome may influence any
other candidate materialized in that same session. Outcomes are attached
only after the complete pre-outcome example manifest is built and hashed.
Review-week outcomes are descriptive only — never used to choose examples,
tune the gate, or claim edge/forward validity.

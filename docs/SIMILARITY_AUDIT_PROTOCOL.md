# Similarity Representation Audit Protocol

This audits every field used by exact-graph matching, reduced-graph matching,
hard compatibility, nearest-neighbor/Gower similarity, evidence shrinkage, and
qualification, starting from the code as it existed at commit `59366db`. This
commit changes no similarity logic, no thresholds, and no representation
fields — but it **does contain two narrow causal-integrity bugfixes**,
disclosed in full in §0, because the audit's own blocking test
(`test_features_unchanged_by_bars_added_after_trigger`, required by the task's
"future structures do not enter candidate features") caught two real
future-information leaks while being written. Both are one-mechanism, low-blast-
radius fixes to bring the *existing* causal-availability design (already stated
in `docs/MULTITIMEFRAME_TARGET_PROTOCOL.md` §3/§8 and already correctly
implemented for several sibling fields) into effect for the two places it had
not yet been applied. Neither changes any similarity field, threshold, grammar,
or trading concept. Findings that indicate a representational gap (as opposed to
a causality bug) are flagged and carried forward into
`docs/ADAPTIVE_RECOGNIZER_AUDIT.md`, not fixed here.

## 0. Two causal-integrity bugfixes made while writing this audit's blocking test

Both were found by `test_features_unchanged_by_bars_added_after_trigger`
(`tests/test_similarity_audit.py`): rerun the graph-native pipeline on the same
bar prefix twice, once with more bars appended after it, and require every
candidate materialized in both runs to have byte-identical frozen geometry and
features. This directly operationalizes the task's requirement to verify
causality "in the running graph-native pipeline, not merely documented."

* **Bug A — inert leak in `sweep_state`.** `signatures.py::build_features` set
  `f["sweep_state"] = origin.has_event("SWEEP")`, which scans a primitive's
  *entire* lifetime event list with no `seq <= entry_seq` cutoff (unlike
  `revisit_number` two lines above, which already does this correctly). Fixed
  to `any(e.kind == "SWEEP" and e.seq <= s.entry_seq for e in origin.events)`.
  **Severity: low.** `sweep_state` is not in `NUM_KEYS`/`CAT_KEYS` and not in
  `hard_compatible` (see finding F10-adjacent note in the field table), so this
  leak had zero effect on similarity, evidence, or qualification — it only
  affected a display/audit-only field. `src/discretion/representations/signatures.py`.
* **Bug B — material leak in target eligibility.** `graph/targets.py::_raw`
  computed wick-liquidity and HTF-FVG/iFVG target freshness as
  `o.fresh_at(entry_seq) and o.active`. `fresh_at(entry_seq)` is already the
  correct, seq-parameterized causal check; `o.active` is a single mutable flag
  that reflects the object's state at the *end* of the entire primitives scan
  and is flipped by whatever bar closes through / fully fills / re-inverts the
  object — which can be **after** a given candidate's own `entry_seq`. ANDing
  it in reintroduced a look-ahead: a target that was genuinely fresh as of a
  candidate's trigger could be silently marked ineligible because it was
  invalidated later in the same loaded window. Fixed by dropping the `and
  o.active` term (both fields the flag was meant to check are already covered
  by `fresh_at`). **Severity: material** — this changed the selected
  `structural_target`/`natural_rr`/`executed_rr` for affected candidates, i.e.
  it is exactly the class of defect the RR-invariant audit exists to catch.
  `src/discretion/graph/targets.py`.
* **Bug C — material leak in equal-high/equal-low cluster confirmation.**
  `structure.py::detect_equal_levels` built each cluster by scanning the
  *entire* loaded swings list and greedily absorbing every later matching
  swing, stamping `created_seq = max(...)` over however many points it
  collected. A two-point cluster confirmed at seq 14 in a short window did not
  exist at all until seq 194 in a longer window over the same underlying data,
  because a third matching swing 180 bars later got absorbed first and pushed
  its confirmation timestamp out — making the level's causal availability a
  function of how much data happens to be loaded after it, not of the market
  itself. Fixed by freezing a cluster at its first confirming pair (`break`
  after the first match), matching the confirm-once, never-retroactively-grown
  pattern already used by every sibling primitive (swings, wicks, FVGs).
  **Severity: material**, same class as Bug B; can change which target/origin
  a candidate uses. `src/discretion/primitives/structure.py`.

All three are covered by regression tests (`tests/test_similarity_audit.py`,
`tests/test_structure.py`) and the full existing suite (238 tests prior to this
commit) was rerun clean afterward. No candidate-outcome data was consulted to
decide on or shape these fixes — they were derived purely from the causal-
availability contract already stated in the codebase's own docstrings and
protocol docs.

## 1. Systems audited

| Layer | File | Function/class |
|---|---|---|
| Exact graph | `graph/materializer.py` | `Materializer.materialize` (builds `exact` string from `trigger.ordered_event_ids` subtypes + entry-mode/direction token) |
| Reduced graph | `representations/signatures.py` | `reduce_graph`, `_reduce_token` |
| Numeric/categorical features | `representations/signatures.py` | `FeatureContext`, `build_features` |
| Hard compatibility | `recognizer/similarity.py` | `hard_compatible`, `entry_mode_class` |
| Gower distance | `recognizer/similarity.py` | `gower`, `numeric_ranges`, `NUM_KEYS`, `CAT_KEYS` |
| Evidence shrinkage | `recognizer/evidence.py` | `build_snapshot`, `_subset_stats`, `_shrink` |
| Qualification | `recognizer/gate.py` | `gate_reasons`, `qualify` |
| Declared schema | `schemas/feature.schema.json` | field types + `symmetric` flags |

## 2. How each matching tier actually uses fields

* **Exact graph** (`c.exact_graph` string equality): the strongest tier.
  Encodes causal event order, event subtypes (which fold in origin/trigger
  family, sweep/reclaim/break/acceptance state, FVG/iFVG lifecycle stage), and
  the terminal `{ENTRY_MODE}_{DIRECTION}_TRIGGER` token. Two candidates match
  here only if their entire causal path string is identical.
* **Reduced graph** (`c.reduced_graph` string equality **and**
  `hard_compatible`): generalizes tokens (e.g. every FVG fill state →
  `GAP_FILL`, `IFVG_ACTIVATION` → `INVERSION_ACTIVATION` vs generic iFVG →
  `INVERSION_INTERACTION`) but preserves order and collapses only adjacent
  duplicates.
* **Nearest-neighbor / broad** (`hard_compatible` **and** Gower distance ≤
  `NN_MAX_DISTANCE`): the only tier where a candidate can match another with a
  **different** exact and reduced graph. `hard_compatible` is the sole
  categorical gate at this tier; everything not in `hard_compatible` is only a
  soft (averaged) Gower contribution, or not used at all.
* **Global**: the full prior pool, no gate.

`hard_compatible` currently checks exactly four fields: `continuation_or_fade`,
`entry_mode_class(entry_mode)` (immediate vs delayed), `origin_family`, and
`target_policy_id`. Every other field below participates only through the
reduced-graph string (if it changes the graph token) or through Gower (if it is
in `NUM_KEYS`/`CAT_KEYS`) — or not at all.

## 3. Field-level table

Legend — **Exact**: changes the exact-graph string. **Reduced**: changes the
reduced-graph string (survives generalization). **Vector**: present in
`features` dict. **Hard**: enforced in `hard_compatible`. **Future-safe**: field
value is computed only from data available at/before the candidate's trigger
timestamp.

| Field | Exact | Reduced | Vector | Hard | Reason included/excluded | Future-safe | Missing-data behavior |
|---|:-:|:-:|:-:|:-:|---|:-:|---|
| Causal graph order | ✅ | ✅ | — | — | order is the graph string itself (`->`-joined) | ✅ | n/a (always present) |
| Continuation vs fade | ~ | ~ | ✅ `continuation_or_fade` | ✅ | primary hypothesis split; must never blend | ✅ | never null (set at branch fork) |
| Origin family | ~ | ~ | ✅ `origin_family` | ✅ | causal source of the path | ✅ | `"unknown"` if origin lookup fails (registry miss) |
| Trigger family | ✅ (via subtypes) | ✅ | ✅ `path_family` | — | drives the graph string directly; **not** separately hard-gated (redundant with graph-string equality at exact/reduced tiers, but at the NN tier two different `path_family` values can share `hard_compatible` if `origin_family`/`continuation_or_fade`/`entry_mode_class`/`target_policy_id` agree) | ✅ | never null |
| Entry mode | ✅ (terminal token) | ✅ (via mode-derived subtype where relevant) | ✅ `entry_mode` (raw) | ✅ (class only) | raw mode in Gower `CAT_KEYS`; class (`immediate`/`delayed`) hard-gated | ✅ | never null |
| Immediate vs delayed entry | ✅ | ✅ | ✅ (`entry_mode` raw) | ✅ (`entry_mode_class`) | **Gap**: `_IMMEDIATE = {formation_close, next_bar}`; all of `first_touch/midpoint/full_fill/retest` collapse to the same `"delayed"` class. FVG-activation-immediate and iFVG-retest both entry via `retest`/`first_touch`-style modes are both `"delayed"` — see §5 finding F1. | ✅ | never null |
| Direction | — | — | ✅ `direction` (±1) | ❌ | **not hard-gated at all**; relies on other symmetric-normalized fields to make cross-direction comparison meaningful — see §5 finding F2 | ✅ | never null |
| Session | — | — | ✅ `session` (CAT) | ❌ | soft only | ✅ (ET wall-clock of entry bar) | never null (`_session()` always returns a bucket) |
| Minutes from relevant time anchor | — | — | ✅ `minutes_from_0930` | ❌ | **Gap**: hardcoded to 09:30 regardless of the origin's actual time anchor (midnight/Asia/London/etc.) — see §5 finding F3 | ✅ | never null (always relative to 09:30) |
| Setup duration | — | — | ❌ | ❌ | **Missing.** `origin_age_bars` (entry_seq − origin.created_seq) is the closest proxy but conflates "how old is the origin" with "how long did the graph take to complete" — see §5 finding F4 | n/a | n/a |
| Displacement quality and direction | — | ~ (`STRONG_/WEAK_/MIXED_DISPLACEMENT` reduced tokens when displacement is itself an event in the path) | ✅ `displacement_grade`, `displacement_body_atr`, `path_body_ratio`, `favorable_close` | ❌ | quality via grade/ATR magnitude; direction is implicit (favorable_close is already direction-normalized) | ✅ | all four `None` when `origin.family != "displacement"` |
| Compression state and duration | — | ~ (`COMPRESSION`/`EXPANSION` reduced tokens only when central to the graph) | ❌ | ❌ | **Missing as a standalone vector field** when compression is a supporting (non-origin) structure — see §5 finding F5 | n/a | n/a |
| FVG state (formation/no-fill/touch/fill/failure) | ✅ | ✅ (`GAP_FORMATION`/`GAP_FILL`/`GAP_FAILURE`) | ~ (`revisit_number`, `zone_width_atr` when `origin_family in (fvg,ifvg)`) | — | state is graph-encoded, not duplicated into the numeric vector (by design — avoids redundant features) | ✅ | `revisit_number`/`zone_width_atr` `None` for non-FVG/iFVG origins |
| iFVG parent lineage and immediate/retest state | ✅ (`ifvg_activation` vs `ifvg_retest` are different `path_family`s → different graph tokens) | ✅ (`INVERSION_ACTIVATION` vs `INVERSION_INTERACTION`) | — (lineage IDs stored on the candidate object: `parent_fvg_id`, `fvg_formation_event_id`, `fvg_failure_event_id`, `ifvg_confirmation_event_id`, `retest_event_id` — **not copied into `features`**) | ❌ (only via reduced-graph string; NN tier can still merge immediate and retest — see F1) | lineage is provenance, kept on the candidate row for audit, not needed for exact/reduced matching since the graph string already encodes it | ✅ | empty string when not an iFVG-lineage candidate |
| RB interaction state | ✅ | ✅ (`STRUCTURAL_ZONE_INTERACTION`) | ✅ `has_rb` (boolean only) | ❌ (soft, `has_rb` in `CAT_KEYS`) | state detail lives in the graph string; only presence is a vector field | ✅ | `has_rb=False` when absent |
| Level family | — | — | ✅ `level_family` | ❌ (soft) | only for `origin_family in (hist_level, liquidity, time_anchor)` | ✅ | `None` otherwise |
| Sweep/reclaim/acceptance state | ✅ | ✅ (`LIQUIDITY_SWEEP`/`RECLAIM`/`ACCEPTANCE`) | ~ `has_sweep` (boolean), `sweep_state` (boolean) | ❌ (soft, `has_sweep` in `CAT_KEYS`) | reclaim/acceptance distinguished only at the graph-string level, not as separate vector fields | ✅ | `sweep_state=None` for non-level origins |
| VWAP side and band | — | ~ (`VWAP_INTERACTION`/`BAND_REJECTION` tokens) | ✅ `vwap_side` (direction-normalized ±1), `nearest_vwap_band` (raw label) | ❌ (soft) | `vwap_side` is direction-normalized per its docstring; `nearest_vwap_band` is **not** — see §5 finding F6 (schema/implementation mismatch) | ✅ (uses `vs.value_at(entry_seq)`, causal) | both `None` when no active VWAP session at entry |
| Target policy | — | — | ✅ `target_policy_id` | ✅ | different research variants of the same trigger must never be treated as comparable | ✅ (policy is a selection rule, not price-derived) | never null on a materialized candidate |
| Target family | — | — | ✅ `target_family` | ❌ (soft only, `CAT_KEYS`) | **Gap**: `htf_fvg` vs `wick_liquidity` vs `opposing_hist_level` targets are materially different mechanics but are only softly weighted, not hard-blocked — see §5 finding F7 | ✅ | always set (falls back to `measured_or_other` in the legacy `_target_family` helper; materializer sets it directly from `tgt_c.family`) |
| Target timeframe | — | — | ✅ `target_timeframe` | ❌ (soft) | 1m vs 60m opposing structure is a different research object; not hard-gated | ✅ | string `"None"` when target has no timeframe (e.g. swing/level) |
| Target surface | — | — | ✅ `target_surface_policy` | ❌ (soft) | **Currently vacuous**: `target_surface` is hardcoded to `"PROXIMAL_EDGE"` for every `TargetCandidate` in `graph/targets.py::make()` — MIDPOINT/DISTAL are exposed as HTF-FVG object properties for research (`f.midpoint`, `f.distal`) but never wired into an executable target surface — see §5 finding F8 | ✅ | constant `"PROXIMAL_EDGE"` |
| Stop-anchor family | — | — | ❌ | ❌ | **Not duplicated into `features`.** `stop_anchor_type` lives on `GraphNativeCandidate` directly. Deterministic function of `(trigger_family, direction)` via `resolve_anchors`, so it is redundant with `path_family` + `direction` for similarity purposes — documented, not a bug | ✅ | always set (falls back to `structural_extreme_fallback`) |
| Natural RR bucket | — | — | ✅ `natural_rr` (continuous) | ❌ | **No discrete bucket field exists**; only the continuous value, used in Gower (`NUM_KEYS`) and evidence display. Commit 3's required "natural RR bucket" breakdown is computed by the audit script itself (bucketing `natural_rr` into `[0.5,1)`/`[1,∞)`/rejected), not by the representation | ✅ | never null on an eligible candidate |
| Wick prominence/timeframe (target side) | — | — | ✅ `target_prominence`, `target_timeframe` | ❌ (soft) | applies only when `target_family == "wick_liquidity"`; wick liquidity is **target-only** in this build (never a branch origin — confirmed by grep: no `origin_family == "wick_liquidity"` path exists) | ✅ | `None` for non-wick targets |
| HTF FVG timeframe and direction (target side) | — | — | ✅ `target_timeframe` (tf); direction implicit (opposing-only by construction) | ❌ (soft, tf only) | HTF FVG direction is not a separate vector field because target selection already constrains it to the opposing direction (`o.direction == opp` in `targets.py::_raw`) — redundant by construction | ✅ | n/a |
| Volatility context | — | — | ❌ | ❌ | **Missing.** No ATR-regime / volatility-bucket feature exists in this representation (the earlier, non-canonical `phase1/recognizer/` prototype had one; it was not carried into `src/discretion/`) — see §5 finding F9 | n/a | n/a |
| Contradictory active structure | — | — | ✅ `contradictory_structure` | ❌ | **Computed but unused in similarity.** `FeatureContext._contradictory` sets this boolean, but it is in neither `NUM_KEYS`/`CAT_KEYS` nor `hard_compatible` — it is audit/display-only at present — see §5 finding F10 | ✅ | boolean, never null |
| Causally available HTF alignment | — | — | ✅ `htf_alignment` | ❌ | **Stub.** Always the literal constant `"unknown_1m_only"` — not a computed field at all — see §5 finding F11 | n/a (constant) | n/a |

## 4. Future-derived fields

None found. Every field in `build_features` reads only `ctx.bars[:entry_seq+1]`,
`ctx.atr[entry_seq]`, `origin` objects available at/before `s.entry_seq`, and
`ctx.vwap_by_seq` values that are themselves causal (`vs.value_at(entry_seq)`
only accumulates through the current bar). No field reads `outcome`,
`outcome_seq`, `realized_r`, or any bar index `> entry_seq`. This was verified
by direct code inspection of `signatures.py::build_features` and
`FeatureContext`; a corresponding blocking test is added in Commit 4
(`test_no_future_features_in_representation`).

## 5. Named findings (not fixed in this commit)

* **F1 — immediate vs retest not hard-blocked at the NN tier.** `ifvg_activation`
  (immediate) and `ifvg_retest` produce different exact/reduced graphs, so they
  never collide at those tiers. At the NN/broad tier, only `hard_compatible` gates
  comparability, and it does not check `path_family` or a immediate-vs-retest
  flag directly — only `entry_mode_class`, which buckets both under `"delayed"`.
  Two candidates with the same `origin_family`, `continuation_or_fade`, and
  `target_policy_id` but different immediate/retest status **can** appear in each
  other's NN neighbor set. Audited quantitatively in Commit 2.
* **F2 — direction is not hard-gated.** Relies entirely on other fields being
  correctly direction-normalized (`favorable_close`, `vwap_side`) to make
  cross-direction comparisons meaningful. `nearest_vwap_band` (F6) is not
  normalized, so this interacts with F6.
* **F3 — `minutes_from_0930` is anchor-agnostic.** For a `midnight_open` or
  `asia_open`-origin candidate, this field still measures distance from 09:30 ET,
  not from the origin's own anchor.
* **F4 — no standalone "setup duration" feature.**
* **F5 — no standalone compression-state/duration feature** when compression is
  a supporting (not central/origin) structure.
* **F6 — schema/implementation mismatch.** `schemas/feature.schema.json` declares
  `nearest_vwap_band` as `"symmetric": true`, but the value is a raw signed band
  label (e.g. `"+1.618"`) that is **not** mirrored by trade direction the way
  `vwap_side` is. A long approaching `+1.618` from below and a short approaching
  `-1.618` from above are structurally mirror-equivalent but receive different
  categorical labels.
* **F7 — target family/timeframe are soft-only.** A `htf_fvg` 60m target and a
  `wick_liquidity` 5m target are materially different target mechanics but are
  not hard-blocked from NN comparison.
* **F8 — `target_surface_policy` is currently a constant.** No candidate has ever
  been materialized with `MIDPOINT` or `DISTAL_EDGE` surface; the field exists in
  the representation and schema but has one live value.
* **F9 — no volatility-context feature** in the canonical representation.
* **F10 — `contradictory_structure` is computed but never consulted** by
  `hard_compatible` or Gower.
* **F11 — `htf_alignment` is an unimplemented stub** (`"unknown_1m_only"`
  constant), not a computed field.

None of these were altered in this commit. They are quantitatively audited
where feasible in Commit 2 (collision counts attributable to F1/F7) and assessed
for severity in `docs/ADAPTIVE_RECOGNIZER_AUDIT.md` (Commit 5).

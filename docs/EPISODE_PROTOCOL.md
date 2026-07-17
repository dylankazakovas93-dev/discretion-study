# Causal Episode & Recognizer Protocol (v1, frozen)

This document freezes the architecture of the causal, branching market-episode
engine and the prior-only adaptive recognizer foundation. It is frozen **before**
any untouched-forward replay. Numeric constants live in `PREREGISTRATION.md`.

```
RAW PRIMITIVE EVENTS
  -> ACTIVE CAUSAL EPISODES
    -> BRANCHING MARKET PATHS
      -> COHERENT SETUP CANDIDATES
        -> PRIOR-ONLY EVIDENCE SNAPSHOT
          -> QUALIFIED / NOT QUALIFIED
            -> OUTCOME RECORDED LATER
```

The canonical primitive + setup foundation is `src/discretion/`. This layer does
**not** re-implement ATR, roll selection, FVG, iFVG, RB, VWAP or levels. It
consumes append-only events derived from the canonical primitives.

## 0. Six separate concepts (never conflated)

| # | Concept | Object | Count reported |
|---|---|---|---|
| 1 | **Primitive event** | `CanonicalEvent` | raw_primitive_events |
| 2 | **Active causal episode** | `Episode` | active_episodes |
| 3 | **Branch state** | `Branch` | branches_created / merged / terminated |
| 4 | **Coherent setup candidate** | `SetupCandidate` | coherent_candidates (raw, deduped) |
| 5 | **Qualified setup** | candidate + `EvidenceSnapshot` + `QUALIFIED` | qualified |
| 6 | **Activated trade** | qualified + trigger fill | activated |

"Eligible" is never used as an umbrella term.

## 1. Canonical append-only event schema

`CanonicalEvent` (see `schemas/event.schema.json`) fields:
`event_id, event_type, event_subtype, object_id, parent_object_id,
timestamp_et, availability_timestamp_et, source_timeframe, absolute_segment_id,
normalization_segment_id, direction, price_low, price_high, reference_price,
state_before, state_after, feature_values, causal_parent_event_ids,
invalidation_timestamp, expiry_timestamp, source_detector_version`.

Rules:
* **Append-only.** A later state change emits a *new* event; prior records are
  never mutated or deleted.
* `timestamp_et` is the ET open of the bar that produced the event.
* `availability_timestamp_et` is when the event became knowable = the bar's
  **close** = `timestamp_et + 1 minute` (completed candles only, zero lookahead).
* `absolute_segment_id` gates absolute-price structures; they never cross a roll.
* `feature_values` are causal (ATR-normalized where cross-contract), current
  candle excluded from its own normalization.
* `event_id` and `object_id` are permanent and deterministic for a given
  chronological pass.

## 2. Episode state machine

`Episode` stores: `episode_id, origin_object_id, origin_event_id, origin_family,
start_timestamp, directional_context, active_branch_ids, primitive_event_ids,
current_object_states, episode_expiry, resolved_timestamp, resolution,
episode_version`.

* An episode begins from one origin object/state (an RB, one FVG lifecycle, one
  level interaction, one sweep-and-response, one compression region, one
  time-anchor interaction).
* Episodes may span **non-consecutive** candles.
* Default intraday episodes do not continue past the relevant session end unless
  the originating structural object is explicitly valid across sessions.
* A multi-session level may survive across sessions, but **each new interaction
  creates a new interaction episode** (new `episode_id`).
* State changes bump `episode_version`; prior versions are retained in the log.

## 3. Causal event linking

A new event may join an active episode only when ALL applicable rules pass, and
the **exact reason** for the permitted edge is stored:

1. availability time strictly after the parent state became available;
2. it refers to the same object, a child object created by the episode, or a
   causally generated price response from that object;
3. it occurs before episode expiry;
4. the parent structure is not invalidated;
5. its direction is consistent with the branch, or it is an explicit
   inversion/failure transition;
6. its price location is structurally connected to the active object/price path
   (within a frozen ATR-scaled proximity, or references the object directly);
7. it is not merely another unrelated nearby label.

Rejected edges (arbitrary adjacency, unrelated VWAP touch, sweep of a different
level, retrospective displacement) are recorded with the failing rule id.

## 4. Branching

`Branch` states: `CONTINUATION, FADE, UNRESOLVED, FAILURE, EXPIRY`.
Branches follow observed deterministic transitions only (never prose).

Canonical branch templates (non-exhaustive; see ontology in code):
* RB tap → good displacement → (optional FVG) → continuation.
* RB tap → mixed/bad displacement → no-progress/compression → **UNRESOLVED**
  (not yet a fade). Becomes FADE only on a measurable failure event (reclaim
  through the RB price, opposing structure break, failed expansion, FVG failure,
  iFVG activation, acceptance through the RB, opposing expansion).
* FVG lifecycle → {immediate close, next-bar, first-touch, midpoint, full-fill,
  no-fill continuation, revisit, failure, iFVG activation, iFVG retest}.
* Level interaction → sweep+fade / sweep+continuation / non-sweep continuation.
* iFVG → immediate / next-bar / retest / continuation-no-retest / failure.
* Time-anchor → rejection-fade / reclaim-continuation / break-acceptance /
  compression / failed-expansion / expansion.
* VWAP/band → bounce / reclaim / rejection / break-acceptance / continuation /
  failed-continuation / fade-to-VWAP / rotation / compression / expansion.
* Compression → expansion-continuation / false-expansion-fade / FVG paths.

### Graph control (deterministic)
* deduplicate identical branch signatures; never add the same event twice;
* merge branches with identical causal history and frozen state;
* repeated interaction nodes only when ordinal state matters (first vs revisit);
* frozen depth cap (`MAX_BRANCH_DEPTH`), large enough for multi-stage paths;
* record branches terminated by depth / expiry / invalidation / duplication;
* depth is **never** chosen after inspecting profitability; branches are **never**
  discarded for poor outcomes. Permanent branch IDs.

## 5. Direction normalization

Store original market direction. Also a direction-normalized numeric view where
positive = movement in the hypothesized setup direction. Bullish/bearish are not
merged where session/economic meaning is genuinely asymmetric (encoded per
feature via a `symmetric` flag).

## 6. Coherent setup completion

A branch becomes a `SetupCandidate` only when it contains: causal origin,
measurable transition, explicit trigger, frozen entry, structural stop,
structural target, expiry, and valid RR under the frozen 0.5R–1R policy
(reused from `src/discretion/setups/model.py`):

* `natural_RR = |target-entry| / |entry-stop|`;
* `< 0.5R` → reject before entry (`INSUFFICIENT_NATURAL_RR`);
* `0.5R–<1R` → retain natural target;
* `>= 1R` → execute at exactly 1R, retain uncapped structural target for diagnostics;
* stops never moved to manufacture eligibility; targets never chosen after the
  future path is visible; same-bar stop/target = AMBIGUOUS.

Not every setup requires an FVG, iFVG, RB, sweep or time anchor.

### Episode/candidate dedup identity
`(origin_object_id, interaction_episode, direction, trigger_family, entry_mode,
stop_anchor, target_anchor)`. Cosmetic re-descriptions collapse; genuinely
different entry modes (formation close / next-bar / first touch / midpoint /
full fill / retest) stay distinct.

## 7. Three deterministic representations

Each candidate gets:
1. **Exact graph signature** — full ordered subtype sequence, e.g.
   `RB_TAP -> BAD_BEARISH_DISPLACEMENT -> COMPRESSION -> TEN_AM_ANCHOR ->
   BULLISH_FVG_FAILURE -> BEARISH_IFVG_ACTIVATION -> IMMEDIATE_SHORT_TRIGGER`.
2. **Reduced graph signature** — generalized but still discriminative, e.g.
   `STRUCTURAL_ZONE_INTERACTION -> FAILED_REACTION -> COMPRESSION ->
   GAP_FAILURE -> INVERSION_TRIGGER`. Not so coarse that distinct situations
   collide.
3. **Numeric feature vector** — causal fields only (origin family, session,
   minutes-from-anchor, direction, displacement grade/score/dist-ATR, path
   efficiency, overlap, wick proportions, compression duration/range-ATR, FVG
   width-ATR/freshness/revisit, iFVG/RB age, level family/age, sweep state,
   VWAP side / nearest band, dist-to-stop-ATR, natural RR, target family,
   contradictory-structure flag, HTF alignment where causally available). No
   future-derived feature. No text embeddings in v1.

## 8. Prior-only adaptive recognizer

For each new candidate at time T:
1. freeze exact graph; 2. freeze reduced graph; 3. freeze numeric vector;
4. retrieve comparable candidates whose outcomes **completed before the current
   trading session**; 5. compute evidence snapshot; 6. store it permanently
   (immutable after trigger); 7. classify qualified/unqualified; 8. only then let
   the future path set the outcome. Current-session outcomes never influence
   later current-session decisions in v1.

### Similarity hierarchy
* **Level 1 exact**: identical exact graph signature.
* **Level 2 reduced-family**: identical reduced signature + compatible origin /
  transition / trigger.
* **Level 3 nearest neighbors**: prior-only normalized **Gower** distance over
  mixed numeric+categorical features, with hard categorical constraints.
Incompatible comparisons are forbidden: continuation vs fade; immediate-formation
vs delayed-retest where entry mode is central; accepted vs failed level break;
materially different target mechanics.

### Lookback horizons
Prior completed sessions: 1, 3, 5, 10, 20, 40, and all-eligible-history.
Overlapping windows are **not** independent votes. Per horizon × level store:
occurrence count, unique-session count, effective sample size, wins, losses,
ambiguous, expired, incomplete, mean R, median R, favorable rate, loss rate,
outcome variance, recency-weighted mean R, target-R and stop-R distributions.
Ambiguous/incomplete are never counted as wins or losses.

### Effective sample size
Sessions are the independence unit: `ESS = unique_sessions` of *resolved*
(WIN/LOSS) comparables. Raw count is reported separately.

### Hierarchical shrinkage (frozen formula)
Realized R: WIN = `+executed_rr`, LOSS = `-1.0`; AMBIGUOUS/EXPIRED/INCOMPLETE
excluded from the R mean. For a level with sample mean `m` and `ESS = n`,
shrink toward its parent prior `p`:
```
shrink(m, n, p) = w*m + (1-w)*p,   w = n / (n + K_SHRINK)
```
Cascade bottom-up over tiers exact ⊂ reduced ⊂ nearest-neighbor(broad) ⊂ global:
```
est_global  = global_mean_R
est_broad   = shrink(nn_mean,      nn_ess,      est_global)
est_reduced = shrink(reduced_mean, reduced_ess, est_broad)
est_exact   = shrink(exact_mean,   exact_ess,   est_reduced)
shrunk_expected_R = est_exact
```
Every tier's contribution and weight is stored. A broad prior can never
invisibly dominate: its weight is `n/(n+K)` at each step and is reported.

## 9. Qualification gate (frozen, configurable)

Fields (values in `PREREGISTRATION.md`): `min_effective_sample`,
`min_unique_sessions`, `min_shrunk_expected_R`, `max_uncertainty`,
`required_level_agreement`, `recency_requirement`, `target_r_breakeven_margin`.

Outcomes of the gate:
* fail → `RECORDED_NOT_ACTIVATED` (kept in the ledger, never simulated as a trade);
* pass → `QUALIFIED_PENDING_TRIGGER` → then `ACTIVATED` / `EXPIRED_UNFILLED` /
  `INVALIDATED_BEFORE_FILL`.
The gate is **not** tuned on any untouched forward period; dev data verifies
mechanics only.

## 10. AI role

The LLM is not the live oracle and never eyeballs a chart to decide a live setup.
It may inspect structured ledgers and propose ontology/grammar changes, which
must become versioned machine-readable grammar before evaluation. The recognizer
stays deterministic and reproducible.

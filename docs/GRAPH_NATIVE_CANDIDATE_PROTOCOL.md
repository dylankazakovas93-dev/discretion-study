# Graph-Native Candidate Protocol (v2, frozen amendment)

This amends `EPISODE_PROTOCOL.md`. It corrects a central architectural defect in
v1 and freezes the graph-native candidate architecture. Frozen constants stay in
`PREREGISTRATION.md`; this document freezes *structure and semantics*.

## 1. Why the prior candidate flow was wrong

v1 generated candidates like this:

```
build_setups(ps)  ->  completed setup candidate
                  ->  find an approximately-matching episode
                  ->  decorate the candidate with an episode path + graph
                  ->  adaptive evidence
```

The hard-coded setup builders were the **source** of candidates; episodes and
branches were attached *after the fact*. Consequences:

* The graph did not create the setup — it was reverse-engineered onto a setup
  that a procedural builder had already decided existed.
* An "episode" was chosen by nearest-price matching, so provenance was
  approximate, not causal.
* The system could only ever express the finite set of paths hand-coded in the
  builders; it could not express a coherent path nobody had encoded.
* Disabling `build_setups(ps)` would have produced **zero** candidates — proof
  that the graph was decorative, not generative.

## 2. Required flow (graph-native)

```
CANONICAL EVENTS
  -> causal episodes
    -> multiple concurrent active branches
      -> deterministic branch transitions (frozen registry)
        -> a branch reaches a valid trigger state
          -> a graph-native candidate is MATERIALIZED from that branch state
            -> prior-only adaptive evidence
              -> qualification
                -> later outcome
```

The episode graph itself creates the candidate. The materializer receives **only
a completed branch-trigger state** and must never call `build_setups(ps)`. The
graph-native pipeline must still function if `build_setups(ps)` is disabled or
raises.

## 3. Static builders are baseline-only

The v1 builders are preserved but demoted. They are reachable **only** through an
explicitly named baseline interface `build_static_baseline_setups(ps)` and are
used solely as:

* a static baseline;
* a diagnostic comparison layer;
* a source of genuinely generic structural stop/target helper utilities.

The graph-native engine does not import or call the builders. Static and
graph-native ledgers are **never** combined; they are counted separately.

## 4. Active episodes own active branches; events advance many branches

An `Episode` owns multiple concurrent `BranchState` objects, each one still-
causally-possible market path. Branch histories are append-only / versioned;
an earlier branch path is never rewritten after later events appear.

A single new event is evaluated against **every** active causally-compatible
branch in the relevant episode set. One event may simultaneously:

* advance one branch;
* invalidate another branch;
* fork a fade child from a third;
* leave a fourth unresolved;
* spawn a new child branch.

Combinatorial growth is bounded **without reference to outcomes** via: signature
deduplication, equivalent-state merging, branch expiry, structural invalidation,
`MAX_BRANCH_DEPTH`, maximum inactive duration, and outcome-independent dominance
rules. Branches are never collapsed merely for being near the same price, and
never deleted because their eventual outcome was poor.

### BranchState (permanent, typed)
`branch_id, episode_id, parent_branch_id, branch_version, origin_event_id,
origin_object_id, hypothesis_direction, continuation_or_fade, current_state,
ordered_event_ids, ordered_transition_ids, exact_graph_so_far,
current_structural_objects, current_directional_state, created_at,
last_advanced_at, expiry, invalidation_conditions, unresolved_conditions,
emitted_candidate_ids, terminal_status, terminal_reason`.

## 5. Structural relationships replace approximate price linkage

ATR proximity may be a **supporting** condition but never establishes a causal
edge on its own. Edges require explicit, machine-readable relationship predicates:

`SAME_OBJECT, PARENT_CHILD_OBJECT, OBJECT_CREATED_BY_LEG, TOUCHES_ZONE,
ENTERS_ZONE, FILLS_ZONE, CLOSES_THROUGH_ZONE, RECLAIMS_BOUNDARY, BREAKS_BOUNDARY,
ACCEPTS_BEYOND_BOUNDARY, REJECTS_BOUNDARY, SWEEPS_REFERENCE,
DISPLACEMENT_ORIGINATES_AT_OBJECT, FVG_CREATED_BY_DISPLACEMENT,
IFVG_CREATED_FROM_PARENT_FVG, COMPRESSION_FORMS_AROUND_OBJECT,
EXPANSION_LEAVES_COMPRESSION, FAILED_EXPANSION_RETURNS_TO_REGION,
TIME_ANCHOR_INTERACTION, SAME_INTERACTION_EPISODE, DIRECTIONALLY_SUPPORTS,
DIRECTIONALLY_INVALIDATES, WITHIN_FROZEN_TIME_GAP, WITHIN_SUPPORTING_ATR_PROXIMITY`.

Every accepted transition stores: `transition_rule_id, source_branch_id,
source_event_id, new_event_id, relationships_satisfied, conditions_satisfied,
state_before, state_after`. Every rejected attempt is countable by rejection
reason.

## 6. Frozen transition registry

Transition logic lives in a machine-readable registry, not procedural prose. Each
rule: `transition_id, allowed_source_state, required_event_family,
required_event_subtype_or_state, required_relationships,
allowed_direction_relationship, min_causal_delay, max_causal_delay,
resulting_branch_state, action (advance|fork|resolve|invalidate|emit),
context_condition_limit, expiry_update, candidate_trigger_family`.

The registry expresses a general causal grammar, not a closed list of named
strategies. Required families (implemented as transitions): rejection blocks
(continuation; unresolved→fade only after a real failure event), FVG lifecycle
(formation-close / next-bar / no-fill continuation / first-touch / first-fill /
midpoint / full-fill / revisit / failure / iFVG activation / iFVG immediate /
iFVG retest / re-inversion — immediate and retest never merged), liquidity &
historical levels (sweep→reject→fade, sweep→reclaim→fade, sweep→accept→
continuation, non-sweep break→accept→continuation, break→failed→return-to-range
fade, exact-touch reaction, ordinal revisits), time anchors (reclaim continuation,
rejection fade, break-acceptance, compression, expansion, failed expansion,
return-to-anchor, no-FVG paths), VWAP/bands 1.618/2.618/3.618 (rejection, bounce,
reclaim, break-acceptance, continuation, failed continuation, fade-to-VWAP,
rotation, compression, expansion, false expansion), compression/expansion
(interaction→compression, valid expansion, false-expansion fade, compression→FVG,
compression→level break, unresolved expiry).

## 7. Graph-native candidate materialization

A candidate is emitted only when a branch trigger state contains all of:
1. a causal origin; 2. ≥1 meaningful transition; 3. an explicit trigger event;
4. a frozen direction; 5. an entry known at trigger time; 6. a structural stop
known at trigger time; 7. a structural target known at trigger time; 8. an
expiry; 9. valid RR under the frozen 0.5R–1R policy.

Stored per candidate: `candidate_id, source_branch_id, source_episode_id,
trigger_event_id, exact_graph, reduced_graph, ordered_event_ids,
ordered_transition_ids, relationship_evidence, direction, entry_mode, entry,
structural_stop, structural_target, natural_rr, executed_target, executed_rr,
expiry, causal_feature_vector, availability_timestamp`. The candidate is stored
permanently **before** later bars determine its outcome.

Structural stop/target anchors arise from the branch state (RB/FVG/iFVG
boundaries, swept extreme, confirmed swing, compression boundary, VWAP-band
acceptance-failure, opposing active structure, opposing level/swing/zone, VWAP or
next band, range boundary, branch-specific objective). Generic helpers may be
reused, but the *choice* comes from the branch. Never pick the target that later
happened to work. Frozen RR: `<0.5R` reject; `0.5–<1R` natural; `≥1R` cap to 1R;
never move the stop to qualify.

## 8. Recognizer integration

After graph-native candidates exist, the existing representation and prior-only
evidence engine are reused unchanged. Evidence uses only outcomes completed in
sessions strictly before the candidate's session. The adaptive gate operates on
graph-native candidates. Gate thresholds are **not** tuned in this task. This
task validates architecture and causality; development results are never called
forward evidence or edge.

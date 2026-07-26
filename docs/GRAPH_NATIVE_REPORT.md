# Graph-Native Candidate Engine (v2) — Implementation Report

## Source & branch
* Repository: `dylankazakovas93-dev/discretion-study`
* Source branch: `claude/causal-episode-recognizer-v1`
* Starting SHA: `4e9f93c19231ea6e70f8e685f5dfccd467439f4b`
* New branch: `claude/graph-native-candidate-engine-v2` (pushed from `4e9f93c`)
* PR #1 left open and in draft; new draft PR #2 opened against the v1 branch.

## Commit sequence (no squash, no force-push)
| # | message | SHA |
|---|---|---|
| 1 | docs: freeze graph-native candidate protocol | `166fac7` |
| 2 | feat: structural relationship engine | `3888125` |
| 3 | feat: frozen transition registry | `a5e6646` |
| 4 | feat: multi-branch episode engine | `e24daa9` |
| 5 | feat: graph-native candidate materializer | `0282553` |
| 6 | feat: pipeline cutover + recognizer integration | `b77a3df` |
| 7 | test: v2 setup-path/link/recognizer invariants | `0c1266e` |
| 8 | docs: development audit pack | _this commit_ |

## Tests
`157 passing` before Phase 8 (`PYTHONPATH=src:tests pytest -q`), including the
prior v1 suite (unchanged) plus new relationship / transition / branch-engine /
materializer / graph-pipeline / setup-path suites.

## Data boundaries read
* File `glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst`, window `2025-07-06`→
  `2025-07-11` UTC (July 6–10 CME sessions), front-month **NQU5**, single segment.
* July 2026 not used. No threshold tuning. Development data only; no
  forward-evidence or edge claims.

## The corrected architecture
```
CANONICAL EVENTS -> causal episodes -> multiple concurrent branches
  -> frozen transition registry -> branch trigger state
    -> graph-native candidate (materialized from the branch)
      -> prior-only adaptive evidence -> qualification -> later outcome
```
New modules under `src/discretion/graph/`: `relationships.py` (typed structural
predicates), `transitions.py` (declarative multi-stage hypothesis registry),
`branch_engine.py` (multi-branch episode engine), `materializer.py`
(graph-native candidate materialization), `pipeline.py` (cutover + isolation +
counts), `audit.py`. Docs: `GRAPH_NATIVE_CANDIDATE_PROTOCOL.md`.

**`build_setups(ps)` is no longer the source of candidates.** It is reachable only
through `build_static_baseline_setups(ps)` (diagnostic baseline, separate ledger).
A test monkeypatches `build_setups` to raise and confirms graph-native generation
still completes.

## Files added
```
src/discretion/graph/{relationships,transitions,branch_engine,materializer,
                      pipeline,audit}.py
tests/test_{relationships,transitions,branch_engine,materializer,graph_pipeline,
            v2_setup_paths}.py
docs/{GRAPH_NATIVE_CANDIDATE_PROTOCOL,GRAPH_NATIVE_REPORT}.md
artifacts/graph_native/{candidates_graph_native.csv,audit_pack.md/json,
                        counts.json,reproducibility.json,charts/*.png}
```

## Development-run counts (July 6–10, 2025)
_(from `artifacts/graph_native/counts.json`)_

| concept | count |
|---|---|
| primitive events | 317,066 |
| episodes | 5,018 |
| branches created | 22,566 |
| branches forked | 17,548 |
| branches merged | 0 |
| branches unresolved | 61 |
| branches expired | 627 |
| branches invalidated | 1,297 |
| branches emitted | 20,581 |
| graph-native raw trigger states | 20,581 |
| **graph-native candidates** | **4,506** |
| graph-native rejected (<0.5R) | 16,006 |
| graph-native unformed (no target) | 69 |
| qualified graph-native | 1,491 |
| recorded-not-activated graph-native | 3,015 |
| static baseline candidates (separate) | 4,302 |
| static baseline rejected (separate) | 71,125 |

Branches by continuation/fade: continuation 12,630 / fade 9,936.
Candidates by trigger mode: formation_close 2662, next_bar 268, first_touch 254, first_fill 320, midpoint 289, full_fill 472, retest 241.
Candidates by continuation/fade: continuation 2,383 / fade 2,123.

Candidate ledger SHA-256: `6867c7e80314f806…` (see `reproducibility.json`).

## Ledgers & hashes
* Committed: `candidates_graph_native.csv`, `audit_pack.md/json`, `counts.json`,
  `reproducibility.json`, `charts/*.png`.
* Gitignored (hash + row count in the manifest): `events.jsonl.gz`,
  `branches.csv.gz`, `rejected_graph.csv.gz`.

## Direct answers
1. **Are setup candidates now created by episode branches rather than old setup
   builders?** Yes. `Materializer` consumes only a branch `TriggerState`; it never
   calls `build_setups`. A test disables `build_setups` and generation still works.
2. **Can one event advance multiple compatible branches?** Yes — verified
   (`test_branch_engine`, audit example 18); one event may advance one branch,
   invalidate another and emit on a third.
3. **Can the system express RB tap → bad displacement → compression → later
   failure fade?** Yes — hypothesis `H_rb_unresolved_fade` stays UNRESOLVED through
   the compression and only emits a fade on a real failure event
   (`rb_failure_fade`); audit examples 02 and 03.
4. **Can it express FVG/iFVG formation, fill, no-fill and retest paths?** Yes —
   separate FVG hypotheses per entry mode (formation-close/next-bar/first-touch/
   first-fill/midpoint/full-fill), continuation-without-fill, and iFVG immediate +
   later retest (never merged).
5. **Can it generate a coherent path not manually encoded as a full static
   setup?** Yes — multi-stage compound paths (e.g. RB tap → good displacement →
   FVG-created-by-that-displacement → first-touch fill) are assembled by the graph;
   the static builders contain no such compound recipe. Audit example 20; graph
   and static ledgers are provably disjoint.
6. **Does price proximity alone ever create a causal edge?** No — every edge
   requires an explicit structural relationship (`has_structural_edge`);
   proximity/direction are supporting-only. Rejections are counted; audit example
   19 shows a within-ATR VWAP event rejected from an RB episode.
7. **Does the adaptive gate operate only on graph-native candidates?** Yes — the
   recognizer runs on `result["graph_candidates"]`; the static baseline is never
   fed to it and is counted separately.
8. **Is any result claimed as forward evidence or edge?** No. July 2025 is
   contaminated development data; the gate is not tuned; nothing here is forward
   evidence or an edge claim.

## Known limitations
* The full 5-day recognizer replay is compute-heavy (evidence is O(N²) across
  candidates); tests use narrow windows. Fades outnumber continuations (frequent
  1-minute liquidity sweeps), so the preregistered gate thresholds are mechanical
  placeholders, not a tuned policy.
* Direction for a few level/VWAP triggers is resolved from event state/subtype
  with geometric fallbacks; unusual cases could resolve conservatively.
* `branches_merged` counts equivalent-state index collisions only; spawn-time
  `(hypothesis, origin)` dedup is separate.
* Structural target selection uses the nearest opposing structural level; some
  branch-specific objectives (e.g. measured moves) are not yet target anchors.
* Multi-session persistence for levels is inherited from v1 primitives; the
  branch engine bounds episodes at the CME session by default.
* Some rare paths (rb_reaction, rb_failure_fade, anchor_reclaim, VWAP) are
  generated as trigger states but every occurrence in this window rejects on the
  <0.5R rule, so their audit examples (01, 03, 12, 14, 15, 20) are drawn from the
  rejected ledger — the causal path is demonstrated even though RR filtered that
  specific instance. This is a property of the window/structure, not a missing
  capability.

---

# Blocking-defect corrections (round 2)

The graph-native cutover was accepted; this round fixes four remaining defects.
Starting SHA `588734483ba5156eba90f18718e10c4849433f9e`.

| # | commit | SHA |
|---|---|---|
| 1 | fix: structural relationship integrity (object-bound edges) | `bdf1e29` |
| 2 | fix: real FVG lifecycle branching (genuine no-fill) | `3e29bc5` |
| 3 | fix: preserve FVG failure -> iFVG lineage | `80438e9` |
| 4 | fix: branch-specific stop/target anchors + rerun | _this commit_ |

**Tests:** 179 passing.

## What changed
1. **Relationship integrity.** `RECLAIMS/BREAKS/ACCEPTS/REJECTS_BOUNDARY`,
   `SWEEPS_REFERENCE`, `CLOSES_THROUGH_ZONE`, `EXPANSION_LEAVES_COMPRESSION`,
   `FAILED_EXPANSION_RETURNS_TO_REGION` now require the event to act on the
   branch's actual focus object (same object / parent-child / provenance);
   `DIRECTIONALLY_INVALIDATES` is supporting-only. Each accepted transition stores
   the object it acted on and the structural relationships proven.
2. **Genuine no-fill.** `H_fvg_no_fill_continuation` emits only on a later
   same-direction move ≥1 ATR beyond the FVG boundary after ≥3 bars with no
   intervening touch (invalidated on touch). Bare FVG formation is excluded from
   coherent setups — formation entries require displacement context.
3. **iFVG lineage.** Every iFVG candidate is a child of its parent FVG, seeded
   with the FVG formation + failure event ids; exact graph shows
   `FVG_FORMED → FVG_FAILURE → IFVG_ACTIVATION`; parent id is mandatory.
4. **Branch-specific anchors.** Stop/target are chosen per trigger family from the
   branch's own objects (RB/FVG/iFVG boundary, swept extreme, compression region,
   accepted level, VWAP/band); nearest generic level only as a named fallback.
   Each candidate stores stop/target anchor type, object id, price and rule id.

## Final development-run counts (July 6–10, 2025)
| concept | count |
|---|---|
| primitive events | 317,066 |
| episodes | 5,018 |
| branches created / forked / merged | 22,352 / 18,531 / 0 |
| branches unresolved / expired / invalidated / emitted | 61 / 1,522 / 2,192 / 18,577 |
| graph-native raw trigger states | 18,577 |
| **graph-native candidates** | **6,107** |
| rejected < 0.5R (+few degenerate) | 12,392 |
| unformed (no structural target) | 78 |
| qualified / not-activated | 770 / 5,337 |
| genuine no-fill FVG candidates | 6 |
| parent-linked FVG→iFVG candidates | 786 |
| static baseline (separate ledger) | 4,302 |

Rejected unrelated transitions are counted in `reproducibility.json`
(`rejections`: `no_structural_edge`, `stage_no_match`).

**Stop anchors by family:** fvg_boundary 2,897 · swept_extreme 1,013 ·
ifvg_invalidation_boundary 786 · failed_break_boundary 743 · accepted_boundary
210 · compression_region 9 · anchor_boundary 8 · vwap 7 ·
structural_extreme_fallback 434.
**Target anchors by family:** opposing_liquidity 5,856 · opposing_hist_level 128 ·
opposing_time_anchor 123.

Candidate ledger SHA-256: `3e37b7d462a1323901ba904c96e6c1526b4d45e8dc84e3b10687cbfe85b2c91b`.

Confirmations: categories 4 (immediate formation) and 5 (no-fill continuation) use
different hypotheses and candidate ids; no generic state label alone completes a
branch (every accepted transition carries a structural relationship).

## Direct answers
1. **Can an unrelated BREAK/RECLAIM/FAILURE complete a branch?** No — the event
   must act on the branch's actual focus object; a generic label from an unrelated
   object no longer creates an edge.
2. **Is FVG no-fill continuation a genuine later path?** Yes — a distinct
   hypothesis emitting on a later continuation-away event, invalidated on touch;
   never the formation candidate relabeled.
3. **Does every graph-native iFVG retain its parent FVG failure lineage?** Yes —
   mandatory parent id + formation/failure event ids; exact graph shows the FVG
   failure and iFVG activation.
4. **Are isolated FVG formations excluded from coherent graph-native setups?**
   Yes — formation entries require displacement context; bare FVGs are primitives
   / static baseline only.
5. **Are stops and targets now selected from the branch's structural objects?**
   Yes — a frozen resolver keyed by trigger family; nearest generic level only as a
   named fallback.
6. **Is PR #2 still development infrastructure only, with no edge/forward claim?**
   Yes — development data only, gate untuned, no forward-evidence or edge claim.

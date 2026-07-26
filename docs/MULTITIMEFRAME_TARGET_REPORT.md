# Multi-Timeframe Target Layer — Development Report

Corrects and extends the structural stop/target layer of the accepted
graph-native architecture with a causal multi-timeframe target inventory and a
branch-aware, policy-driven target resolver under a frozen reward-to-risk policy.
**Development (contaminated) data only. No edge or forward claim.**

## SHAs
- Starting HEAD: `2f5c56057f97619f274aaba312847e8e5f3510c9`
- Commit 1 (freeze protocol doc): `6288906`
- Commit 2 (causal 5/15/30/60m aggregation): `d18b06a`
- Commit 3 (prominent-wick liquidity inventory): `60ab6d4`
- Commit 4 (HTF FVG + iFVG target inventory): `4d40629`
- Commit 5 (target-candidate universe + policy resolver): `f506dc8`
- Commit 6 (blocking tests + geometry): `04ec745`; (dev rerun + audit pack +
  report): this commit. Commit 6 landed as two pushes because a mid-run container
  restart forced an early checkpoint of the completed test code; nothing was
  squashed or force-pushed.
- Final SHA: see branch head of `claude/graph-native-candidate-engine-v2`.

## PR
- PR #2 on `dylankazakovas93-dev/discretion-study`, kept **open and draft**. Not
  merged. The static baseline and adaptive recognizer were not tuned.

## Tests
- **238 passed** (full suite). New this task: `test_aggregation` (7),
  `test_wick_liquidity` (10), `test_htf_fvg` (10), `test_targets` (9),
  `test_rr_blocking` (11), `test_target_integration` (12), plus updates to
  `test_anchors` / `test_materializer`.

## Data boundaries
- `2025-07-06T00:00Z .. 2025-07-11T23:59:59Z` (end-exclusive `2025-07-12`), NQU5
  front month. The same contaminated development window. **Not July 2026.**

## HTF aggregation: reused or repaired?
- **Added new.** The canonical `src/discretion/` layer had **no** HTF
  aggregation; the only multi-timeframe code was the legacy, contaminated
  `phase1/recognizer/`, which is not reused. A single canonical aggregation was
  added at `src/discretion/data/aggregation.py`. No third aggregation stack was
  created.

## Files added / changed
Added: `docs/MULTITIMEFRAME_TARGET_PROTOCOL.md`, `docs/MULTITIMEFRAME_TARGET_REPORT.md`,
`src/discretion/data/aggregation.py`, `src/discretion/primitives/wick_liquidity.py`,
`src/discretion/primitives/htf_fvg.py`, `src/discretion/graph/targets.py`,
`src/discretion/graph/mtf_audit.py`, `scripts/run_mtf_audit.py`,
`scripts/run_gate_integration.py`, and the tests listed above.
Changed: `src/discretion/primitives/engine.py` (build inventory into `PrimitiveSet`),
`src/discretion/graph/materializer.py` (per-policy variants + considered ledger),
`src/discretion/graph/anchors.py` (stop always returned; branch objective optional),
`src/discretion/graph/pipeline.py` (ledger target-policy columns),
`src/discretion/setups/model.py` (`STOP_WRONG_SIDE` geometry check),
`src/discretion/recognizer/similarity.py` (target-policy hard-incompatibility +
Gower keys), `src/discretion/events/adapter.py` (skip non-event target objects),
`.gitignore`.

## Counts (development window)
**Completed HTF candles:** 5m 1380, 15m 460, 30m 230, 60m 115.

**Wick-liquidity candidates (by tf/side):** 5m 1276↑/1277↓, 15m 429↑/435↓,
30m 206↑/211↓, 60m 97↑/99↓.
**Wick grades:** HIGH 138, MEDIUM 306, LOW 3586.
**Exposed-zone variants (objects with an exposed zone):** N=3 1239, N=5 967, N=10 642.
**Wick final states:** fresh 56, overlapped 54, swept 48, closed_through 3872.

**HTF FVGs (tf/direction):** 5m 130 bearish/151 bullish, 15m 39/41, 30m 18/20,
60m 6/10 (415 total).
**HTF FVG states:** fresh 6, filled 12, failed 397.
**HTF iFVGs:** 397 total, all 397 parent-linked.

**Target candidates considered (by family, aggregated over unique triggers):**
wick_liquidity 490339, htf_ifvg 422042, htf_fvg 410233, swing 789546,
rejection_block 765716, structure 328956, liquidity 327833, hist_level 244676,
time_anchor 169232, vwap_band 56456, vwap 9090, branch objectives 18953.
**Considered by timeframe:** 5m 880859, 15m 272140, 30m 119910, 60m 49705, plus
1m/session/branch structures.
**Considered targets rejected by reason:** STALE 2551997, WRONG_DIRECTION 1100653,
LOW_PROMINENCE 404750, WRONG_SIDE_OF_ENTRY 10. (Behind-price structures are not
targets and never enter the universe; OVERLAPPED/SWEPT/FILLED/FAILED are folded
into the freshness state that produces STALE. OCCLUDED is recorded per target via
`frontmost`/`occluded_by_object_id`.)

**Targets selected by policy:** NEAREST_VALID_STRUCTURE 12343,
NEAREST_PROMINENT_WICK 11600, NEAREST_OPPOSING_HTF_FVG 9579, BRANCH_SEMANTIC 6861.

**Candidates by target family:** wick_liquidity 11726, htf_fvg 9585,
branch:opposing_liquidity 6564, rejection_block 6139, structure 2365, swing 2027,
vwap_band 843, vwap 448, liquidity 237, branch:opposing_hist_level 155,
branch:opposing_time_anchor 142, hist_level 85, htf_ifvg 49, time_anchor 18.
**Candidates by target timeframe:** 5m 9112, 15m 2388, 30m 3424, 60m 6436,
1m 10871, session 1291, branch(None) 6861.

**RR buckets (executed candidate variants):** below 0.5R rejected 25992;
natural 0.5–<1R (retained) 7899; natural ≥1R (capped to exactly 1R) 32484.
**Graph-native candidates before target-policy variants (unique triggers that
formed ≥1 target):** 16191. **After variants:** 40383.

**Qualification (mechanical integration output only):** the 6-day artifact run is
gate-free; a bounded gate-integration run over 2025-07-07..07-08 flowed 15381
policy-tagged candidates through the prior-only recognizer without error →
RECORDED_NOT_ACTIVATED 14984, QUALIFIED_PENDING_TRIGGER 397 (spread across all
four policies). See `artifacts/mtf_targets/gate_integration.json`. This is not an
edge claim.

## Stop-anchor counts (unchanged branch-specific resolver)
fvg_boundary 14640, swept_extreme 7841, ifvg_invalidation_boundary 6835,
failed_break_boundary 4048, structural_extreme_fallback 3653, accepted_boundary 3174,
compression_region 82, anchor_boundary 49, vwap 23, rb_invalidation_boundary 23,
vwap_band 13, failure_region_boundary 2. Stop placement never depends on target
distance.

## Target-anchor counts by family and timeframe (top)
htf_fvg@5m 8099, wick_liquidity@60m 6391, rejection_block@1m 6139,
wick_liquidity@30m 3405, structure@1m 2365, swing@1m 2027, htf_fvg@15m 1422,
wick_liquidity@5m 968, wick_liquidity@15m 962, vwap_band@session 843,
vwap@session 448, htf_fvg@60m 45, htf_ifvg@5m 45, htf_fvg@30m 19.

## Natural-RR distribution (eligible variants)
min 0.5, p25 1.0, median 4.93, p75 32.4, max 529.5, mean 31.8. All eligible
variants have executed RR in `[0.5, 1.0]` (7899 at 0.5–<1R, 32484 at exactly 1R).

## Rejected below 0.5R / capped to 1R
Rejected `INSUFFICIENT_NATURAL_RR`: 25992. Capped to exactly 1R: 32484.

## Target-selection fallback rate
Generic branch-objective fallback (the BRANCH_SEMANTIC nearest-opposing-level
fallback, i.e. `branch:opposing_*`): 6861 / 40383 = **17.0%**. The other three
policies always select a concrete structural MTF/wick/FVG/level target; they
never fall back to a generic nearest level.

## Ledgers, paths and hashes
- `artifacts/mtf_targets/counts.json` — all counts above (committed).
- `artifacts/mtf_targets/candidates_mtf.csv.gz` — 40383 rows (gitignored),
  sha256 `9b45a7af18bbe481801aa37d7457b92d9a916220fc2f13dfb2bb1098ea2b86a1`.
- `artifacts/mtf_targets/considered_targets.csv.gz` — 4033072 rows (gitignored),
  sha256 `313a79b7994351f74cd5e68485639e7d99e2a8d3b47449e66eed59de0228144b`.
- HTF candle inventory sha256 `7434177089ce78af7add13467e95ba8d77dd28c549d537eebad8b697574fec7b`.
- Wick inventory sha256 `5c8105ffa5be4733130b94034456f21bc182ed5ef35f562fa73d329907102ea3`.
- HTF FVG inventory sha256 `23814f0510f9696124b9e3ed52fb01e14c002eb30c1117a11de2e37be9492e29`.
- `artifacts/mtf_targets/reproducibility.json` — manifest (committed). Reruns
  reproduce identical HTF candles, wick objects, HTF FVGs, considered-target
  ledger and candidate ledger (asserted by `test_target_integration`).

## Audit pack (25 examples, all populated)
`artifacts/mtf_targets/audit_pack.md` (+ `.json`, + `charts/`, 25/25 categories,
chronological, never profit-selected). Each example shows the ids, graph, trigger
timestamp, stop anchor + rule, considered targets with per-target rejection
reasons, the selected target (id/family/tf/surface/policy), natural + executed
RR, outcome shown separately, and a chart with the HTF zone visible.

## Known limitations
- Development (contaminated) window only; nothing here is a forward or edge claim.
- The considered universe keeps the nearest 25 eligible + 25 ineligible per family
  ahead of price. This is proven selection-equivalent to the uncapped universe
  (a farther object is always occluded and never selectable), and bounds cost; the
  gitignored `considered_targets.csv.gz` reflects the capped ledger.
- Target surfaces MIDPOINT/DISTAL_EDGE are frozen research variants exposed on
  every zone object; executable candidates default to PROXIMAL_EDGE. Distinct
  surface variants were not separately materialized in this pass.
- The 6-day artifact run is gate-free for tractability; gate integration is
  demonstrated on a bounded sub-window and by the recognizer test suite.
- Most HTF FVGs in the window ultimately fail/close-through by end-of-window
  (397/415); freshness is always evaluated causally at the trigger seq, so a gap
  that is fresh at a trigger is still a valid target there even if it later fails.

## Direct answers
1. **Does a natural 3R setup remain valid and execute at 1R?** Yes — natural RR is
   retained for diagnostics and the executed target is capped to exactly 1R;
   3R candidates are accepted, not rejected (32484 variants capped to 1R).
2. **Is every setup below natural 0.5R rejected without moving its stop or
   target?** Yes — `INSUFFICIENT_NATURAL_RR` (25992), stop untouched, no farther
   target searched, no later-bar search (`test_rr_blocking`,
   `test_resolver_never_skips_near_low_rr_for_farther`).
3. **Does the target inventory contain fresh prominent 5m/15m/30m/60m wick
   liquidity?** Yes — all four timeframes, upper and lower, graded HIGH/MEDIUM/LOW
   with causal prominence; only MEDIUM/HIGH are default executable targets.
4. **Does it contain fresh 5m/15m/30m/60m FVGs?** Yes — detected independently on
   each HTF via the canonical three-candle definition, with causal lifecycle.
5. **Can an opposing HTF FVG act as a TP because price may react on entry into the
   zone?** Yes — `NEAREST_OPPOSING_HTF_FVG` selected 9579 variants; default
   surface is the proximal edge.
6. **Is the default FVG target the proximal edge rather than assuming full-zone
   traversal?** Yes — PROXIMAL_EDGE is the frozen default; MIDPOINT/DISTAL_EDGE
   are separate named research surfaces, never chosen from outcome.
7. **Are target policies frozen before outcome and represented as separate
   candidates?** Yes — four frozen policies, each a distinct research variant with
   its own `target_policy_id`; the recognizer treats different policies as
   hard-incompatible; outcome is evaluated only after the candidate is stored.
8. **Are stops still tied to actual branch invalidation?** Yes — the
   branch-specific stop resolver is unchanged (FVG/iFVG/RB boundary, swept
   extreme, accepted/anchor/compression/VWAP-band boundary); stop never depends
   on target distance.
9. **Can future structures or outcomes affect target selection?** No — only
   structures with `available_seq <= entry_seq` enter the universe; states are
   stamped from completed 1-minute bars after availability; outcome is separate.
10. **Is this still development infrastructure only, with no edge or forward
    claim?** Yes — contaminated development data only; the gate is run purely to
    confirm integration; no edge is claimed.

# Stage 0 Evidence Lock

## Scope and repository lock

Remote `origin` is `https://github.com/dylankazakovas93-dev/discretion-study.git`. After `git fetch origin`, `origin/claude/graph-native-candidate-engine-v2` resolved to `770f46e739846cdfd34f33e30cb47713994bb716`; the clone was clean before the Stage 0 branch was created. This work is on `codex/ten-am-open-stage0` from that exact commit.

Files inspected included the requested primitives, graph/anchor/target/setup modules, loaders, aggregation, session/VWAP code, tests, README, reports, protocols, artifacts, history, and all five supplied archive manifests/metadata/conditions and CSV schemas. No 10:00 event outcome, return, candidate performance, or final-holdout result was calculated or viewed.

## Verified reusable facts

`RejectionBlock` subclasses `Primitive` (`src/discretion/primitives/rejection_block.py`). Bullish support is `[low, min(open, close)]`, direction `+1`; bearish resistance is `[max(open, close), high]`, direction `-1`. Candidate qualification applies `WICK_TO_BODY=2.0`, `MIN_WICK_ATR=0.4`, and `LOCAL_WINDOW=2`. The implemented local-extreme test reads **only preceding completed bars** in the window (not a centered/future-bar test), so it has no delayed future confirmation.

An RB candidate is created on the candidate bar's completed close (`created_seq=candidate_seq`, `FORMED`). It is confirmed only when a later bar closes beyond the body-edge: bullish `close > hi`, bearish `close < lo`; an unconfirmed candidate fails at three bars after its candidate sequence. Current downstream target inventory exposes RBs from `created_seq`, not confirmation: it stores their availability as `created_seq` and only tests invalidation freshness. Therefore:

| RB timestamp | Implemented state | Stage 1 implication |
| --- | --- | --- |
| formation/candidate | candidate bar close | currently target-visible; not necessarily confirmed |
| confirmation | completed later confirming close | must be used for any “confirmed RB context/target/stop” interpretation |
| first usable setup context | not separately gated; caller decision | define confirmed-only versus candidate-visible explicitly |
| first target usable | `created_seq` in `TargetInventory` | extension needed if project requires confirmed-only targets |
| first stop anchor usable | branch resolver reads an RB origin; no independent confirmation gate | the 10:00 stop rule must require its chosen RB availability |
| invalidation | completed close outside distal wick | `invalidated_seq` is causally queryable |

For a confirmed bullish RB, a wick into the zone (`low <= hi`) produces touch/revisit and may remain active; a close inside the wick surface remains active; only `close < lo` invalidates. Bearish is mirrored: `high >= lo` touches; a close inside remains active; only `close > hi` invalidates. Exact body-edge touches and a close back out create `EXACT_TOUCH`/`REJECTION`. Target freshness is causal: `invalidated_seq is None or invalidated_seq > entry_seq`, rather than mutable end-of-scan `active` state. The same protection exists for HTF FVG/iFVG and wick freshness using timestamped lifecycle fields. Structure objects are a concern: `TargetInventory` reads their mutable `active` flag, so Stage 1 must not use that family without an as-of freshness rule.

`PrimitiveSet` includes RBs, FVGs, iFVGs, HTF FVG/iFVGs, wicks, levels, swings, VWAP and structures. `TargetInventory` includes RB, wick liquidity, HTF FVG/iFVG, swing, session/time-anchor/equal levels, structures, plus point-in-time VWAP/bands. Frozen target policies are `BRANCH_SEMANTIC`, `NEAREST_VALID_STRUCTURE`, `NEAREST_PROMINENT_WICK`, and `NEAREST_OPPOSING_HTF_FVG`. It filters to same-segment, known-at-entry objects, selects nearest eligible structural target, then applies RR. Natural RR is `abs(target-entry)/abs(entry-stop)`; `<0.5R` rejects; `[0.5,1)` retains natural target; `>=1R` keeps natural diagnostics but executes at exactly 1R. Tests explicitly confirm that a nearer sub-0.5R obstruction is not skipped for a farther target.

The setup evaluator is individual-candidate, not an authoritative global portfolio engine. It evaluates bars strictly after `entry_seq`, marks same-bar stop-and-target contact `AMBIGUOUS`, and expires at the frozen sequence. It does not provide order submission/fill queue modelling, a global one-position controller, same-bar re-entry policy, session cutoff, execution costs, or MAE/MFE path accounting. NQ tick is `0.25`; multiplier is not defined in canonical code. Existing stop anchors include RB invalidation boundaries, but the proposed pre-confirmation excursion-extreme stop is not implemented.

## Anchor and timestamp feasibility

`Bar.ts_utc` is explicitly the **bar-open** UTC timestamp and `ts_et` is its DST-aware `America/New_York` conversion; a bar is complete only at `ts_utc + 1 minute`. `build_time_anchors` already recognizes `open_1000`, takes the 10:00 one-minute bar's `open`, but creates the level at that bar's sequence. That is a causality mismatch for this project: the price is observable at 10:00:00, while the current completed-bar engine may only consume an object after that bar completes; Stage 1 must state whether this special anchor is a live opening-price datum available at 10:00:00, while prohibiting its high/low/close/volume until 10:01:00.

The engine converts UTC to New York using pandas timezone conversion, so DST wall-clock matching is supported. Its day/session grouping is ET calendar date for anchors and 18:00 ET reset for VWAP. It has no explicit exchange holiday/early-close calendar; missing anchor bars simply produce no anchor. Archive condition files identify non-available days, but missing/duplicate 10:00 bars must be explicitly excluded and logged in Stage 1. The raw data are genuine Databento `ohlcv-1m`, not reconstructed by this repository. Five-minute aggregation is wall-clock ET; a 10:00–10:04 candle is usable at the first subsequent 1-minute sequence (10:05), after its close. It protects against contract-roll crossing.

## Contamination and gate

Repository documentation/artifacts establish that July 6–10, 2025 was already used as contaminated development/visual-validation data. Phase 1 also contains 2026 exploratory/replay outputs. Neither period can be treated as an untouched final holdout for this project. No final 10:00 holdout is designated or accessed here.

Existing test suite: `python3 -m pytest -q` → 185 passed, 105 skipped, 0 failed, 6.87 seconds. Skips are data-gated because no licensed raw file is staged under `data/raw`. No unrelated failure was found.

## Final gate: PASS

The repository, causal primitive machinery, and 2018–2026 1-minute dataset support a causal Stage 1 specification. Passing Stage 0 does not validate the hypothesis. The required unresolved research choices are isolated in `DECISION_SHEET.md`.

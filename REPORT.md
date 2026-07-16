# Full Setup-Grammar Reset — Deliverables Report

This is the clean architectural reset of the setup-generation layer: a causal
grammar of deterministic primitives that assembles setups as causally coherent
paths (continuation **and** fade) with a frozen 0.5R–1R execution policy.

> **Status of the data.** July 2025 is used strictly as contaminated
> development / visual-validation data. Nothing here is forward evidence, no
> edge is claimed, and no thresholds were tuned against these results.

---

## 1. Branch & commits

| Item | Value |
|---|---|
| Branch | `claude/inspiring-edison-ai71eu` |
| Base of existing work | `39f927d` (Phase 2 replay + review pack) |
| Foundation commit | `36609ae` data layer + causal primitives |
| Setup/tests commit | `f171620` setup constructor, frozen RR policy, dedup, tests |
| Pipeline/review commit | `8863365` |

> **Note on the starting point and existing infrastructure.** My local clone
> was created from `main` (only `README.md`), so the first pass looked like a
> bare repo. The named branch `claude/inspiring-edison-ai71eu`, however, already
> carried the prior project's history: **Phase 1** (`phase1/` — causal contract
> selection, frozen quarterly roll, ATR normalization, primitives, observational
> setups, audit pack) and **Phase 2** (`phase1/recognizer/` — the preregistered
> rolling-recognizer July replay). This new work was **rebased on top of that
> history; nothing under `phase1/` was modified or deleted**, honouring "do not
> delete working infrastructure" and "preserve the contaminated rolling-recognizer
> July results for audit history."
>
> This reset re-implements the causal primitive + setup-generation stack cleanly
> under `src/discretion/` rather than reusing the `phase1/` modules in place —
> a deliberate architectural reset of the setup-generation layer. The two trees
> coexist: `phase1/` is the preserved audit history; `src/discretion/` is the new
> grammar engine. The previous rolling-recognizer July results are retained for
> audit only and are **not** treated as forward evidence here.

## 2. Tests

`57 passed` (`pytest`). Coverage includes: bullish/bearish FVG formation and
every entry-mode state; FVG full-fill and continuation-without-fill; bullish/
bearish iFVG activation, immediate and retest; RB creation/confirmation/revisit/
exact-boundary/invalidation; good/mixed/bad and failed displacement; level
sweep/break/reclaim/acceptance and continuation-without-sweep; time-anchor
construction; VWAP bounce/acceptance/continuation/band-fade/session-reset;
compression→expansion and failed break; confirmed-swing right-edge dating; equal
clusters; the full RR policy (natural RR, cap-to-1R, retain 0.5–1R, reject
<0.5R, no stop manufacture, no target move after outcome); same-bar ambiguity;
episode dedup and distinct-mode separation; ATR/segment causality; no cross-roll
levels; and data-gated whole-pipeline invariants.

## 3. Exact data boundaries read

| | |
|---|---|
| File | `glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst` |
| Requested window | `2025-07-06` → `2025-07-11` UTC (exclusive) |
| First / last bar (UTC) | `2025-07-06 22:00` → `2025-07-10 23:59` |
| Bars | 5,638 |
| Front-month contract | `NQU5` (single segment; no roll inside the window) |

## 4. Files created

```
src/discretion/
  data/      bars.py loader.py atr.py
  primitives/ base.py fvg.py ifvg.py rejection_block.py displacement.py
              levels.py vwap.py structure.py engine.py
  setups/    model.py structural.py builders.py constructor.py
  pipeline/  coverage.py run.py
  review/    charts.py review_pack.py
tests/       12 test modules (helpers.py + test_*.py)
artifacts/   ledgers/, coverage/, charts/, review_pack/, summary.json
```

## 5. Coverage table

`artifacts/coverage/coverage.csv` (+ `.json`) — **102 rows**, one per required
primitive family/subtype/state and per entry/path family, with columns: family,
subtype, implemented, unit_tested, detected_in_dev_history, eligible_as_origin/
transition/trigger, eligible_for_continuation/fade, generated_occurrence_count,
rejection_count, reason_for_zero.

**Every row is implemented, unit-tested, and detected in the dev window — there
are zero empty families.**

## 6. Candidate counts

| | count |
|---|---|
| Raw candidates (pre-dedup) | 77,953 |
| Rejected (RR/other) | 71,091 |
| — of which `INSUFFICIENT_NATURAL_RR` (<0.5R) | 71,043 |
| — `TARGET_WRONG_SIDE` | 47 |
| — `DEGENERATE_STOP` | 1 |
| **Eligible, deduplicated** | **4,290** |

### Counts by origin family (eligible)
liquidity 3,392 · vwap 493 · fvg 153 · rejection_block 74 · ifvg 67 ·
hist_level 42 · displacement 39 · time_anchor 26 · structure 4

### Counts by trigger / entry mode (eligible)
formation_close 3,246 · retest 751 · first_touch 132 · midpoint 100 ·
next_bar 43 · full_fill 18

### Counts by path family (transition class)
fade 3,213 · retracement_continuation 924 · formation_continuation 153

### Continuation vs fade
continuation 1,077 · fade 3,213

### With / without FVG · with / without sweep
with FVG 220 / without 4,070 · with iFVG 67 · with RB 74 ·
with sweep 2,737 / without 1,553

### Natural-RR distribution (executed)
0.5–0.6: 1,553 · 0.6–0.7: 775 · 0.7–0.8: 312 · 0.8–0.9: 304 · 0.9–<1.0: 67 ·
=1.0 (capped): 1,279

| policy bucket | count |
|---|---|
| Capped to exactly 1R | 1,279 |
| Accepted 0.5R–<1R (natural target) | 3,011 |
| Rejected below 0.5R | 71,043 |

All 4,290 executed rewards lie in [0.5R, 1.0R] by construction.

### Outcomes (diagnostic only, shown separately)
WIN 1,836 · LOSS 1,476 · AMBIGUOUS 977 · OPEN 1 — reported for audit, never used
to select or size setups.

> **Honest caveat on balance.** Fades dominate (liquidity-sweep origins are the
> largest single group) because confirmed swings and equal clusters are frequent
> on 1-minute NQ. Unlike the previous prototype this is *not* a narrow generator
> — every family is represented — but the distribution is imbalanced. No
> balancing was applied because the current stage forbids threshold tuning; the
> review pack instead selects one deterministic example per category so variety
> is visible regardless of raw counts.

## 7. Canonical ledgers, charts, review pack

| Artifact | Path |
|---|---|
| Primitives ledger | `artifacts/ledgers/primitives.csv` |
| Raw candidates | `artifacts/ledgers/candidates_raw.csv.gz` |
| Eligible setups | `artifacts/ledgers/setups_eligible.csv` / `.jsonl` |
| Rejected candidates | `artifacts/ledgers/setups_rejected.csv.gz` |
| Coverage table | `artifacts/coverage/coverage.csv` / `.json` |
| Summary counts | `artifacts/summary.json` |
| Charts | `artifacts/charts/*.png` (25) |
| Review pack | `artifacts/review_pack/review_pack.md` / `.json` |

## 8. Direct answers

1. **FVG formation entries without waiting for a fill?** Yes — `formation_close`
   and `next_bar` entries fire at/after the gap becomes knowable
   (`build_fvg_formation`); example `09_fvg_formation_continuation`.
2. **FVG fill and retest entries?** Yes — `first_touch`, `midpoint`, `full_fill`
   (`build_fvg_fill_entries`); example `10_fvg_fill_continuation`.
3. **Immediate iFVG entries and later iFVG retests?** Yes — immediate at the
   activation close/next bar and later retest (`build_ifvg_immediate`,
   `build_ifvg_retest`); examples `11`, `12`.
4. **RB formation and revisit setups?** Yes — confirmed-formation and
   first-revisit (`build_rb_immediate`, `build_rb_revisit`); charts `05`, `06`.
5. **Setups from the listed time anchors?** Yes — all of midnight/Asia/London/
   09:00/09:30/10:00/NY-open/prev-RTH-close are built and interact; anchor-origin
   setups exist (26 eligible); example `13_time_anchor_no_fvg`.
6. **Continuation and fade paths?** Yes — 1,077 continuation and 3,213 fade
   eligible setups; examples `22`, `23`.
7. **Valid setups without FVG, iFVG, RB or a liquidity sweep?** Yes — 4,070
   without FVG, 1,553 without sweep; example `24_no_fvg_no_ifvg` (neither FVG nor
   iFVG) and `25_no_liquidity_sweep`.
8. **All executed targets between 0.5R and 1R?** Yes — enforced by the frozen RR
   policy and verified across all 4,290 eligible setups and in tests.
9. **Which required families produced zero real occurrences, and why?** None —
   every coverage row has a non-zero dev-window count. (The `structure`
   continuation path is thin: only 4 eligible, because most compression breakouts
   reject on the <0.5R rule; the state itself is detected 40× and unit-tested.)
10. **Is the full grammar implemented, or is any portion missing?** The grammar
    is implemented end-to-end: all primitive families, all listed entry modes,
    continuation and fade, structural stops/targets, the 0.5R–1R policy, causal
    dedup, ledgers, charts and the review pack. Not done (correctly out of scope
    for this stage): adaptive grading/expectancy, threshold optimisation, and any
    untouched-forward replay.

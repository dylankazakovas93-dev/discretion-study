# Causal Episode Recognizer v1 — Implementation Report

## Source & branch
* Repository: `dylankazakovas93-dev/discretion-study`
* Starting branch: `claude/inspiring-edison-ai71eu`
* Starting SHA: `198cabf`
* New branch: `claude/causal-episode-recognizer-v1` (pushed from `198cabf`)

## Commit sequence (no squash, no force-push)
| # | message | SHA |
|---|---|---|
| 1 | docs: freeze causal episode graph protocol | `32fb096` |
| 2 | feat: add canonical append-only event schema | `02147ae` |
| 3 | feat: implement causal episode state engine | `1cbd261` |
| 4 | feat: implement branching coherent setup graph | `d198021` |
| 5 | feat: add deterministic setup representations | `6bfd4b0` |
| 6 | feat: add prior-only adaptive evidence engine | `6930854` |
| 7 | test: lock episode and recognizer invariants | `0d63b8f` |
| 8 | docs: add development audit pack | _this commit_ |

## Tests
`110 passing` before Phase 8 (event layer, episodes, branching, representations,
recognizer/evidence/gate, reproducibility). Run: `PYTHONPATH=src:tests pytest -q`.

## Data boundaries read
* File `glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst`, window `2025-07-06`→
  `2025-07-11` UTC (July 6–10 CME sessions), front-month **NQU5**, single segment.
* July 2026 not used. No profitability optimization. Development data only.

## Canonical engine used
`src/discretion/` (primitives, ATR, roll selection, FVG/iFVG/RB/VWAP/levels/
structure and the frozen 0.5R–1R setup RR policy). **No second implementation**
of any of these was created. The episode layer consumes append-only canonical
events derived from them.

## Architecture (new modules)
```
src/discretion/events/        schema.py (CanonicalEvent, EventLog) + adapter.py
src/discretion/episodes/      linking.py, state_machine.py, branches.py
src/discretion/representations/ signatures.py (reduced graph + features)
src/discretion/recognizer/    similarity.py, evidence.py, gate.py, pipeline.py, audit.py
docs/                         EPISODE_PROTOCOL.md, PREREGISTRATION.md, this report
schemas/                      event.schema.json, feature.schema.json
```

Pipeline: `RAW PRIMITIVE EVENTS → ACTIVE CAUSAL EPISODES → BRANCHING PATHS →
COHERENT SETUP CANDIDATES → PRIOR-ONLY EVIDENCE SNAPSHOT → QUALIFIED / NOT`.
The six concepts (primitive event, episode, branch, coherent candidate, qualified
setup, activated trade) are separate objects with separate counts.

## Frozen-rule compliance
Chronological replay; completed candles only; availability = bar close; causal
ATR with current candle excluded from its own normalization; no future pivots /
centered calc; absolute structures never cross a roll (segment ids); permanent
event/episode/branch/candidate ids; same-bar stop/target = AMBIGUOUS; losing /
expired / ambiguous / not-activated cases retained; RR <0.5R rejected, 0.5–<1R
retained, ≥1R capped to 1R; stops never moved to manufacture eligibility; targets
never chosen after the future path is visible; prior-only evidence.

## Development-run counts (July 6–10, 2025)
Separate counts for the six distinct concepts:

| concept | count |
|---|---|
| raw primitive events (`events.jsonl.gz`) | 317,066 |
| active causal episodes (`episodes.csv.gz`) | 44,742 |
| branches created (`branches.csv.gz`) | 4,638 |
| — continuation / fade / unresolved | 1,043 / 3,224 / 371 |
| — merged (identical signatures) | 35 |
| raw setup candidates (pre-dedup) | 78,006 |
| coherent candidates (deduplicated) | 4,302 |
| — with synthetic-episode provenance | 4 |
| rejected setups (<0.5R etc.) | 71,125 |

Coherent candidates by **branch state**: fade 3,224 · continuation 1,078.
By **entry mode (trigger)**: formation_close 3,257 · retest 752 · first_touch 132 ·
midpoint 100 · next_bar 43 · full_fill 18.
**RR policy**: all 4,302 executed RR in [0.5, 1.0]; 1,279 capped to exactly 1R,
3,023 retained at natural 0.5–<1R.

**Qualification (prior-only gate)**: `QUALIFIED_PENDING_TRIGGER` 30 ·
`RECORDED_NOT_ACTIVATED` 4,272. Qualified candidates appear only in later sessions
once prior-session comparables accumulate (sessions 4–8), never in session 0 —
the prior-only property in action.

**Outcomes (diagnostic, shown separately, never feed qualification)**: WIN 1,845 ·
LOSS 1,476 · AMBIGUOUS 980 · OPEN 1.

Candidate ledger SHA-256 (reproducibility): `6f7d3435…` (see manifest).

## Ledgers, schemas, manifest
* Committed: `artifacts/recognizer/candidates_ledger.csv`, `audit_pack.md/json`,
  `charts/*.png`, `reproducibility.json`, `schemas/*.json`, `docs/*`.
* Gitignored (hashes + row counts in the manifest): `events.jsonl.gz`,
  `episodes.csv.gz`, `branches.csv.gz`.

## Scope boundary
This task stops at the recognizer *foundation*: event ledger, episode engine,
branching, coherent candidates, deterministic representations, prior-only evidence
snapshots, qualification-gate mechanics, and the development audit pack. Freezing
the recognizer and sequential untouched-forward testing are a separate later stage.
Gate thresholds are preregistered placeholders verified mechanically on dev data,
not tuned against any forward period.

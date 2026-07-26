# FROZEN MULTI-YEAR VALIDATION PROTOCOL — v1.0.0

Frozen at git HEAD `16957e0233cf9056127a051706fdd8bf9cb1091e`.
Engine combined hash: `17f0b518a2ece9de38cded2644e74dada06100c00270c26ac922f28abe5b1528`
(see `artifacts/multiyear_validation/FROZEN_CONFIG.json` for the per-file SHA-256 list).

**This document is written and committed BEFORE any multi-year outcome is
opened or calculated.** After this file is written the engine is not altered
during the run. If a genuine mechanical defect is found mid-run, the fix,
protocol-version bump, and full invalidation/rerun are logged as a new
protocol version, never as a silent patch to v1.0.0's results.

## Data scope

- **Development / mechanical-audit data:** 2026 (Apr 19 – Jul 17). Used to
  build, visually review, and outcome-check the engine. **Excluded from the
  primary multi-year edge claim.**
- **Locked validation target:** 2018–2025.
- **Locked validation actual:** **2018–2019 only.** The `2020`, `2021-2022`,
  and `2023-2024` raw data files referenced in `data/loader.DATA_FILES` are
  **not present in this environment** — not fabricated, not substituted. This
  is disclosed in `data_manifest.csv` / `data_coverage.json`, not hidden.

## Frozen definitions (unchanged for this run)

| Component | Definition |
|---|---|
| Primitives | Audited `FVGRecord` / `IFVGRecord` / `RBCandidateRecord`; iFVG lifecycle timing (`deactivation_seq/ts/available_seq/active_until_seq`) additive-only, persisted at the exact completed candle causing every existing deactivation path |
| Setup lanes | A (RB), B (FVG), C (iFVG direct), D (iFVG retest), E (RB→new FVG/iFVG), F (confluence) |
| Entry variants | TAP, FIRST_CLOSE_OUTSIDE, MINIMAL_WICK_REJECTION, STRONG_REJECTION, IMMEDIATE_DISPLACEMENT, DELAYED_DISPLACEMENT, COMPRESSION_BREAK, NEW_FVG, NEW_IFVG, IFVG_RETEST |
| Reaction states | TAP_ONLY, CLOSE_BACK_OUTSIDE, MINIMAL_WICK_REJECTION, STRONG_REJECTION_DEPARTURE, IMMEDIATE_DISPLACEMENT, DELAYED_DISPLACEMENT, COMPRESSION_THEN_BREAK, SCRAPING_NO_REACTION, FAILED_REACTION |
| Session boundaries (ET) | GLOBEX_EVENING 18:00–19:59 · ASIA 20:00–02:59 · LONDON 03:00–07:59 · NY_PREMARKET 08:00–09:29 · NY_AM 09:30–11:59 · NY_LUNCH 12:00–12:59 · NY_PM 13:00–16:59 |
| Session identity | True CME session: 18:00:00 ET → 17:59:59 ET next day |
| Timeframe architecture | `TIMEFRAMES=(1,3,5,15,30,60)`; trigger tf ∈ {context_tf, 1} |
| Lookbacks | PREV_1 / PREV_3 / PREV_10 / PREV_20 completed sessions |
| Fingerprint (EXACT) | `playbook.EXACT_FIELDS` — 19 categorical/binned fields |
| Fingerprint (REDUCED) | `playbook.REDUCED_FIELDS` — 13-field family analogue |
| Stop rule | raw structural stop (RB source-wick / FVG-iFVG distal boundary) widened to `effective_stop_distance = max(raw, atr_1m_24)` — never tightened |
| Target rule | `NEAREST_OPPOSING_VALID_STRUCTURE`: genuinely opposing, active, causal, non-component; `target_distance >= atr_5m_24`; no synthetic target; nearer valid blocker never bypassed |
| ATR | Wilder ATR(24), completed candles only; `atr_1m_24` from the last completed 1m candle; `atr_5m_24` from the last completed 5m candle with `available_seq <= trigger` |
| Min target distance | `atr_5m_24` |
| Min stop distance | `atr_1m_24` |
| RR floor | effective natural RR ≥ 0.5 |
| Outcome resolution | next-bar entry; stop-first same-bar ambiguity; `MAX_HOLD_BARS=480` time exit |
| Cost assumptions | gross / 0.50pt round-trip / 1.00pt round-trip, applied uniformly, never altering signal or sizing |

## Frozen research arms (Part F) — no arms added after viewing results

Individual lookback: `L1_EXACT`, `L1_EXACT_PLUS_REDUCED`, `L3_EXACT`,
`L3_EXACT_PLUS_REDUCED`, `L10_EXACT`, `L10_EXACT_PLUS_REDUCED`, `L20_EXACT`,
`L20_EXACT_PLUS_REDUCED`.

Cross-lookback: `ANY_EXACT`, `ANY_EXACT_PLUS_REDUCED`, `MULTI_LOOKBACK_EXACT`
(exact from ≥2 lookbacks), `MULTI_LOOKBACK_ANY` (exact/reduced from ≥2
lookbacks), `ALL_LOOKBACKS` (support from all 4). `SIMILARITY_DIAGNOSTIC`
remains non-executable in every arm.

## Frozen portfolio policies (Part G) — one position at a time

- `POLICY_EARLIEST_ACTIONABLE` — first actionable trigger while flat; ignore
  later signals until flat.
- `POLICY_EXACT_FIRST` — while flat, rank by (1) exact > reduced, (2) more
  supporting lookbacks, (3) higher historical support count, (4) earlier
  trigger, (5) lexical variant ID as final tie-break.
- `POLICY_MULTI_LOOKBACK_SUPPORT` — only setups with ≥2 supporting lookbacks,
  same deterministic ranking on simultaneous triggers.

## Frozen acceptance gates (Part J) — not lowered after viewing results

PF ≥ 2.0 is reported as an aspirational benchmark only. A portfolio policy
passes the **minimum robust-edge gate** only when **all** hold:

1. positive net R after 0.50pt cost
2. PF after 0.50pt cost ≥ 1.20
3. positive in ≥ 75% of fully covered validation years
4. ≥ 200 occupancy-controlled trades overall
5. no single year > 40% of total positive R
6. removing the best 20 trades leaves positive net R
7. finite, fully reported max drawdown
8. 0 causal-invariant violations
9. 0 stale/deactivated target use
10. no rule added after inspecting outcomes

Verdicts: `ROBUST_EDGE_PASS` / `WEAK_EDGE_INCONCLUSIVE` / `NO_EDGE` /
`INVALID_RUN`.

## Amendment log

None. v1.0.0 is the only version used in this run.

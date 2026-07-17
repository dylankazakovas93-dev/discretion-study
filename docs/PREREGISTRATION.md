# Preregistration — Causal Episode Recognizer v1 (frozen constants)

Frozen **before** any untouched-forward replay. These values are for mechanical
verification on **development data only** (July 2025, already contaminated). They
are **not** optimized against any forward period. A later stage will freeze the
recognizer and run sequential forward testing; that stage is out of scope here.

## Data boundaries (this task)
* Development window: `2025-07-06` → `2025-07-11` UTC (July 6–10 sessions), NQ.
* Contract: front-month NQU5 (single segment, no roll inside window).
* July 2026 is **not** used. No profitability optimization is performed.

## Canonical engine
* Primitives/ATR/roll/FVG/iFVG/RB/VWAP/levels: `src/discretion/` (unchanged).
* Detector version string recorded on every event: `src_discretion@v1`.

## Episode engine constants
| name | value | meaning |
|---|---|---|
| `MAX_BRANCH_DEPTH` | 8 | max ordered nodes in a branch path |
| `EPISODE_MAX_AGE_BARS` | 240 | hard cap on episode life (bars) |
| `SESSION_BOUNDARY` | 18:00 ET | CME session reset for intraday episodes |
| `LINK_PROXIMITY_ATR` | 1.5 | max ATR distance for price-connected linkage |
| `LINK_MAX_GAP_BARS` | 120 | max bars between linked events in an episode |

## RR policy (inherited, frozen)
`MIN_RR = 0.5`, `CAP_RR = 1.0`. Reject `<0.5R`; retain `0.5–<1R`; cap `>=1R` to 1R.
Realized R: WIN `= +executed_rr`, LOSS `= -1.0`; AMBIGUOUS/EXPIRED/INCOMPLETE
excluded from R means.

## Shrinkage constant
| name | value |
|---|---|
| `K_SHRINK` | 5.0 |
Tiers: exact ⊂ reduced ⊂ nearest-neighbor(broad) ⊂ global.
`shrink(m, n, p) = w*m + (1-w)*p`, `w = n / (n + K_SHRINK)`, `n = ESS` (unique
resolved sessions).

## Nearest-neighbor similarity
* Distance: **Gower** over mixed features, prior-only min/max & category sets.
* `NN_MAX_DISTANCE` = 0.35 (a neighbor must be at least this close).
* `NN_MAX_NEIGHBORS` = 50.
* Hard categorical constraints (must match): `continuation_or_fade`,
  `trigger_family`, `entry_mode_class` (immediate vs delayed), `origin_family`.

## Lookback horizons (prior completed sessions)
`[1, 3, 5, 10, 20, 40, ALL]`. Recency-weight half-life `RECENCY_HALFLIFE_SESSIONS = 10`.

## Qualification gate (v1 development values)
| field | value |
|---|---|
| `min_effective_sample` | 4 |
| `min_unique_sessions` | 3 |
| `min_shrunk_expected_R` | 0.05 |
| `max_uncertainty` (std-error of R) | 0.60 |
| `required_level_agreement` | exact & reduced shrunk-R both `>= 0` |
| `recency_requirement` | >=1 comparable within last 20 sessions |
| `target_r_breakeven_margin` | 0.0 |

A candidate failing any active field → `RECORDED_NOT_ACTIVATED`. These thresholds
verify gate mechanics on dev data; they are placeholders, not a tuned policy.

## Reproducibility
* Deterministic chronological replay; deterministic IDs; deterministic example
  selection.
* Schemas locked in `schemas/`. Canonical ledger paths, schemas, SHA-256 hashes
  and row counts are committed in `artifacts/recognizer/reproducibility.json`.
* Large generated ledgers/charts may be gitignored; their hashes/row counts are
  committed. A rerun must reproduce identical canonical ledger hashes.

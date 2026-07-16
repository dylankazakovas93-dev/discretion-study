# Phase 2 — Rolling Causal Pattern-Recognizer: Implementation Report

**Observational prototype. No edge is claimed. One July week proves nothing.**

## Provenance
- **Branch:** `claude/inspiring-edison-ai71eu`
- **Starting commit:** `99bf28b` (Phase 1B)
- **Phase 1B correction:** none required — Phase 1B foundations verified (causal ATR excludes current candle; ATR availability stored & precedes candle availability; recognizer feature vector is ATR/dimensionless with no raw-point cross-contract magnitude; post-roll NQU6 structures carried chronologically; examples reconcile to canonical ledgers). Confirmed by `tests.py` (150/150) + `recognizer_tests.py` (42/42).
- **Preregistration commit:** `61be9c2` (`PREREGISTRATION.md` + `prereg.py` + recognizer code, committed before this recorded replay).
- **Final commit:** this commit (replay outputs, review pack, deliverables).

## Data & boundaries
- **Files (SHA-256 verified against delivery manifests):** discovery `1d0aac6…f91cf007`, warm-up `4a56638d…b7dc7cad`, gap-fill `a5778278…6aa54c72`.
- **Timestamps read:** 2025-01-01 18:00 ET → 2026-07-12 19:59 ET (continuous). **Prototype window:** setups instantiated on trigger sessions ≥ 2026-01-01 (earlier data feeds ATR/level/VWAP lookback only).
- **July replay boundary:** 2026-07-06 00:00 → 2026-07-11 00:00 ET (untouched forward demo). Roll NQM6→NQU6 at 2026-06-15 18:00 ET.

## Tests
- `phase1/tests.py` → **150/150**. `recognizer/recognizer_tests.py` → **42/42** (ATR excludes current candle; availability after bar close; no raw-point cross-contract magnitude; absolute structures don't cross the roll; post-roll NQU6 only via chronological state; causal VWAP + 1.618/2.618/3.618 bands + reset; graph ordering & coherence; ≤3 context conditions; dedup; shrinkage; insufficient-evidence; same-1m-bar ambiguity; incomplete excluded from evidence; losers retained; ESS non-decreasing = earlier-sessions-only; outcome cannot enter structural score).

## Counts (bounded window 2026-01→07)
- **Primitive counts (setup TFs):** FVG 5m 1059 / 15m 352; iFVG 5m 1027 / 15m 330.
- **Total admissible setups:** 1363 · **rejected candidates:** ~6.0k · **July admissible:** 342.
- **Graph templates:** 4 reduced-origin families → 12 reduced graphs (`origin|dir|tf`); **963 exact graphs** overall, **244 exact graphs in July**.
- **July prediction-class distribution:** FAVORABLE 318 · NEUTRAL 22 · INSUFFICIENT_EVIDENCE 2 · ADVERSE 0.
- **July outcome distribution:** WIN 196 · LOSS 46 · AMBIGUOUS 54 · EXPIRED 46 · INCOMPLETE 0.
- **July ESS (reduced-family) distribution:** min 7 · median 80 · max 224. `evidence_count` (exact-graph priors) is ~0 for almost all (exact graphs nearly unique).

## Layer 1 vs 2 vs 3 (descriptive only)
| Layer | group | n | completed | fav_rate | mean_R |
|---|---|--:|--:|--:|--:|
| L1 isolated | LIQ_SWEEP | 15 | 10 | 1.00 | 0.67 |
| L1 | VWAP_BAND | 114 | 75 | 0.83 | 0.53 |
| L1 | FVG_FAILURE | 213 | 157 | 0.79 | 0.22 |
| L1 | HIST_LEVEL | 0 | 0 | — | — |
| L2 coherent graphs | all | 342 | 242 | 0.81 | 0.33 |
| L2 | VWAP_BAND\|short\|5m | 31 | 19 | 1.00 | 1.41 |
| L2 | VWAP_BAND\|long\|5m | 37 | 23 | 0.61 | 0.07 |
| L3 recognizer | FAVORABLE | 318 | 225 | 0.81 | 0.34 |
| L3 | NEUTRAL | 22 | 16 | 0.81 | 0.19 |
| L3 | INSUFFICIENT_EVIDENCE | 2 | 1 | 1.00 | 1.48 |
| L3 | ADVERSE | 0 | 0 | — | — |

**New graph candidates:** 229 July exact graphs had **no prior exact-graph evidence** (exact graphs are near-unique; the recognizer therefore predicts from reduced-family priors, not exact). Full list in `setup_occurrences_july.csv` (rows with `exact_n=0`).

## Paths
- Canonical primitive ledgers: `phase1/outputs/ledgers/`. HTF candles: `phase1/outputs/htf_candles_*.csv`.
- Recognizer ledgers: `recognizer/outputs/setup_occurrences_all.csv`, `…_july.csv`, `july_occurrences_full.json`, `levels.csv`, `vwap_1m_july.csv`, `layer_comparison.json`, `replay_summary.json`.
- Charts: `recognizer/outputs/charts/`. Review pack: `recognizer/outputs/REVIEW_PACK.md`. Preregistration: `recognizer/PREREGISTRATION.md`.

---

## Plain-English answers

**1. What kinds of coherent setup paths actually appeared?**
`ORIGIN → displacement → same-direction FVG → retest-fill`, from four origin families: **FVG_FAILURE (iFVG)** (213, most common), **VWAP_BAND rejection** (114), **LIQ_SWEEP** (15), and **HIST_LEVEL** (0 in July). Across 5m/15m and both directions = 12 reduced graphs. No single primitive was universal; most July paths started from an iFVG activation or a VWAP-band rejection rather than a liquidity sweep.

**2. Which paths had favorable prior evidence before appearing in July?**
At the reduced-family level (the class with real sample size), essentially all had prior favorable rates > 0.55, so 318/342 were classed FAVORABLE. Highest prior families were the LIQ_SWEEP and short-side VWAP_BAND graphs. At the **exact-graph** level almost nothing had prior evidence (ESS_exact ≈ 0), so predictions leaned on family priors.

**3. Which visually/structurally strong paths had weak historical evidence?**
Two July setups were INSUFFICIENT_EVIDENCE (thin reduced family, e.g. a 15m LIQ_SWEEP short) despite reasonable structural scores — structural strength did **not** buy evidence. Broadly, every exact graph (229 of them) was structurally instantiated yet had zero exact-graph history.

**4. Did any favorable predicted setup fail?**
Yes — **43** FAVORABLE setups ended in LOSS (plus 42 EXPIRED, 51 AMBIGUOUS). FAVORABLE is a prior, not a promise. Example in the review pack.

**5. Did any adverse or weakly-predicted setup win?**
No ADVERSE class occurred this week (no family had an adverse prior). Of the weaker **NEUTRAL** class, **13** won. Example in the review pack.

**6. Did VWAP, 1.618/2.618/3.618 bands participate materially?**
Yes. **114** July setups originated at a VWAP band rejection, and **81** had their nearest band at exactly **1.618 / 2.618 / 3.618**. VWAP-band graphs were the second-largest family and included both the best (short 5m, fav 1.00) and weakest (long 5m, fav 0.61) reduced graphs.

**7. Did the rolling recognizer add descriptive separation beyond isolated concepts and structural quality?**
**Not materially, this week.** Layer-3 FAVORABLE (fav 0.81) and NEUTRAL (fav 0.81) were indistinguishable in favorable rate; both tracked the ~0.81 base rate. Layer-2 reduced graphs showed more spread (0.61 → 1.00) than Layer-3 classes did. So in this bounded window the family/graph structure (Layer 2) carried more visible dispersion than the recognizer's confidence label (Layer 3).

**8. What cannot yet be concluded?**
Everything about edge. The base favorable rate is inflated by close structural targets (median target ≈ 0.5R), so a high win rate does not imply positive expectancy at size; ambiguous/expired outcomes are ~29% of setups; ADVERSE never triggered; exact-graph evidence is essentially empty; and one 5-session forward window cannot separate skill from base rate or estimate variance. Whether Layer 3 carries predictive information beyond Layers 1–2 is **undetermined** and requires far more (properly out-of-sample, non-overlapping) history — explicitly out of scope here.

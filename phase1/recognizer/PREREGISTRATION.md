# PREREGISTRATION — Rolling Causal Pattern-Recognizer Prototype

**Setup-definition version:** `cg-recognizer-v1.0.0`
**Frozen constants:** `recognizer/prereg.py` (authoritative; this prose mirrors it).
**Committed BEFORE any July outcome is exposed to the recognizer.** No definition, bin, threshold, shrinkage parameter, target/stop/expiry rule, or classification cutoff below may be changed or tuned on July data. July 6–10 2026 is an untouched forward-demonstration period.

## 0. Separated fields (never conflated)
`structural_score` · `learned_expected_R` · `learned_favorable_probability` · `evidence_count`/`effective_sample_size` · `uncertainty` · `final_predicted_class` · `realized_outcome`. The realized outcome of a setup is **never** used to define, grade, select, repair, or explain that same setup.

## 1. Data & causality
NQ GLBX.MDP3 1-minute OHLCV. Continuous series = warm-up (2025-01-01→2026-06-07) + gap-fill (2026-06-08→2026-07-05) + discovery (2026-07-06→2026-07-12). Deterministic quarterly roll **NQM6→NQU6 at 2026-06-15 18:00 ET**. Absolute structures reset at the roll; only dimensionless/ATR-normalized quantities cross contracts. All features usable only after the contributing bar closes.

## 2. Primitive ontology (built on existing frozen ledgers)
- Existing: FVG, iFVG, rejection-block, displacement, liquidity, permanent IDs, ATR14 (causal, current-candle-excluded, availability stored).
- Added here: **causal NY-session VWAP** (reset 09:30 ET) with weighted-deviation bands **±1, ±1.618, ±2, ±2.618, ±3, ±3.618** (1.618/2.618/3.618 required); values usable only after the bar closes.
- **Historical levels** (per absolute segment, per session, with availability/age/sweep): prev-RTH H/L, overnight H/L, prev-day H/L, prior-3/5/10/20-session H/L, and the 09:00/09:30/10:00 ET candle H/L. Families: `LIQ_SWEEP` (session/intraday liquidity) and `HIST_LEVEL` (multi-session structure).
- **Time anchors:** midnight, Asia, London, 09:00, 09:30/NY, 10:00, RTH.

## 3. Setup-graph grammar
A setup is a causally ordered path. **Every admissible setup contains** exactly: (1) one contextual origin/active state; (2) one measurable directional transition (**displacement is mandatory**); (3) one primary entry trigger; (4) one structural invalidation; (5) one target or expiry. At most **3** entry-context conditions. No single primitive is universally required (a setup need not start with liquidity/FVG/rejection/VWAP/time). Admitted origin families: `LIQ_SWEEP`, `HIST_LEVEL`, `VWAP_BAND` (band rejection), `FVG_FAILURE` (iFVG activation).

**Rejected:** isolated FVG with no causal path; unrelated nearby labels; setups requiring future bars to exist; duplicated episodes (see dedup); graphs assembled only because they won.

**Three representations (stored permanently before outcome):**
1. Exact graph — origin family + specific origin source + direction + tf, e.g. `LIQ_SWEEP(overnight_high)|short|5m->DISP->FVG_bear->FILL` (very specific, usually sparse).
2. Reduced graph (operating similarity class) — `ORIGIN_{family}|{direction}|{tf}->DISPLACEMENT->FVG_RETEST` (16 combos).
3. Broad family — `{origin_family}|{direction}` (8). Global = ALL.
4. Frozen feature vector — dimensionless only: direction, session, origin family, time anchor, displacement/ATR, path efficiency, FVG width/ATR, VWAP side, nearest VWAP band + distance/ATR, level family, target distance in R, opposing distance/ATR, volatility bucket, risk/ATR. **No raw-point cross-contract magnitude, no LLM embedding.**

**Dedup:** one interaction episode = `(tf, origin_object_id, trigger_object_id)`; keep earliest trigger; later duplicates rejected.
**Timeframes:** 5m, 15m. Reversal window R=5 bars.

## 4. Structural score (0–100; OUTCOME contributes ZERO)
Weighted components (weights in `prereg.py`): context coherence 20, trigger clarity 15, **displacement quality 25**, freshness 10, invalidation clarity 10, target room 15, minus contradiction penalty 5. Components stored separately. Highest structural score is **not** called high-probability unless prior evidence supports it.

## 5. Entry / stop / target / expiry (frozen before forward bars)
- **Entry:** trigger FVG proximal boundary (short = lower, long = upper).
- **Structural stop (hierarchy):** trigger FVG far boundary → origin swept extreme → confirmed swing → ATR buffer. (Primary: trigger FVG far boundary.)
- **Structural target (hierarchy):** nearest opposing unswept historical level → opposing FVG/iFVG/rejection → VWAP → next VWAP band → opposing range side → **fixed 2R fallback only when no structural target exists**.
- **Expiry:** entry must fill within **E=20** tf-bars of trigger availability, else EXPIRED. Outcome resolved within **H=120** one-minute bars after fill, else INCOMPLETE.

## 6. Outcome (observed only; never feeds score/selection)
On 1-minute bars: first bar touching target → **WIN** (realized R = target distance in R); first touching stop → **LOSS** (R = −1); **same 1-minute bar spanning both → AMBIGUOUS** (intrabar order not inferred); no fill by expiry → **EXPIRED**; unresolved by horizon → **INCOMPLETE**. Only WIN/LOSS are completed evidence. Record MFE/MAE in R, times to target/invalidation, full path validity.

## 7. Rolling prior-evidence engine
For each occurrence, evidence uses ONLY completed occurrences from **strictly earlier trading sessions** (globex-day session unit; current-session outcomes excluded). Diagnostic horizons **1/3/5/10/20/all** completed sessions are reported but **NOT summed** as independent samples (they overlap).

**Hierarchical empirical-Bayes shrinkage** (pseudo-counts frozen): exact graph → reduced family (K=10) → broad family (K=20) → global prior (K=40). `w = n/(n+K)`; estimate = `w·child + (1−w)·parent`, applied to both favorable-probability and expected-R; global prior falls back to p=0.5, R=0 when empty. Sparse exact evidence shrinks strongly to its parent. `evidence_count` = completed EXACT-graph priors; `effective_sample_size` (ESS) = completed REDUCED-family priors (the class that actually drives the estimate and the classification gate). Stored: prior mean, exact/reduced/broad contributions, ESS, shrunk expected R, shrunk favorable probability, uncertainty half-width. A single recent winner cannot produce high confidence.

## 8. Predicted classification (frozen thresholds)
`INSUFFICIENT_EVIDENCE` if ESS < 8. Else `FAVORABLE` if shrunk favorable prob ≥ 0.55 **and** shrunk expected R ≥ 0.10; `ADVERSE` if shrunk prob ≤ 0.45 **or** shrunk expected R ≤ −0.10; else `NEUTRAL`. Structural strength alone never yields FAVORABLE. Structurally strong setups may be INSUFFICIENT_EVIDENCE or ADVERSE.

## 9. July replay protocol
Build prior ledger from pre-July history; replay July chronologically. For each admissible July setup: instantiate under the frozen grammar, **store before outcome**, compute structural score, attach only prior-session evidence, **freeze prediction**, then evaluate outcome. Keep all winners, losers, ambiguous, expired, incomplete. No setup edited after trigger; no loser removed; no July bar alters any definition, bin, shrinkage, or threshold.

## 10. Layer comparison (descriptive only)
Layer 1 = isolated concept interactions (by origin family). Layer 2 = coherent structural graphs (structural quality). Layer 3 = coherent graphs scored by prior completed history. Hypothesis: Layer 3 *may* carry more predictive information — **not to be claimed from one July week**.

## 11. Review-pack example selection (deterministic)
Frozen rules select: one valid rejection block, one good & one bad displacement (by displacement/ATR extremes among valid), one valid FVG, one valid iFVG, one FAVORABLE and one ADVERSE/INSUFFICIENT_EVIDENCE July setup; plus (if present) a FAVORABLE-that-lost, a weak/ADVERSE-that-won, a structurally-strong-but-insufficient-evidence, and a genuinely new graph candidate. No manual aesthetic choice.

## 11b. Development-disclosure
A pipeline dry-run during development surfaced the *aggregate* July outcome mix and a structural flaw (an exact-graph ESS gate marked every setup INSUFFICIENT). In response only the **similarity granularity and ESS definition** were finalized (reduced family = `origin|direction|tf`; ESS = reduced-family completed priors) — a structural/methodological choice. **No numeric threshold** (`FAVORABLE_PROB`, `FAVORABLE_R`, `ADVERSE_*`, `MIN_ESS`, shrinkage K's) was changed in response to July, and no per-setup outcome-conditioned tuning was performed. All thresholds in `prereg.py` are a-priori. This file and `prereg.py` are committed before the recorded replay.

## 12. Deferred (documented, not silently omitted)
Equal-high/low clusters, confirmed-swing pivots, compression/expansion/acceptance as separately-labeled discrete states, ES cross-market confirmation, and repeated-retest counters are **not** frozen in v1.0.0 and are not used by the recognizer; they remain future work. Their absence does not affect any committed definition above.

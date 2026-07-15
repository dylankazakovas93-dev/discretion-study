# Phase 1 — NQ 1-Minute OHLCV Primitive-Definition & Implementation Audit

**Parameter version:** `phase1-v1.0.0`
**Instrument:** NQ front-month outright — `NQU6`, `instrument_id 42004177` (selected by total traded volume)
**Scope:** Primitive definition + implementation audit only. **No setups discovered, no trades evaluated, no profitability computed, no entries/stops/targets, no outcome-based classification.**

All numbers below were produced by executing code against the attached dataset (every row inspected). Nothing is visually estimated. Reproduce with:

```
python3 core.py  <decompressed.csv> <original.csv.zst>   # audit + HTF ledgers
python3 run.py    <decompressed.csv> <original.csv.zst>   # all primitive ledgers
python3 charts.py                                         # deterministic audit examples + charts
```

---

## 0. WARM-UP STATUS (resolved) + SEAM CAVEAT (read first)

The warm-up requirement — **≥ 40 completed sessions before 2026-07-06** — is now **MET**. A second file (`nq2025.zip` → `glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst`, SHA-256 verified against its manifest) supplies **371 Globex sessions** (2025-01-01 → 2026-06-07).

| Requirement | Delivered |
|---|---|
| ≥ 40 sessions before Jul 6 | **371 sessions** ✅ |
| Discovery week Jul 6–10 | ✅ present and complete |
| Combined series | 511,567 one-minute bars (warm-up + discovery) |

**Contract handling.** Across 2025–26 the front month rolls quarterly (NQH5→NQM5→NQU5→NQZ5→NQH6→NQM6; 6 roll dates). The warm-up is stitched into a **continuous front-month series** by choosing, per UTC day, the outright with the greatest volume. The series is **unadjusted** (raw roll steps). The discovery week is pure **NQU6**.

**Seam caveat.** The warm-up ends **2026-06-07 (NQM6)** and the discovery series begins **2026-07-05 20:00 ET (NQU6)** — a seam carrying both a **~28-day calendar gap** and a **contract change**. To keep this sound, the warm-up is used **only for relative trailing size percentiles**; **structural detection (FVG triples, iFVG conversions, liquidity sweeps, invalidations) is confined to the post-seam discovery series** so no June NQM6 structure spuriously interacts with July NQU6 prices across the gap.

**Effect of adding warm-up:**

1. **Trailing percentiles (N = 10/20/40)** are now **fully populated — 0 null across all 17,302 rejection-block rows and all 51,894 displacement legs** (previously null on higher timeframes for lack of history).
2. Discovery-week **structure counts are unchanged** vs. the warm-up-free run (e.g. `fvg_1m` = 1136), confirming warm-up affected only relative statistics, not what was detected.
3. **Still open:** the first daily (Globex) candle of the discovery week (ending 2026-07-06) is missing its first two hours (18:00–20:00 ET Sun Jul 5), so it is flagged incomplete; and a **contiguous** "previous completed RTH" for Jul 6 morning still does not exist (June RTH is stale across the seam) — the first usable previous-RTH remains Jul 6's own, used from Jul 7.

---

## 1. Data-Quality Report

Full machine version: `outputs/data_quality_report.json`.

| Field | Value |
|---|---|
| Columns | `ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol` |
| Timestamp timezone (source) | **UTC** (`ts_event`, ISO-8601 `Z`) |
| Timestamp marks | **bar OPENING** (interval start); Databento `ohlcv-1m` convention. Availability = open + 1 min |
| Converted timezone | **America/New_York** (DST-aware; sample is entirely EDT / UTC−4) |
| First / last (UTC) | 2026-07-06 00:00 → 2026-07-12 23:59 |
| First / last (ET) | 2026-07-05 20:00 → 2026-07-12 19:59 |
| Raw rows | 9,057 (3 symbols: `NQU6`, `NQZ6`, spread `NQU6-NQZ6`) |
| Selected-instrument rows | 6,900 (`NQU6`) |
| Duplicate timestamps (selected) | **0** |
| Missing intervals vs full 1-min grid | 3,180 → **420 maintenance** (7×60) + **2,940 weekend** (Fri 17:00→Sun 18:00) + **0 unexplained** |
| Malformed / NaN OHLCV rows | **0** |
| Nonpositive volume | **0** |
| `high < max(open, close)` | **0** |
| `low > min(open, close)` | **0** |
| `high < low` | **0** |

**No data was silently repaired.** The raw CSV was preserved; the multi-symbol structure was resolved by selecting the highest-volume outright and excluding the calendar spread.

**Instrument selection:** `NQU6` 2,445,469 vol vs `NQZ6` 4,500 vol (outrights); `NQU6-NQZ6` (1,522) is a spread and excluded from the study instrument.

**Warm-up file** (`glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst`): SHA-256 `4a56638d…7dc7cad` — **matches** its manifest ✅. Range 2025-01-01 → 2026-06-07 UTC; continuous front-month series 200,941 bars after per-day volume roll; 371 Globex sessions; 6 contract rolls (see manifest `warmup.roll_dates`). Same `GLBX.MDP3 / ohlcv-1m / NQ.FUT` query as discovery.

---

## 2. Time Conventions Applied

* Globex trading day: **18:00 ET → 17:00 ET** next calendar day.
* Overnight: **18:00–09:29 ET**; RTH: **09:30–16:00 ET**; maintenance **17:00–18:00 ET** (no synthetic bars).
* HTF fixed ET clock boundaries — 5m `min%5==0`, 15m `min%15==0`, 30m `{00,30}`, 1h clock hour, 4h `{00,04,08,12,16,20}`, daily = one Globex day.
* A HTF candle becomes **available only when its full interval has ended** (`availability_et = bucket_close_et`).

Combined series: 511,567 one-minute bars. Discovery-week (Jul 6–10) completed-candle counts: 1m 6540 · 5m 1308 · 15m 436 · 30m 218 · 1h 109 · 4h 29 · daily 4.

---

## 3. Complete Machine-Readable Primitive Ledgers

Discovery-week emission window: availability in `[2026-07-06 00:00 ET, 2026-07-11 00:00 ET)`. Every record carries `instrument, tf, source timestamp(s), availability_et, boundaries, later state-change timestamps, param_version`.

Files in `outputs/ledgers/`. **CSV is canonical** for every ledger; a JSON mirror is also written for compact ledgers (≤ 5000 rows) to avoid multi-MB duplicates of the large 1m/5m ledgers. Row counts (discovery week):

| Primitive | 1m | 5m | 15m | 30m | 1h | 4h | daily |
|---|--:|--:|--:|--:|--:|--:|--:|
| FVG | 1136 | 274 | 90 | 40 | 22 | 5 | 2 |
| iFVG conversions | 1103 | 254 | 81 | 34 | 19 | 2 | 1 |
| Rejection-block candidates | 13082 | 2618 | 874 | 438 | 220 | 60 | 10 |
| Displacement legs | 39246 | 7854 | 2622 | 1314 | 660 | 174 | 24 |

**Liquidity references:** `outputs/ledgers/liquidity_references.csv` — 50 records across 10 source types (prev-RTH high/low, overnight high/low, 09:00/09:30/10:00 one-minute high/low). Each has extreme, availability, first exact touch, first wick passage, sweep timestamp, unswept flag. (Under OHLCV-only rules, first wick passage and sweep coincide — both = first strict penetration; recorded in separate columns for auditability.)

These are **complete ledgers, not selected examples.**

---

## 4. Deterministic Human-Audit Examples

37 examples with annotated charts in `outputs/charts/`; machine index in `outputs/examples/audit_examples.json`. Every one is selected chronologically or by a **structural** rank metric — **none** by subsequent profitability.

* **First bullish / bearish FVG on each timeframe** — `fvg_<tf>_<dir>.png` (14 charts).
  Verified example — first 1m bullish FVG `FVG-1m-bull-20260706T0005`: A(00:03) high 29725.0 < C(00:05) low 29732.5, B(00:04) bullish, body-containment holds; zone [29725.0, 29732.5]; available 00:06 ET; first wick entry 00:07; full fill 00:10.
* **First FVG→iFVG conversion each direction** — `ifvg_bull.png`, `ifvg_bear.png`. Bull example: bearish source `FVG-1m-bear-20260705T2342` converts when a later candle **closes** 29785.5 above the upper boundary at 00:17 ET (a warm-up structure maintained into the discovery week — exactly the pre-existing-structure case).
* **First swept + first still-unswept liquidity reference per source type** — `liq_<source>_<swept|unswept>.png`.
* **Three highest-ranked *valid* rejection-block candidates on three different timeframes** — `rejblock_top1_5m.png`, `rejblock_top2_1m.png`, `rejblock_top3_daily.png` (provisional display rank = directional-wick/range ratio among never-invalidated candidates; **not** a frozen threshold).
* **First rejection-block invalidated by body overlap** — `rejblock_first_bodyoverlap.png`.
* **First invalidated by complete wick traversal beyond far boundary** — `rejblock_first_traversal.png`.
* **High / middle / low displacement examples** — `disp_high.png`, `disp_middle.png`, `disp_low.png` (provisional structural score = path-efficiency × proportion-aligned × prev-20 body percentile; no outcome optimization).

---

## 5. Cases the Implementation Could Not Classify Without Additional Rules

1. **Warm-up percentiles — RESOLVED.** With the warm-up file, all `prev10/20/40` percentiles are now computable and fully populated (0 null). The only residual is philosophical: the trailing window for the very first discovery bars reaches across the seam (gap + contract change); because these are *relative size* measures this is acceptable, and it is documented rather than hidden.
2. **First daily candle completeness.** The Globex day ending Jul 6 is missing 18:00–20:00 ET. Emitted but flagged incomplete; whether an incomplete HTF candle should participate in FVG/displacement detection is a definitional choice (currently: it participates, flagged).
3. **First-RTH liquidity reference.** No *contiguous* "previous RTH" exists for Jul 6 (June RTH is stale across the 28-day seam); that reference is absent, not imputed. First usable previous-RTH is Jul 6's own.
4. **Wick-passage vs sweep under OHLCV.** Bar ordering inside a minute is unknown, so "first wick passage" and "sweep" cannot be distinguished from OHLCV alone; they are recorded as coincident. A tick/quote feed would be needed to separate them.
5. **Zero-body candles (dojis) in ratio denominators.** `dwick/body` is `null` when body = 0 (division guarded), rather than assigned ∞.

---

## 6. Unresolved Definition Decisions (for human freeze)

1. **Warm-up seam handling** — *(resolved for statistics; one decision remains.)* Warm-up now supplies 371 sessions, but it ends Jun 7 on NQM6 while discovery is NQU6, with a 28-day gap between. Current policy: warm-up feeds only relative trailing percentiles; structural continuity does not cross the seam. Confirm this policy, and confirm the unadjusted (raw-roll) continuous-contract choice vs. a back-adjusted series. Ideally the warm-up would be extended to be contiguous through Jul 5 on NQU6.
2. **Rejection-block "prominence" threshold** — deliberately **not** frozen. Candidates are ranked, not certified. Needs a human-frozen percentile/ratio cutoff.
3. **Displacement classification threshold** — raw measurements preserved; no single label assigned. Needs human freeze.
4. **FVG "full fill" vs "invalidation" semantics** — currently invalidation = full fill (gap fully retraced). If partial mitigation should invalidate, redefine.
5. **iFVG re-conversion** — currently a single conversion event is recorded per FVG. Whether an iFVG can revert/re-convert on subsequent closes is unspecified.
6. **"Consecutive candles" across session gaps** — FVGs use consecutive *ledger* candles regardless of weekend/maintenance calendar gaps. Confirm this is desired for HTFs spanning a break.
7. **Rejection-block direction per candle** — every candle yields both a bullish (lower-wick) and bearish (upper-wick) candidate. Confirm both should always be emitted.
8. **4h anchor** — anchored to midnight ET (00,04,08,12,16,20). Confirm vs a Globex-open (18:00) anchor.
9. **Displacement leg direction enumeration** — both directions computed for every window/length. Confirm vs. intrinsic-direction-only.
10. **Liquidity sweep equality** — exact touch excluded from sweep (per spec); confirm the same for the daily/HTF-derived levels.

---

## 7. Reproducibility Manifest

Full machine version: `outputs/reproducibility_manifest.json`.

* **Discovery file SHA-256:** `1d0aac62…f91cf007` — **matches** its delivery manifest ✅
* **Warm-up file SHA-256:** `4a56638d…b7dc7cad` — **matches** its delivery manifest ✅
* **Param version:** `phase1-v1.0.0`
* **Code SHA-256:** `core.py`, `primitives.py`, `run.py`, `charts.py` (hashes in manifest).
* **Environment:** Python 3.11.15 · pandas 3.0.3 · numpy 2.4.6 · Linux.
* **Reproduce:** `python3 run.py data.csv <discovery.zst> warmup.csv <warmup.zst> && python3 charts.py`
* **Timezone rules / session definitions / HTF boundaries / causality rules:** as in §2 and the manifest.
* **Determinism:** no randomness, no seeds; identical inputs → identical outputs.

---

**Phase 1 stops here.** No setup discovery, no profitability inspection, no primitive-combination analysis was performed.

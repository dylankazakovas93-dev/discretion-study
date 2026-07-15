# Phase 1 — NQ 1-Minute OHLCV Primitive-Definition & Implementation Audit

**Parameter version:** `phase1-v1.0.0`
**Instrument:** NQ front-month; discovery week = **NQU6**; warm-up = continuous front-month via **causal** (previous-session) volume roll.
**Scope:** Primitive definition + implementation audit only. **No setup discovery, no trade evaluation, no profitability, no selection/grading.**

All numbers were produced by executing code against the two attached datasets (every row inspected). Reproduce:

```
python3 run.py  data.csv <discovery.zst>  warmup.csv <warmup.zst>
python3 charts.py
python3 tests.py        # 114/114 invariant checks
```

---

## 0. CAUSAL STATUS — warm-up is NOT "fully resolved" for setup discovery

Two causal defects from the prior revision have been corrected, and one over-claim retracted.

**(1) Contract selection is now causal.** The front-month contract for session *S* is decided from the **previous completed session *S-1*'s** outright volume, frozen at *S-1*'s close (17:00 ET, one hour before *S* opens). The current session never participates in its own decision — eliminating the intra-session volume look-ahead. Every decision is stored in `roll_decisions.csv` (selected contract, evidence session, decision timestamp, selected + competing volumes). Causal roll dates:

| Session | Selected | Evidence session | Bootstrap |
|---|---|---|---|
| 2025-01-02 | NQH5 | — | yes (data start) |
| 2025-03-19 | NQM5 | 2025-03-18 | no |
| 2025-06-17 | NQU5 | 2025-06-16 | no |
| 2025-09-17 | NQZ5 | 2025-09-16 | no |
| 2025-12-16 | NQH6 | 2025-12-15 | no |
| 2026-03-17 | NQM6 | 2026-03-16 | no |
| **2026-07-06** | **NQU6** | 2026-06-08 | **yes (seam; prior winner NQM6 expired)** |

Only two disclosed bootstraps exist (data start, and the post-seam session where the previous session's winner had expired across the gap).

**(2) Explicit continuity segments.** A new segment begins after every contract roll, after the seam, and after any non-calendar data gap > 60 min (sub-60-min single no-trade minutes are logged as minor illiquidity, not breaks). **26 segments** total (`continuity_segments.csv`). **No HTF candle spans a segment boundary** (grouped per `(bucket, segment_id)`; a split bucket is marked `spans_segment_boundary` + `complete=False` and excluded from normalization). The **discovery week is one clean segment (id 25, NQU6, 6900 bars, 0 minor gaps)**.

**(3) Retraction.** The warm-up requirement is **NOT** fully resolved merely because ≥40 older sessions exist. Under per-segment continuity, a trailing 10/20/40 statistic requires that many **complete predecessors in the same segment**; the warm-up (segments 0–24, ending on NQM6) is **never** an immediate predecessor of July across the **28-day seam** (last pre-seam bar 2026-06-07 19:59 ET → first discovery bar 2026-07-05 20:00 ET). Consequently the July features have the validity below.

### Trailing-feature validity in the discovery week (`trailing_validity_table.csv`)

| tf | N=10 | N=20 | N=40 |
|---|---|---|---|
| 1m | ✅ all valid | ✅ | ✅ |
| 5m | ✅ | ✅ | ✅ |
| 15m | ✅ | 5 null → valid 07-06 01:15 | 25 null → valid 07-06 06:15 |
| 30m | 3 null → 01:30 | 13 null → 06:30 | 33 null → 16:30 |
| 1h | 7 null → 07-06 07:00 | 17 null → 07-06 17:00 | 37 null → 07-07 14:00 |
| 4h | 11 null → 07-07 20:00 | 23 null → 07-09 20:00 | **all 30 null — never valid in July** |
| daily | **all null** | **all null** | **all null** |

Nulls are written explicitly with `exclusion_reason = insufficient_same_segment_complete_predecessors` — never fabricated. As predicted, **daily (all horizons) and 4h prev40 are unavailable throughout the July week** because the preceding 28 days are missing.

---

## 1. Data-Quality Report

Full machine version: `outputs/data_quality_report.json`.

| Field | Discovery file |
|---|---|
| Columns | `ts_event, rtype, publisher_id, instrument_id, open, high, low, close, volume, symbol` |
| Timestamp tz (source) | **UTC**; marks **bar OPENING**; availability = open + interval |
| Converted tz | **America/New_York** (DST-aware) |
| Range (ET) | 2026-07-05 20:00 → 2026-07-12 19:59 |
| Selected rows (NQU6) | 6,900 |
| Duplicates / NaN / nonpos vol | 0 / 0 / 0 |
| `high<max(o,c)` / `low>min(o,c)` / `high<low` | 0 / 0 / 0 |
| Missing minutes | maintenance + weekend only; **0 unexplained** |

**Hashes (both match their delivery manifests):** discovery `1d0aac6…f91cf007` ✅; warm-up `4a56638d…b7dc7cad` ✅.
**Warm-up file:** 2025-01-01 → 2026-06-07; continuous front-month has some sparse no-trade minutes (logged as minor illiquidity gaps). **No data was silently repaired.**

---

## 2. Time Conventions

* Globex day **18:00 → 17:00 ET**; overnight **18:00–09:29**; RTH **09:30–16:00**; maintenance **17:00–18:00** (no synthetic bars).
* **Daily candle span fix:** the daily candle now covers the full Globex day **18:00 → 16:59 ET** (1380 tradeable minutes). The prior revision truncated it at 16:00, dropping 16:01–16:59; this is corrected. Full discovery days now show `n_source_minutes = 1380, complete = True`; the 2026-07-06 daily is `complete = False` (missing 18:00–20:00 ET).
* HTF fixed ET clock boundaries: 5m `%5`, 15m `%15`, 30m `{00,30}`, 1h clock hour, 4h `{00,04,08,12,16,20}`, daily = Globex day. A HTF candle is available only when its interval ends; every HTF candle carries `availability_et`, `complete`, `segment_id`, `spans_segment_boundary`.

Combined series: 511,566 one-minute bars. Discovery-week completed candles: 1m 6540 · 5m 1308 · 15m 436 · 30m 218 · 1h 109 · 4h 29 · daily 4.

---

## 3. Complete Machine-Readable Ledgers

Files in `outputs/ledgers/` (CSV canonical; JSON mirror for ≤5000-row ledgers). Every record carries `instrument, tf, source timestamp(s), availability_et, boundaries, later state-change timestamps, segment_id, param_version`.

| Primitive | 1m | 5m | 15m | 30m | 1h | 4h | daily |
|---|--:|--:|--:|--:|--:|--:|--:|
| FVG | 1136 | 274 | 90 | 40 | 22 | 5 | 2 |
| iFVG conversions | 1103 | 254 | 81 | 34 | 19 | 2 | 1 |
| Rejection-block candidates | 13082 | 2618 | 874 | 438 | 220 | 60 | 10 |
| Displacement legs | 39246 | 7854 | 2622 | 1314 | 660 | 174 | 24 |

Plus: `liquidity_references.csv` (50), `roll_decisions.csv` (377 sessions), `continuity_segments.csv` (26), `trailing_validity_table.csv` (7 tf × 3 horizons). **Discovery structural counts are identical to the pre-causal-fix run — the causal contract/segment changes did not alter what was detected, only the trailing-feature validity.**

---

## 4. Deterministic Human-Audit Examples

37 annotated charts in `outputs/charts/`; index in `outputs/examples/audit_examples.json`. Selected chronologically or by a structural rank metric — never by outcome. First bull/bear FVG per tf; first FVG→iFVG each direction; first swept + first still-unswept liquidity per source; three top valid rejection candidates on three tfs; first body-overlap and first complete-traversal invalidations; high/middle/low displacement.

Verified: first 1m bullish FVG `FVG-1m-bull-20260706T0005` — A(00:03) high 29725.0 < C(00:05) low 29732.5, B bullish, containment holds; zone [29725.0, 29732.5]; available 00:06; segment 25.

---

## 5. Cases Requiring Additional Rules

1. **Segment-limited HTF histories.** daily prev10/20/40 and 4h prev40 are unavailable in July (28-day seam). Resolvable only with warm-up data **contiguous through Jul 5 on NQU6**.
2. **Post-seam contract bootstrap.** July 6's contract cannot be decided from an in-segment predecessor (none exists); it is a disclosed bootstrap from the session's own dominant outright.
3. **First discovery daily incomplete** (missing 18:00–20:00 ET) — flagged, excluded from normalization.
4. **Wick-passage vs sweep** indistinguishable from OHLCV (no intrabar order) — recorded as coincident.
5. **Zero-body candles** → `dwick/body` null (guarded), not ∞.

---

## 6. Unresolved Definition Decisions

1. **Warm-up contiguity** — extend to be continuous through Jul 5 on NQU6 so daily/4h July histories become available. Older non-contiguous data does not suffice.
2. **Segment gap threshold** (currently 60 min for non-calendar gaps) — confirm.
3. **Unadjusted (raw-roll) continuous contract** vs back-adjusted — confirm (unadjusted chosen; structures never cross a roll, so absolute levels are only ever compared within one contract).
4. **Rejection-block prominence threshold** — deliberately unfrozen (candidates ranked, not certified).
5. **Displacement classification threshold** — unfrozen.
6. **FVG "full fill" = invalidation** semantics — confirm.
7. **iFVG single conversion** per FVG — confirm no re-conversion.
8. **Rejection-block dual emission** (bullish + bearish per candle) — confirm.
9. **4h anchor** midnight-ET vs Globex-open — confirm.

---

## 7. Reproducibility Manifest

Full: `outputs/reproducibility_manifest.json`.

* Discovery SHA-256 `1d0aac6…f91cf007` ✅ · Warm-up SHA-256 `4a56638d…b7dc7cad` ✅ (both match delivery manifests).
* Param version `phase1-v1.0.0`; code hashes for `core/primitives/run/charts/tests`.
* Python 3.11.15 · pandas 3.0.3 · numpy 2.4.6.
* **Tests:** `tests.py` → **114/114** invariant checks pass (counts stable, all structures in discovery segment, none pre-seam, daily/4h validity, roll causality, completeness fields present).
* Determinism: no randomness, no seeds.

### Confirmations requested
- **Primitive definitions unchanged** ✅ (identical detection logic; identical discovery counts).
- **Discovery-only structural counts unchanged** ✅ (FVG/iFVG/rejection/displacement/liquidity identical).
- **No warm-up structure interacts with July** ✅ (all emitted structures in segment 25; no emitted timestamp precedes the seam — tested).
- **No absolute structure survives a roll** ✅ (FVG triples require a single segment; detection confined post-seam).
- **All HTF candles have completeness + availability fields** ✅ (`complete`, `availability_et`, `segment_id`, `spans_segment_boundary`).
- **Roll-decision and continuity ledgers included** ✅ (`roll_decisions.csv`, `continuity_segments.csv`).

**Phase 1 stops here** — no setup discovery, selection, grading, or profitability.

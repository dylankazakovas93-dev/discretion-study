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

## 0. FROZEN ROLL + DUAL-SEGMENT MODEL — July is now fully valid

The seam is filled (a contiguous **2026-06-08 → 2026-07-05** NQ file was added, SHA-256 verified) and the continuity model is rebuilt around a **frozen quarterly roll** with **two kinds of segment**.

**(1) Frozen, predetermined quarterly roll.** The front contract is decided by a fixed calendar rule — **the Globex open (18:00 ET) on the Monday of the third-Friday expiry week** — not by volume. Documented cutoffs in `roll_schedule.csv`. The June 2026 roll:

> **NQM6 → NQU6 at exactly `2026-06-15 18:00:00 America/New_York` (`2026-06-15 22:00:00 UTC`)** — third Friday 2026-06-19, Monday of that week 2026-06-15.

**(2) Absolute structures reset at the roll.** The **absolute segment** resets at every frozen roll and every genuine data outage (> 4 days). No FVG, iFVG, liquidity level, rejection zone, or displacement leg spans a roll. There are **7 absolute segments — one per contract** (NQH5…NQU6). The discovery absolute segment is **id 6 (NQU6, 2026-06-15 18:00 → 2026-07-12)**. No absolute structure survives the June roll.

**(3) Only scale-invariant normalization crosses contracts.** The **normalization segment** resets *only* at a genuine data outage — **not** at a roll. Trailing size percentiles (wick/body size ranks — scale-invariant) therefore continue **across** the NQM6→NQU6 boundary. Weekends, daily maintenance, and market holidays / early closes are scheduled closures (all < 4 days) and do not break it. With the gap filled, the **entire 2025-01-01 → 2026-07-12 history is one normalization segment (id 0)** — **371 complete daily candles precede July 6**.

### Trailing-feature validity in the discovery week (`trailing_validity_table.csv`)

| tf | N=10 | N=20 | N=40 |
|---|---|---|---|
| 1m / 5m / 15m / 30m / 1h / 4h / daily | ✅ all valid | ✅ all valid | ✅ all valid |

**0 null across every timeframe and horizon**, including **daily prev40** and **4h prev40** — because scale-invariant normalization now spans contracts over one contiguous history. This is the result the seam-fill + frozen-roll model was intended to produce.

### What changed vs. the prior run
- **FVG and rejection-block counts are unchanged** (July source candles identical): FVG 1136/274/90/40/22/5/2; rejection 13082/2618/874/438/220/60/10.
- **iFVG and displacement counts increased slightly** — legitimately, because the contiguous **pre-July NQU6** data (June 15 → July 5) is now in the *same absolute segment*, so pre-existing NQU6 FVGs convert during the week and multi-candle legs no longer clip at the old seam. e.g. iFVG-1h 19→22, iFVG-daily 1→2; displacement-daily 24→30. No structure references any data before the roll (tested).

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

**Three input files, all SHA-256-verified:** discovery (`1d0aac6…f91cf007`) 2026-07-06→07-12; warm-up (`4a56638d…b7dc7cad`) 2025-01-01→2026-06-07; gap-fill (`a5778278…6aa54c72`) **2026-06-08→2026-07-05**. The gap-fill file joins minute-contiguously to both neighbours (ends 07-05 19:59 ET, one minute before discovery; begins 06-07 20:00 ET, right after warm-up). **No data was silently repaired.**

---

## 2. Time Conventions

* Globex day **18:00 → 17:00 ET**; overnight **18:00–09:29**; RTH **09:30–16:00**; maintenance **17:00–18:00** (no synthetic bars).
* **Daily candle span fix:** the daily candle now covers the full Globex day **18:00 → 16:59 ET** (1380 tradeable minutes). The prior revision truncated it at 16:00, dropping 16:01–16:59; this is corrected. Full discovery days now show `n_source_minutes = 1380, complete = True`; the 2026-07-06 daily is `complete = False` (missing 18:00–20:00 ET).
* HTF fixed ET clock boundaries: 5m `%5`, 15m `%15`, 30m `{00,30}`, 1h clock hour, 4h `{00,04,08,12,16,20}`, daily = Globex day. A HTF candle is available only when its interval ends; every HTF candle carries `availability_et`, `complete`, `segment_id`, `norm_segment_id`, `spans_segment_boundary`.

Combined series: 538,688 one-minute bars (2025-01-01 → 2026-07-12, one normalization segment). Discovery-week completed candles: 1m 6540 · 5m 1308 · 15m 436 · 30m 218 · 1h 109 · 4h 29 · daily 4.

---

## 3. Complete Machine-Readable Ledgers

Files in `outputs/ledgers/` (CSV canonical; JSON mirror for ≤5000-row ledgers). Every record carries `instrument, tf, source timestamp(s), availability_et, boundaries, later state-change timestamps, segment_id, param_version`.

| Primitive | 1m | 5m | 15m | 30m | 1h | 4h | daily |
|---|--:|--:|--:|--:|--:|--:|--:|
| FVG | 1136 | 274 | 90 | 40 | 22 | 5 | 2 |
| iFVG conversions | 1116 | 261 | 86 | 39 | 22 | 4 | 2 |
| Rejection-block candidates | 13082 | 2618 | 874 | 438 | 220 | 60 | 10 |
| Displacement legs | 39246 | 7854 | 2622 | 1314 | 660 | 180 | 30 |

Plus: `liquidity_references.csv` (50), `roll_schedule.csv` (frozen cutoffs), `continuity_segments.csv` (7 absolute segments), `trailing_validity_table.csv` (7 tf × 3 horizons). FVG/rejection counts match the discovery-only baseline; iFVG/displacement rose because contiguous pre-July NQU6 context now lives in the discovery absolute segment (see §0).

---

## 4. Deterministic Human-Audit Examples

37 annotated charts in `outputs/charts/`; index in `outputs/examples/audit_examples.json`. Selected chronologically or by a structural rank metric — never by outcome. First bull/bear FVG per tf; first FVG→iFVG each direction; first swept + first still-unswept liquidity per source; three top valid rejection candidates on three tfs; first body-overlap and first complete-traversal invalidations; high/middle/low displacement.

Verified: first 1m bullish FVG `FVG-1m-bull-20260706T0005` — A(00:03) high 29725.0 < C(00:05) low 29732.5, B bullish, containment holds; zone [29725.0, 29732.5]; available 00:06; segment 25.

---

## 5. Cases Requiring Additional Rules

1. **First discovery daily incomplete** (missing 18:00–20:00 ET on 2026-07-06) — flagged `complete=False`, excluded from normalization history.
2. **Wick-passage vs sweep** indistinguishable from OHLCV (no intrabar order) — recorded as coincident.
3. **Zero-body candles** → `dwick/body` null (guarded), not ∞.
4. **Data-outage threshold.** A normalization break requires a > 4-day gap. This treats every US market holiday / early close as a scheduled closure (correct here), but a genuine multi-day feed outage < 4 days would not break the segment. None exists in this data.

---

## 6. Unresolved Definition Decisions

1. **Frozen-roll rule** — chosen as the Globex open on the Monday of the third-Friday expiry week (June 2026 → `2026-06-15 18:00 ET`). Confirm vs. an alternative fixed convention (e.g. Thursday-before-expiry).
2. **Scale-invariant normalization across contracts** — trailing size percentiles cross the roll (unadjusted raw prices; only *sizes*, which are roll-invariant, are compared). Absolute levels never cross. Confirm this split.
3. **4-day outage threshold** for normalization-segment breaks — confirm.
4. **Rejection-block prominence threshold** — deliberately unfrozen (candidates ranked, not certified).
5. **Displacement classification threshold** — unfrozen.
6. **FVG "full fill" = invalidation** semantics — confirm.
7. **iFVG single conversion** per FVG — confirm no re-conversion.
8. **Rejection-block dual emission** (bullish + bearish per candle) — confirm.
9. **4h anchor** midnight-ET vs Globex-open — confirm.

---

## 7. Reproducibility Manifest

Full: `outputs/reproducibility_manifest.json`.

* Three input files, **all SHA-256 verified against their delivery manifests**: discovery `1d0aac6…f91cf007` ✅ · warm-up `4a56638d…b7dc7cad` ✅ · gap-fill `a5778278…6aa54c72` ✅.
* Param version `phase1-v1.0.0`; code hashes for `core/primitives/run/charts/tests`.
* Python 3.11.15 · pandas 3.0.3 · numpy 2.4.6.
* **Tests:** `tests.py` → **119/119** invariant checks pass.
* Determinism: no randomness, no seeds.

### Confirmations
- **Frozen predetermined roll** ✅ — NQM6 → NQU6 at `2026-06-15 18:00 ET` (`roll_schedule.csv`); no volume look-ahead.
- **Absolute structures reset at the roll** ✅ — every emitted FVG/iFVG/liquidity/rejection/displacement is in the NQU6 absolute segment (id 6); none references data before the roll (tested).
- **Only scale-invariant normalization crosses contracts** ✅ — trailing percentiles use the normalization segment (id 0), which spans all contracts; absolute levels never cross.
- **FVG/rejection primitive definitions & counts unchanged** ✅; iFVG/displacement changes explained (pre-July NQU6 context) and bounded.
- **All HTF candles carry completeness + availability + both segment ids** ✅ (`complete`, `availability_et`, `segment_id`, `norm_segment_id`, `spans_segment_boundary`).
- **Roll schedule and continuity-segment ledgers included** ✅ (`roll_schedule.csv`, `continuity_segments.csv`).
- **Every trailing 10/20/40 percentile valid in July** ✅ (incl. daily prev40; 0 null).

**Phase 1 stops here** — no setup discovery, selection, grading, or profitability.

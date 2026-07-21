# Primitive reset — NQU6 timestamp audit report

Narrow primitive reset (FVG, iFVG, rejection blocks) only. No strategy
testing, no adaptive evidence, no profitability claims, no large historical
rerun. New code lives entirely in `src/discretion/primitive_reset/`, isolated
from `discretion.primitives.*` and never imported by `branch_engine`,
`materializer`, or `pipeline` — the existing candidate/evidence pipeline is
untouched and does not run on these new primitives.

## Correction: RB causal lifecycle bug (fixed before this report)

Dylan's review of the first version of this report caught an impossible
timestamp: `RB2-000009` showed `deactivation: 19:40 ET` before
`activation: 19:50 ET`. Root cause: a newly confirmed RB was appended to
the causally-processed `active` list in the same outer-loop iteration that
detected its source candle, so it was tracked against every candle between
the source and its real confirming candle — before it had actually
activated. This was a processing-order bug, not a report-formatting issue.

Fixed with a pending-activation queue (`primitive_reset/rejection_block.py`):
a confirmed RB is scheduled to start tracking at `confirming_index + 1` and
is never processed against any candle from its source through the confirming
candle itself. The frozen confirmation/MFE/ATR/traversal/lifetime
definitions were **not** touched — only *when* a confirmed record joins the
tracked list changed. See "Validation" below for the real-data proof (zero
timestamp-order violations across all 3,709 confirmed RBs) and "Tests" for
the 10 new synthetic proofs plus a real-NQU6 invariant check.

## Repository integrity

- Branch: `claude/graph-native-candidate-engine-v2`
- Starting HEAD (verified before work began): `4468ffebfdc65778f2f7e4cc4e6ff2f04194235f`
  (matched local, remote, and the task's expected SHA; working tree was clean)
- PR #2: open, draft, unmerged throughout this task (not touched)
- See the top-level completion report (delivered in the same turn as this
  file) for the final HEAD and full commit list.

## Supersession

- `artifacts/review_week_atlas_2025_07_14_18/PRIMITIVE_AUDIT_STATUS.md` and
  the matching file in `..._repaired/` mark both prior atlases
  `PRIMITIVE_AUDIT_FAIL — SUPERSEDED`. Nothing was deleted.
- No candidate or evidence object from those atlases was reused. No large
  rerun occurred: this task loads only the requested ~5-day NQU6 window
  (6,900 one-minute bars), not the 61-prior-session universe used by the
  superseded atlas.
- The 40-prior-session requirement, checkpointing, streaming materialization,
  target-policy separation and outcome-after-selection ordering from the
  existing pipeline are untouched — this task never calls into them.

## Exact logic implemented

### Candle colour (`primitive_reset/colour.py`)
`bullish` iff `close >= open`, `bearish` iff `close < open`. The exact-doji
case (`close == open`) is classified **bullish** by this convention — a
single-bar, lookback-free tie-break chosen only for determinism, carrying no
claim that a doji is directionally bullish.

### FVG geometry and grading (Parts 1-2)
Three consecutive same-timeframe, same-segment, same-colour candles A/B/C.
Bullish: `C.low > A.high`, zone `[A.high, C.low]`. Bearish: `C.high < A.low`,
zone `[C.high, A.low]`. No minimum body size; no doji exclusion. Available
only once C closes (`formation_ts = C`'s close timestamp). `width_atr =
width_points / atr_at_c_close`, binned into the six spec-defined ATR buckets.
`atr_at_c_close` is the completed same-timeframe Wilder ATR(14) **inclusive**
of candle C's own true range (see "ATR contract" below).

### iFVG lineage and inversion speed (Parts 4-5)
Only ever built from a parent FVG on the *same* timeframe series that is
still active and unexpired when a completed candle closes fully through its
distal boundary (a wick-only breach that recovers by close is not an
inversion — see traversal contract below). Parent transitions to inverted;
child activates opposite-direction in the same instant. Stored:
`bars_from_parent_formation_to_inversion`, `bars_from_parent_first_touch_to_
inversion`, a speed bucket (`1_candles` … `5plus_candles`), plus penetration/
distance-through-zone/scraping-candle statistics. **Disclosed, not spec-pinned
exactly:** "total distance moved through the parent zone" is computed as
`near-edge minus inversion close` (bullish) — i.e. how far the close ended up
beyond the zone's entry edge; "scraping candles" are bars between first touch
and inversion (exclusive) that reached the zone without closing through.
Dylan should confirm these definitions read as intended.

### RB candidate + confirmation (Parts 6-7)
No local-pivot/swing requirement. Candidate floor:
`relevant_wick_length / max(real_body_length, 1 tick) >= 0.20` (the
`max(body, 1 tick)` floor is the documented zero-body numerical-stability
convention the spec explicitly permitted; it also means many small-bodied
candles trivially clear the floor — see "audit output" below).
Confirmation: within the next 3 completed same-timeframe candles, the
**running maximum favourable excursion** (`MAX(high)` for bullish,
`MIN(low)` for bearish, cumulative across the window) must reach
`1.5 * ATR-at-source-close` measured from the proximal boundary; confirmed at
the first candle whose running MFE crosses the threshold. A completed close
back through the *opposite* zone boundary before that happens fails the
candidate (`invalidated_before_confirmation`). Reaching threshold only on a
4th candle, or never, both fail to confirm.

### Common traversal contract (Part 8)
Shared by FVG/iFVG/RB (`primitive_reset/traversal.py`). For zone `[lo, hi]`,
`W = hi - lo`, `tolerance = 0.20 * W`: a completed candle whose **close**
breaches the distal boundary deactivates (`DEACTIVATED_CLOSE_THROUGH`),
checked first and independent of wick depth — this is the unconditional
trigger the iFVG detector keys on. Otherwise, a wick excursion beyond the
distal boundary that exceeds tolerance deactivates
(`DEACTIVATED_OVERSHOOT_LIMIT`) even though the close recovered. A tiny
float epsilon (`1e-9`) absorbs floating-point arithmetic drift at an
exact-tolerance boundary (real prices are tick-quantized to 0.25, so this
cannot mask a genuine distinction). Deactivation is immutable; no
reactivation.

### Structure lifetime (Part 3)
Timeframes below 1h (1/3/5/15/30m): 8 real elapsed hours from activation,
measured via ET timestamps. `EXPIRED_ACTIVE_8H` if touched-but-not-closed by
then, `EXPIRED_UNTOUCHED_8H` if never touched. 1h+: no arbitrary expiry —
only structural invalidation, or `DATA_END_ACTIVE` if still active when data
runs out. No `CONTINUATION` label anywhere; confirmed absent by test.

### ATR contract
Completed same-timeframe Wilder ATR(14), **including** the bar's own true
range — the value knowable the instant that bar closes. This is deliberately
a fresh, unshifted computation (`primitive_reset/timeframes.py`), not a reuse
of `discretion.data.aggregation.HTFBar.atr`, which is shifted by one candle
for an unrelated feature-normalization purpose elsewhere in the codebase;
reusing it here would have silently violated this task's causal-freeze
contract.

## Audit output

### Data coverage
Symbol `NQU6` (literal symbol filter, not front-month-by-volume). Full
symbol coverage in the licensed file: `2026-04-19 18:01 ET` – `2026-07-17
16:59 ET`. Requested window `2026-07-12 18:00 ET` – `2026-07-17 17:59:59 ET`
is present **except the final ~61 minutes** (`17:00`–`17:59:59 ET` on
`2026-07-17`, past the file's end). 6,900 one-minute bars used. Four
1-hour gaps appear inside the window at each day's `17:00`–`18:00 ET`
maintenance break — this is the normal CME daily halt, not missing data
(disclosed in `data_coverage.json`'s `internal_gaps`).

### Counts by timeframe

| tf (min) | completed candles | FVGs | iFVGs | RB candidates | RB confirmed |
|---:|---:|---:|---:|---:|---:|
| 1  | 6900 | 817 | 429 | 9614 | 2231 |
| 3  | 2300 | 263 | 131 | 3307 |  786 |
| 5  | 1380 | 154 |  62 | 1954 |  443 |
| 15 |  460 |  41 |  20 |  642 |  132 |
| 30 |  230 |  22 |   7 |  320 |   68 |
| 60 |  115 |  13 |   3 |  163 |   49 |

Totals: 1,310 FVGs, 652 iFVGs, 16,000 RB candidates (3,709 confirmed, 12,291
rejected). Full ATR-bin breakdown in `fvg_atr_bin_summary.csv`.

**Disclosed data characteristic:** the RB candidate floor's `max(body, 1
tick)` zero-body convention (spec-sanctioned) means many small/zero-bodied
candles trivially clear `wick/body >= 0.20` at 1-tick wicks, which is most of
why the raw 1m candidate count (9,614) is large relative to confirmations
(2,231). This is the detector working as specified, not a bug — flagged so
Dylan isn't surprised by the volume in `rb_rejected_candidates.csv`.

### FVG examples (5, spanning ATR bins)

1. **FVG2-000003** — 1m bullish, `<0.05 ATR` (0.0226). Open NQU6 on 1m at
   `2026-07-12 18:52 ET`. Formed by A/B/C at `18:50`/`18:51`/`18:52 ET`, zone
   `[29882.75, 29883.00]`. Deactivated `DEACTIVATED_OVERSHOOT_LIMIT`.
2. **FVG2-000002** — 1m bullish, `0.05-<0.10 ATR` (0.0600). Open NQU6 on 1m
   at `18:44 ET`. A/B/C `18:42`/`18:43`/`18:44 ET`, zone
   `[29888.00, 29888.75]`. Deactivated `DEACTIVATED_OVERSHOOT_LIMIT`.
3. **FVG2-000012** — 1m bullish, `0.10-<0.20 ATR` (0.1860). Open NQU6 on 1m
   at `20:10 ET`. A/B/C `20:08`/`20:09`/`20:10 ET`, zone
   `[29992.25, 29996.50]`. Inverted (`DEACTIVATED_CLOSE_THROUGH`) at
   `20:17 ET`.
4. **FVG2-000008** — 1m bullish, `0.20-<0.30 ATR` (0.2022). Open NQU6 on 1m
   at `19:29 ET`. A/B/C `19:27`/`19:28`/`19:29 ET`, zone
   `[29884.75, 29886.50]`. Deactivated `DEACTIVATED_OVERSHOOT_LIMIT`.
5. **FVG2-000014** — 1m bearish, `0.30-<0.50 ATR` (0.3337). Open NQU6 on 1m
   at `20:29 ET`. A/B/C `20:27`/`20:28`/`20:29 ET`, zone
   `[29977.25, 29983.50]`. Never touched; `EXPIRED_UNTOUCHED_8H` at
   `2026-07-13 04:29 ET`.

(No `>=0.50 ATR` example landed in the first-match pick within this window;
`fvg_candidates.csv` has the full population if Dylan wants one from later
in the week.)

### iFVG examples (5, spanning inversion speed)

1. **IFVG2-000010** (parent `FVG2-000029`) — 1m, 1-candle inversion. Parent
   bullish FVG formed `22:34 ET`, width/ATR 0.067. Open NQU6 on 1m at
   `22:35 ET` — the very next candle after formation closes fully through
   `29772.75`, activating a bearish iFVG.
2. **IFVG2-000015** (parent `FVG2-000042`) — 1m, 2-candle inversion. Parent
   bearish FVG formed `00:36 ET` (7/13), width/ATR 0.201. Open NQU6 on 1m at
   `00:38 ET` — inversion 2 candles after formation, activating a bullish
   iFVG through `29638.25`.
3. **IFVG2-000002** (parent `FVG2-000005`) — 1m, 3-candle inversion. Parent
   bullish FVG formed `18:57 ET`, width/ATR 0.047. Open NQU6 on 1m at
   `19:00 ET` — inversion through `29908.25`, activating a bearish iFVG.
4. **IFVG2-000001** (parent `FVG2-000004`) — 1m, 4-candle inversion. Parent
   bullish FVG formed `18:56 ET`, width/ATR 0.849. Open NQU6 on 1m at
   `19:00 ET` — inversion through `29892.75`, activating a bearish iFVG.
5. **IFVG2-000003** (parent `FVG2-000009`) — 1m, 5+-candle inversion. Parent
   bearish FVG formed `19:46 ET`, width/ATR 0.887. Open NQU6 on 1m at
   `19:51 ET` (5 candles from formation) — inversion through `29888.75`,
   activating a bullish iFVG.

### RB confirmed examples (5, spanning wick/body ratio and timeframe — causally corrected)

Each line reports `source_ts < activation_ts <= first_tap_ts/deactivation_ts`
explicitly so the fix is directly checkable against every example.

1. **RB2-000068** — 1m bearish. Open NQU6 on 1m at source `18:59 ET`. Source
   OHLC `(29913.25, 29914.25, 29909.50, 29910.25)`, wick/body 0.333.
   Confirmed on confirming candle 1 (MFE 32.75 pts, ATR 9.71) →
   **activation `19:00 ET`**. First tap `20:01 ET`, deactivated
   `DEACTIVATED_CLOSE_THROUGH` at `20:02 ET`.
2. **RB2-000032** — 3m bearish. Open NQU6 on 3m at source `19:45 ET`.
   Wick/body 0.762. Confirmed on candle 1 (MFE 49.0 pts, ATR 16.34) →
   **activation `19:48 ET`**. First tap `19:54 ET`, deactivated
   `DEACTIVATED_CLOSE_THROUGH` at `20:03 ET`.
3. **RB2-000009** — 5m bearish. Open NQU6 on 5m at source `19:35 ET`.
   Wick/body 1.444. Confirmed on candle 3 (MFE 43.25 pts, ATR 24.30) →
   **activation `19:50 ET`** (previously misreported as `19:50 ET`
   activation with an impossible `19:40 ET` deactivation — now corrected).
   First tap and deactivation both land on the very next 5m candle,
   `19:55 ET` (`DEACTIVATED_OVERSHOOT_LIMIT`).
4. **RB2-000034** — 15m bullish. Open NQU6 on 15m at source
   `2026-07-13 04:00 ET`. Wick/body 2.0. Confirmed on candle 2 (MFE 88.75
   pts, ATR 55.53) → **activation `04:30 ET`**. First tap and deactivation
   both `09:45 ET` (`DEACTIVATED_CLOSE_THROUGH`).
5. **RB2-000065** — 30m bullish. Open NQU6 on 30m at source
   `2026-07-13 23:30 ET`. Wick/body 5.232. Confirmed on candle 3 (MFE 139.75
   pts, ATR 89.03) → **activation `2026-07-14 01:00 ET`**. Never tapped;
   `EXPIRED_UNTOUCHED_8H` at `09:00 ET` (8h measured from activation, not
   from source).

### RB rejected examples (3 distinct mechanical reasons — all that exist)

1. **RB2-000001** — 1m bullish, wick/body 0.212. Open NQU6 on 1m at
   `18:14 ET`. MFE stayed flat at 23.5 pts across all 3 confirmation
   candles, never reaching 1.5x ATR (25.52) → `threshold_not_reached_in_3_
   candles`.
2. **RB2-000007** — 1m bearish, wick/body 0.235. Open NQU6 on 1m at
   `18:17 ET`. A later candle in the 3-candle window closed back through the
   zone's opposite boundary before MFE reached threshold →
   `invalidated_before_confirmation`.
3. **RB2-009611** — 1m bullish, wick/body 3.333. Open NQU6 on 1m at
   `2026-07-17 16:57 ET` — the data file ends 3 minutes later, leaving fewer
   than 3 completed confirmation candles → `insufficient_data_for_
   confirmation_window`.

(Only three distinct mechanical rejection reasons are implemented; five was
not achievable and none were fabricated.)

## Validation (RB causal-lifecycle correction)

Computed across all 3,709 confirmed RBs, all 6 governing timeframes, the
actual NQU6 audit run:

| metric | value |
|---|---:|
| confirmed RBs | 3,709 |
| confirmed RBs with a recorded first tap | 3,185 |
| confirmed RBs with a recorded deactivation | 3,709 |
| minimum activation → first-tap duration | 1 minute |
| minimum activation → deactivation duration | 1 minute |
| **timestamp-order violations** | **0** |

"Timestamp-order violation" = `source_ts >= activation_ts`, or
`first_tap_ts < activation_ts` (when a tap exists), or `deactivation_ts <
activation_ts` (when a deactivation exists). Every confirmed RB in the real
audit satisfies `source_ts < activation_ts <= first_tap_ts` and
`activation_ts <= deactivation_ts`; the minimum 1-minute gaps are exactly
what's expected on the 1m series (tracking cannot begin before the candle
immediately after confirmation), and every higher timeframe's minimum is at
least one of its own candles.

## Tests

```
PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
```
62 collected, 62 passed, 0 failed, 0 skipped, 3.24s (52 from the original
Part-10 suite, unchanged and still passing, plus 10 new tests for the RB
causal-lifecycle fix: activation-never-after-first-tap/deactivation,
no-event-before-activation, confirmation-on-candle-{1,2,3}-begins-tracking-
on-the-next-candle, confirmation-candle-cannot-tap-or-invalidate-itself,
pre-confirmation-traversal-cannot-leak-into-post-activation, rejected-
candidates-never-enter-the-active-set, expiry-measured-from-activation, a
segment-boundary edge case, and a real-NQU6-data invariant check asserting
zero violations across all 3,709 confirmed RBs). Per Part 10's instruction,
only this fast, synthetic-plus-invariant-check suite was run for this task —
the complete slow historical suite was not run.

## Honest verdict

**PRIMITIVE_RESET_READY_WITH_LIMITATIONS**

The exact FVG/iFVG/RB rules, the common traversal contract, the 8h/no-expiry
lifetime split, every Part-10 synthetic proof, and the RB causal-lifecycle
correction (zero timestamp-order violations across all 3,709 confirmed RBs
in the real audit) pass. Limitations, so Dylan inspects before anything
downstream is unblocked:

1. Requested audit window is short one final hour (`17:00`–`17:59:59 ET` on
   `2026-07-17`) — the licensed file ends there; disclosed, not fabricated.
2. A handful of Part 5's more open-ended descriptive iFVG fields ("total
   distance moved through the parent zone", "scraping candles", "average
   scraping body") were given exact, documented formulas since the spec
   described them qualitatively rather than with a pinned formula — these
   are provisional pending Dylan's confirmation they read as intended.
3. The RB candidate floor's `max(body, 1 tick)` convention (spec-sanctioned)
   produces a large volume of near-doji RB candidates; not a defect, but
   worth Dylan's awareness before he opens `rb_rejected_candidates.csv`.
4. This is a coded, timestamp-based audit only — no chart was rendered and
   no visual pattern selection was used at any point, per the task's
   explicit restriction.

Primitives are not claimed correct until Dylan inspects the timestamps above
on his own chart. No strategy, evidence, or profitability claim is made.

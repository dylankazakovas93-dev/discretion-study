# Primitive reset — NQU6 timestamp audit report (repaired)

Narrow primitive reset (FVG, iFVG, rejection blocks) only. No strategy
testing, no adaptive evidence, no profitability claims, no large historical
rerun. New code lives entirely in `src/discretion/primitive_reset/`, isolated
from `discretion.primitives.*` and never imported by `branch_engine`,
`materializer`, or `pipeline`.

**All timestamps below are candle OPEN time (how a chart plots/labels a
candle), not the internal causal-availability instant.** A prior version of
this report used the availability instant for multi-minute timeframes, which
is one full candle later than its open — that mislabeling is what made
RB2-000034(old)/RB2-000009(old) look wrong on a real chart. See "Correction 2"
below.

## Combined timestamp audit verdict inputs (from the prior turn)

- FVG: provisional PASS
- iFVG: AUDIT INCONCLUSIVE
- RB: SOURCE-SELECTION FAIL

This report resolves all three.

## Repository integrity

- Branch: `claude/graph-native-candidate-engine-v2`
- Starting HEAD (verified before work began): `065b6f30afec8aed9994651c810ec0107ea7f7c7`
  (matched local, remote, and the task's expected SHA; working tree was clean)
- PR #2: open, draft, unmerged throughout (not touched)
- See the top-level completion report for the final HEAD and commit list.

## Correction 1 — exact-doji colour handling

`colour.py` previously used `close >= open`, silently classifying every
exact `open == close` candle bullish. Dylan did not freeze that tie-break.
FVG2-000029(old)'s C candle was exactly such a case (`open == close ==
29777.25`) and it seeded IFVG2-000010(old) — a structure Dylan correctly
did not see on his chart.

**Fix:** `colour_state()` now returns `bullish` / `bearish` /
`exact_doji_colour_unresolved`. `eligible_same_colour()` requires all three
FVG candles to be resolved (never doji) and share the same resolved colour;
an exact-doji anywhere in A/B/C makes the triple ineligible. Small/near-doji
bodies (`close != open`, however small) are **still never excluded** — only
literal equality is held back. A blocked-but-geometrically-valid triple is
logged to `fvg_doji_blocked.csv` with `exclusion_reason =
EXACT_DOJI_COLOUR_UNRESOLVED` (never silently dropped) and can never seed an
iFVG (no `FVGRecord` exists for it to invert).

**Impact:** 61 raw triples across all 6 timeframes were geometry-valid gaps
with a doji-ambiguous candle (54 on 1m, 3 on 3m, 3 on 5m, 1 on 15m, 0 on
30m/60m) — logged, none of them entered the active population.
`n_fvg_total` moved 1,310 → 1,291; `n_ifvg_total` moved 652 → 639 (only the
subset of the 61 that had actually been valid under the old bullish
tie-break disappears from the *active* population; the rest were never
valid FVGs under any convention and the geometry-only diagnostic count
(61) is larger than the population delta for that reason).

FVG2-000029(old) is confirmed as one of the 61: A/B bullish, C exact doji,
geometry `C.low(29773.75) > A.high(29772.75)` — real geometry, doji-blocked,
correctly absent from the current population. **IFVG2-000010(old) no longer
exists.**

## Correction 2 — HTF candle-open vs candle-close labeling

Every RB/FVG/iFVG timestamp field (`activation_ts`, `source_ts`,
`formation_ts`, etc.) is internally the candle's **causal-availability**
instant (`close_ts` for an aggregated HTF candle) — correct and unchanged
for causal decision-making. For timeframes above 1m this is a full candle
period *later* than the candle's own open, which is how a real chart plots
it. A new, purely additive, display-only helper —
`timeframes.candle_open_ts_et()` — returns the true open time and is used
for every human-facing timestamp in this report and the combined table
below. No detector logic, internal field, or existing test changed; this is
strictly a reporting-layer fix.

This is the reason RB2-000034(old)'s "4:00 AM" source candle and
RB2-000009(old)'s "19:35" source candle were each one candle late — see the
forensic audits below.

## Correction 3 — RB dominant-wick direction selection

Previously each source candle was tested independently for a bullish
candidate (lower wick) *and* a bearish candidate (upper wick), so one candle
could emit two opposing RBs. Fixed: direction now follows whichever wick is
strictly longer (`lower_wick > upper_wick` → bullish only;
`upper_wick > lower_wick` → bearish only); equal-length wicks emit **no**
active RB and are logged to `rb_equal_wick_ambiguous.csv`. A new continuous
`dominant_wick_ratio = relevant_wick / max(opposite_wick, 1 tick)` grading
field is stored (not gated on) for every RB. The frozen 1.5-ATR/next-3-candle
MFE confirmation rule is unchanged.

**Impact:** `n_rb_candidates_total` 16,000 → 8,045 (roughly half, as
expected — most candles no longer double-count); `n_rb_confirmed_total`
3,709 → 1,951. 154 candles were exactly-equal-wick and logged as ambiguous.

## Correction 4 — existing-structure precedence

Before creating a new RB candidate, the detector now checks whether any
already-active same-direction RB was tapped by *this* candle (using the
tap/traversal state already computed for that RB, strictly from candles
before the current one — no look-ahead). If so, the tap is recorded on the
**original** RB and no duplicate overlapping RB is created from the reaction
candle; logged to `rb_precedence_suppressed.csv`. Opposite-direction
candidates on the same candle are never suppressed by this rule.

**Impact:** 1,699 reaction candles suppressed across all timeframes that
would otherwise have relabelled a tap of an existing RB as a brand-new one.

## Forensic audit — RB2-000009(old), 5m, reported source "19:35 ET"

**Corrected source open time: Sunday, July 12, 2026, 7:30 PM ET** (not
7:35 PM — the old label was the candle's close/availability instant).

5m candles, open-time labeled, idx 13–23:

| idx | open ET | O | H | L | C | lower_wick | upper_wick | lw/body | uw/body |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 13 | 19:05 | 29896.00 | 29905.25 | 29889.50 | 29890.75 | 1.25 | 9.25 | 0.24 | 1.76 |
| 14 | 19:10 | 29892.00 | 29897.50 | 29884.50 | 29891.25 | 6.75 | 5.50 | 9.00 | 7.33 |
| 15 | 19:15 | 29890.25 | 29894.25 | 29869.50 | 29891.50 | **20.75** | 2.75 | **16.60** | 2.20 |
| 16 | 19:20 | 29890.00 | 29894.00 | 29876.00 | 29881.50 | 5.50 | 4.00 | 0.65 | 0.47 |
| 17 | 19:25 | 29881.00 | 29891.50 | 29879.00 | 29890.25 | 2.00 | 1.25 | 0.22 | 0.14 |
| **18** | **19:30** | 29888.25 | 29891.50 | 29880.75 | 29886.00 | 5.25 | 3.25 | 2.33 | 1.44 |
| 19 | 19:35 | 29886.25 | 29893.50 | 29875.50 | 29890.75 | 10.75 | 2.75 | 2.39 | 0.61 |
| 20 | 19:40 | 29892.50 | 29898.25 | 29888.75 | 29888.75 | 0.00 | 5.75 | 0.00 | 1.53 |
| 21 | 19:45 | 29889.25 | 29890.75 | 29845.00 | 29863.50 | 18.50 | 1.50 | 0.72 | 0.06 |
| 22 | 19:50 | 29864.00 | 29895.50 | 29864.00 | 29876.50 | 0.00 | 19.00 | 0.00 | 1.52 |
| 23 | 19:55 | 29876.50 | 29895.00 | 29865.75 | 29893.25 | 10.75 | 1.75 | 0.64 | 0.10 |

**Source candle (idx 18, open 19:30):** `lower_wick=5.25 > upper_wick=3.25` →
dominant direction is now **bullish**, not bearish. The old detector's
bearish candidate (`upper_wick/body=1.44≥0.20`) was a legitimate floor-pass
under the old (non-dominant) rule but is exactly the "too permissive"
behaviour the repair removes.

**Every candidate the old detector created from this candle:** bullish
(`lower_wick/body=2.33`) and bearish (`upper_wick/body=1.44`) — both,
independently.

**Why the old detector selected bearish:** it never compared the two wicks
against each other; both independently cleared the 0.20 floor, and the
report happened to surface the bearish one.

**Result under the repaired rule:** only the dominant bullish candidate is
created (`RB2-000005`, `dominant_wick_ratio=1.62`). It does **not** confirm —
`rejection_reason=invalidated_before_confirmation` (MFE stayed at 12.25,
0.50x ATR, well under the 1.5x threshold, before a close-through the
opposite boundary). **RB2-000009(old) no longer exists in any form** —
neither the old bearish read nor the new bullish read produces a confirmed
RB from this candle.

**Nearby superior candidate wicks:** idx 15 (open 19:15) has a dramatically
larger lower wick — 20.75 points, `lw/body=16.60`, `dominant_wick_ratio=7.55`
— tested and **also fails to confirm** within its own 3-candle window
(`threshold_not_reached_in_3_candles`). idx 21 (open 19:45) has an 18.50-point
lower wick but a large body (ratio only 0.72, below the 1.44/2.33 seen at
idx 18/19). **Honest finding: this specific 5-candle neighbourhood does not
produce a clean confirmed RB under the repaired rules** — there is no
"replacement" example to substitute here; none was fabricated.

## Forensic audit — RB2-000034(old), 15m, reported source "04:00 ET"

**Corrected source open time: Monday, July 13, 2026, 3:45 AM ET** (not
4:00 AM).

15m candles, open-time labeled, idx 33–45:

| idx | open ET | O | H | L | C | lower_wick | upper_wick | lw/body | uw/body |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 33 | 02:15 | 29592.00 | 29635.25 | 29588.75 | 29630.00 | 3.25 | 5.25 | 0.09 | 0.14 |
| 34 | 02:30 | 29630.25 | 29650.50 | 29598.50 | 29643.75 | 31.75 | 6.75 | 2.35 | 0.50 |
| 35 | 02:45 | 29641.75 | 29652.00 | 29611.25 | 29632.50 | 21.25 | 10.25 | 2.30 | 1.11 |
| 36 | 03:00 | 29631.50 | 29675.50 | 29607.00 | 29670.75 | 24.50 | 4.75 | 0.62 | 0.12 |
| 37 | 03:15 | 29671.50 | 29690.25 | 29642.25 | 29674.50 | 29.25 | 15.75 | 9.75 | 5.25 |
| 38 | 03:30 | 29670.75 | 29671.25 | 29636.00 | 29660.50 | 24.50 | 0.50 | 2.39 | 0.05 |
| **39** | **03:45** | 29660.75 | 29663.00 | 29636.75 | 29652.75 | **16.00** | 2.25 | **2.00** | 0.28 |
| 40 | 04:00 | 29654.25 | 29707.00 | 29647.50 | 29703.75 | 6.75 | 3.25 | 0.14 | 0.07 |
| 41 | 04:15 | 29705.00 | 29741.50 | 29704.25 | 29725.75 | 0.75 | 15.75 | 0.04 | 0.76 |
| 42 | 04:30 | 29728.00 | 29735.00 | 29700.00 | 29726.50 | 26.50 | 7.00 | 17.67 | 4.67 |
| 43 | 04:45 | 29727.25 | 29754.00 | 29721.75 | 29747.50 | 5.50 | 6.50 | 0.27 | 0.32 |
| 44 | 05:00 | 29747.50 | 29751.25 | 29718.00 | 29732.75 | 14.75 | 3.75 | 1.00 | 0.25 |
| 45 | 05:15 | 29733.75 | 29766.25 | 29729.75 | 29763.25 | 4.00 | 3.00 | 0.14 | 0.10 |

**All active RB zones at candle idx 40 (04:00 open), just before it opens:**
one bearish RB, zone `[29797.25, 29808.75]`, source idx 17 (7/12 23:15),
active `23:15 ET (7/12)`–`07:15 ET (7/13)` — far above the current price
range (~29,650–29,710) and the opposite direction. **The 04:00 candle did
not touch any earlier active RB.**

**Result:** the source candle genuinely is idx 39 (open 03:45), a fresh
low with no prior active structure to have suppressed it —
`dominant_wick_ratio=7.11` (16.00 vs 2.25), a real and clean dominant wick.
Confirmed on window-candle 2 (idx 41, open 04:15), MFE 88.75 pts = 1.60x ATR.
The candle at idx 40 (04:00 open) is exactly what Dylan identified: it dips
into the zone (`low 29647.50` vs `zone_hi 29652.75`) and reacts upward
(+53.5 pts to close) — **a tap/reaction of the idx-39 RB, not a separate
source**. **RB2-000034(old) is confirmed correct under the repaired
rules** (now `RB2-000022`) — Dylan's read was right on both counts: the real
source is 03:45, and 04:00 is the reaction candle.

## Re-audit — FVG2-000042(old) / IFVG2-000015(old)

Requested boundaries: A 00:34 ET, B 00:35 ET, C 00:36 ET, zone
`[29636.25, 29638.25]`, inversion 00:38 ET (Monday, July 13, 2026).

Raw NQU6 OHLC (confirmed, unchanged from the original report):
A `(29646.75, 29650.00, 29638.25, 29641.00)` bearish,
B `(29641.50, 29641.50, 29631.75, 29632.50)` bearish,
C `(29632.25, 29636.25, 29629.00, 29630.75)` bearish. None of A/B/C is an
exact doji (`close != open` on all three) — **this triple is not affected
by Correction 1**. Geometry: `C.high(29636.25) < A.low(29638.25)` — exactly
the reported zone, no disagreement.

**Explanation for the visual disagreement:** this is a genuine 2.0-point gap
(`width/ATR = 0.20`, right at this audit's example-selection preference
threshold) on an index trading near 29,636 — real per the literal A-vs-C
rule, but small enough that candle B's much larger range (29631.75–29641.50,
which fully spans both A's low and C's high) visually "fills in" the area
even though A and C's specific levels don't overlap. Retained in the full
population (`fvg_candidates.csv`); **not** selected as one of the 5 audit
examples below (a wider parent was available and is used instead, per the
new "prefer ≥0.20 ATR" audit-selection rule — note this parent is exactly at
0.20, so a slightly wider one was preferred where available for the 2-candle
bucket).

## Regenerated combined audit table

### FVGs — 5, spanning ATR bins

| ID | TF | Dir | Bin | A / B / C (weekday, date, ET) | Zone |
|---|---|---|---|---|---|
| FVG2-000003 | 1m | bullish | <0.05 ATR | Sun Jul 12 2026 18:50 / 18:51 / **18:52 ET** | [29882.75, 29883.00] |
| FVG2-000002 | 1m | bullish | 0.05–<0.10 ATR | Sun Jul 12 2026 18:42 / 18:43 / **18:44 ET** | [29888.00, 29888.75] |
| FVG2-000013 | 1m | bearish | 0.10–<0.20 ATR | Sun Jul 12 2026 20:29 / 20:30 / **20:31 ET** | [29960.75, 29964.00] |
| FVG2-000007 | 1m | bullish | 0.20–<0.30 ATR | Sun Jul 12 2026 19:27 / 19:28 / **19:29 ET** | [29884.75, 29886.50] |
| FVG2-000012 | 1m | bearish | 0.30–<0.50 ATR | Sun Jul 12 2026 20:27 / 20:28 / **20:29 ET** | [29977.25, 29983.50] |

*Instruction:* open NQU6 on 1m at the bolded C time; A/B/C are the 3 candles
ending there. (1m open time == the causal timestamp already reported
previously — unaffected by Correction 2.)

### iFVGs — 5, spanning inversion speed, full parent detail

Selection is now **widest parent per speed bucket** (audit-example rule only,
not a detector threshold), replacing the earlier "first parent ≥0.20 ATR"
rule that surfaced the 2.0-point (0.20 ATR) 2-candle example Dylan correctly
called unusable on a chart. Every parent below is a clean same-colour triple
with **no exact doji**, and every gap is large enough to read directly.

**1. IFVG2-000039** (parent FVG2-000082, 1-candle inversion)
Parent A **Mon Jul 13 2026 7:18 AM ET** `(29780.00, 29780.75, 29765.50,
29766.50)` bearish; B **7:19 AM ET** `(29766.75, 29767.50, 29754.00,
29755.00)` bearish; C **7:20 AM ET** `(29753.25, 29755.00, 29741.50,
29746.00)` bearish. Zone `[29755.00, 29765.50]`, width **10.5 pts**, width/ATR
0.943. Parent formed at C (7:20), remained active with no close-through until
the very next candle. Inversion candle **7:21 AM ET**
`(29744.75, 29769.00, 29744.75, 29769.00)` closes fully through the distal
boundary 29765.50 → **bullish** child.

**2. IFVG2-000274** (parent FVG2-000524, 2-candle inversion) — *replaces the
disputed 2.0-pt example*
Parent A **Thu Jul 16 2026 2:04 AM ET** `(29709.75, 29713.00, 29703.75,
29708.50)` bearish; B **2:05 AM ET** `(29707.50, 29719.75, 29671.75,
29674.00)` bearish; C **2:06 AM ET** `(29674.00, 29677.75, 29654.50,
29666.75)` bearish. Zone `[29677.75, 29703.75]`, width **26.0 pts**, width/ATR
1.616. Parent formed at C (2:06), stayed active through the next candle, then
inverted. Inversion candle **2:08 AM ET** `(29651.50, 29733.00, 29646.50,
29708.25)` closes fully through 29703.75 → **bullish** child. This is a large,
unambiguous 26-point gap — directly inspectable, unlike the old pick.

**3. IFVG2-000006** (parent FVG2-000019, 3-candle inversion, **3m**)
Parent A **Mon Jul 13 2026 1:18 AM ET** `(29656.75, 29661.25, 29633.25,
29633.25)` bearish; B **1:21 AM ET** `(29634.50, 29637.00, 29597.00,
29602.25)` bearish; C **1:24 AM ET** `(29602.25, 29606.00, 29589.75,
29591.00)` bearish. Zone `[29606.00, 29633.25]`, width **27.25 pts**, width/ATR
1.259. Parent formed at C (1:24 open), remained active through 2 further 3m
candles. Inversion candle **1:33 AM ET open** `(29577.75, 29640.25, 29576.50,
29635.00)` closes fully through 29633.25 → **bullish** child. *(3m timestamps
are candle-open, per Correction 2 — open the 3m chart at these times.)*

**4. IFVG2-000280** (parent FVG2-000534, 4-candle inversion)
Parent A **Thu Jul 16 2026 2:54 AM ET** `(29670.75, 29675.25, 29666.25,
29675.25)` bullish; B **2:55 AM ET** `(29674.50, 29687.50, 29672.25,
29685.25)` bullish; C **2:56 AM ET** `(29686.25, 29694.00, 29686.25,
29689.25)` bullish. Zone `[29675.25, 29686.25]`, width **11.0 pts**, width/ATR
1.091. Parent formed at C (2:56), first touched 2:57, remained active through
3 further candles. Inversion candle **3:00 AM ET** `(29684.75, 29686.50,
29648.50, 29650.00)` closes fully through 29675.25 → **bearish** child.

**5. IFVG2-000131** (parent FVG2-000254, 5+-candle inversion)
Parent A **Tue Jul 14 2026 8:29 AM ET** `(29653.25, 29694.00, 29652.50,
29694.00)` bullish; B **8:30 AM ET** `(29694.00, 29908.25, 29677.00,
29901.25)` bullish; C **8:31 AM ET** `(29903.50, 29921.75, 29858.75,
29906.00)` bullish. Zone `[29694.00, 29858.75]`, width **164.75 pts**,
width/ATR 4.953 — the July-14 08:30 cash-open ramp gap. Parent formed at C
(8:31), first touched 8:35, remained active for **93** 1-minute candles.
Inversion candle **10:04 AM ET** `(29722.00, 29733.00, 29690.00, 29692.00)`
closes fully through 29694.00 → **bearish** child. (A slow, large inversion —
maximally visible. The previously-verified compact 5-bar example IFVG2-000002
at Sun Jul 12 7:46–7:51 PM ET remains valid in `ifvg_candidates.csv` if a
tighter 5-candle representative is preferred.)

*(1m timestamps are candle-open == causal time; only the 3m example (#3)
required Correction-2 open-time conversion.)*

### RB — known-good regression examples (retained)

| ID | TF | Dir | Source (open) | Activation (open) | First tap (open) | Deactivation (open) |
|---|---|---|---|---|---|---|
| RB2-000038 | 1m | bearish | Sun Jul 12 **18:59** | Sun Jul 12 **19:00** | Sun Jul 12 **20:01** | Sun Jul 12 **20:02** (CLOSE_THROUGH) |
| RB2-000017 | 3m | bearish | Sun Jul 12 **19:42** | Sun Jul 12 **19:45** | Sun Jul 12 **19:51** | Sun Jul 12 **20:00** (CLOSE_THROUGH) |

### RB — repaired example (RB2-000034(old), now confirmed valid)

| ID | TF | Dir | Source (open) | Activation (open) | First tap (open) | Deactivation (open) |
|---|---|---|---|---|---|---|
| RB2-000022 | 15m | bullish | Mon Jul 13 **03:45** | Mon Jul 13 **04:15** | Mon Jul 13 **09:30** | Mon Jul 13 **09:30** (CLOSE_THROUGH) |

### RB — 3 newly selected corrected examples

| ID | TF | Dir | Source (open) | Activation (open) | First tap (open) | Deactivation (open) | wick/body | dominant ratio |
|---|---|---|---|---|---|---|---:|---:|
| RB2-000438 | 5m | bearish | Tue Jul 14 **20:20** | Tue Jul 14 **20:35** | Tue Jul 14 **20:50** | Tue Jul 14 **21:35** (CLOSE_THROUGH) | 2.04 | 106.0 |
| RB2-000182 | 15m | bearish | Wed Jul 15 **10:00** | Wed Jul 15 **10:15** | (never tapped) | Wed Jul 15 **18:15** (EXPIRED_UNTOUCHED_8H) | 4.29 | 139.5 |
| RB2-000030 | 60m | bullish | Tue Jul 14 **18:00** | Tue Jul 14 **21:00** | Wed Jul 15 **09:00** | Wed Jul 15 **10:00** (CLOSE_THROUGH) | 0.87 | 22.2 |

### RB — rejected/ambiguous counterexamples

| ID | TF | Dir | Source (open) | Zone | wick/body | dominant ratio | Reason |
|---|---|---|---|---|---:|---:|---|
| RB2-000005 (RB2-000009(old) equivalent) | 5m | bullish (reclassified) | Sun Jul 12 **19:30** | [29880.75, 29886.00] | 2.33 | 1.62 | `invalidated_before_confirmation` — no longer qualifies as any RB |

## Tests

```
PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
```
**72 collected, 72 passed, 0 failed, 0 skipped, ~3.5s.** 62 from the prior
suite (unchanged, still passing) + 10 new: 2 exact-doji-colour tests, 2
doji-blocks-FVG/iFVG tests, 2 dominant-wick tests, 5 existing-structure-
precedence tests. Per the task, only this fast suite and the narrow NQU6
audit were run — no evidence, materialization, or historical scan.

## Counts before/after

| | before | after |
|---|---:|---:|
| FVG total | 1,310 | 1,291 |
| iFVG total | 652 | 639 |
| RB candidates total | 16,000 | 8,045 |
| RB confirmed total | 3,709 | 1,951 |
| FVG doji-blocked | n/a | 61 |
| RB equal-wick ambiguous | n/a | 154 |
| RB duplicate/reaction suppressed (precedence) | n/a | 1,699 |
| RB timestamp-order violations | 0 (already fixed prior turn) | **0** |

Validation detail (real NQU6 audit, all 6 timeframes): 1,951 confirmed RBs,
1,684 with a recorded first tap, all 1,951 with a recorded deactivation,
minimum activation→tap and activation→deactivation gap 1 minute (1m
timeframe), **0 timestamp-order violations**.

## Verdict

**PRIMITIVE_AUDIT_READY_WITH_LIMITATIONS**

FVG geometry/traversal/ATR/lifetime are unchanged and remain PASS. The
exact-doji colour gap (iFVG audit was INCONCLUSIVE) is fixed and disclosed
(61 blocked, logged, none silently reclassified). The RB source-selection
FAIL is fixed via dominant-wick selection + existing-structure precedence,
both forensically verified against the exact two failing examples Dylan
flagged — one (RB2-000034-equivalent) is now confirmed correct and
explained, the other (RB2-000009-equivalent) no longer produces any RB and
is reported as a genuine non-example, not defended or hidden. Zero
timestamp-order violations across 1,951 real confirmed RBs. Limitations:
(1) the FVG2-000042(old)-equivalent structure is real but small (2.0 pts,
0.20 ATR) and remains a judgment call for visual review; (2) Part 5's
descriptive iFVG distance/scraping-candle formulas remain provisional per
the original disclosure; (3) the 5m neighbourhood around the old
RB2-000009 genuinely has no clean confirmed replacement — reported honestly
rather than forced. Primitives are not claimed correct until Dylan performs
the combined audit above himself.

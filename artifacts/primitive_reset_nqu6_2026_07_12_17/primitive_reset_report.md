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

Before creating a new RB candidate, the detector checks whether an
already-active same-direction RB was tapped by *this* candle (using the
tap/traversal state already computed for that RB, strictly from candles
before the current one — no look-ahead) **and whose zone the proposed new
wick zone overlaps** (see Correction 5). If so, the tap is recorded on the
**original** RB and no duplicate overlapping RB is created from the reaction
candle; logged to `rb_precedence_suppressed.csv`. Opposite-direction
candidates on the same candle are never suppressed by this rule.

## Correction 5 — precedence requires actual zone overlap

The first version of Correction 4 suppressed a new candidate whenever *any*
active same-direction RB was tapped, keyed on direction alone — broader than
the frozen rule, which requires the reaction to actually re-enter the
existing RB's zone. Fixed: the detector now retains the exact tapped active
RB objects (not just their directions) and suppresses a proposed candidate
`[zlo, zhi]` only when a tapped same-direction RB `[old_lo, old_hi]` satisfies
inclusive interval intersection `max(zlo, old_lo) <= min(zhi, old_hi)`. A
same-direction tap of a *different, non-overlapping* zone now proceeds to a
new candidate normally; opposite-direction candidates are still never
suppressed by this rule; with multiple active same-direction RBs, suppression
fires if the candidate overlaps *any* tapped zone (the suppression record
cites the specific overlapping RB). No future information is used.

**Impact:** overlap-qualified suppression was 1,699 → 1,550 (149
direction-matched taps whose zones did not actually overlap were re-allowed).
That figure changes again under Correction 6 below (all candidates now live).

## Correction 6 — activation is no longer a usability gate (RB lifecycle)

Per Dylan: a rejection block should be a usable structure the moment its
source candle closes, not only if it later produces a 1.5x-ATR move. Many
valid RBs are tapped and react on the very next candle without ever making
that move; gating usability on activation discarded exactly those.

**Change (rejection_block.py, then frozen):** every dominant-wick candle that
clears the 0.20 floor becomes a **live** RB from its source-candle close and
is tracked forward under the common traversal contract. The 1.5x-ATR /
next-3-candle MFE rule is still computed — exactly as before, now
incrementally during forward processing — but only sets a descriptive
**`activated`** status (with `activation_seq`/`activation_candle_number`);
it never gates whether the RB exists. Each tap is stamped
**`was_activated`** = the RB's activated state at that candle, so a setup
taken at a tap can be labelled activated / not-activated **causally, with no
look-ahead** (`RBCandidateRecord.was_activated_at(seq)`). The 8h intraday
lifetime is re-anchored from activation to source-candle close (its new
birth); the 0.20 floor, dominant-wick selection, the MFE computation itself,
the traversal contract and overlap precedence are unchanged.

**Consequences (NQU6 audit):**
- **5,165 live RBs** total — **1,132 activated**, **4,033 not-activated**.
- **4,384** live RBs had their *first* tap occur before (or without)
  activation — the newly-usable "fresh wick that reacted" class.
- Precedence-suppressed rose **1,550 → 4,579**: because *all* dominant-wick
  candles are now live (not just the ~2k that used to activate), far more
  reaction candles tap-and-overlap an existing live RB and are correctly
  suppressed as duplicates. This is the frozen overlap-precedence rule acting
  over a larger live population, not a rule change — it means choppy zones
  keep one structural RB instead of one per candle. Flagged for awareness.
- **0** causal-invariant violations across all 5,165 live RBs (source <
  first-tap; source ≤ deactivation; activation, when set, after source; every
  tap's `was_activated` equals `was_activated_at(tap_seq)`).

The two forensic audits below predate this change (they were about
dominant-wick *direction* selection, which is unchanged); RB2-000009's source
candle is still bullish-dominant, and RB2-000034's is still the 03:45 source
— both conclusions stand. Under the new model a non-activating RB is retained
as a live structure rather than dropped, so "no longer qualifies as any RB"
now reads "is a live, not-activated RB".

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

### FVGs — 5, a refreshed one-per-ATR-bin sample

These are one representative FVG per ATR size bin (the first match per bin),
**a refreshed sample — not literally the same five examples Dylan approved
earlier**. The full FVG population is in `fvg_candidates.csv`; the geometry,
ATR and bin definitions are unchanged (frozen).

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
maximally visible, but 93 bars is far beyond a "just over 5" representative;
see #6 for a clean compact one.)

**6. IFVG2-000002** (parent FVG2-000001, **5m**, 6-candle inversion — clean
compact companion to #5, retained per request)
Parent A **Sun Jul 12 2026 7:55 PM ET** `(29876.50, 29895.00, 29865.75,
29893.25)` bullish; B **8:00 PM ET** `(29892.00, 29986.25, 29871.50,
29965.50)` bullish; C **8:05 PM ET** `(29967.00, 30007.75, 29953.50,
29995.50)` bullish. Zone `[29895.00, 29953.50]`, width **58.5 pts**, width/ATR
1.756 — a clean, large, doji-free gap. Parent formed at C (8:05 open), first
touched 8:30, remained active for **6** 5-minute candles. Inversion candle
**8:35 PM ET open** `(29912.00, 29928.50, 29886.00, 29894.00)` closes fully
through 29895.00 → **bearish** child. *(5m timestamps are candle-open, per
Correction 2.)*

*(1m timestamps are candle-open == causal time; the 3m example (#3) and the
5m example (#6) required Correction-2 open-time conversion.)*

### RB — ACTIVATED examples (reached 1.5x ATR within 3 candles)

Note the `1st tap activated?` column: an RB can be tapped *before* it
activates (RB2-000272 below), and that first tap is correctly stamped
not-activated even though the RB later activates.

| ID | TF | Dir | Source (open) | Activated (open) | 1st tap (open) | 1st tap activated? | Deactivation (open) |
|---|---|---|---|---|---|---|---|
| RB2-000272 | 5m | bearish | Tue Jul 14 **8:20 PM** | Tue Jul 14 **8:35 PM** | Tue Jul 14 **8:25 PM** | **No** | Tue Jul 14 **9:35 PM** (CLOSE_THROUGH) |
| RB2-000102 | 15m | bearish | Wed Jul 15 **10:00 AM** | Wed Jul 15 **10:15 AM** | Wed Jul 15 **10:15 AM** | **Yes** | Wed Jul 15 **6:00 PM** (EXPIRED_ACTIVE_8H) |
| RB2-000033 | 60m | bearish | Thu Jul 16 **5:00 AM** | Thu Jul 16 **7:00 AM** | never tapped | — | Fri Jul 17 **4:00 PM** (DATA_END_ACTIVE) |

### RB — NOT-ACTIVATED examples (newly usable: tapped and reacted without the 1.5x-ATR move)

These are the class the activation-gate removal unlocks — a fresh dominant
wick that price returns to and reacts from, but which never made the 1.5x-ATR
move. Every first tap here is stamped **not-activated** (causal at the tap).

| ID | TF | Dir | Source (open) | Zone | 1st tap (open) | 1st tap activated? | n taps | Deactivation |
|---|---|---|---|---|---|---|---:|---|
| RB2-000045 | 15m | bearish | Mon Jul 13 **10:00 PM** | [29447.25, 29489.00] | Mon Jul 13 **10:30 PM** | No | 5 | CLOSE_THROUGH |
| RB2-000485 | 5m | bullish | Thu Jul 16 **11:05 AM** | [29366.00, 29392.75] | Thu Jul 16 **11:10 AM** | No | 1 | CLOSE_THROUGH |
| RB2-000952 | 3m | bearish | Fri Jul 17 **4:27 AM** | [28609.75, 28634.25] | Fri Jul 17 **4:30 AM** | No | 5 | CLOSE_THROUGH |
| RB2-002318 | 1m | bearish | Thu Jul 16 **10:02 AM** | [29393.50, 29417.75] | Thu Jul 16 **10:03 AM** | No | 3 | CLOSE_THROUGH |
| RB2-000012 | 30m | bullish | Mon Jul 13 **10:00 AM** | [29488.50, 29631.00] | Mon Jul 13 **10:30 AM** | No | 6 | CLOSE_THROUGH |

*(Full per-tap activation status for every RB is in `rb_tap_events.csv`; all
live RBs with activation flags are in `rb_candidates.csv`.)*

## Tests

```
PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
```
**69 collected, 69 passed, 0 failed, 0 skipped.** The RB-lifecycle change
retired the obsolete pending-activation-queue tests (activation no longer
gates tracking) and added new ones: a non-activated RB is still live and
tappable; a tap before activation is stamped not-activated while a later tap
after activation is stamped activated; `was_activated_at` never reports
activation early; 8h lifetime is measured from source; and a real-NQU6
invariant check over all 5,165 live RBs (0 causal violations). Per the task,
only this fast suite and the narrow NQU6 audit were run — no evidence,
materialization, or historical scan.

## Counts (current, after the RB-lifecycle change)

FVG / iFVG counts are unchanged by the RB-lifecycle change. "RB live" now
means every dominant-wick floor-passer (usable regardless of activation);
"activated" is the descriptive 1.5x-ATR subset.

| | value | note |
|---|---:|---|
| FVG total | 1,291 | 19 removed from eligibility by exact-doji rule |
| iFVG total | 639 | 13 removed (children of those FVGs) |
| FVG doji-blocked (diagnostic) | 61 | superset of geometry-valid triples with a doji |
| **RB live total** | **5,165** | all dominant-wick floor-passers, usable |
| RB activated | 1,132 | reached 1.5x ATR within 3 candles |
| RB not-activated | 4,033 | live & usable, never made the 1.5x-ATR move |
| RB first-tap-before-activation | 4,384 | the newly-usable "fresh wick reacted" class |
| RB equal-wick ambiguous (diagnostic) | 154 | no active RB |
| RB precedence-suppressed | 4,579 | reaction candles overlapping an existing live RB |
| RB causal-invariant violations | **0** | source<tap, source≤deact, activation after source, tap flags causal |

Precedence-suppressed rose from 1,550 (previous, over the ~2k activated-only
population) to 4,579 because the overlap-precedence rule now runs over all
5,165 live RBs — same frozen rule, larger live population (disclosed under
Correction 6).

## Verdict

**PRIMITIVE_AUDIT_READY_WITH_LIMITATIONS**

FVG, iFVG and RB primitives are all verified by Dylan on NQU6 and now
**frozen** (`src/discretion/primitive_reset/__init__.py` records the frozen
contract). FVG geometry/ATR/traversal/lifetime unchanged; exact-doji colour
gap fixed and disclosed; RB direction via dominant-wick with overlap-gated
precedence; and rejection blocks are now usable from source-candle close with
activation tracked as a causal, look-ahead-free status (Correction 6), so a
setup can label an RB activated / not-activated at the moment it is taken.
Zero causal-invariant violations across all 5,165 live RBs. Limitations:
(1) removing the activation gate greatly enlarges the live RB population and,
via the frozen overlap-precedence rule, raises suppression to 4,579 — choppy
zones keep one structural RB rather than one per candle (flagged, not a rule
change); (2) the small 2.0-pt iFVG-parent case and Part 5's provisional
iFVG distance/scraping formulas remain as previously disclosed. The primitives
are frozen and audit-ready; edge is not claimed and requires the deliberately-
deferred historical/adaptive-evidence machinery.

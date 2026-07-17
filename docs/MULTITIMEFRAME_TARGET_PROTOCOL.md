# Multi-Timeframe Target Protocol (frozen)

Freezes the causal multi-timeframe target inventory and the branch-aware target
resolver used by the graph-native engine. Frozen **before** the development
replay. Development data only; nothing here is forward evidence or an edge claim.

## 0. Canonical aggregation decision
The canonical `src/discretion/` layer had **no** HTF aggregation. The only
multi-timeframe code in the repo is the legacy, contaminated `phase1/recognizer/`,
which is **not** reused (it belongs to the exploratory history). This adds a
**single** canonical aggregation under `src/discretion/data/aggregation.py`. No
third aggregation stack is created.

## 1. Setup logic (the objective)
A setup identifies (a) a causally coherent graph path, (b) a genuine structural
invalidation (stop), (c) a genuine structural objective where price may react or
reverse (target), and (d) the natural reward-to-risk of those two structures. The
engine never invents a farther target, never tightens a stop, never chooses stop
or target from a later outcome, never treats every horizontal level as equally
meaningful, never assumes price traverses the whole target zone, and never accepts
a natural target below 0.5R.

## 2. Frozen reward-to-risk policy
Identify, without future information: entry, natural structural stop, natural
structural target.
```
risk           = abs(entry - structural_stop)
natural_reward = abs(structural_target - entry)
natural_RR     = natural_reward / risk
```
Geometry must be directionally valid: long `stop < entry < target`; short
`target < entry < stop`. Any violation is rejected before entry.
* `natural_RR < 0.5` → reject (`INSUFFICIENT_NATURAL_RR`); never activated; stop
  not tightened; no farther target; no later-bar search.
* `0.5 <= natural_RR < 1.0` → executed target = natural target; executed RR =
  natural RR.
* `natural_RR >= 1.0` → retain natural target/RR for diagnostics; executed target
  capped at exactly 1R (`entry ± risk`); executed RR = 1.0; **not** rejected for
  being farther than 1R.
Executed RR always lies in `[0.5, 1.0]`. The 1R executed target may fall before
the farther structural objective — intentional.

## 3. HTF aggregation semantics (5m/15m/30m/60m)
Each higher-timeframe candle stores: timeframe, open timestamp,
close/availability timestamp, source one-minute bar index range, OHLCV, absolute
segment id, normalization segment id, ATR, permanent candle id.
* Bucketing is by **ET wall-clock** anchored to the frozen CME session open
  (18:00 ET): 60m boundaries fall on the hour (18:00, 19:00, …) so they are
  session-aligned, not arbitrary UTC buckets; 30m on :00/:30; 15m on
  :00/:15/:30/:45; 5m on every 5 minutes. DST-aware.
* A candle is **unavailable** until its final constituent one-minute bar closes;
  `available_seq` = index of the first 1-minute bar after the bucket. No partial
  HTF candle creates any structure.
* Structures never cross an absolute contract-roll segment (bucket keyed by
  segment id).
* ATR is causal Wilder ATR over **previous completed** same-timeframe candles; the
  current candle is excluded from its own ATR and from all trailing percentiles.
* Percentiles use previous 40 completed same-timeframe candles (current excluded).
* IDs are deterministic (`HTF{tf}-NNNNNN`); reruns are identical.

## 4. Prominent-wick liquidity
`ProminentWickLiquidity` = liquidity at the **exposed** wick of a completed
5m/15m/30m/60m candle — not every candle high/low.

Raw geometry per completed candle: `body_top=max(open,close)`,
`body_bottom=min(open,close)`, `upper_wick=high-body_top`,
`lower_wick=body_bottom-low`, `range=high-low`. Per side store wick length,
wick/ATR, wick/range, wick/body (zero-body safe), range/ATR, close-location,
protrusion beyond previous completed candles, wick/ATR percentile and range/ATR
percentile vs previous 40 (current excluded), and prior 5/10/20-bar extremeness.

**Exposed non-overlapped surface** (immutable variants N=3, 5, 10):
* upper wick: full `[body_top, high]`; exposed lower boundary(N) =
  `max(body_top, max(previous N highs))`; exposed `[boundary, high]`, exists iff
  boundary `< high` strictly.
* lower wick: full `[low, body_bottom]`; exposed upper boundary(N) =
  `min(body_bottom, min(previous N lows))`; exposed `[low, boundary]`, exists iff
  `low <` boundary strictly.

**Prominence score** (causal 0–100, prior same-tf distributions only):
`30% wick/ATR pct + 20% wick/range + 20% range/ATR pct +
20% exposed-protrusion/ATR pct + 10% close-away-from-wick`.
close-away: upper wick → higher as close nears the low; lower wick → higher as
close nears the high. Grades: `HIGH ≥ 80`, `MEDIUM 65–<80`, `LOW < 65`. LOW is
retained in the audit ledger but only MEDIUM/HIGH are default executable targets.
Thresholds are frozen and never changed from outcomes.

**States** (tracked on completed 1-minute bars after availability): an exact
boundary touch without positive overlap does **not** consume freshness; any
positive overlap into the exposed zone → `OVERLAPPED`; a trade through the extreme
→ `SWEPT`; a body close through the whole exposed zone → `CLOSED_THROUGH`.
OVERLAPPED/SWEPT/CLOSED_THROUGH are no longer fresh default targets. Objects are
never deleted. Each object stores the full state set listed in the task.

**Frontmost / occlusion** (per candidate timestamp + direction): retain every
active target ahead of price; the nearest proximal boundary is `frontmost`;
farther active targets are `occluded_by_object_id`; store distance in ATR; never
delete occluded structures.

## 5. HTF FVG / iFVG target inventory
FVGs are detected **independently** on completed 5m/15m/30m/60m candles using the
canonical three-candle definition (not by grouping 1-minute FVGs). Store id, tf,
direction, A/B/C candle ids, proximal/distal boundary, midpoint (consequent
encroachment), width, width/ATR, formation/availability (after C closes), segment
ids, freshness, and the lifecycle states (first touch, first positive fill,
midpoint, full fill, failure, iFVG activation, invalidation, parent/child
lineage). A failed HTF FVG becomes an HTF iFVG carrying parent lineage.

Default HTF-FVG target eligibility: available before trigger; same segment;
active; fresh; ahead of entry in trade direction; opposing/branch-relevant
direction; not fully filled; not failed before trigger; not occluded under the
selected policy. Long ↦ an opposing bearish HTF FVG above price; short ↦ an
opposing bullish HTF FVG below price.

**Target surfaces** per zone: `PROXIMAL_EDGE` (default — price may reverse on
initial entry), `MIDPOINT`, `DISTAL_EDGE`. Midpoint/distal are **separate named
research variants**; the surface is never chosen retrospectively.

## 6. Target-candidate universe and policies
At each graph-native trigger timestamp collect every causally available target
ahead of price from: prominent-wick liquidity (5/15/30/60m), HTF FVGs
(5/15/30/60m), HTF iFVGs, active RBs, confirmed swings, historical/session levels,
time-anchor levels, VWAP + 1.618/2.618/3.618 bands, compression/range boundaries,
and branch-native objectives. Each `TargetCandidate` stores object id, family,
subtype, timeframe, direction, target surface, price, availability, freshness,
prominence grade (where relevant), age, touches/overlaps, frontmost, occlusion,
distance (points and ATR), natural RR under the frozen stop, eligibility and
rejection reasons. Rejection reasons: `NOT_AVAILABLE_AT_TRIGGER`, `WRONG_DIRECTION`,
`WRONG_SIDE_OF_ENTRY`, `STALE`, `OVERLAPPED`, `SWEPT`, `FILLED`, `FAILED`,
`CROSS_SEGMENT`, `LOW_PROMINENCE`, `OCCLUDED`, `TARGET_BELOW_MIN_RR`,
`NO_STRUCTURAL_RELATIONSHIP`.

**Four frozen policies** (each yields a separate research candidate variant only
when it finds a valid target; never collapsed; never simultaneous live trades):
* `BRANCH_SEMANTIC` — a frozen per-path hierarchy identified by a rule id.
* `NEAREST_VALID_STRUCTURE` — nearest fresh frontmost eligible structure from any
  allowed family.
* `NEAREST_PROMINENT_WICK` — only MEDIUM/HIGH 5/15/30/60m wick targets.
* `NEAREST_OPPOSING_HTF_FVG` — only eligible opposing HTF FVG targets, proximal
  edge by default.
Each variant stores `target_policy_id`, `target_surface_policy`,
`target_anchor_type/object_id/timeframe/price`, the full considered-target ledger,
selected-target rank and selection-rule id. `target_policy_id`, target family,
timeframe, prominence grade and surface policy enter the causal feature vector;
the recognizer's exact/reduced/hard compatibility treats different target policies
as **not** equivalent.

**Stops** keep the existing branch-specific resolver (RB/FVG/iFVG boundary, swept
extreme, accepted-level boundary, compression region, anchor boundary, VWAP/band
failure boundary, confirmed swing / prominent-wick extreme where that structure is
the origin). Stop placement never depends on target distance.

## 7. RR application order (frozen)
1. freeze graph; 2. freeze entry; 3. freeze natural stop; 4. build the target
inventory available at that moment; 5. select target under the frozen policy;
6. compute natural RR; 7. reject `<0.5R`; 8. retain natural `0.5–<1R`; 9. cap
`>=1R` to executed 1R; 10. store candidate; 11. **only afterward** evaluate
outcome. Outcome never affects stop, target or policy selection.

## 8. Causal availability & audit
Every structure is usable only when `available_seq <= trigger_seq`. Target
selection reads no future object or bar. The audit shows, per candidate: all
considered targets, each rejection reason, the selected target (id/family/tf/
surface/policy), natural + executed RR, and a chart with the HTF zone visible.

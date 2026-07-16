# Phase 1B — Compact Audit Pack

Deterministic primitive examples + observational candidate setups. All examples are chosen chronologically or by a structural (ATR-normalized) metric — never by outcome. Charts are in `charts/` and `candidate_setups/`.


## Fair Value Gaps (bullish & bearish, per timeframe)

**first bull FVG 1m (FVG-1m-bull-20260706T0005)** — `fvg_1m_bull.png`

![fvg_1m_bull.png](charts/fvg_1m_bull.png)

**first bull FVG 5m (FVG-5m-bull-20260706T0015)** — `fvg_5m_bull.png`

![fvg_5m_bull.png](charts/fvg_5m_bull.png)

**first bull FVG 15m (FVG-15m-bull-20260706T0015)** — `fvg_15m_bull.png`

![fvg_15m_bull.png](charts/fvg_15m_bull.png)

**first bull FVG 30m (FVG-30m-bull-20260706T0300)** — `fvg_30m_bull.png`

![fvg_30m_bull.png](charts/fvg_30m_bull.png)

**first bull FVG 1h (FVG-1h-bull-20260707T1300)** — `fvg_1h_bull.png`

![fvg_1h_bull.png](charts/fvg_1h_bull.png)

**first bull FVG 4h (FVG-4h-bull-20260709T1200)** — `fvg_4h_bull.png`

![fvg_4h_bull.png](charts/fvg_4h_bull.png)


## Inverse FVG conversions (bullish & bearish)

**first_ifvg_to_bull** — `ifvg_bull.png`

![ifvg_bull.png](charts/ifvg_bull.png)

**first_ifvg_to_bear** — `ifvg_bear.png`

![ifvg_bear.png](charts/ifvg_bear.png)


## Rejection blocks (bull/bear, invalidation & exact-boundary touch)

**bullish rejection block** — `rejblock_bull_example.png`

![rejblock_bull_example.png](charts/rejblock_bull_example.png)

**bearish rejection block** — `rejblock_bear_example.png`

![rejblock_bear_example.png](charts/rejblock_bear_example.png)

**exact-boundary body touch** — `rejblock_exact_boundary_touch.png`

![rejblock_exact_boundary_touch.png](charts/rejblock_exact_boundary_touch.png)

**top valid rejection #1 5m** — `rejblock_top1_5m.png`

![rejblock_top1_5m.png](charts/rejblock_top1_5m.png)

**top valid rejection #2 1m** — `rejblock_top2_1m.png`

![rejblock_top2_1m.png](charts/rejblock_top2_1m.png)

**top valid rejection #3 daily** — `rejblock_top3_daily.png`

![rejblock_top3_daily.png](charts/rejblock_top3_daily.png)

**first invalidation by body overlap** — `rejblock_first_bodyoverlap.png`

![rejblock_first_bodyoverlap.png](charts/rejblock_first_bodyoverlap.png)

**first invalidation by complete wick traversal** — `rejblock_first_traversal.png`

![rejblock_first_traversal.png](charts/rejblock_first_traversal.png)


## Liquidity references (swept & unswept, each source)

**liquidity_swept candle_0900_high** — `liq_candle_0900_high_swept.png`

![liq_candle_0900_high_swept.png](charts/liq_candle_0900_high_swept.png)

**liquidity_swept candle_0900_low** — `liq_candle_0900_low_swept.png`

![liq_candle_0900_low_swept.png](charts/liq_candle_0900_low_swept.png)

**liquidity_swept candle_0930_high** — `liq_candle_0930_high_swept.png`

![liq_candle_0930_high_swept.png](charts/liq_candle_0930_high_swept.png)

**liquidity_swept candle_0930_low** — `liq_candle_0930_low_swept.png`

![liq_candle_0930_low_swept.png](charts/liq_candle_0930_low_swept.png)

**liquidity_swept candle_1000_high** — `liq_candle_1000_high_swept.png`

![liq_candle_1000_high_swept.png](charts/liq_candle_1000_high_swept.png)

**liquidity_swept candle_1000_low** — `liq_candle_1000_low_swept.png`

![liq_candle_1000_low_swept.png](charts/liq_candle_1000_low_swept.png)

**liquidity_swept overnight_high** — `liq_overnight_high_swept.png`

![liq_overnight_high_swept.png](charts/liq_overnight_high_swept.png)

**liquidity_swept overnight_low** — `liq_overnight_low_swept.png`

![liq_overnight_low_swept.png](charts/liq_overnight_low_swept.png)

**liquidity_swept prev_rth_high** — `liq_prev_rth_high_swept.png`

![liq_prev_rth_high_swept.png](charts/liq_prev_rth_high_swept.png)

**liquidity_swept prev_rth_low** — `liq_prev_rth_low_swept.png`

![liq_prev_rth_low_swept.png](charts/liq_prev_rth_low_swept.png)

**liquidity_unswept overnight_low** — `liq_overnight_low_unswept.png`

![liq_overnight_low_unswept.png](charts/liq_overnight_low_unswept.png)

**liquidity_unswept prev_rth_high** — `liq_prev_rth_high_unswept.png`

![liq_prev_rth_high_unswept.png](charts/liq_prev_rth_high_unswept.png)

**liquidity_unswept prev_rth_low** — `liq_prev_rth_low_unswept.png`

![liq_prev_rth_low_unswept.png](charts/liq_prev_rth_low_unswept.png)


## Displacement (good / mixed / bad, several timeframes)

**displacement_high** — `disp_high.png`

![disp_high.png](charts/disp_high.png)

**displacement_middle** — `disp_middle.png`

![disp_middle.png](charts/disp_middle.png)

**displacement_low** — `disp_low.png`

![disp_low.png](charts/disp_low.png)


## Observational candidate setups (frozen grammar CG-1)

_Observational only — not evidence of edge. Selected chronologically, not by outcome; losers kept; nothing altered after the outcome was seen._


| ID | tf | dir | trigger (ET) | swept | entry | stop | target | outcome |
|---|---|---|---|---|--:|--:|--:|---|
| CG1-5m-20260706T1340-L | 5m | long | 2026-07-06 13:40 | candle_1000_low | 29923.75 | 29903.25 | 29924.25 | **incomplete** |
| CG1-5m-20260706T2120-L | 5m | long | 2026-07-06 21:20 | prev_rth_low | 29787.25 | 29776.25 | 29790.75 | **ambiguous** |
| CG1-30m-20260707T1000-L | 30m | long | 2026-07-07 10:00 | prev_rth_low | 29377.0 | 29273.75 | 29414.75 | **loss** |
| CG1-30m-20260708T1030-L | 30m | long | 2026-07-08 10:30 | candle_0930_low | 29245.5 | 29201.0 | 29277.5 | **incomplete** |
| CG1-15m-20260709T0345-S | 15m | short | 2026-07-09 03:45 | prev_rth_high | 29681.5 | 29685.75 | 29675.75 | **ambiguous** |
| CG1-5m-20260710T0940-L | 5m | long | 2026-07-10 09:40 | candle_0930_low | 29913.5 | 29812.5 | 29918.0 | **win** |
| CG1-30m-20260710T1030-L | 30m | long | 2026-07-10 10:30 | overnight_low | 30004.0 | 29717.25 | 30011.25 | **win** |


**CG1-5m-20260706T1340-L** [long] — trigger 2026-07-06 13:40, outcome **incomplete**

- trigger: sweep of `candle_1000_low` @ 29903.25
- context: swept:candle_1000_low | session:RTH | fvg_width_atr:0.397
- entry 29923.75 · structural stop 29903.25 · structural target 29924.25 · expiry E=20 bars
- primitives: LIQ:candle_1000_low@29903.25 ; FVG:FVG-5m-bull-20260706T1405 ; DISP:bull-leg->C106582

![CG1-5m-20260706T1340-L.png](candidate_setups/CG1-5m-20260706T1340-L.png)


**CG1-5m-20260706T2120-L** [long] — trigger 2026-07-06 21:20, outcome **ambiguous**

- trigger: sweep of `prev_rth_low` @ 29776.25
- context: swept:prev_rth_low | session:ONX | fvg_width_atr:0.376
- entry 29787.25 · structural stop 29776.25 · structural target 29790.75 · expiry E=20 bars
- primitives: LIQ:prev_rth_low@29776.25 ; FVG:FVG-5m-bull-20260706T2145 ; DISP:bull-leg->C106662

![CG1-5m-20260706T2120-L.png](candidate_setups/CG1-5m-20260706T2120-L.png)


**CG1-30m-20260707T1000-L** [long] — trigger 2026-07-07 10:00, outcome **loss**

- trigger: sweep of `prev_rth_low` @ 29273.75
- context: swept:prev_rth_low | session:RTH | fvg_width_atr:0.19
- entry 29377.0 · structural stop 29273.75 · structural target 29414.75 · expiry E=20 bars
- primitives: LIQ:prev_rth_low@29273.75 ; FVG:FVG-30m-bull-20260707T1200 ; DISP:bull-leg->C17808

![CG1-30m-20260707T1000-L.png](candidate_setups/CG1-30m-20260707T1000-L.png)


**CG1-30m-20260708T1030-L** [long] — trigger 2026-07-08 10:30, outcome **incomplete**

- trigger: sweep of `candle_0930_low` @ 29201.0
- context: swept:candle_0930_low | session:RTH | fvg_width_atr:0.721
- entry 29245.5 · structural stop 29201.0 · structural target 29277.5 · expiry E=20 bars
- primitives: LIQ:candle_0930_low@29201.0 ; FVG:FVG-30m-bull-20260708T1230 ; DISP:bull-leg->C17855

![CG1-30m-20260708T1030-L.png](candidate_setups/CG1-30m-20260708T1030-L.png)


**CG1-15m-20260709T0345-S** [short] — trigger 2026-07-09 03:45, outcome **ambiguous**

- trigger: sweep of `prev_rth_high` @ 29685.75
- context: swept:prev_rth_high | session:ONX | fvg_width_atr:0.258
- entry 29681.5 · structural stop 29685.75 · structural target 29675.75 · expiry E=20 bars
- primitives: LIQ:prev_rth_high@29685.75 ; FVG:FVG-15m-bear-20260709T0445 ; DISP:bear-leg->C35766

![CG1-15m-20260709T0345-S.png](candidate_setups/CG1-15m-20260709T0345-S.png)


**CG1-5m-20260710T0940-L** [long] — trigger 2026-07-10 09:40, outcome **win**

- trigger: sweep of `candle_0930_low` @ 29812.5
- context: swept:candle_0930_low | session:RTH | fvg_width_atr:0.861
- entry 29913.5 · structural stop 29812.5 · structural target 29918.0 · expiry E=20 bars
- primitives: LIQ:candle_0930_low@29812.5 ; FVG:FVG-5m-bull-20260710T0950 ; DISP:bull-leg->C107635

![CG1-5m-20260710T0940-L.png](candidate_setups/CG1-5m-20260710T0940-L.png)


**CG1-30m-20260710T1030-L** [long] — trigger 2026-07-10 10:30, outcome **win**

- trigger: sweep of `overnight_low` @ 29717.25
- context: swept:overnight_low | session:RTH | fvg_width_atr:0.123
- entry 30004.0 · structural stop 29717.25 · structural target 30011.25 · expiry E=20 bars
- primitives: LIQ:overnight_low@29717.25 ; FVG:FVG-30m-bull-20260710T1230 ; DISP:bull-leg->C17947

![CG1-30m-20260710T1030-L.png](candidate_setups/CG1-30m-20260710T1030-L.png)

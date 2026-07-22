# Development-week pre-outcome setup cards — NQU6, Jul 5–10 2026
Fully causal replay over the FROZEN audited primitive-reset structures (FVG / iFVG / RB). **No outcomes** are computed or attached — this is the pre-outcome review stage. These are the **first 12 trigger events in strict chronological order** (by entry bar), selected with no reference to outcome, clarity, family, timeframe or RR.
- Data coverage: 2026-07-05 18:00:00-04:00 → 2026-07-10 16:59:00-04:00 (6900 bars).
- Total trigger events: **5671** (executable 284, rejected 5387). Families: {'RB_TAP': 5015, 'IFVG_ACTIVATION': 656}.
- Terminology: TRIGGER_EVENT (branch completed) vs EXECUTABLE_SETUP (valid stop + causal target + RR ≥ 0.5 + not occupancy-rejected) vs REJECTED_TRIGGER. Not a trade until a next-bar entry and its path are processed — not done here.
- `activated_at_trigger` is a descriptive branch feature (causal at the tap), **not** an eligibility gate — an RB can trigger while not activated.
- Displacement / compression state: **N/A** — not part of the audited FVG/iFVG/RB vocabulary (no invented structures).

## TRIG-00001 — RB_TAP (LONG, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:16 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000001 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000001 — rb 1m, source Sunday, July 5, 2026, 6:14 PM ET, zone [29892.25, 29895.25]
- **RB wick/body:** 0.48 | **dominant-wick ratio:** 6.0
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq15 was_activated=False; tap@seq16 was_activated=False
- **Proposed next-bar entry:** 29897.25
- **Frozen structural stop:** 29892.25 (anchor RB2-000001) — below the rejection block's source-candle low (wick extreme)
- **Target:** none causally available
- **Natural RR:** n/a
- **Status:** REJECTED_TRIGGER (NO_CAUSAL_TARGET)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a long reaction out of the block; rejected: NO_CAUSAL_TARGET.

## TRIG-00002 — RB_TAP (LONG, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:19 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000002 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000002 — rb 1m, source Sunday, July 5, 2026, 6:17 PM ET, zone [29907.25, 29911.5]
- **RB wick/body:** 1.7 | **dominant-wick ratio:** 1.06
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq18 was_activated=False
- **Proposed next-bar entry:** 29894.25
- **Frozen structural stop:** 29907.25 (anchor RB2-000002) — below the rejection block's source-candle low (wick extreme)
- **Target:** 29909.25 (structure RB2-000003 — rb 1m zone [29909.25, 29913.0], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** n/a
- **Status:** REJECTED_TRIGGER (NO_STRUCTURAL_STOP)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a long reaction out of the block; rejected: NO_STRUCTURAL_STOP.

## TRIG-00003 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:20 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000003 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000003 — rb 1m, source Sunday, July 5, 2026, 6:18 PM ET, zone [29909.25, 29913.0]
- **RB wick/body:** 0.28 | **dominant-wick ratio:** 1.25
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq19 was_activated=False; tap@seq20 was_activated=False
- **Proposed next-bar entry:** 29905.25
- **Frozen structural stop:** 29913.0 (anchor RB2-000003) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29895.25 (structure RB2-000001 — rb 1m zone [29892.25, 29895.25], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 1.29
- **Status:** EXECUTABLE_SETUP
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; executable.

## TRIG-00004 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:22 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000004 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000004 — rb 1m, source Sunday, July 5, 2026, 6:20 PM ET, zone [29929.5, 29939.0]
- **RB wick/body:** 0.39 | **dominant-wick ratio:** 3.17
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq21 was_activated=False; tap@seq22 was_activated=False
- **Proposed next-bar entry:** 29928.0
- **Frozen structural stop:** 29939.0 (anchor RB2-000004) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29927.25 (structure RB2-000005 — rb 1m zone [29922.5, 29927.25], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 0.07
- **Status:** REJECTED_TRIGGER (INSUFFICIENT_NATURAL_RR)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; rejected: INSUFFICIENT_NATURAL_RR.

## TRIG-00005 — RB_TAP (LONG, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:24 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000005 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000005 — rb 1m, source Sunday, July 5, 2026, 6:21 PM ET, zone [29922.5, 29927.25]
- **RB wick/body:** 1.27 | **dominant-wick ratio:** 1.73
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq23 was_activated=False; tap@seq24 was_activated=False; tap@seq25 was_activated=False; tap@seq26 was_activated=False; tap@seq27 was_activated=False; tap@seq28 was_activated=False; tap@seq70 was_activated=False; tap@seq121 was_activated=False
- **Proposed next-bar entry:** 29931.5
- **Frozen structural stop:** 29922.5 (anchor RB2-000005) — below the rejection block's source-candle low (wick extreme)
- **Target:** 29942.0 (structure RB2-000006 — rb 1m zone [29942.0, 29948.75], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 1.17
- **Status:** EXECUTABLE_SETUP
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a long reaction out of the block; executable.

## TRIG-00006 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:24 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000006 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000006 — rb 1m, source Sunday, July 5, 2026, 6:22 PM ET, zone [29942.0, 29948.75]
- **RB wick/body:** 0.48 | **dominant-wick ratio:** 27.0
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq23 was_activated=False; tap@seq24 was_activated=False; tap@seq28 was_activated=False; tap@seq29 was_activated=False; tap@seq30 was_activated=False; tap@seq31 was_activated=False; tap@seq32 was_activated=False
- **Proposed next-bar entry:** 29931.5
- **Frozen structural stop:** 29948.75 (anchor RB2-000006) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29927.25 (structure RB2-000005 — rb 1m zone [29922.5, 29927.25], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 0.25
- **Status:** REJECTED_TRIGGER (INSUFFICIENT_NATURAL_RR)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; rejected: INSUFFICIENT_NATURAL_RR.

## TRIG-00007 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:28 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000007 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000007 — rb 1m, source Sunday, July 5, 2026, 6:26 PM ET, zone [29930.25, 29932.25]
- **RB wick/body:** 0.35 | **dominant-wick ratio:** 2.0
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq27 was_activated=False; tap@seq28 was_activated=False
- **Proposed next-bar entry:** 29927.5
- **Frozen structural stop:** 29932.25 (anchor RB2-000007) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29927.25 (structure RB2-000005 — rb 1m zone [29922.5, 29927.25], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 0.05
- **Status:** REJECTED_TRIGGER (INSUFFICIENT_NATURAL_RR)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; rejected: INSUFFICIENT_NATURAL_RR.

## TRIG-00008 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:36 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000009 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000009 — rb 1m, source Sunday, July 5, 2026, 6:34 PM ET, zone [29952.25, 29957.0]
- **RB wick/body:** 2.11 | **dominant-wick ratio:** 2.11
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq35 was_activated=False; tap@seq36 was_activated=False
- **Proposed next-bar entry:** 29946.0
- **Frozen structural stop:** 29957.0 (anchor RB2-000009) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29939.0 (structure RB2-000004 — rb 1m zone [29929.5, 29939.0], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 0.64
- **Status:** EXECUTABLE_SETUP
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; executable.

## TRIG-00009 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:37 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000008 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000008 — rb 1m, source Sunday, July 5, 2026, 6:33 PM ET, zone [29957.25, 29959.25]
- **RB wick/body:** 0.35 | **dominant-wick ratio:** 1.6
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq36 was_activated=False
- **Proposed next-bar entry:** 29959.75
- **Frozen structural stop:** 29959.25 (anchor RB2-000008) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29957.0 (structure RB2-000009 — rb 1m zone [29952.25, 29957.0], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** n/a
- **Status:** REJECTED_TRIGGER (NO_STRUCTURAL_STOP)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; rejected: NO_STRUCTURAL_STOP.

## TRIG-00010 — RB_TAP (SHORT, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:39 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000010 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000010 — rb 1m, source Sunday, July 5, 2026, 6:37 PM ET, zone [29962.5, 29966.5]
- **RB wick/body:** 1.45 | **dominant-wick ratio:** 4.0
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq38 was_activated=False; tap@seq39 was_activated=False; tap@seq40 was_activated=False
- **Proposed next-bar entry:** 29964.5
- **Frozen structural stop:** 29966.5 (anchor RB2-000010) — above the rejection block's source-candle high (wick extreme)
- **Target:** 29961.75 (structure RB2-000011 — rb 1m zone [29959.25, 29961.75], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 1.38
- **Status:** EXECUTABLE_SETUP
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a short reaction out of the block; executable.

## TRIG-00011 — RB_TAP (LONG, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:40 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000011 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000011 — rb 1m, source Sunday, July 5, 2026, 6:38 PM ET, zone [29959.25, 29961.75]
- **RB wick/body:** 0.71 | **dominant-wick ratio:** 1.43
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq39 was_activated=False; tap@seq40 was_activated=False
- **Proposed next-bar entry:** 29960.75
- **Frozen structural stop:** 29959.25 (anchor RB2-000011) — below the rejection block's source-candle low (wick extreme)
- **Target:** 29962.5 (structure RB2-000010 — rb 1m zone [29962.5, 29966.5], policy NEAREST_CAUSAL_STRUCTURE)
- **Natural RR:** 1.17
- **Status:** EXECUTABLE_SETUP
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a long reaction out of the block; executable.

## TRIG-00012 — RB_TAP (LONG, 1m)
- **Trigger time (entry bar open):** Sunday, July 5, 2026, 6:43 PM ET
- **Session date:** 2026-07-05
- **Branch / state-machine path:** ORIGIN_RB:RB2-000012 → LIVE_FROM_SOURCE → PRICE_RETURNED_TO_ZONE → RB_TAP_TRIGGER
- **Trigger rule:** price returned to and tapped a live rejection block's zone in the block's direction
- **Trigger structure:** RB2-000012 — rb 1m, source Sunday, July 5, 2026, 6:41 PM ET, zone [29959.5, 29965.0]
- **RB wick/body:** 11.0 | **dominant-wick ratio:** 2.0
- **RB activated_at_trigger:** False
- **All RB taps (activation flags):** tap@seq42 was_activated=False; tap@seq43 was_activated=False
- **Proposed next-bar entry:** 29967.75
- **Frozen structural stop:** 29959.5 (anchor RB2-000012) — below the rejection block's source-candle low (wick extreme)
- **Target:** none causally available
- **Natural RR:** n/a
- **Status:** REJECTED_TRIGGER (NO_CAUSAL_TARGET)
- **What the setup believes:** price returned to a live rejection block (not yet activated at the tap) and the engine expects a long reaction out of the block; rejected: NO_CAUSAL_TARGET.


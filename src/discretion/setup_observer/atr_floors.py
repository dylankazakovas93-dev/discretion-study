"""Causal absolute-volatility floors (spec: BLOCKING ATR DISTANCE FLOOR).

Two frozen ATR(24) references are read at each variant trigger, both from
COMPLETED candles only (never the unfinished current candle, never any
application outcome):

- ``atr_1m_24``: ATR(24) of the most recently completed 1m candle at the
  trigger (bar ``entry_seq - 1``);
- ``atr_5m_24``: ATR(24) of the most recently completed 5m candle whose
  availability is no later than the trigger (``available_seq <= entry_seq``).

Stop floor: the effective stop distance is ``max(raw_structural_distance,
atr_1m_24)`` -- the structural invalidation is never tightened, only widened.
Target floor: a structural target is execution-eligible only when its distance
from entry is ``>= atr_5m_24``. No synthetic ATR target is ever created; the
floor is a gate on the genuine nearest opposing structure, and a nearer real
blocker is never skipped to reach a farther one.
"""

from __future__ import annotations

import bisect

TARGET_BELOW_5M_ATR = "TARGET_DISTANCE_BELOW_5M_ATR24"
ATR_FLOOR_UNAVAILABLE = "ATR_FLOOR_UNAVAILABLE"


def atr1m_at_trigger(atr24_1m, entry_seq):
    """ATR(24) of the most recently completed 1m candle at the trigger."""
    j = entry_seq - 1
    if j < 0 or j >= len(atr24_1m):
        return None
    return atr24_1m[j]


def atr5m_at_trigger(atr24_5m, avail5, entry_seq):
    """ATR(24) of the most recently completed 5m candle available no later than
    the trigger. ``avail5`` is the ascending per-5m-candle availability-seq
    array. The still-forming 5m candle (availability > entry_seq) is excluded."""
    idx = bisect.bisect_right(avail5, entry_seq) - 1
    if idx < 0 or idx >= len(atr24_5m):
        return None
    return atr24_5m[idx]


def stop_floor(entry_price, direction, raw_stop_price, atr_1m):
    """Widen (never tighten) the structural stop to the 1m ATR(24) floor."""
    raw_dist = abs(entry_price - raw_stop_price)
    if atr_1m is None:
        eff_dist = raw_dist
        widened = False
    else:
        eff_dist = max(raw_dist, atr_1m)
        widened = eff_dist > raw_dist + 1e-9
    eff_price = (entry_price - eff_dist) if direction > 0 else (entry_price + eff_dist)
    return {
        "raw_stop_price": round(raw_stop_price, 4),
        "raw_stop_distance": round(raw_dist, 4),
        "effective_stop_price": round(eff_price, 4),
        "effective_stop_distance": round(eff_dist, 4),
        "stop_widened_by_atr_floor": widened,
    }


def target_floor_ok(target_distance, atr_5m):
    """A structural target clears the floor only when it is at least one 5m
    ATR(24) away from entry."""
    return atr_5m is not None and target_distance is not None and target_distance >= atr_5m

"""Structural stop/target helpers.

Targets and stops must be structural and knowable at entry. ``nearest_level_*``
only considers levels whose ``created_seq`` is at or before the query seq and
that live in the same contract segment, so nothing future or cross-roll leaks
in. When no structural level exists on the needed side we return None and the
caller rejects the candidate (never a fabricated stop/target).
"""

from __future__ import annotations

from ..data.bars import NQ_TICK
from ..primitives.levels import Level

STOP_BUFFER = 2 * NQ_TICK


def nearest_level_above(price: float, seq: int, segment_id: int,
                        levels: list[Level], min_gap: float = NQ_TICK):
    best = None
    for lv in levels:
        if lv.segment_id != segment_id or lv.created_seq > seq:
            continue
        if lv.price_ref > price + min_gap:
            if best is None or lv.price_ref < best.price_ref:
                best = lv
    return best


def nearest_level_below(price: float, seq: int, segment_id: int,
                        levels: list[Level], min_gap: float = NQ_TICK):
    best = None
    for lv in levels:
        if lv.segment_id != segment_id or lv.created_seq > seq:
            continue
        if lv.price_ref < price - min_gap:
            if best is None or lv.price_ref > best.price_ref:
                best = lv
    return best

"""Fair value gaps (FVG) with causal interaction tracking.

Formation (bullish): three consecutive bars A,B,C in one segment with
``C.low > A.high`` leave an unfilled gap zone ``[A.high, C.low]``. The gap is
only knowable after C closes, so ``created_seq = C.seq``. Bearish is the mirror:
``C.high < A.low`` leaving ``[C.high, A.low]``.

Interaction states are stamped at the completed bar that produced them:
  FORMED, EXACT_TOUCH, FIRST_TOUCH, FIRST_FILL, MIDPOINT (consequent
  encroachment), FULL_FILL, REVISIT, FAILURE (close-through / invalidation),
  CONTINUATION (expired fresh, price moved away without a fill), EXPIRY.

A close-through FAILURE is the deterministic seed for an inverse FVG; the iFVG
module consumes it. Nothing here reads a bar before it has closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.bars import Bar, NQ_TICK
from .base import IdRegistry, Primitive

# How long a fresh FVG is tracked before it expires (8h of 1-min bars).
DEFAULT_MAX_AGE = 480


@dataclass
class FVG(Primitive):
    direction: int = 0  # +1 bullish, -1 bearish
    formation_seq: int = -1
    a_seq: int = -1
    c_seq: int = -1
    failed_seq: int | None = None  # bar seq of close-through (iFVG seed)
    touched: bool = False

    @property
    def near_edge(self) -> float:
        """Edge price first reached when price returns toward the gap."""
        return self.hi if self.direction > 0 else self.lo

    @property
    def far_edge(self) -> float:
        """Edge reached on a full fill."""
        return self.lo if self.direction > 0 else self.hi


def _penetration_events(fvg: FVG, bar: Bar) -> list[str]:
    """Return the ordered new interaction kinds this bar triggers on ``fvg``.

    Only geometry is used; the caller decides first-vs-revisit bookkeeping.
    """
    lo, hi, mid = fvg.lo, fvg.hi, fvg.price
    events: list[str] = []
    if fvg.direction > 0:
        # Bullish gap; price returns from above, testing the top edge (hi) first.
        if bar.low <= hi:  # reached/into zone
            if abs(bar.low - hi) < NQ_TICK / 2 and bar.low >= hi - NQ_TICK / 2:
                events.append("EXACT_TOUCH")
            events.append("TOUCH")
            if bar.low < hi:
                events.append("FILL")
            if bar.low <= mid:
                events.append("MIDPOINT")
            if bar.low <= lo:
                events.append("FULL_FILL")
        if bar.close < lo:
            events.append("FAILURE")
    else:
        # Bearish gap; price returns from below, testing the bottom edge (lo).
        if bar.high >= lo:
            if abs(bar.high - lo) < NQ_TICK / 2 and bar.high <= lo + NQ_TICK / 2:
                events.append("EXACT_TOUCH")
            events.append("TOUCH")
            if bar.high > lo:
                events.append("FILL")
            if bar.high >= mid:
                events.append("MIDPOINT")
            if bar.high >= hi:
                events.append("FULL_FILL")
        if bar.close > hi:
            events.append("FAILURE")
    return events


def detect_fvgs(
    bars: list[Bar],
    registry: IdRegistry,
    max_age: int = DEFAULT_MAX_AGE,
) -> list[FVG]:
    """Single causal pass: form FVGs and track their interactions.

    Returns every FVG occurrence (fresh, filled, failed, expired) — none are
    discarded.
    """
    fvgs: list[FVG] = []
    active: list[FVG] = []

    for i, c in enumerate(bars):
        # 1) Update interactions on active FVGs using this completed bar.
        still_active: list[FVG] = []
        for fvg in active:
            if fvg.segment_id != c.segment_id:
                fvg.add_event("EXPIRY", i - 1, bars[i - 1].ts_utc,
                              note="segment_end")
                fvg.active = False
                continue
            age = i - fvg.created_seq
            kinds = _penetration_events(fvg, c)
            first_touch = not fvg.touched
            for k in kinds:
                if k == "TOUCH":
                    if first_touch:
                        fvg.add_event("FIRST_TOUCH", i, c.ts_utc, price=fvg.near_edge)
                        fvg.touched = True
                    else:
                        fvg.add_event("REVISIT", i, c.ts_utc, price=fvg.near_edge)
                elif k == "EXACT_TOUCH":
                    if not fvg.has_event("EXACT_TOUCH"):
                        fvg.add_event("EXACT_TOUCH", i, c.ts_utc, price=fvg.near_edge)
                elif k == "FILL":
                    if not fvg.has_event("FIRST_FILL"):
                        fvg.add_event("FIRST_FILL", i, c.ts_utc)
                elif k == "MIDPOINT":
                    if not fvg.has_event("MIDPOINT"):
                        fvg.add_event("MIDPOINT", i, c.ts_utc, price=fvg.price)
                elif k == "FULL_FILL":
                    if not fvg.has_event("FULL_FILL"):
                        fvg.add_event("FULL_FILL", i, c.ts_utc, price=fvg.far_edge)
                elif k == "FAILURE":
                    if not fvg.has_event("FAILURE"):
                        fvg.add_event("FAILURE", i, c.ts_utc, price=c.close)
                        fvg.failed_seq = i
                        fvg.invalidated_seq = i
                        fvg.active = False
            if not fvg.active:
                continue
            if age >= max_age:
                if not fvg.touched:
                    fvg.add_event("CONTINUATION", i, c.ts_utc, note="away_no_fill")
                fvg.add_event("EXPIRY", i, c.ts_utc, note="max_age")
                fvg.active = False
                continue
            still_active.append(fvg)
        active = still_active

        # 2) Detect a new FVG formed by the triple (i-2, i-1, i).
        if i < 2:
            continue
        a, b, cc = bars[i - 2], bars[i - 1], bars[i]
        if not (a.segment_id == b.segment_id == cc.segment_id):
            continue
        direction = 0
        lo = hi = 0.0
        if cc.low > a.high:  # bullish gap
            direction, lo, hi = 1, a.high, cc.low
        elif cc.high < a.low:  # bearish gap
            direction, lo, hi = -1, cc.high, a.low
        if direction == 0:
            continue
        pid = registry.new_id("FVG")
        fvg = FVG(
            id=pid,
            family="fvg",
            subtype="bullish" if direction > 0 else "bearish",
            segment_id=cc.segment_id,
            created_seq=i,
            created_ts=cc.ts_utc,
            lo=lo,
            hi=hi,
            direction=direction,
            formation_seq=i,
            a_seq=i - 2,
            c_seq=i,
        )
        fvg.add_event("FORMED", i, cc.ts_utc, price=fvg.near_edge)
        registry.register(fvg)
        fvgs.append(fvg)
        active.append(fvg)

    # Close out anything still open at end of data.
    last = len(bars) - 1
    for fvg in active:
        if not fvg.touched:
            fvg.add_event("CONTINUATION", last, bars[last].ts_utc, note="away_no_fill")
        fvg.add_event("EXPIRY", last, bars[last].ts_utc, note="data_end")
        fvg.active = False
    return fvgs

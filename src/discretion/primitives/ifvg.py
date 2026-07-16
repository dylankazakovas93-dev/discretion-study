"""Inverse fair value gaps (iFVG).

A bullish FVG that price *closes through* to the downside inverts into a bearish
iFVG (the old support zone now acts as resistance); a bearish FVG closed through
to the upside inverts into a bullish iFVG. Activation is the qualifying
close-through candle (the source FVG's FAILURE bar) — this is when the iFVG
becomes knowable, so an immediate entry is causal and does not require a retest.

States: CONFIRMED (activation), FIRST_TOUCH/REVISIT (later retest of the zone),
REJECTION (tests then closes back on the trend side), REINVERSION (price accepts
back through — the iFVG fails), EXPIRY.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.bars import Bar
from .base import IdRegistry, Primitive
from .fvg import FVG, DEFAULT_MAX_AGE


@dataclass
class IFVG(Primitive):
    direction: int = 0        # +1 bullish iFVG, -1 bearish iFVG
    source_fvg_id: str = ""
    activation_seq: int = -1
    touched: bool = False


def detect_ifvgs(
    bars: list[Bar],
    fvgs: list[FVG],
    registry: IdRegistry,
    max_age: int = DEFAULT_MAX_AGE,
) -> list[IFVG]:
    """Build iFVGs from FVG close-through failures and track their interactions."""
    # Index the activation bar -> list of source FVGs failing there.
    by_fail: dict[int, list[FVG]] = {}
    for f in fvgs:
        if f.failed_seq is not None:
            by_fail.setdefault(f.failed_seq, []).append(f)

    ifvgs: list[IFVG] = []
    active: list[IFVG] = []

    for i, bar in enumerate(bars):
        # 1) update active iFVGs
        still: list[IFVG] = []
        for iv in active:
            if iv.segment_id != bar.segment_id:
                iv.add_event("EXPIRY", i - 1, bars[i - 1].ts_utc, note="segment_end")
                iv.active = False
                continue
            lo, hi = iv.lo, iv.hi
            if iv.direction < 0:
                # bearish iFVG: resistance above; price sits below after activation
                if bar.high >= lo:  # retest into zone
                    if not iv.touched:
                        iv.add_event("FIRST_TOUCH", i, bar.ts_utc, price=lo)
                        iv.touched = True
                    else:
                        iv.add_event("REVISIT", i, bar.ts_utc, price=lo)
                    if bar.close < lo:
                        iv.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
                if bar.close > hi:  # accepted back above -> re-inverted, failed
                    iv.add_event("REINVERSION", i, bar.ts_utc, price=bar.close)
                    iv.invalidated_seq = i
                    iv.active = False
            else:
                # bullish iFVG: support below; price sits above after activation
                if bar.low <= hi:
                    if not iv.touched:
                        iv.add_event("FIRST_TOUCH", i, bar.ts_utc, price=hi)
                        iv.touched = True
                    else:
                        iv.add_event("REVISIT", i, bar.ts_utc, price=hi)
                    if bar.close > hi:
                        iv.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
                if bar.close < lo:
                    iv.add_event("REINVERSION", i, bar.ts_utc, price=bar.close)
                    iv.invalidated_seq = i
                    iv.active = False
            if not iv.active:
                continue
            if i - iv.created_seq >= max_age:
                iv.add_event("EXPIRY", i, bar.ts_utc, note="max_age")
                iv.active = False
                continue
            still.append(iv)
        active = still

        # 2) activate new iFVGs from FVGs that failed on this bar
        for src in by_fail.get(i, []):
            pid = registry.new_id("IFVG")
            direction = -src.direction  # inversion
            iv = IFVG(
                id=pid,
                family="ifvg",
                subtype="bullish" if direction > 0 else "bearish",
                segment_id=bar.segment_id,
                created_seq=i,
                created_ts=bar.ts_utc,
                lo=src.lo,
                hi=src.hi,
                direction=direction,
                source_fvg_id=src.id,
                activation_seq=i,
            )
            iv.add_event("CONFIRMED", i, bar.ts_utc, price=bar.close,
                         note=f"from {src.id}")
            registry.register(iv)
            ifvgs.append(iv)
            active.append(iv)

    last = len(bars) - 1
    for iv in active:
        iv.add_event("EXPIRY", last, bars[last].ts_utc, note="data_end")
        iv.active = False
    return ifvgs

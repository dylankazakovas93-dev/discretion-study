"""Rejection blocks (RB) — frozen wick-zone definition.

A bullish RB is a local-low bar whose *lower wick* dominates its body; the
rejection zone is the wick region ``[low, min(open,close)]``. It is confirmed
when the next bar closes back above the body edge, and thereafter acts as
support. Bearish RB is the mirror at a local high with the upper wick zone
``[max(open,close), high]``.

States: FORMED (candidate), CONFIRMED, FIRST_TOUCH/REVISIT, EXACT_TOUCH (touch
of the body-edge boundary to the tick), REJECTION (reaction back out of the
zone), FAILURE/INVALIDATION (a bar closes fully through the wick), EXPIRY.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.bars import Bar, NQ_TICK
from .base import IdRegistry, Primitive
from .fvg import DEFAULT_MAX_AGE

WICK_TO_BODY = 2.0      # lower/upper wick must be >= this * body
MIN_WICK_ATR = 0.4      # and >= this fraction of ATR to be significant
LOCAL_WINDOW = 2        # bars each side considered for the local extreme


@dataclass
class RejectionBlock(Primitive):
    direction: int = 0    # +1 bullish (support), -1 bearish (resistance)
    candidate_seq: int = -1
    confirmed: bool = False
    touched: bool = False


def _is_local_low(bars: list[Bar], i: int, w: int) -> bool:
    lo = bars[i].low
    for j in range(max(0, i - w), i):
        if bars[j].segment_id == bars[i].segment_id and bars[j].low < lo:
            return False
    return True


def _is_local_high(bars: list[Bar], i: int, w: int) -> bool:
    hi = bars[i].high
    for j in range(max(0, i - w), i):
        if bars[j].segment_id == bars[i].segment_id and bars[j].high > hi:
            return False
    return True


def detect_rejection_blocks(
    bars: list[Bar],
    atr: list[float | None],
    registry: IdRegistry,
    max_age: int = DEFAULT_MAX_AGE,
) -> list[RejectionBlock]:
    rbs: list[RejectionBlock] = []
    active: list[RejectionBlock] = []

    for i, bar in enumerate(bars):
        # 1) update active RBs
        still: list[RejectionBlock] = []
        for rb in active:
            if rb.segment_id != bar.segment_id:
                rb.add_event("EXPIRY", i - 1, bars[i - 1].ts_utc, note="segment_end")
                rb.active = False
                continue
            zlo, zhi = rb.lo, rb.hi
            if not rb.confirmed:
                # confirmation window: next bar must close back out of the zone
                if rb.direction > 0 and bar.close > zhi:
                    rb.confirmed = True
                    rb.add_event("CONFIRMED", i, bar.ts_utc, price=bar.close)
                elif rb.direction < 0 and bar.close < zlo:
                    rb.confirmed = True
                    rb.add_event("CONFIRMED", i, bar.ts_utc, price=bar.close)
                elif i - rb.candidate_seq >= 3:
                    rb.add_event("FAILURE", i, bar.ts_utc, note="unconfirmed")
                    rb.active = False
                    continue
                still.append(rb)
                continue
            # confirmed: track interactions
            if rb.direction > 0:
                if bar.low <= zhi:  # into support zone
                    boundary = abs(bar.low - zhi) < NQ_TICK / 2
                    if not rb.touched:
                        rb.add_event("FIRST_TOUCH", i, bar.ts_utc, price=zhi)
                        rb.touched = True
                    else:
                        rb.add_event("REVISIT", i, bar.ts_utc, price=zhi)
                    if boundary:
                        rb.add_event("EXACT_TOUCH", i, bar.ts_utc, price=zhi)
                    if bar.close > zhi:
                        rb.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
                if bar.close < zlo:  # closed through the wick -> invalidated
                    rb.add_event("INVALIDATION", i, bar.ts_utc, price=bar.close)
                    rb.invalidated_seq = i
                    rb.active = False
            else:
                if bar.high >= zlo:
                    boundary = abs(bar.high - zlo) < NQ_TICK / 2
                    if not rb.touched:
                        rb.add_event("FIRST_TOUCH", i, bar.ts_utc, price=zlo)
                        rb.touched = True
                    else:
                        rb.add_event("REVISIT", i, bar.ts_utc, price=zlo)
                    if boundary:
                        rb.add_event("EXACT_TOUCH", i, bar.ts_utc, price=zlo)
                    if bar.close < zlo:
                        rb.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
                if bar.close > zhi:
                    rb.add_event("INVALIDATION", i, bar.ts_utc, price=bar.close)
                    rb.invalidated_seq = i
                    rb.active = False
            if not rb.active:
                continue
            if i - rb.created_seq >= max_age:
                rb.add_event("EXPIRY", i, bar.ts_utc, note="max_age")
                rb.active = False
                continue
            still.append(rb)
        active = still

        # 2) detect new candidate on this completed bar
        a = atr[i]
        if a is None or a <= 0:
            continue
        body = bar.body
        body_lo = min(bar.open, bar.close)
        body_hi = max(bar.open, bar.close)
        lower_wick = body_lo - bar.low
        upper_wick = bar.high - body_hi
        eff_body = max(body, NQ_TICK)
        direction = 0
        zlo = zhi = 0.0
        if (
            lower_wick >= WICK_TO_BODY * eff_body
            and lower_wick >= MIN_WICK_ATR * a
            and _is_local_low(bars, i, LOCAL_WINDOW)
        ):
            direction, zlo, zhi = 1, bar.low, body_lo
        elif (
            upper_wick >= WICK_TO_BODY * eff_body
            and upper_wick >= MIN_WICK_ATR * a
            and _is_local_high(bars, i, LOCAL_WINDOW)
        ):
            direction, zlo, zhi = -1, body_hi, bar.high
        if direction == 0 or zhi <= zlo:
            continue
        pid = registry.new_id("RB")
        rb = RejectionBlock(
            id=pid,
            family="rejection_block",
            subtype="bullish" if direction > 0 else "bearish",
            segment_id=bar.segment_id,
            created_seq=i,
            created_ts=bar.ts_utc,
            lo=zlo,
            hi=zhi,
            direction=direction,
            candidate_seq=i,
        )
        rb.add_event("FORMED", i, bar.ts_utc, price=zhi if direction > 0 else zlo)
        registry.register(rb)
        rbs.append(rb)
        active.append(rb)

    last = len(bars) - 1
    for rb in active:
        rb.add_event("EXPIRY", last, bars[last].ts_utc, note="data_end")
        rb.active = False
    return rbs

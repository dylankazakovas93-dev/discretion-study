"""Exact FVG detector for the primitive reset (spec Parts 1-3).

Independent of, and never mixed with, the superseded IDs in
``discretion.primitives.fvg``. Each timeframe is detected on its own
completed-candle series (see ``timeframes.candle_series``); nothing here
ever reads a lower-timeframe bar to form or invalidate a higher-timeframe
FVG, or vice versa.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.bars import NQ_TICK
from .colour import colour, same_colour, BULLISH, BEARISH
from .timeframes import candle_series, atr_series, candle_ts_et, INTRADAY_LIFETIME_TFS
from .traversal import zone_step, DEACTIVATED_CLOSE_THROUGH

LIFETIME_HOURS = 8

SIZE_BINS = (
    ("<0.05 ATR", 0.0, 0.05),
    ("0.05-<0.10 ATR", 0.05, 0.10),
    ("0.10-<0.20 ATR", 0.10, 0.20),
    ("0.20-<0.30 ATR", 0.20, 0.30),
    ("0.30-<0.50 ATR", 0.30, 0.50),
    (">=0.50 ATR", 0.50, float("inf")),
)


def size_bin(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    for label, lo, hi in SIZE_BINS:
        if lo <= ratio < hi:
            return label
    return SIZE_BINS[-1][0]


@dataclass
class FVGRecord:
    id: str
    timeframe: int
    direction: str          # "bullish" / "bearish"
    segment_id: int

    a_seq: int
    b_seq: int
    c_seq: int
    a_ts: object
    b_ts: object
    c_ts: object
    a_ohlc: tuple
    b_ohlc: tuple
    c_ohlc: tuple
    a_colour: str
    b_colour: str
    c_colour: str

    lo: float
    hi: float
    width_points: float
    width_ticks: float
    atr_at_c_close: float | None
    width_atr: float | None
    size_bin: str | None

    formation_ts: object

    first_touch_ts: object = None
    first_touch_seq: int | None = None
    midpoint_ts: object = None
    full_fill_ts: object = None
    inversion_ts: object = None       # close-through -> iFVG seed
    inversion_seq: int | None = None  # index into this timeframe's candle series
    expiry_ts: object = None
    deactivation_reason: str | None = None
    child_ifvg_id: str | None = None

    active: bool = True
    touched: bool = False


def _lifetime_check(tf: int, formation_ts, now_ts, touched: bool) -> str | None:
    if tf not in INTRADAY_LIFETIME_TFS:
        return None
    elapsed = now_ts - formation_ts
    if elapsed >= __import__("pandas").Timedelta(hours=LIFETIME_HOURS):
        return "EXPIRED_ACTIVE_8H" if touched else "EXPIRED_UNTOUCHED_8H"
    return None


def detect_fvgs(bars, tf: int, registry) -> list[FVGRecord]:
    series = candle_series(bars, tf)
    atr = atr_series(series)
    out: list[FVGRecord] = []
    active: list[FVGRecord] = []

    for i, c in enumerate(series):
        still: list[FVGRecord] = []
        for f in active:
            if c.segment_id != f.segment_id:
                f.expiry_ts = candle_ts_et(series[i - 1]) if i > 0 else f.formation_ts
                f.deactivation_reason = "DATA_END_ACTIVE"
                f.active = False
                continue

            lo, hi, mid = f.lo, f.hi, (f.lo + f.hi) / 2.0
            ts = candle_ts_et(c)
            if f.direction == BULLISH:
                reached = c.low <= hi
                if reached and f.first_touch_ts is None:
                    f.first_touch_ts = ts
                    f.first_touch_seq = i
                    f.touched = True
                if reached and f.midpoint_ts is None and c.low <= mid:
                    f.midpoint_ts = ts
                if reached and f.full_fill_ts is None and c.low <= lo:
                    f.full_fill_ts = ts
            else:
                reached = c.high >= lo
                if reached and f.first_touch_ts is None:
                    f.first_touch_ts = ts
                    f.touched = True
                if reached and f.midpoint_ts is None and c.high >= mid:
                    f.midpoint_ts = ts
                if reached and f.full_fill_ts is None and c.high >= hi:
                    f.full_fill_ts = ts

            direction_sign = 1 if f.direction == BULLISH else -1
            step = zone_step(direction_sign, lo, hi, c)
            if step.deactivated:
                f.deactivation_reason = step.reason
                f.active = False
                if step.reason == DEACTIVATED_CLOSE_THROUGH:
                    f.inversion_ts = ts
                    f.inversion_seq = i
                continue

            expiry = _lifetime_check(tf, f.formation_ts, ts, f.touched)
            if expiry is not None:
                f.expiry_ts = ts
                f.deactivation_reason = expiry
                f.active = False
                continue
            still.append(f)
        active = still

        if i < 2:
            continue
        a, b, cc = series[i - 2], series[i - 1], c
        if not (a.segment_id == b.segment_id == cc.segment_id):
            continue
        if not same_colour(a, b, cc):
            continue
        col = colour(a)
        direction = None
        lo = hi = 0.0
        if col == BULLISH and cc.low > a.high:
            direction, lo, hi = BULLISH, a.high, cc.low
        elif col == BEARISH and cc.high < a.low:
            direction, lo, hi = BEARISH, cc.high, a.low
        if direction is None:
            continue

        width = hi - lo
        a_close = atr[i]
        width_atr = (width / a_close) if a_close and a_close > 0 else None
        pid = registry.new_id("FVG2")
        ts_c = candle_ts_et(cc)
        rec = FVGRecord(
            id=pid, timeframe=tf, direction=direction, segment_id=cc.segment_id,
            a_seq=i - 2, b_seq=i - 1, c_seq=i,
            a_ts=candle_ts_et(a), b_ts=candle_ts_et(b), c_ts=ts_c,
            a_ohlc=(a.open, a.high, a.low, a.close),
            b_ohlc=(b.open, b.high, b.low, b.close),
            c_ohlc=(cc.open, cc.high, cc.low, cc.close),
            a_colour=colour(a), b_colour=colour(b), c_colour=colour(cc),
            lo=lo, hi=hi, width_points=width, width_ticks=width / NQ_TICK,
            atr_at_c_close=a_close, width_atr=width_atr, size_bin=size_bin(width_atr),
            formation_ts=ts_c,
        )
        registry.register_fvg(rec)
        out.append(rec)
        active.append(rec)

    if series:
        last_ts = candle_ts_et(series[-1])
        for f in active:
            f.expiry_ts = last_ts
            f.deactivation_reason = "DATA_END_ACTIVE"
            f.active = False
    return out

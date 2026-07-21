"""Exact iFVG detector for the primitive reset (spec Parts 4-5).

An iFVG is only ever built from an FVGRecord produced by ``fvg.detect_fvgs``
on the *same* timeframe series, and only from a parent whose terminal
deactivation was ``DEACTIVATED_CLOSE_THROUGH`` (a completed same-timeframe
candle closing fully through the parent's distal boundary while the parent
was still active and unexpired -- see ``traversal.zone_step``). A wick-only
breach (``DEACTIVATED_OVERSHOOT_LIMIT``) or an already-expired/deactivated
parent never seeds an iFVG (spec rules 2-4, 7).

Descriptive-grading formulas not pinned down exactly by the spec text are
documented at each field below; these are provisional, disclosed choices for
Dylan to confirm, not silent inventions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .colour import BULLISH, BEARISH
from .timeframes import candle_ts_et, INTRADAY_LIFETIME_TFS
from .traversal import zone_step, DEACTIVATED_CLOSE_THROUGH

LIFETIME_HOURS = 8


@dataclass
class IFVGRecord:
    id: str
    parent_fvg_id: str
    timeframe: int
    segment_id: int
    parent_direction: str
    child_direction: str

    parent_formation_ts: object
    parent_width_points: float
    parent_width_atr: float | None
    parent_first_touch_ts: object

    inversion_ts: object
    inversion_ohlc: tuple
    close_through_boundary: float
    atr_at_inversion: float | None
    inversion_body_atr: float | None
    inversion_range_atr: float | None

    bars_from_formation_to_inversion: int
    bars_from_first_touch_to_inversion: int | None
    inversion_speed_bucket: str

    max_penetration_before_inversion: float
    distance_through_zone: float
    distance_through_zone_over_width: float | None
    n_scraping_candles: int
    avg_scraping_body: float | None

    lo: float
    hi: float
    activation_ts: object

    expiry_ts: object = None
    deactivation_reason: str | None = None
    active: bool = True
    touched: bool = False
    first_touch_ts: object = None


def _speed_bucket(n: int) -> str:
    return f"{n}_candles" if n <= 4 else "5plus_candles"


def _lifetime_check(tf: int, activation_ts, now_ts, touched: bool) -> str | None:
    if tf not in INTRADAY_LIFETIME_TFS:
        return None
    elapsed = now_ts - activation_ts
    if elapsed >= __import__("pandas").Timedelta(hours=LIFETIME_HOURS):
        return "EXPIRED_ACTIVE_8H" if touched else "EXPIRED_UNTOUCHED_8H"
    return None


def detect_ifvgs(bars, tf: int, fvgs, atr, series, registry) -> list[IFVGRecord]:
    """``atr``/``series`` are this timeframe's ``atr_series``/``candle_series``
    (passed in so callers reuse the same arrays already built for ``fvgs``).
    """
    scraping_by_parent: dict[str, list] = {rec.id: [] for rec in fvgs}
    max_pen_by_parent: dict[str, float] = {rec.id: 0.0 for rec in fvgs}

    # Track scraping (touched, not-yet-inverted) candles for each still-live
    # parent as we sweep forward -- needed for n_scraping_candles / max
    # penetration / average scraping body, all "before the final close-through".
    parents_by_id = {rec.id: rec for rec in fvgs}
    live_parents = {rec.id: True for rec in fvgs}

    out: list[IFVGRecord] = []
    active: list[IFVGRecord] = []

    inversions_at: dict[int, list] = {}
    for rec in fvgs:
        if rec.deactivation_reason == DEACTIVATED_CLOSE_THROUGH and rec.inversion_seq is not None:
            inversions_at.setdefault(rec.inversion_seq, []).append(rec)

    for i, c in enumerate(series):
        # 0) update scraping stats for still-live, touched, not-yet-inverted parents
        for rec in fvgs:
            if not live_parents.get(rec.id, False):
                continue
            if i <= rec.c_seq:
                continue
            if rec.inversion_seq is not None and i >= rec.inversion_seq:
                continue  # this is the inversion candle itself, handled below
            lo, hi = rec.lo, rec.hi
            if rec.direction == BULLISH:
                reached = c.low <= hi
                penetration = max(0.0, lo - c.low)
            else:
                reached = c.high >= lo
                penetration = max(0.0, c.high - hi)
            if reached:
                scraping_by_parent[rec.id].append(c)
                if penetration > max_pen_by_parent[rec.id]:
                    max_pen_by_parent[rec.id] = penetration

        # 1) advance active iFVGs
        still: list[IFVGRecord] = []
        for iv in active:
            if c.segment_id != iv.segment_id:
                iv.expiry_ts = candle_ts_et(series[i - 1]) if i > 0 else iv.activation_ts
                iv.deactivation_reason = "DATA_END_ACTIVE"
                iv.active = False
                continue
            lo, hi = iv.lo, iv.hi
            ts = candle_ts_et(c)
            if iv.child_direction == BULLISH:
                reached = c.low <= hi
            else:
                reached = c.high >= lo
            if reached and iv.first_touch_ts is None:
                iv.first_touch_ts = ts
                iv.touched = True

            direction_sign = 1 if iv.child_direction == BULLISH else -1
            step = zone_step(direction_sign, lo, hi, c)
            if step.deactivated:
                iv.deactivation_reason = step.reason
                iv.active = False
                continue
            expiry = _lifetime_check(tf, iv.activation_ts, ts, iv.touched)
            if expiry is not None:
                iv.expiry_ts = ts
                iv.deactivation_reason = expiry
                iv.active = False
                continue
            still.append(iv)
        active = still

        # 2) activate any parents that inverted on this candle
        for parent in inversions_at.get(i, []):
            live_parents[parent.id] = False
            child_direction = BEARISH if parent.direction == BULLISH else BULLISH
            a = atr[i]
            body = abs(c.close - c.open)
            rng = c.high - c.low
            n_form_to_inv = i - parent.c_seq
            n_touch_to_inv = (i - parent.first_touch_seq) if parent.first_touch_seq is not None else None
            scraping = scraping_by_parent.get(parent.id, [])
            distal = parent.lo if parent.direction == BULLISH else parent.hi
            distance = (distal - c.close) if parent.direction == BULLISH else (c.close - distal)
            pid = registry.new_id("IFVG2")
            ts_i = candle_ts_et(c)
            rec = IFVGRecord(
                id=pid, parent_fvg_id=parent.id, timeframe=tf, segment_id=c.segment_id,
                parent_direction=parent.direction, child_direction=child_direction,
                parent_formation_ts=parent.formation_ts,
                parent_width_points=parent.width_points, parent_width_atr=parent.width_atr,
                parent_first_touch_ts=parent.first_touch_ts,
                inversion_ts=ts_i, inversion_ohlc=(c.open, c.high, c.low, c.close),
                close_through_boundary=distal, atr_at_inversion=a,
                inversion_body_atr=(body / a) if a else None,
                inversion_range_atr=(rng / a) if a else None,
                bars_from_formation_to_inversion=n_form_to_inv,
                bars_from_first_touch_to_inversion=n_touch_to_inv,
                inversion_speed_bucket=_speed_bucket(n_form_to_inv),
                max_penetration_before_inversion=max_pen_by_parent.get(parent.id, 0.0),
                distance_through_zone=distance,
                distance_through_zone_over_width=(
                    distance / parent.width_points if parent.width_points else None),
                n_scraping_candles=len(scraping),
                avg_scraping_body=(
                    sum(abs(s.close - s.open) for s in scraping) / len(scraping)
                    if scraping else None),
                lo=parent.lo, hi=parent.hi, activation_ts=ts_i,
            )
            parent.child_ifvg_id = pid
            registry.register_ifvg(rec)
            out.append(rec)
            active.append(rec)

    if series:
        last_ts = candle_ts_et(series[-1])
        for iv in active:
            iv.expiry_ts = last_ts
            iv.deactivation_reason = "DATA_END_ACTIVE"
            iv.active = False
    return out

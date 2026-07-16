"""Displacement and reaction quality (causal, ATR-normalised).

A displacement is a strong directional 1-bar leg (optionally extended by the
2- and 3-bar context around it). All magnitude features are ATR-normalised so
they are comparable across contracts and cannot leak absolute price scale
across a roll.

Frozen structural grade in {good, mixed, bad} from a fixed rubric — no adaptive
tuning. We also stamp the leg's follow-through: CONTINUATION (next bar extends)
or FAILED_CONTINUATION (next bar closes back through the leg's origin).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import Bar
from .base import IdRegistry, Primitive

MIN_BODY_ATR = 0.5  # below this a bar is not a displacement candidate


@dataclass
class Displacement(Primitive):
    direction: int = 0
    grade: str = "bad"
    features: dict = field(default_factory=dict)


def _close_location(bar: Bar) -> float:
    """0 at the low, 1 at the high."""
    rng = bar.high - bar.low
    if rng <= 0:
        return 0.5
    return (bar.close - bar.low) / rng


def displacement_features(bar: Bar, prev: Bar | None, atr: float) -> dict:
    """Causal, ATR-normalised features for the 1-bar leg ending at ``bar``."""
    rng = bar.high - bar.low
    body = bar.body
    direction = 1 if bar.close > bar.open else (-1 if bar.close < bar.open else 0)
    close_loc = _close_location(bar)
    if direction >= 0:
        opposing_wick = bar.open - bar.low if body else 0.0
        favorable_close = close_loc
    else:
        opposing_wick = bar.high - bar.open if body else 0.0
        favorable_close = 1.0 - close_loc
    overlap = None
    if prev is not None and prev.segment_id == bar.segment_id:
        inter = min(bar.high, prev.high) - max(bar.low, prev.low)
        overlap = max(0.0, inter) / rng if rng > 0 else 1.0
    return {
        "direction": direction,
        "body_atr": body / atr if atr else 0.0,
        "range_atr": rng / atr if atr else 0.0,
        "body_ratio": body / rng if rng > 0 else 0.0,
        "close_loc": close_loc,
        "favorable_close": favorable_close,
        "opposing_wick_ratio": opposing_wick / rng if rng > 0 else 0.0,
        "adjacent_overlap": overlap,
    }


def grade_displacement(f: dict) -> str:
    """Frozen good/mixed/bad rubric."""
    good = (
        f["body_atr"] >= 1.0
        and f["body_ratio"] >= 0.60
        and f["favorable_close"] >= 0.66
        and f["opposing_wick_ratio"] <= 0.25
    )
    if good:
        return "good"
    bad = (
        f["body_atr"] < MIN_BODY_ATR
        or f["body_ratio"] < 0.40
        or f["favorable_close"] < 0.50
        or f["opposing_wick_ratio"] > 0.45
    )
    if bad:
        return "bad"
    return "mixed"


def detect_displacements(
    bars: list[Bar],
    atr: list[float | None],
    registry: IdRegistry,
) -> list[Displacement]:
    """Detect and grade displacement legs, then stamp follow-through."""
    disps: list[Displacement] = []
    for i, bar in enumerate(bars):
        a = atr[i]
        if a is None or a <= 0:
            continue
        prev = bars[i - 1] if i > 0 else None
        f = displacement_features(bar, prev, a)
        if f["direction"] == 0 or f["body_atr"] < MIN_BODY_ATR:
            continue
        grade = grade_displacement(f)
        pid = registry.new_id("DISP")
        d = Displacement(
            id=pid,
            family="displacement",
            subtype=grade,
            segment_id=bar.segment_id,
            created_seq=i,
            created_ts=bar.ts_utc,
            lo=bar.low,
            hi=bar.high,
            direction=f["direction"],
            grade=grade,
            features=f,
        )
        d.add_event("FORMED", i, bar.ts_utc, price=bar.close, note=grade)
        # Follow-through on the very next bar (causal, no look further ahead here).
        if i + 1 < len(bars) and bars[i + 1].segment_id == bar.segment_id:
            nxt = bars[i + 1]
            if d.direction > 0:
                if nxt.close > bar.close:
                    d.add_event("CONTINUATION", i + 1, nxt.ts_utc, price=nxt.close)
                elif nxt.close < bar.open:
                    d.add_event("FAILED_CONTINUATION", i + 1, nxt.ts_utc,
                                price=nxt.close)
            else:
                if nxt.close < bar.close:
                    d.add_event("CONTINUATION", i + 1, nxt.ts_utc, price=nxt.close)
                elif nxt.close > bar.open:
                    d.add_event("FAILED_CONTINUATION", i + 1, nxt.ts_utc,
                                price=nxt.close)
        registry.register(d)
        disps.append(d)
    return disps

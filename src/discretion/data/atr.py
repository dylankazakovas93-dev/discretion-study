"""Causal ATR (Wilder), computed on completed bars only, reset per segment.

``atr[i]`` is the Average True Range known once bar ``i`` has closed. It uses
only bars 0..i within the same contract segment, so it is safe to normalise a
feature of bar ``i`` by ``atr[i]``. Values are ``None`` until ``period`` true
ranges have accumulated inside the segment (no cross-roll contamination).
"""

from __future__ import annotations

from .bars import Bar


def true_ranges(bars: list[Bar]) -> list[float | None]:
    """Per-bar true range; None for the first bar of each segment."""
    out: list[float | None] = []
    prev: Bar | None = None
    for b in bars:
        if prev is None or prev.segment_id != b.segment_id:
            out.append(None)  # no previous close within this segment
        else:
            tr = max(
                b.high - b.low,
                abs(b.high - prev.close),
                abs(b.low - prev.close),
            )
            out.append(tr)
        prev = b
    return out


def wilder_atr(bars: list[Bar], period: int = 14) -> list[float | None]:
    """Wilder-smoothed ATR aligned to ``bars`` (completed-bar causal).

    Seeded per segment with the simple average of the first ``period`` true
    ranges, then Wilder-smoothed. The first valid TR in a segment is at the
    second bar, so the seed lands at ``within == period``.
    """
    trs = true_ranges(bars)
    atr: list[float | None] = [None] * len(bars)

    seg_start = 0
    for i, b in enumerate(bars):
        if i == 0 or bars[i - 1].segment_id != b.segment_id:
            seg_start = i
        within = i - seg_start
        if within == period:
            window = [trs[seg_start + k] for k in range(1, period + 1)]
            atr[i] = sum(window) / period
        elif within > period:
            atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period
    return atr

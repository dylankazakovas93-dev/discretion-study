"""Canonical causal 5m/15m/30m/60m aggregation of 1-minute bars.

The only HTF aggregation in the canonical layer (phase1's is legacy and not
reused). Buckets are ET wall-clock, anchored to the frozen CME session open
(18:00 ET) — since 18:00 is a multiple of every supported timeframe, hourly/30/15/5
boundaries are session-aligned, not arbitrary UTC. A candle is knowable only after
its final constituent 1-minute bar closes; ATR reuses the frozen Wilder ATR over
previous completed same-timeframe candles (current excluded). Candles never cross
a contract-roll segment. Deterministic ids; identical output across reruns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .atr import wilder_atr

TIMEFRAMES = (5, 15, 30, 60)


@dataclass
class HTFBar:
    candle_id: str
    timeframe: int
    open_ts: str            # ET, bucket open
    close_ts: str           # ET, availability (last constituent close = +1 min)
    start_seq: int          # first constituent 1m bar index
    end_seq: int            # last constituent 1m bar index
    available_seq: int      # first 1m seq at which this candle is usable
    open: float
    high: float
    low: float
    close: float
    volume: int
    segment_id: int         # absolute segment
    norm_segment_id: int    # normalization segment (same as absolute here)
    atr: float | None = None


def _bucket_key(bar, tf: int):
    minute_of_day = bar.ts_et.hour * 60 + bar.ts_et.minute
    return (bar.segment_id, bar.ts_et.date(), minute_of_day // tf)


def aggregate(bars, tf: int) -> list[HTFBar]:
    """Aggregate 1-minute bars into completed `tf`-minute candles."""
    candles: list[HTFBar] = []
    if not bars:
        return candles
    n = 0
    i = 0
    N = len(bars)
    while i < N:
        key = _bucket_key(bars[i], tf)
        j = i
        while j < N and _bucket_key(bars[j], tf) == key:
            j += 1
        group = bars[i:j]
        n += 1
        last = group[-1]
        candles.append(HTFBar(
            candle_id=f"HTF{tf}m-{n:06d}", timeframe=tf,
            open_ts=str(group[0].ts_et),
            close_ts=str(last.ts_et + pd.Timedelta(minutes=1)),
            start_seq=i, end_seq=j - 1, available_seq=j,   # global 1m indices
            open=float(group[0].open), high=float(max(b.high for b in group)),
            low=float(min(b.low for b in group)), close=float(last.close),
            volume=int(sum(b.volume for b in group)),
            segment_id=last.segment_id, norm_segment_id=last.segment_id))
        i = j
    # ATR over previous completed same-timeframe candles (current excluded).
    # wilder_atr[k] is knowable once candle k has closed, i.e. it already excludes
    # future candles; it uses candles 0..k so we shift by one to exclude the
    # current candle from its own ATR.
    atr = wilder_atr(candles, period=14)
    for k, c in enumerate(candles):
        c.atr = atr[k - 1] if k > 0 else None
    return candles


def aggregate_all(bars) -> dict[int, list[HTFBar]]:
    return {tf: aggregate(bars, tf) for tf in TIMEFRAMES}


def candles_available_at(candles: list[HTFBar], seq: int) -> list[HTFBar]:
    """Completed candles usable at 1-minute bar index `seq` (available_seq<=seq)."""
    return [c for c in candles if c.available_seq <= seq]

"""Per-timeframe completed-candle series and same-timeframe ATR, for the
primitive reset detectors only.

Timeframes supported: 1m (raw bars, no aggregation) and 3/5/15/30/60m (built
from :func:`discretion.data.aggregation.aggregate`, reused as-is -- the
18:00 ET session-open bucket alignment it already implements is exactly
correct for 3m too, since 1080 minutes-of-day divides evenly by 3).

ATR contract for this reset (deliberately NOT the same object as
``aggregation.HTFBar.atr``): ``atr_at_close(series, i)`` is the completed
same-timeframe Wilder ATR(14) *as of and including* candle ``i``'s own true
range -- the value knowable the instant candle ``i`` closes. This is the
literal reading of "ATR available when candle C closes" / "same-timeframe
ATR at source candle close". ``aggregation.py``'s ``HTFBar.atr`` is shifted
by one candle (excludes the candle's own range) for an unrelated
feature-normalisation purpose elsewhere in the codebase; reusing it here
would silently violate the causal-freeze contract this task specifies, so a
fresh, unshifted computation is used instead.
"""

from __future__ import annotations

from ..data.aggregation import aggregate as _aggregate_htf
from ..data.atr import wilder_atr

TIMEFRAMES = (1, 3, 5, 15, 30, 60)
INTRADAY_LIFETIME_TFS = (1, 3, 5, 15, 30)  # below 1h: 8h elapsed-time lifetime
NO_EXPIRY_TFS = (60,)                       # 1h and higher: no arbitrary expiry


def candle_series(bars, tf: int):
    """Completed candles for ``tf``, closes-only-known ordering preserved.

    tf == 1 returns ``bars`` unchanged (already 1-minute completed candles).
    """
    if tf == 1:
        return list(bars)
    return _aggregate_htf(bars, tf)


def atr_series(series) -> list[float | None]:
    """Unshifted Wilder ATR(14), aligned 1:1 with ``series`` (index i =
    ATR knowable the instant candle/bar i closes)."""
    return wilder_atr(series, period=14)


def candle_ts_et(candle):
    """ET timestamp usable for elapsed-time lifetime math, for either a raw
    1m ``Bar`` (``ts_et``) or an aggregated ``HTFBar`` (``close_ts``, an ET
    string -- the timestamp at which the candle became knowable)."""
    ts_et = getattr(candle, "ts_et", None)
    if ts_et is not None:
        return ts_et
    import pandas as pd
    return pd.Timestamp(candle.close_ts)

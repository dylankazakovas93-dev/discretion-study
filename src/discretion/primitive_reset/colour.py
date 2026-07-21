"""Deterministic candle-colour convention for the primitive reset.

A candle (any timeframe) is classified purely from its own close/open, never
from neighbouring bars and never from a rendered chart:

    bullish  iff  close >= open
    bearish  iff  close <  open

The exact-doji case (``close == open``) is classified **bullish** by this
convention. This is a single-bar, lookback-free tie-break (no dependency on
the previous candle), chosen only for determinism -- it carries no claim that
a doji is directionally bullish. Every FVG/RB reader must go through
``colour()`` rather than re-deriving up/down locally, so the doji rule is
applied uniformly everywhere a "same colour" check is made.
"""

from __future__ import annotations

BULLISH = "bullish"
BEARISH = "bearish"


def colour(candle) -> str:
    """``candle`` needs only ``.open``/``.close`` (Bar or HTFBar both work)."""
    return BULLISH if candle.close >= candle.open else BEARISH


def same_colour(*candles) -> bool:
    cols = {colour(c) for c in candles}
    return len(cols) == 1

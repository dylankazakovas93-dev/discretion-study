"""Deterministic candle-colour convention for the primitive reset.

A candle (any timeframe) is classified purely from its own close/open, never
from neighbouring bars and never from a rendered chart:

    bullish   iff  close  > open
    bearish   iff  close  < open
    unresolved iff close == open   (EXACT_DOJI_COLOUR_UNRESOLVED)

The exact-doji case is **not** silently assigned a direction. Dylan flagged a
real instance (FVG2-000029's C candle) where an earlier `close >= open`
tie-break arbitrarily called an exact doji bullish and let it seed an FVG/
iFVG that did not read as a genuine same-colour triple on his chart. Small
bodies are still never excluded (per Part 1 rule 5/6) -- only the literal
`open == close` case is held back until the target chart's own doji-colour
convention is explicitly frozen.
"""

from __future__ import annotations

BULLISH = "bullish"
BEARISH = "bearish"
EXACT_DOJI_COLOUR_UNRESOLVED = "exact_doji_colour_unresolved"


def colour_state(candle) -> str:
    """``candle`` needs only ``.open``/``.close`` (Bar or HTFBar both work)."""
    if candle.close > candle.open:
        return BULLISH
    if candle.close < candle.open:
        return BEARISH
    return EXACT_DOJI_COLOUR_UNRESOLVED


def eligible_same_colour(*candles) -> bool:
    """True iff every candle is resolved (not an exact doji) and all share
    the same resolved colour. An exact-doji candle anywhere in the group
    makes the group ineligible, regardless of the others' colours."""
    states = [colour_state(c) for c in candles]
    if any(s == EXACT_DOJI_COLOUR_UNRESOLVED for s in states):
        return False
    return len(set(states)) == 1

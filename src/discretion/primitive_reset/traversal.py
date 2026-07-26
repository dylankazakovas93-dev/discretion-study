"""Common zone-penetration / deactivation contract (spec Part 8), shared by
the FVG, iFVG and RB detectors so bullish/bearish and all three families use
byte-identical traversal logic.

For a zone ``[lo, hi]`` with width ``W = hi - lo``:

  * bullish structures (support): the trade-side *distal* boundary is ``lo``.
    A wick may temporarily overshoot below ``lo`` by up to ``0.20 * W``
    without deactivating, provided the candle's *close* is back on the valid
    (>= lo) side.
  * bearish structures (resistance): the distal boundary is ``hi``; the
    mirrored tolerance is above ``hi``.

Permanent deactivation (checked in this order -- a close beyond the distal
boundary is checked first regardless of how far the wick went, because it is
the unconditional trigger the iFVG detector keys on (spec Part 4 rule 6: "a
completed same-timeframe candle closes fully through the parent FVG's distal
boundary" -- nothing there is conditioned on wick depth); wick-only overshoot
is a softer, close-independent kill switch for a bar that spiked through and
recovered):

  1. the candle *closes* beyond the ordinary distal boundary
     -> ``DEACTIVATED_CLOSE_THROUGH`` (checked first, regardless of wick depth)
  2. otherwise, a wick excursion beyond the distal boundary exceeds
     ``0.20 * W`` while the close recovered back to the valid side
     -> ``DEACTIVATED_OVERSHOOT_LIMIT``

While still active, a bar that reaches into the zone (or overshoots within
tolerance and closes back) emits a non-terminal lifecycle event:
``VALID_TAP`` (ordinary reach into ``[lo, hi]``) or
``VALID_OVERSHOOT_RECLAIM`` (wick beyond the distal boundary, within
tolerance, closing back on the valid side).

Once deactivated a structure never reactivates; later price returning into
the zone is not evaluated (the caller must stop calling ``zone_step`` for a
deactivated structure).
"""

from __future__ import annotations

from dataclasses import dataclass

DEACTIVATED_CLOSE_THROUGH = "DEACTIVATED_CLOSE_THROUGH"
DEACTIVATED_OVERSHOOT_LIMIT = "DEACTIVATED_OVERSHOOT_LIMIT"
VALID_TAP = "VALID_TAP"
VALID_OVERSHOOT_RECLAIM = "VALID_OVERSHOOT_RECLAIM"


@dataclass
class TraversalResult:
    event: str | None          # VALID_TAP / VALID_OVERSHOOT_RECLAIM / None
    deactivated: bool
    reason: str | None         # DEACTIVATED_* or None


def zone_step(direction: int, lo: float, hi: float, bar) -> TraversalResult:
    """One completed bar's effect on an active zone ``[lo, hi]``.

    ``direction``: +1 bullish (support, distal boundary = lo), -1 bearish
    (resistance, distal boundary = hi). ``bar`` needs ``.high``/``.low``/
    ``.close`` (a raw Bar or an HTFBar both satisfy this).
    """
    w = hi - lo
    tolerance = 0.20 * w
    # Floating-point epsilon: real prices are tick-quantized (NQ_TICK=0.25),
    # so any genuine boundary distinction is orders of magnitude larger than
    # this -- it only absorbs arithmetic drift at an exact-tolerance edge.
    eps = 1e-9

    if direction > 0:
        distal = lo
        penetration = distal - bar.low          # > 0 means wick broke below lo
        if bar.close < distal - eps:
            return TraversalResult(None, True, DEACTIVATED_CLOSE_THROUGH)
        if penetration > tolerance + eps:
            return TraversalResult(None, True, DEACTIVATED_OVERSHOOT_LIMIT)
        reached = bar.low <= hi
        if not reached:
            return TraversalResult(None, False, None)
        if penetration > eps:  # wick beyond lo, within tolerance, close held
            return TraversalResult(VALID_OVERSHOOT_RECLAIM, False, None)
        return TraversalResult(VALID_TAP, False, None)
    else:
        distal = hi
        penetration = bar.high - distal          # > 0 means wick broke above hi
        if bar.close > distal + eps:
            return TraversalResult(None, True, DEACTIVATED_CLOSE_THROUGH)
        if penetration > tolerance + eps:
            return TraversalResult(None, True, DEACTIVATED_OVERSHOOT_LIMIT)
        reached = bar.high >= lo
        if not reached:
            return TraversalResult(None, False, None)
        if penetration > eps:
            return TraversalResult(VALID_OVERSHOOT_RECLAIM, False, None)
        return TraversalResult(VALID_TAP, False, None)

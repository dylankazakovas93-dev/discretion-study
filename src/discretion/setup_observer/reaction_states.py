"""Descriptive reaction-state classification for a structure interaction.

STRONG DISPLACEMENT IS NOT A UNIVERSAL ENTRY REQUIREMENT. This module measures
the complete per-candle reaction path after an interaction and reports, for
each distinct observable state, the *first completed same-timeframe candle
offset* at which that state's condition is causally satisfied (or None).

Nothing here decides that only the strongest state is tradeable. Each state may
seed a separate frozen entry variant (see variants.py). All thresholds are
FROZEN and documented; none is tuned to outcomes.

States (mutually distinguishable in the fingerprint):
  TAP_ONLY, CLOSE_BACK_OUTSIDE, MINIMAL_WICK_REJECTION,
  STRONG_REJECTION_DEPARTURE, IMMEDIATE_DISPLACEMENT, DELAYED_DISPLACEMENT,
  COMPRESSION_THEN_BREAK, SCRAPING_NO_REACTION, FAILED_REACTION.
"""

from __future__ import annotations

from .displacement import (
    _candle_measures, _body, _rng,
    DISP_BODY_ATR, REJECTION_WICK_BODY, COMPRESSION_RANGE_ATR, SCRAP_BODY_ATR,
)

# Frozen state labels.
TAP_ONLY = "TAP_ONLY"
CLOSE_BACK_OUTSIDE = "CLOSE_BACK_OUTSIDE"
MINIMAL_WICK_REJECTION = "MINIMAL_WICK_REJECTION"
STRONG_REJECTION_DEPARTURE = "STRONG_REJECTION_DEPARTURE"
IMMEDIATE_DISPLACEMENT = "IMMEDIATE_DISPLACEMENT"
DELAYED_DISPLACEMENT = "DELAYED_DISPLACEMENT"
COMPRESSION_THEN_BREAK = "COMPRESSION_THEN_BREAK"
SCRAPING_NO_REACTION = "SCRAPING_NO_REACTION"
FAILED_REACTION = "FAILED_REACTION"

# Frozen reaction-window: completed same-tf candles allowed to react.
REACTION_WINDOW = 8
STRONG_CLOSE_LOCATION = 0.60      # strong rejection close toward directional extreme
DISP_CLOSE_LOCATION = 0.65        # displacement close toward directional extreme
DELAYED_MIN, DELAYED_MAX = 2, 5   # delayed displacement candle offsets
COMPRESSION_MIN_CANDLES = 2       # candles of compression before a break


def _entered_zone(c, zone_lo, zone_hi):
    return c.low <= zone_hi and c.high >= zone_lo


def _closed_outside(c, direction, zone_lo, zone_hi):
    return (c.close > zone_hi) if direction > 0 else (c.close < zone_lo)


def penetration_depth(c, direction, zone_lo, zone_hi):
    """How far the interaction candle reached into the zone (points, >=0)."""
    width = zone_hi - zone_lo
    if direction > 0:            # support: price enters from above, wick down
        pen = zone_hi - c.low
    else:                        # resistance: price enters from below, wick up
        pen = c.high - zone_lo
    return round(max(0.0, min(pen, width if width > 0 else pen)), 4)


def build_trace(series, atr, i_idx, direction, zone_lo, zone_hi):
    """Full per-candle reaction measures for the interaction candle and up to
    REACTION_WINDOW completed candles after it (spec Part 3)."""
    trace = []
    n = len(series)
    for k in range(0, REACTION_WINDOW + 1):
        j = i_idx + k
        if j >= n:
            break
        m = _candle_measures(series, atr, j, direction, zone_lo, zone_hi, i_idx)
        m["k"] = k
        m["entered_zone"] = _entered_zone(series[j], zone_lo, zone_hi)
        m["closed_outside"] = _closed_outside(series[j], direction, zone_lo, zone_hi)
        trace.append(m)
    return trace


def _median_prior(series, j, fn, look=10):
    prior = series[max(0, j - look):j]
    if not prior:
        return 0.0
    vals = sorted(fn(x) for x in prior)
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _is_strong_rejection(series, m, j, direction, zone_lo, zone_hi):
    if not m["is_directional_close"]:
        return False
    if (m["rejection_wick_over_body"] is None
            or m["rejection_wick_over_body"] < REJECTION_WICK_BODY):
        return False
    if m["directional_progress_pts"] <= 0:      # positive departure from the zone
        return False
    med_rng = _median_prior(series, j, _rng)
    med_body = _median_prior(series, j, _body)
    if not (m["range_pts"] >= med_rng):
        return False
    if not (m["body_pts"] >= med_body or (m["body_atr"] is not None and m["body_atr"] >= SCRAP_BODY_ATR)):
        return False
    return m["close_location"] >= STRONG_CLOSE_LOCATION


def _is_displacement(m):
    return (m["is_directional_close"] and m["body_atr"] is not None
            and m["body_atr"] >= DISP_BODY_ATR and m["directional_progress_pts"] > 0
            and m["close_location"] >= DISP_CLOSE_LOCATION)


def classify(series, atr, i_idx, direction, zone_lo, zone_hi, fvg_form, ifvg_form,
             invalidation_idx=None):
    """Return dict: trace, penetration, per-state first-trigger offsets, and the
    dominant descriptive state label. Offsets are candle offsets from ``i_idx``
    (k); entry for a variant is the next 1m bar after candle ``i_idx + k``.

    ``fvg_form`` / ``ifvg_form``: same-tf candle indices where a same-direction
    FVG / iFVG formed (supplied by the observer, causal).
    """
    trace = build_trace(series, atr, i_idx, direction, zone_lo, zone_hi)
    pen = penetration_depth(series[i_idx], direction, zone_lo, zone_hi)

    offsets = {s: None for s in (
        TAP_ONLY, CLOSE_BACK_OUTSIDE, MINIMAL_WICK_REJECTION,
        STRONG_REJECTION_DEPARTURE, IMMEDIATE_DISPLACEMENT, DELAYED_DISPLACEMENT,
        COMPRESSION_THEN_BREAK, "NEW_FVG", "NEW_IFVG")}

    # TAP_ONLY: the interaction itself, requires no later info.
    offsets[TAP_ONLY] = 0

    compression_run = 0
    for m in trace:
        k, j = m["k"], i_idx + m["k"]
        # stop scanning states that need later candles once the structure fails
        failed_here = (invalidation_idx is not None and j >= invalidation_idx)

        if k >= 1 and not failed_here:
            if offsets[CLOSE_BACK_OUTSIDE] is None and m["closed_outside"] \
                    and m["is_directional_close"]:
                offsets[CLOSE_BACK_OUTSIDE] = k
            if offsets[MINIMAL_WICK_REJECTION] is None and m["entered_zone"] \
                    and m["is_directional_close"] and m["closed_outside"] \
                    and (m["rejection_wick_over_body"] or 0) > 0:
                offsets[MINIMAL_WICK_REJECTION] = k
            if offsets[STRONG_REJECTION_DEPARTURE] is None \
                    and _is_strong_rejection(series, m, j, direction, zone_lo, zone_hi):
                offsets[STRONG_REJECTION_DEPARTURE] = k
            if _is_displacement(m):
                if k == 1 and offsets[IMMEDIATE_DISPLACEMENT] is None:
                    offsets[IMMEDIATE_DISPLACEMENT] = k
                elif DELAYED_MIN <= k <= DELAYED_MAX and offsets[DELAYED_DISPLACEMENT] is None:
                    offsets[DELAYED_DISPLACEMENT] = k
            if offsets[COMPRESSION_THEN_BREAK] is None \
                    and compression_run >= COMPRESSION_MIN_CANDLES and _is_displacement(m):
                offsets[COMPRESSION_THEN_BREAK] = k
            if j in fvg_form and offsets["NEW_FVG"] is None:
                offsets["NEW_FVG"] = k
            if j in ifvg_form and offsets["NEW_IFVG"] is None:
                offsets["NEW_IFVG"] = k
            # compression tally (small-range candle before a break)
            if m["range_atr"] is not None and m["range_atr"] < COMPRESSION_RANGE_ATR:
                compression_run += 1
            else:
                compression_run = 0

    # dominant descriptive state (strongest observed reaction), for reporting.
    prog8 = None
    for m in trace:
        if m["k"] in (5, 8):
            prog8 = m["directional_progress_pts"]
    if invalidation_idx is not None and invalidation_idx <= i_idx + REACTION_WINDOW \
            and offsets[STRONG_REJECTION_DEPARTURE] is None \
            and offsets[IMMEDIATE_DISPLACEMENT] is None \
            and offsets[DELAYED_DISPLACEMENT] is None:
        dominant = FAILED_REACTION
    elif offsets[IMMEDIATE_DISPLACEMENT] is not None:
        dominant = IMMEDIATE_DISPLACEMENT
    elif offsets[COMPRESSION_THEN_BREAK] is not None:
        dominant = COMPRESSION_THEN_BREAK
    elif offsets[DELAYED_DISPLACEMENT] is not None:
        dominant = DELAYED_DISPLACEMENT
    elif offsets[STRONG_REJECTION_DEPARTURE] is not None:
        dominant = STRONG_REJECTION_DEPARTURE
    elif offsets[MINIMAL_WICK_REJECTION] is not None:
        dominant = MINIMAL_WICK_REJECTION
    elif offsets[CLOSE_BACK_OUTSIDE] is not None:
        dominant = CLOSE_BACK_OUTSIDE
    elif prog8 is not None and prog8 <= 0:
        dominant = SCRAPING_NO_REACTION
    else:
        dominant = TAP_ONLY

    return {"trace": trace, "penetration_depth": pen, "offsets": offsets,
            "dominant_state": dominant, "invalidation_idx": invalidation_idx}

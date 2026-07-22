"""Post-interaction reaction / displacement measurement and branch
classification (spec Part 3). Purely mechanical from OHLC + completed
same-timeframe ATR; no outcome, no look-ahead beyond the bounded confirmation
window. All thresholds are FROZEN and documented here (never tuned to
outcomes).
"""

from __future__ import annotations

from statistics import median

# Frozen, documented reaction thresholds (two-week demo).
DISP_BODY_ATR = 0.5          # a displacement candle's body >= 0.5 * ATR
REJECTION_WICK_BODY = 1.0    # a rejection candle's relevant wick >= 1.0 * body
COMPRESSION_RANGE_ATR = 0.5  # candle range < 0.5 * ATR == compressed
SCRAP_BODY_ATR = 0.30        # body < 0.30 * ATR and no progress == scraping
CONFIRM_WINDOW = 5           # completed same-TF candles allowed to confirm

IMMEDIATE = "IMMEDIATE_DISPLACEMENT"
DELAYED = "DELAYED_DISPLACEMENT"
COMPRESSION = "COMPRESSION_THEN_BREAK"
SCRAPING = "SCRAPING_NO_REACTION"
FAILED = "FAILED_REACTION"


def _body(c):
    return abs(c.close - c.open)


def _rng(c):
    return c.high - c.low


def _overlap(a, b):
    lo = max(min(a.open, a.close, a.low), min(b.open, b.close, b.low))
    # use full-range overlap (high-low) for a simple deterministic measure
    lo = max(a.low, b.low)
    hi = min(a.high, b.high)
    return max(0.0, hi - lo)


def _candle_measures(series, atr, j, direction, zone_lo, zone_hi, i_idx):
    c = series[j]
    a = atr[j] or 0.0
    body = _body(c)
    rng = _rng(c)
    prior = series[max(0, j - 10):j]
    med_body = median([_body(x) for x in prior]) if prior else 0.0
    med_rng = median([_rng(x) for x in prior]) if prior else 0.0
    if direction > 0:
        rej_wick = min(c.open, c.close) - c.low
        close_loc = (c.close - c.low) / rng if rng else 0.0
        # progress away from the zone: how far the close is above the zone top
        progress = c.close - zone_hi
    else:
        rej_wick = c.high - max(c.open, c.close)
        close_loc = (c.high - c.close) / rng if rng else 0.0
        progress = zone_lo - c.close
    ov = [round(_overlap(c, series[j - k]), 4) for k in (1, 2, 3) if j - k >= 0]
    return {
        "offset": j - i_idx,
        "body_pts": round(body, 4), "range_pts": round(rng, 4),
        "body_atr": round(body / a, 4) if a else None,
        "range_atr": round(rng / a, 4) if a else None,
        "body_vs_median10": round(body / med_body, 4) if med_body else None,
        "range_vs_median10": round(rng / med_rng, 4) if med_rng else None,
        "rejection_wick_pts": round(max(0.0, rej_wick), 4),
        "rejection_wick_over_body": round(rej_wick / body, 4) if body else None,
        "close_location": round(close_loc, 4),
        "directional_progress_pts": round(progress, 4),
        "overlap_prior3": ov,
        "atr": a,
        "is_directional_close": (c.close > c.open) if direction > 0 else (c.close < c.open),
    }


def _cum_progress(series, i_idx, direction, zone_lo, zone_hi):
    out = {}
    for n in (1, 2, 3, 5, 8):
        j = i_idx + n
        if j < len(series):
            c = series[j]
            out[f"cum_progress_{n}"] = round(
                (c.close - zone_hi) if direction > 0 else (zone_lo - c.close), 4)
        else:
            out[f"cum_progress_{n}"] = None
    return out


def measure_reaction(series, atr, i_idx, direction, zone_lo, zone_hi,
                     fvg_form_idx, ifvg_form_idx, invalidation_idx=None):
    """Measure the reaction after an interaction at candle ``i_idx`` on this
    timeframe. Returns per-candle measures, cumulative progress, the branch
    label, and (confirm_offset, confirm_idx) or (None, None) if it never
    confirmed within the window.

    ``fvg_form_idx`` / ``ifvg_form_idx``: sets of same-timeframe candle indices
    at which a *same-direction* FVG / iFVG formed (supplied by the observer).
    ``invalidation_idx``: candle index at which the context structure was
    structurally invalidated (close-through), or None.
    """
    n = len(series)
    per = []
    confirm_offset = None
    confirm_idx = None
    confirm_reason = None
    saw_compression = False

    for k in range(1, CONFIRM_WINDOW + 1):
        j = i_idx + k
        if j >= n:
            break
        # failed reaction: structure invalidated before confirmation
        if invalidation_idx is not None and j >= invalidation_idx and confirm_idx is None:
            per.append(_candle_measures(series, atr, j, direction, zone_lo, zone_hi, i_idx))
            branch = FAILED
            return {"per_candle": per, "cumulative": _cum_progress(series, i_idx, direction, zone_lo, zone_hi),
                    "branch": branch, "confirm_offset": None, "confirm_idx": None,
                    "confirm_reason": "structure_invalidated_before_confirmation"}
        m = _candle_measures(series, atr, j, direction, zone_lo, zone_hi, i_idx)
        per.append(m)
        if (m["range_atr"] is not None and m["range_atr"] < COMPRESSION_RANGE_ATR):
            saw_compression = True
        # confirmation tests (any one; must be directional)
        disp = (m["body_atr"] is not None and m["body_atr"] >= DISP_BODY_ATR
                and m["is_directional_close"] and m["directional_progress_pts"] > 0)
        rej = (m["rejection_wick_over_body"] is not None
               and m["rejection_wick_over_body"] >= REJECTION_WICK_BODY
               and m["is_directional_close"])
        new_fvg = j in fvg_form_idx
        new_ifvg = j in ifvg_form_idx
        if disp or rej or new_fvg or new_ifvg:
            confirm_offset = k
            confirm_idx = j
            confirm_reason = ("displacement" if disp else "rejection" if rej
                              else "same_dir_fvg" if new_fvg else "same_dir_ifvg")
            break

    cumulative = _cum_progress(series, i_idx, direction, zone_lo, zone_hi)
    if confirm_idx is None:
        # never confirmed: scraping (no progress, small bodies) vs failed
        prog = cumulative.get(f"cum_progress_{CONFIRM_WINDOW}")
        branch = SCRAPING if (prog is None or prog <= 0) else DELAYED
        if branch == SCRAPING:
            return {"per_candle": per, "cumulative": cumulative, "branch": SCRAPING,
                    "confirm_offset": None, "confirm_idx": None,
                    "confirm_reason": "no_confirmation_in_window"}
        # progressed but no single confirmation candle -> treat as no setup
        return {"per_candle": per, "cumulative": cumulative, "branch": SCRAPING,
                "confirm_offset": None, "confirm_idx": None,
                "confirm_reason": "no_confirmation_candle"}

    if confirm_offset == 1 and confirm_reason in ("displacement", "rejection"):
        branch = IMMEDIATE
    elif saw_compression:
        branch = COMPRESSION
    else:
        branch = DELAYED
    return {"per_candle": per, "cumulative": cumulative, "branch": branch,
            "confirm_offset": confirm_offset, "confirm_idx": confirm_idx,
            "confirm_reason": confirm_reason}

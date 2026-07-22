"""Shared frozen helpers for the setup observer (bins, direction, causal
availability, timeframe start-seq). Kept separate so observer.py and
variants.py can both use them without a circular import."""

from __future__ import annotations

MIN_EXECUTABLE_RR = 0.5   # frozen execution floor (unchanged)

# frozen continuous-feature bins for EXACT matching
WIDTH_ATR_BINS = ((0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1e9))
WICKBODY_BINS = ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 1e9))
RR_BINS = ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 1e9))
DELAY_BINS = ((0, 1), (1, 2), (2, 4), (4, 6), (6, 1e9))   # interaction->trigger candles


def _bin(x, bins):
    if x is None:
        return "na"
    for lo, hi in bins:
        if lo <= x < hi:
            return f"{lo}-{hi}"
    return f">{bins[-1][0]}"


def _dir(word):
    return 1 if word == "bullish" else -1


def _avail(tf, series, candle_seq):
    """First global 1m seq at which the completed ``tf`` candle is usable."""
    return candle_seq + 1 if tf == 1 else series[candle_seq].available_seq


def _tf_start_seq(tf, series, candle_seq):
    """Global 1m seq of the candle's first constituent bar (its open)."""
    return candle_seq if tf == 1 else series[candle_seq].start_seq

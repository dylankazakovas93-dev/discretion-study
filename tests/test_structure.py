"""Compression/expansion, failed break, swings, equal-level clusters."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.levels import Level
from discretion.primitives.structure import (
    detect_swings, detect_equal_levels, detect_compression_expansion,
)
from helpers import make_bars


def _atr(bars):
    return [1.0] * len(bars)


def test_compression_then_expansion_continuation():
    rows = [(100, 100.4, 99.8, 100.1)] * 8      # tight compression band
    rows += [(100.1, 102, 100.1, 101.8)]        # breakout up (range 1.9 >= 1.5 ATR)
    rows += [(101.8, 103, 101.7, 102.6)]        # continuation
    bars = make_bars(rows)
    zones = detect_compression_expansion(bars, _atr(bars), IdRegistry())
    comp = [z for z in zones if z.subtype == "compression"]
    assert comp
    z = comp[0]
    assert z.has_event("COMPRESSION")
    assert z.has_event("BREAK")
    assert z.has_event("CONTINUATION")


def test_compression_failed_break_returns_to_range():
    rows = [(100, 100.4, 99.8, 100.1)] * 8
    rows += [(100.1, 102, 100.1, 101)]          # break up (close 101 > band_hi)
    rows += [(101, 101, 100.0, 100.1)]          # closes back inside band -> failed
    bars = make_bars(rows)
    zones = detect_compression_expansion(bars, _atr(bars), IdRegistry())
    z = [z for z in zones if z.subtype == "compression"][0]
    assert z.has_event("FAILED_CONTINUATION")


def test_confirmed_swing_high_is_right_edge_dated():
    # peak at index 2; with K=2 it is confirmed at index 4, never at index 2.
    bars = make_bars([
        (100, 100.5, 99.5, 100),
        (100, 101.5, 100, 101),
        (101, 103, 101, 102),      # pivot high 103 at idx2
        (102, 102, 101, 101.5),
        (101.5, 101.8, 100.5, 101),
    ])
    swings = detect_swings(bars, IdRegistry())
    highs = [s for s in swings if s.subtype == "swing_high" and s.price_ref == 103.0]
    assert len(highs) == 1
    assert highs[0].created_seq == 4  # confirmation stamped at right edge, not idx2


def test_equal_highs_cluster():
    reg = IdRegistry()
    a = Level(id="LVL-1", family="liquidity", subtype="swing_high", segment_id=0,
              created_seq=4, created_ts=None, lo=100.0, hi=100.0, price_ref=100.0,
              source="swing")
    b = Level(id="LVL-2", family="liquidity", subtype="swing_high", segment_id=0,
              created_seq=10, created_ts=None, lo=100.25, hi=100.25, price_ref=100.25,
              source="swing")
    equals = detect_equal_levels([a, b], reg)
    eq_highs = [e for e in equals if e.subtype == "equal_highs"]
    assert len(eq_highs) == 1
    assert eq_highs[0].created_seq == 10  # knowable only after the later swing

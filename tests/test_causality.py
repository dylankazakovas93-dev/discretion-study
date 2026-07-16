"""Causality invariants: ATR reset per segment, no cross-roll structures,
completed-bars-only availability."""

from __future__ import annotations

from discretion.data.atr import wilder_atr, true_ranges
from discretion.primitives.levels import Level
from discretion.setups.structural import nearest_level_above, nearest_level_below
from helpers import make_bars, concat_segments


def test_atr_resets_per_segment():
    seg0 = make_bars([(100, 101, 99, 100)] * 6, contract="NQM5", segment=0)
    seg1 = make_bars([(200, 201, 199, 200)] * 6, start="2025-07-07 10:00",
                     contract="NQU5", segment=1)
    bars = concat_segments(seg0, seg1)
    atr = wilder_atr(bars, period=3)
    # first bar of segment 1 has no in-segment predecessor -> its TR is None
    trs = true_ranges(bars)
    assert trs[6] is None
    # ATR is not seeded until `period` in-segment TRs accumulate after the roll
    assert atr[6] is None
    assert atr[7] is None
    assert atr[8] is None
    assert atr[9] is not None  # seeded at within==period (index 6+3)


def test_atr_is_causal_backward_only():
    bars = make_bars([
        (100, 102, 99, 101), (101, 103, 100, 102), (102, 104, 101, 103),
        (103, 105, 102, 104),
    ])
    atr = wilder_atr(bars, period=2)
    # atr at index 2 must equal avg of TRs at indices 1,2 only (no future bar 3)
    trs = true_ranges(bars)
    assert atr[2] == (trs[1] + trs[2]) / 2


def test_levels_never_selected_across_segments():
    a = Level(id="LVL-1", family="hist_level", subtype="x", segment_id=0,
              created_seq=0, created_ts=None, lo=90.0, hi=90.0, price_ref=90.0)
    b = Level(id="LVL-2", family="hist_level", subtype="x", segment_id=1,
              created_seq=0, created_ts=None, lo=110.0, hi=110.0, price_ref=110.0)
    # querying within segment 0 must never return the segment-1 level
    above = nearest_level_above(100.0, 10, 0, [a, b])
    below = nearest_level_below(100.0, 10, 0, [a, b])
    assert above is None            # no same-segment level above 100
    assert below is a               # only the same-segment level below


def test_level_not_available_before_creation():
    a = Level(id="LVL-1", family="hist_level", subtype="x", segment_id=0,
              created_seq=50, created_ts=None, lo=90.0, hi=90.0, price_ref=90.0)
    # at seq 10 the level (created at 50) is not yet knowable
    assert nearest_level_below(100.0, 10, 0, [a]) is None
    assert nearest_level_below(100.0, 60, 0, [a]) is a

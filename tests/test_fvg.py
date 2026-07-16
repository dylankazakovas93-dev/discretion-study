"""FVG formation and interaction/entry-mode states."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.fvg import detect_fvgs
from helpers import make_bars, concat_segments


def test_bullish_fvg_formation():
    # A.high=101, C.low=102 -> bullish gap [101,102], knowable at C (index 2).
    bars = make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),
        (105, 105.5, 104.5, 105),  # away, no touch
    ])
    fvgs = detect_fvgs(bars, IdRegistry())
    bull = [f for f in fvgs if f.direction > 0 and (f.lo, f.hi) == (101.0, 102.0)]
    assert len(bull) == 1
    f = bull[0]
    assert f.subtype == "bullish"
    assert f.created_seq == 2  # only knowable after candle C closes
    assert f.first_event("FORMED").seq == 2


def test_bearish_fvg_formation():
    # A.low=99, C.high=98 -> bearish gap [98,99].
    bars = make_bars([
        (100, 101, 99, 99.5),
        (99, 99, 96, 96.5),
        (96.5, 98, 94, 95),
        (95, 95.5, 94.5, 95),
    ])
    fvgs = detect_fvgs(bars, IdRegistry())
    bear = [f for f in fvgs if f.direction < 0 and (f.lo, f.hi) == (98.0, 99.0)]
    assert len(bear) == 1
    f = bear[0]
    assert f.created_seq == 2


def test_no_future_information_before_c_closes():
    # If the "C" bar does not clear A.high, no FVG exists yet.
    bars = make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 100.5, 105),  # C.low=100.5 < A.high 101 -> no gap
    ])
    fvgs = detect_fvgs(bars, IdRegistry())
    assert [f for f in fvgs if f.direction > 0] == []


def test_fvg_entry_mode_states_first_touch_mid_full():
    bars = make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),   # bull gap [101,102], C idx 2
        (105, 105, 101.6, 101.6),  # touch (low 101.6<=hi 102) + fill + partial
        (101.6, 101.6, 100.9, 101.2),  # midpoint(<=101.5) + full fill(<=101) but close 101.2>=101 no failure
    ])
    f = [x for x in detect_fvgs(bars, IdRegistry()) if x.direction > 0][0]
    assert f.first_event("FIRST_TOUCH").seq == 3
    assert f.first_event("FIRST_FILL").seq == 3
    assert f.first_event("MIDPOINT").seq == 4
    assert f.first_event("FULL_FILL").seq == 4
    assert not f.has_event("FAILURE")


def test_fvg_continuation_without_fill():
    bars = make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),   # bull gap [101,102]
        (105, 108, 105, 107),     # continues up
        (107, 110, 107, 109),
    ])
    f = [x for x in detect_fvgs(bars, IdRegistry()) if x.direction > 0][0]
    assert not f.touched
    assert f.has_event("CONTINUATION")


def test_fvg_failure_close_through():
    bars = make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),   # bull gap [101,102]
        (105, 105, 100, 100.4),   # closes 100.4 < lo 101 -> FAILURE
    ])
    f = [x for x in detect_fvgs(bars, IdRegistry()) if x.direction > 0][0]
    assert f.has_event("FAILURE")
    assert f.failed_seq == 3
    assert not f.active


def test_fvg_does_not_cross_contract_roll():
    seg0 = make_bars([(100, 101, 99, 100.5), (101, 104, 101, 103.5)],
                     contract="NQM5", segment=0)
    # C is in a different segment; the triple must not form across the roll.
    seg1 = make_bars([(103.5, 106, 102, 105)], start="2025-07-07 09:32",
                     contract="NQU5", segment=1)
    bars = concat_segments(seg0, seg1)
    fvgs = detect_fvgs(bars, IdRegistry())
    assert fvgs == []

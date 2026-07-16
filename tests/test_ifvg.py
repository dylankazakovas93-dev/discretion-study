"""iFVG activation (immediate) and retest."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.fvg import detect_fvgs
from discretion.primitives.ifvg import detect_ifvgs
from helpers import make_bars


def _bearish_ifvg_bars():
    # bullish gap [101,102] then close-through down -> bearish iFVG, then retest up.
    return make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),    # bull gap [101,102], idx2
        (105, 105, 100, 100.4),    # FAILURE close 100.4 -> bearish iFVG idx3
        (100.4, 101.5, 100.4, 100.8),  # retest into [101,102], reject (close<101)
    ])


def test_bearish_ifvg_activation_immediate():
    bars = _bearish_ifvg_bars()
    reg = IdRegistry()
    fvgs = detect_fvgs(bars, reg)
    ifvgs = detect_ifvgs(bars, fvgs, reg)
    bear = [iv for iv in ifvgs if iv.direction < 0]
    assert len(bear) == 1
    iv = bear[0]
    assert iv.subtype == "bearish"
    assert (iv.lo, iv.hi) == (101.0, 102.0)
    conf = iv.first_event("CONFIRMED")
    assert conf is not None and conf.seq == 3  # activation at close-through bar
    assert iv.source_fvg_id.startswith("FVG-")


def test_bearish_ifvg_retest_and_rejection():
    bars = _bearish_ifvg_bars()
    reg = IdRegistry()
    fvgs = detect_fvgs(bars, reg)
    iv = [x for x in detect_ifvgs(bars, fvgs, reg) if x.direction < 0][0]
    ft = iv.first_event("FIRST_TOUCH")
    assert ft is not None and ft.seq == 4  # retest happens later, not required same bar
    assert iv.has_event("REJECTION")


def test_bullish_ifvg_from_bearish_fvg_failure():
    # bearish gap [98,99] then close-through up -> bullish iFVG.
    bars = make_bars([
        (100, 101, 99, 99.5),
        (99, 99, 96, 96.5),
        (96.5, 98, 94, 95),     # bear gap [98,99], idx2
        (95, 100, 95, 99.5),    # close 99.5 > hi 99 -> FAILURE -> bullish iFVG
    ])
    reg = IdRegistry()
    fvgs = detect_fvgs(bars, reg)
    bull = [iv for iv in detect_ifvgs(bars, fvgs, reg) if iv.direction > 0]
    assert len(bull) == 1
    assert bull[0].first_event("CONFIRMED").seq == 3

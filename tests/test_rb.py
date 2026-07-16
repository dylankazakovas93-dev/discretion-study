"""Rejection block creation, confirmation, revisit, exact boundary, invalidation."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.rejection_block import detect_rejection_blocks
from helpers import make_bars


def _atr(bars):
    return [1.0] * len(bars)


def test_bullish_rb_creation_and_confirmation():
    bars = make_bars([
        (101, 101, 100, 100.5),
        (100.5, 100.6, 100.2, 100.4),
        (100.4, 100.5, 98, 100.2),   # long lower wick, local low -> bullish RB cand
        (100.2, 101, 100.2, 100.8),  # closes above body edge -> CONFIRMED
    ])
    rbs = detect_rejection_blocks(bars, _atr(bars), IdRegistry())
    bull = [r for r in rbs if r.direction > 0]
    assert len(bull) == 1
    r = bull[0]
    assert (r.lo, r.hi) == (98.0, 100.2)
    assert r.candidate_seq == 2
    assert r.first_event("CONFIRMED").seq == 3


def test_bullish_rb_revisit_and_exact_boundary_and_reject():
    bars = make_bars([
        (101, 101, 100, 100.5),
        (100.5, 100.6, 100.2, 100.4),
        (100.4, 100.5, 98, 100.2),   # RB zone [98,100.2]
        (100.2, 101, 100.2, 100.8),  # CONFIRMED
        (100.8, 101, 100.8, 101),    # away
        (101, 101, 100.2, 100.9),    # low touches boundary 100.2 exactly -> EXACT_TOUCH + REJECTION
    ])
    r = [x for x in detect_rejection_blocks(bars, _atr(bars), IdRegistry())
         if x.direction > 0][0]
    assert r.first_event("FIRST_TOUCH").seq == 5
    assert r.has_event("EXACT_TOUCH")
    assert r.has_event("REJECTION")


def test_bullish_rb_invalidation_close_through_wick():
    bars = make_bars([
        (101, 101, 100, 100.5),
        (100.5, 100.6, 100.2, 100.4),
        (100.4, 100.5, 98, 100.2),   # RB zone [98,100.2]
        (100.2, 101, 100.2, 100.8),  # CONFIRMED
        (100.8, 100.8, 97, 97.5),    # closes 97.5 < zlo 98 -> INVALIDATION
    ])
    r = [x for x in detect_rejection_blocks(bars, _atr(bars), IdRegistry())
         if x.direction > 0][0]
    assert r.has_event("INVALIDATION")
    assert not r.active


def test_bearish_rb_creation():
    bars = make_bars([
        (99, 100, 99, 99.5),
        (99.5, 99.8, 99.4, 99.6),
        (99.6, 102, 99.5, 99.8),   # long upper wick, local high -> bearish RB
        (99.8, 99.8, 99, 99.2),    # closes below body edge -> CONFIRMED
    ])
    rbs = detect_rejection_blocks(bars, _atr(bars), IdRegistry())
    bear = [r for r in rbs if r.direction < 0]
    assert len(bear) == 1
    assert bear[0].first_event("CONFIRMED") is not None

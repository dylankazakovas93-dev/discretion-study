"""Horizontal level interactions: touch, sweep, break, reclaim, acceptance,
continuation without a sweep; plus time-anchor construction."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.levels import (
    Level, track_level_interactions, build_time_anchors,
)
from helpers import make_bars


def _level(price, seg=0):
    lv = Level(
        id="LVL-000001", family="hist_level", subtype="test", segment_id=seg,
        created_seq=0, created_ts=None, lo=price, hi=price, price_ref=price,
    )
    return lv


def test_sweep_and_rejection():
    lv = _level(100.0)
    lv.created_ts = None
    bars = make_bars([
        (99, 99.5, 98.5, 99),      # seq0 (level knowable, tracking from seq1)
        (99, 100.5, 99, 99.2),     # seq1 pierces 100, closes back below -> SWEEP+REJECTION
    ])
    track_level_interactions([lv], bars)
    assert lv.has_event("SWEEP")
    assert lv.has_event("REJECTION")


def test_break_and_acceptance_and_continuation_without_sweep():
    lv = _level(100.0)
    bars = make_bars([
        (99, 99.5, 98.5, 99),      # seq0
        (99, 101, 99, 100.5),      # seq1 close above -> BREAK (no wick back = no sweep)
        (100.5, 101, 100.3, 100.8),  # seq2 second close above -> ACCEPTANCE_ABOVE
        (100.8, 101.2, 100.6, 101),  # seq3 third close above -> CONTINUATION
    ])
    track_level_interactions([lv], bars)
    assert lv.has_event("BREAK")
    assert lv.has_event("ACCEPTANCE_ABOVE")
    assert lv.has_event("CONTINUATION")
    assert not lv.has_event("SWEEP")  # clean break, no liquidity sweep required


def test_reclaim_after_break():
    lv = _level(100.0)
    bars = make_bars([
        (99, 99.5, 98.5, 99),
        (99, 101, 99, 100.5),      # break up
        (100.5, 100.6, 99, 99.2),  # close back below -> RECLAIM (side flip)
    ])
    track_level_interactions([lv], bars)
    assert lv.has_event("RECLAIM")


def test_time_anchor_constructed_at_0930():
    bars = make_bars([
        (100, 101, 99, 100.5),   # 09:30 ET
        (100.5, 101, 100, 100.2),
    ], start="2025-07-07 09:30")
    anchors = build_time_anchors(bars, IdRegistry())
    a0930 = [a for a in anchors if a.subtype == "open_0930"]
    assert len(a0930) == 1
    assert a0930[0].price_ref == 100.0  # anchor price = open of the 09:30 bar
    assert a0930[0].created_seq == 0

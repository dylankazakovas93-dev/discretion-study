"""Prominent-wick liquidity inventory tests."""

from __future__ import annotations

import os

import pytest

from discretion.data.aggregation import HTFBar, aggregate_all
from discretion.primitives.base import IdRegistry
from discretion.primitives.wick_liquidity import detect_wick_liquidity
from discretion.data.loader import load_front_month, DATA_FILES
from helpers import make_bars

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _htf(cid, o, h, l, c, seg=0, avail=1, atr=2.0, tf=5, seq=0):
    return HTFBar(candle_id=cid, timeframe=tf, open_ts="t", close_ts="t",
                  start_seq=seq, end_seq=seq, available_seq=avail, open=o, high=h,
                  low=l, close=c, volume=100, segment_id=seg, norm_segment_id=seg,
                  atr=atr)


def _detect(candles, bars=None):
    return detect_wick_liquidity(bars or [], {5: candles}, IdRegistry())


def test_every_wick_from_completed_candle():
    candles = [_htf("HTF5m-000001", 100, 110, 99, 104)]
    objs = _detect(candles)
    assert objs
    for o in objs:
        assert o.source_candle_id == "HTF5m-000001"
        assert o.created_seq == candles[0].available_seq


def test_exposed_prominent_wick_detected():
    # a big protruding upper wick above the (empty) prior set -> exposed exists
    o = _detect([_htf("HTF5m-000001", 100, 112, 99.5, 101)])
    up = [x for x in o if x.side == "upper"][0]
    assert up.exposed[5] is not None
    assert up.full_hi == 112 and up.proximal == 101  # body_top=max(open,close)=101


def test_previous_candle_overlap_removes_exposed_surface():
    # candle 2's upper wick is buried below candle 1's high -> no exposed surface
    c1 = _htf("HTF5m-000001", 100, 120, 99, 118, avail=1)
    c2 = _htf("HTF5m-000002", 110, 112, 109, 110.5, avail=2)  # high 112 < prev high 120
    objs = _detect([c1, c2])
    up2 = [o for o in objs if o.source_candle_id == "HTF5m-000002" and o.side == "upper"]
    assert up2 and up2[0].exposed[5] is None


def test_weak_ordinary_wick_is_low():
    # tiny wick, small range -> LOW grade
    o = _detect([_htf("HTF5m-000001", 100, 100.3, 99.9, 100.1, atr=5.0)])
    for x in o:
        assert x.prominence_grade == "LOW"


def test_positive_overlap_removes_freshness_but_exact_touch_does_not():
    c = _htf("HTF5m-000001", 100, 110, 99, 101, avail=1)  # upper wick [101,110]
    # bar1: high exactly at proximal 101 (touch, no overlap); bar2: into zone
    bars = make_bars([(100, 100, 99, 100),         # seq0 (before avail)
                      (100.5, 101.0, 100, 100.5),   # seq1 exact boundary touch
                      (100.5, 105.0, 100, 104)])     # seq2 positive overlap into zone
    up = [o for o in _detect([c], bars) if o.side == "upper"][0]
    assert up.first_touch_seq == 1
    assert up.fresh_at(1) is True               # exact touch keeps freshness
    assert up.positive_overlap_seq == 2
    assert up.fresh_at(2) is False              # overlap consumes freshness


def test_sweep_consumes_object():
    c = _htf("HTF5m-000001", 100, 110, 99, 101, avail=1)
    bars = make_bars([(100, 100, 99, 100), (100, 111, 100, 105)])  # seq1 sweeps 110
    up = [o for o in _detect([c], bars) if o.side == "upper"][0]
    assert up.swept_seq == 1


def test_upper_lower_symmetry():
    up = _detect([_htf("HTF5m-000001", 105, 112, 104, 106)])   # upper wick 106..112
    lo = _detect([_htf("HTF5m-000001", 105, 106, 98, 104)])    # lower wick 98..104
    u = [o for o in up if o.side == "upper"][0]
    d = [o for o in lo if o.side == "lower"][0]
    assert (u.full_hi - u.proximal) == (d.proximal - d.full_lo)   # symmetric wick len


def test_interaction_does_not_cross_contract_roll():
    c = _htf("HTF5m-000001", 100, 110, 99, 101, seg=0, avail=1)
    # bar in a different segment must not consume the object
    bars = make_bars([(100, 100, 99, 100)], segment=0) + \
        make_bars([(100, 111, 100, 105)], start="2025-07-07 09:31", segment=1)
    up = [o for o in _detect([c], bars) if o.side == "upper"][0]
    assert up.swept_seq is None   # the seg-1 sweep is not applied


def test_no_future_bar_contributes_to_prominence():
    # first candle of a segment has empty history -> neutral percentiles (no future)
    o = _detect([_htf("HTF5m-000001", 100, 112, 99, 101)])
    up = [x for x in o if x.side == "upper"][0]
    assert up.metrics["wick_atr_pct"] == 0.5
    assert up.metrics["range_atr_pct"] == 0.5


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_all_timeframes_present_in_dev_data():
    bars = load_front_month(DATA, start="2025-07-07", end="2025-07-08")
    objs = detect_wick_liquidity(bars, aggregate_all(bars), IdRegistry())
    tfs = {o.timeframe for o in objs}
    assert tfs == {5, 15, 30, 60}
    assert any(o.prominence_grade == "HIGH" for o in objs)

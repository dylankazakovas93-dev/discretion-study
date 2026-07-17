"""HTF FVG + iFVG target inventory tests."""

from __future__ import annotations

import os

import pytest

from discretion.data.aggregation import HTFBar, aggregate_all
from discretion.primitives.base import IdRegistry
from discretion.primitives.htf_fvg import detect_htf_fvgs
from discretion.data.loader import load_front_month, DATA_FILES
from helpers import make_bars

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _htf(cid, o, h, l, c, seg=0, avail=1, atr=5.0, tf=5, seq=0):
    return HTFBar(candle_id=cid, timeframe=tf, open_ts="t", close_ts="t",
                  start_seq=seq, end_seq=seq, available_seq=avail, open=o, high=h,
                  low=l, close=c, volume=100, segment_id=seg, norm_segment_id=seg,
                  atr=atr)


def _bearish_triple(avail=3):
    # A high 100, C high 90 -> bearish gap [90(C.high), 95(A.low)]
    a = _htf("HTF5m-000001", 99, 100, 95, 96, avail=1)
    b = _htf("HTF5m-000002", 95, 96, 90, 92, avail=2)
    c = _htf("HTF5m-000003", 91, 90, 85, 88, avail=avail)  # C.high 90 < A.low 95
    return [a, b, c]


def _detect(candles, bars=None):
    return detect_htf_fvgs(bars or [], {5: candles}, IdRegistry())


def test_bearish_htf_fvg_detected_with_zone_and_availability():
    fvgs, _ = _detect(_bearish_triple(avail=3))
    assert len(fvgs) == 1
    f = fvgs[0]
    assert f.direction == -1 and f.subtype == "bearish"
    assert (f.lo, f.hi) == (90, 95)
    assert f.a_candle_id == "HTF5m-000001" and f.c_candle_id == "HTF5m-000003"
    assert f.created_seq == 3               # C's available_seq
    assert f.proximal == 90 and f.distal == 95 and f.midpoint == 92.5


def test_bullish_htf_fvg_detected():
    # C.low 108 > A.high 100 -> bullish gap [100,108]
    a = _htf("HTF5m-000001", 96, 100, 95, 99, avail=1)
    b = _htf("HTF5m-000002", 100, 104, 99, 103, avail=2)
    c = _htf("HTF5m-000003", 109, 112, 108, 110, avail=3)
    fvgs, _ = _detect([a, b, c])
    assert len(fvgs) == 1 and fvgs[0].direction == 1
    assert (fvgs[0].lo, fvgs[0].hi) == (100, 108)
    assert fvgs[0].proximal == 108 and fvgs[0].distal == 100  # near edge first


def test_no_gap_when_candles_overlap():
    a = _htf("HTF5m-000001", 99, 105, 95, 100)
    b = _htf("HTF5m-000002", 100, 106, 96, 101)
    c = _htf("HTF5m-000003", 101, 104, 97, 102)   # C.low 97 < A.high 105
    fvgs, _ = _detect([a, b, c])
    assert fvgs == []


def test_surfaces_exposed():
    f = _detect(_bearish_triple())[0][0]
    assert f.surface("PROXIMAL_EDGE") == 90
    assert f.surface("MIDPOINT") == 92.5
    assert f.surface("DISTAL_EDGE") == 95


def test_touch_keeps_freshness_positive_fill_removes_it():
    candles = _bearish_triple(avail=3)   # bearish gap [90,95], proximal 90
    bars = make_bars([(80, 80, 79, 80),          # 0
                      (85, 85, 84, 85),          # 1
                      (85, 86, 84, 85),          # 2
                      (88, 90.0, 87, 89),        # 3 exact proximal touch (high==90)
                      (89, 93.0, 88, 92)])       # 4 positive fill into zone
    f = _detect(candles, bars)[0][0]
    assert f.first_touch_seq == 3
    assert f.fresh_at(3) is True                 # touch alone keeps freshness
    assert f.first_fill_seq == 4
    assert f.fresh_at(4) is False


def test_full_fill_stamped():
    candles = _bearish_triple(avail=3)
    bars = make_bars([(80, 80, 79, 80), (80, 80, 79, 80), (80, 80, 79, 80),
                      (88, 96, 87, 94)])          # 3 pierces distal 95
    f = _detect(candles, bars)[0][0]
    assert f.full_fill_seq == 3


def test_failure_inverts_into_ifvg_with_parent_lineage():
    candles = _bearish_triple(avail=3)   # bearish gap [90,95]
    bars = make_bars([(80, 80, 79, 80), (80, 80, 79, 80), (80, 80, 79, 80),
                      (94, 97, 93, 96.5)])        # 3 closes above hi 95 -> failure
    fvgs, ifvgs = _detect(candles, bars)
    f = fvgs[0]
    assert f.failed_seq == 3 and f.active is False
    assert len(ifvgs) == 1
    iv = ifvgs[0]
    assert iv.source_fvg_id == f.id              # parent lineage
    assert iv.direction == 1 and iv.subtype == "bullish"   # inverted
    assert iv.created_seq == 3 and (iv.lo, iv.hi) == (90, 95)
    assert iv.timeframe == f.timeframe


def test_ifvg_reinversion_invalidates():
    candles = _bearish_triple(avail=3)
    bars = make_bars([(80, 80, 79, 80), (80, 80, 79, 80), (80, 80, 79, 80),
                      (94, 97, 93, 96.5),         # 3 failure -> bullish iFVG [90,95]
                      (95, 96, 94, 95.5),         # 4 holds above
                      (92, 93, 88, 89)])          # 5 closes below lo 90 -> reinvert
    _, ifvgs = _detect(candles, bars)
    iv = ifvgs[0]
    assert iv.reinversion_seq == 5 and iv.active is False


def test_interaction_does_not_cross_contract_roll():
    candles = _bearish_triple(avail=1)   # gap available from seq 1
    bars = make_bars([(80, 80, 79, 80)], segment=0) + \
        make_bars([(94, 97, 93, 96.5)], start="2025-07-07 09:31", segment=1)
    fvgs, ifvgs = _detect(candles, bars)
    assert fvgs[0].failed_seq is None    # the seg-1 close-through is not applied
    assert ifvgs == []


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_all_timeframes_and_ifvgs_present_in_dev_data():
    bars = load_front_month(DATA, start="2025-07-07", end="2025-07-09")
    fvgs, ifvgs = detect_htf_fvgs(bars, aggregate_all(bars), IdRegistry())
    assert {f.timeframe for f in fvgs} == {5, 15, 30, 60}
    assert ifvgs                                   # at least one failure inverted
    assert all(iv.source_fvg_id for iv in ifvgs)   # every iFVG carries lineage

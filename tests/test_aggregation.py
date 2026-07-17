"""Causal 5m/15m/30m/60m aggregation tests."""

from __future__ import annotations

import os

import pytest

from discretion.data.aggregation import aggregate, aggregate_all, TIMEFRAMES
from discretion.data.loader import load_front_month, DATA_FILES
from helpers import make_bars, concat_segments

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _ramp(n, start="2025-07-07 09:30", segment=0, contract="NQU5"):
    rows = []
    for i in range(n):
        base = 100 + i
        rows.append((base, base + 1, base - 1, base + 0.5))
    return make_bars(rows, start=start, segment=segment, contract=contract)


def test_exact_constituent_membership_and_ohlc():
    bars = _ramp(15)
    c5 = aggregate(bars, 5)
    assert len(c5) == 3
    first = c5[0]
    assert (first.start_seq, first.end_seq) == (0, 4)
    assert first.open == bars[0].open
    assert first.close == bars[4].close
    assert first.high == max(b.high for b in bars[:5])
    assert first.low == min(b.low for b in bars[:5])
    assert first.volume == sum(b.volume for b in bars[:5])


def test_availability_only_after_completion():
    bars = _ramp(30)
    for c in aggregate(bars, 15):
        assert c.available_seq == c.end_seq + 1   # usable only after last 1m closes


def test_boundaries_align_per_timeframe():
    # 60m buckets are session/hour-aligned, so anchor at a full hour
    bars = _ramp(60, start="2025-07-07 10:00")
    assert len(aggregate(bars, 5)) == 12
    assert len(aggregate(bars, 15)) == 4
    assert len(aggregate(bars, 30)) == 2
    assert len(aggregate(bars, 60)) == 1
    # a mid-hour start splits the first 60m bucket at the hour boundary
    assert len(aggregate(_ramp(60, start="2025-07-07 09:30"), 60)) == 2


def test_current_candle_excluded_from_atr():
    # many uniform candles then one huge candle; the huge candle's ATR is from
    # priors only, so it is far below the huge candle's own range
    rows = []
    for k in range(20):        # 20 uniform 5m candles (range ~1)
        for m in range(5):
            b = 100 + k * 0.0
            rows.append((b, b + 1, b - 1, b))
    for m in range(5):         # one huge 5m candle (range ~40)
        rows.append((100, 140, 60, 100))
    bars = make_bars(rows)
    c5 = aggregate(bars, 5)
    huge = c5[-1]
    assert huge.high - huge.low >= 40
    assert huge.atr is not None and huge.atr < 10   # not inflated by itself


def test_no_candle_crosses_a_contract_roll():
    seg0 = _ramp(5, contract="NQM5", segment=0)
    seg1 = _ramp(5, start="2025-07-07 09:35", contract="NQU5", segment=1)
    bars = concat_segments(seg0, seg1)
    c5 = aggregate(bars, 5)
    # the roll splits the 5-minute bucket into two single-segment candles
    assert len(c5) == 2
    assert {c.segment_id for c in c5} == {0, 1}


def test_deterministic_ids_and_rerun_identical():
    bars = _ramp(45)
    a = aggregate(bars, 15)
    b = aggregate(bars, 15)
    assert [x.candle_id for x in a] == [x.candle_id for x in b]
    assert all(x.candle_id == f"HTF15m-{i+1:06d}" for i, x in enumerate(a))
    assert all(x.high == y.high and x.available_seq == y.available_seq
               for x, y in zip(a, b))


@pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")
def test_all_timeframes_present_in_dev_data():
    bars = load_front_month(DATA, start="2025-07-07", end="2025-07-08")
    agg = aggregate_all(bars)
    for tf in TIMEFRAMES:
        assert len(agg[tf]) > 0
    # rerun identical
    agg2 = aggregate_all(bars)
    for tf in TIMEFRAMES:
        assert [c.candle_id for c in agg[tf]] == [c.candle_id for c in agg2[tf]]

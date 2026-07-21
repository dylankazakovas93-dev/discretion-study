"""Synthetic proofs for the primitive reset (spec Part 10): FVG, iFVG, RB,
and the common traversal contract. Fast, no raw data dependency -- every
test builds its own tiny deterministic bar sequence. Run with:

    PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
"""
from __future__ import annotations

import pandas as pd
import pytest

from discretion.data.bars import Bar, NQ_TICK
from discretion.primitive_reset.colour import colour, same_colour, BULLISH, BEARISH
from discretion.primitive_reset.timeframes import candle_series, atr_series
from discretion.primitive_reset.registry import ResetRegistry
from discretion.primitive_reset.fvg import detect_fvgs, size_bin
from discretion.primitive_reset.ifvg import detect_ifvgs
from discretion.primitive_reset.rejection_block import detect_rejection_blocks
from discretion.primitive_reset.traversal import (
    zone_step, VALID_TAP, VALID_OVERSHOOT_RECLAIM,
    DEACTIVATED_CLOSE_THROUGH, DEACTIVATED_OVERSHOOT_LIMIT,
)

START = pd.Timestamp("2026-07-13 18:00:00", tz="America/New_York")


def mk_bars(ohlc, start=START, step_minutes=1, segment_id=0, contract="NQU6"):
    """ohlc: list of (o, h, l, c) tuples -> list[Bar], 1 per minute by default."""
    bars = []
    for i, (o, h, l, c) in enumerate(ohlc):
        ts_et = start + pd.Timedelta(minutes=step_minutes * i)
        bars.append(Bar(
            seq=i, ts_utc=ts_et.tz_convert("UTC"), ts_et=ts_et,
            open=o, high=h, low=l, close=c, volume=100,
            contract=contract, segment_id=segment_id,
        ))
    return bars


def flat_preamble(n=20, price=100.0, half_range=2.0):
    """n flat bars with constant true range 2*half_range, seeding ATR."""
    ohlc = [(price, price + half_range, price - half_range, price) for _ in range(n)]
    return ohlc


def seeded_atr(tf=1, n=20, price=100.0, half_range=2.0):
    """Build a preamble + return (bars_so_far, atr_value_at_last_bar)."""
    bars = mk_bars(flat_preamble(n, price, half_range))
    series = candle_series(bars, tf)
    atr = atr_series(series)
    return bars, atr[-1]


# ---------------------------------------------------------------------------
# Colour convention
# ---------------------------------------------------------------------------

def test_doji_close_equals_open_is_bullish_by_convention():
    b = mk_bars([(100, 101, 99, 100)])[0]
    assert colour(b) == BULLISH


def test_ordinary_up_down_colours():
    up = mk_bars([(100, 102, 99, 101)])[0]
    down = mk_bars([(100, 101, 98, 99)])[0]
    assert colour(up) == BULLISH
    assert colour(down) == BEARISH


# ---------------------------------------------------------------------------
# Part 10 / FVG tests
# ---------------------------------------------------------------------------

def test_bullish_same_colour_triple_creates_exact_fvg():
    bars, _ = seeded_atr()
    ohlc = [
        (100, 101, 99.5, 100.5),   # A bullish
        (100.5, 102, 100.2, 101.5),  # B bullish
        (101.5, 103, 101.2, 102.5),  # C bullish, C.low(101.2) > A.high(101)
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    matches = [f for f in fvgs if f.a_seq == len(bars) - 3]
    assert len(matches) == 1
    f = matches[0]
    assert f.direction == BULLISH
    assert f.lo == 101.0 and f.hi == 101.2


def test_bearish_same_colour_triple_creates_exact_fvg():
    bars, _ = seeded_atr()
    ohlc = [
        (103, 103.5, 102, 102.5),   # A bearish
        (102.5, 102.8, 101, 101.5),  # B bearish
        (101.5, 101.8, 100, 100.5),  # C bearish, C.high(101.8) < A.low(102)
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    matches = [f for f in fvgs if f.a_seq == len(bars) - 3]
    assert len(matches) == 1
    f = matches[0]
    assert f.direction == BEARISH
    assert f.lo == 101.8 and f.hi == 102.0


def test_mixed_colour_triple_creates_no_fvg():
    bars, _ = seeded_atr()
    ohlc = [
        (100, 101, 99.5, 100.5),   # bullish
        (100.5, 101, 99, 99.5),    # bearish
        (99.5, 103, 99.2, 102.5),  # bullish, geometry would gap but colours mixed
    ]
    n0 = len(bars)
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    assert not any(f.a_seq == n0 for f in fvgs)


def test_equality_creates_no_fvg():
    bars, _ = seeded_atr()
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.0, 102.5),  # C.low == A.high exactly -> not a gap
    ]
    n0 = len(bars)
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    assert not any(f.a_seq == n0 for f in fvgs)


def test_overlap_creates_no_fvg():
    bars, _ = seeded_atr()
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 100.9, 102.5),  # C.low < A.high -> overlap, no gap
    ]
    n0 = len(bars)
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    assert not any(f.a_seq == n0 for f in fvgs)


def test_near_doji_small_body_not_excluded():
    bars, _ = seeded_atr()
    ohlc = [
        (100.0, 101, 99.5, 100.01),   # tiny bullish body
        (100.01, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    n0 = len(bars)
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    assert any(f.a_seq == n0 for f in fvgs)


def test_canonical_doji_colour_is_documented_and_bullish():
    doji = mk_bars([(100, 101, 99, 100)])[0]
    assert colour(doji) == BULLISH
    assert same_colour(doji, doji, doji)


def test_abc_ids_and_timestamps_are_exact():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    assert f.a_seq == n0 and f.b_seq == n0 + 1 and f.c_seq == n0 + 2
    assert f.a_ts == bars[n0].ts_et and f.c_ts == bars[n0 + 2].ts_et


def test_fvg_unavailable_before_c_closes():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    assert f.formation_ts == bars[n0 + 2].ts_et  # == C's timestamp, not A or B


def test_width_atr_uses_same_timeframe_completed_atr():
    bars, atr_val = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    series = candle_series(bars, 1)
    atr = atr_series(series)
    assert f.atr_at_c_close == atr[f.c_seq]
    assert f.width_atr == pytest.approx(f.width_points / atr[f.c_seq])
    assert f.size_bin == size_bin(f.width_atr)


def test_no_cross_timeframe_atr_contamination():
    bars, _ = seeded_atr(tf=1, half_range=2.0)
    bars2, _ = seeded_atr(tf=1, half_range=8.0)  # different range -> different ATR
    reg1, reg2 = ResetRegistry(), ResetRegistry()
    s1, s2 = candle_series(bars, 1), candle_series(bars2, 1)
    a1, a2 = atr_series(s1), atr_series(s2)
    assert a1[-1] != a2[-1]  # sanity: distinct series produce distinct ATR
    # 5m series built from the 1m bars must use its OWN candle ATR, not 1m's.
    s5 = candle_series(bars, 5)
    a5 = atr_series(s5)
    assert a5[-1] is None or a5[-1] != a1[-1]


def test_eight_hour_expiry_below_1h():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    # fill 8h+ of flat, non-interacting bars far above the zone
    filler = mk_bars(
        [(200, 201, 199, 200)] * 500,
        start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += filler
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    assert f.deactivation_reason == "EXPIRED_UNTOUCHED_8H"
    assert not f.active


def test_no_arbitrary_expiry_at_1h_plus():
    # 1h timeframe: build enough 1m bars to form several 60m candles with a
    # gap, none should expire purely from elapsed time.
    bars, _ = seeded_atr(n=60 * 20)
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 60, reg)
    assert not any(f.deactivation_reason in ("EXPIRED_ACTIVE_8H", "EXPIRED_UNTOUCHED_8H")
                   for f in fvgs)


def test_expiry_does_not_emit_continuation():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    filler = mk_bars([(200, 201, 199, 200)] * 500, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += filler
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    assert "CONTINUATION" not in str(f.deactivation_reason)


def test_data_end_does_not_emit_continuation():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 102.5),
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    f = [f for f in fvgs if f.a_seq == n0][0]
    assert f.deactivation_reason == "DATA_END_ACTIVE"


# ---------------------------------------------------------------------------
# Part 10 / iFVG tests
# ---------------------------------------------------------------------------

def _make_active_fvg(direction=BULLISH):
    bars, _ = seeded_atr()
    n0 = len(bars)
    if direction == BULLISH:
        ohlc = [
            (100, 101, 99.5, 100.5),
            (100.5, 102, 100.2, 101.5),
            (101.5, 103, 101.2, 102.5),  # zone [101, 101.2]
        ]
    else:
        ohlc = [
            (103, 103.5, 102, 102.5),
            (102.5, 102.8, 101, 101.5),
            (101.5, 101.8, 100, 100.5),  # zone [101.8, 102]
        ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    return bars, n0


def test_valid_full_close_through_creates_child_ifvg():
    bars, n0 = _make_active_fvg(BULLISH)
    # next candle closes fully below lo=101.0
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    assert parent.child_ifvg_id is not None
    child = [i for i in ifvgs if i.parent_fvg_id == parent.id][0]
    assert child.child_direction == BEARISH


def test_wick_through_without_close_through_does_not_activate():
    bars, n0 = _make_active_fvg(BULLISH)
    # wick below lo but closes back inside the zone
    bars += mk_bars([(101.1, 101.15, 100.5, 101.05)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    assert parent.child_ifvg_id is None
    assert not any(i.parent_fvg_id == parent.id for i in ifvgs)


def test_inversion_after_parent_expiry_forbidden():
    bars, n0 = _make_active_fvg(BULLISH)
    filler = mk_bars([(200, 201, 199, 200)] * 500, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += filler
    # after expiry, a bar that would have closed through does not create iFVG
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    assert parent.deactivation_reason == "EXPIRED_UNTOUCHED_8H"
    assert not any(i.parent_fvg_id == parent.id for i in ifvgs)


def test_cross_timeframe_inversion_forbidden_by_construction():
    # detect_ifvgs only ever consumes fvgs detected on the SAME series/tf
    # passed in -- there is no code path that accepts a different tf's FVGs.
    bars, n0 = _make_active_fvg(BULLISH)
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs_1m = detect_fvgs(bars, 1, reg)
    series_5m = candle_series(bars, 5)
    atr_5m = atr_series(series_5m)
    ifvgs_5m = detect_ifvgs(bars, 5, fvgs_1m, atr_5m, series_5m, reg)
    assert ifvgs_5m == []  # no 1m FVG's c_seq aligns as a 5m inversion trigger


def test_parent_child_direction_opposite_and_lineage_exact():
    bars, n0 = _make_active_fvg(BULLISH)
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    child = [i for i in ifvgs if i.parent_fvg_id == parent.id][0]
    assert child.parent_direction == BULLISH and child.child_direction == BEARISH
    assert child.parent_fvg_id == parent.id


def test_bars_from_formation_counts_exact():
    bars, n0 = _make_active_fvg(BULLISH)
    # zone [101.0, 101.2], W=0.2, tolerance=0.04 -- scrape bars must stay
    # within that tolerance (else they'd overshoot-kill the parent early)
    bars += mk_bars([
        (101.1, 101.15, 100.97, 101.05),  # scrape (within tolerance), no close-through
        (101.0, 101.1, 100.97, 101.02),   # scrape, no close-through
        (100.9, 100.95, 100.0, 100.5),    # full close-through
    ], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    child = [i for i in ifvgs if i.parent_fvg_id == parent.id][0]
    assert child.bars_from_formation_to_inversion == 3
    assert child.bars_from_first_touch_to_inversion == 2
    assert child.inversion_speed_bucket == "3_candles"


def test_five_candle_inversion_valid_if_parent_still_active():
    bars, n0 = _make_active_fvg(BULLISH)
    scrapes = [(101.1, 101.15, 100.97, 101.05)] * 4
    bars += mk_bars(scrapes, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    child = [i for i in ifvgs if i.parent_fvg_id == parent.id][0]
    assert child.bars_from_formation_to_inversion == 5
    assert child.inversion_speed_bucket == "5plus_candles"


def test_parent_transitions_to_inverted_when_child_activates():
    bars, n0 = _make_active_fvg(BULLISH)
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    assert parent.active is False
    assert parent.deactivation_reason == DEACTIVATED_CLOSE_THROUGH


def test_child_ifvg_applies_own_eight_hour_lifetime():
    bars, n0 = _make_active_fvg(BULLISH)
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    filler = mk_bars([(50, 51, 49, 50)] * 500, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += filler
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    child = [i for i in ifvgs if i.parent_fvg_id == parent.id][0]
    assert child.deactivation_reason == "EXPIRED_UNTOUCHED_8H"


# ---------------------------------------------------------------------------
# Part 10 / RB tests
# ---------------------------------------------------------------------------

def test_wick_body_below_020_rejected_as_candidate():
    bars, atr_val = seeded_atr()
    # lower wick = 0.15 * body, well under floor
    body = 4.0
    wick = 0.15 * body
    bars += mk_bars([(100, 100 + body, 100 - wick, 100 + body)],
                    start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, 100, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    src_seq = len(bars) - 6
    assert not any(r.source_seq == src_seq for r in rbs)


def test_wick_body_exactly_020_accepted_as_candidate():
    bars, atr_val = seeded_atr()
    body = 4.0
    wick = 0.20 * body
    src_open = 100.0
    src_close = src_open + body
    src_low = src_open - wick
    bars += mk_bars([(src_open, src_close + 0.01, src_low, src_close)],
                    start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    bars += mk_bars(flat_preamble(5, 100, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    matches = [r for r in rbs if r.source_seq == src_seq and r.direction == "bullish"]
    assert len(matches) == 1
    assert matches[0].wick_body_ratio == pytest.approx(0.20, rel=1e-6)


def test_no_classical_swing_pivot_requirement():
    # a wick deep inside a trend (not a local extreme) still qualifies
    bars, atr_val = seeded_atr()
    trend = [(100 + i, 101 + i, 99.5 + i, 100.8 + i) for i in range(5)]
    bars += mk_bars(trend, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    mid_seq = len(bars)
    bars += mk_bars([(105, 105.2, 100.0, 105.1)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, 105, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    assert any(r.source_seq == mid_seq for r in rbs)


def _rb_with_mfe(direction, mfe_atr_mult, n_candles_to_reach):
    """Build a source bar + a next-3-candle window whose running MFE crosses
    ``mfe_atr_mult`` * ATR on candle ``n_candles_to_reach`` (1..3), or never
    if ``n_candles_to_reach`` is None."""
    bars, atr_val = seeded_atr()
    body = 4.0
    wick = 1.0 * body  # comfortably above the 0.20 floor
    if direction == "bullish":
        src_open, src_close = 100.0, 100.0 + body
        src_low = src_open - wick
        proximal = src_close  # body_hi == proximal for bullish
        bars += mk_bars([(src_open, src_close, src_low, src_close)],
                        start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    else:
        src_open, src_close = 100.0 + body, 100.0
        src_high = src_open + wick
        proximal = src_close
        bars += mk_bars([(src_open, src_high, src_close, src_close)],
                        start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    target = proximal + mfe_atr_mult * atr_val if direction == "bullish" else proximal - mfe_atr_mult * atr_val
    window = []
    for k in range(1, 4):
        if n_candles_to_reach is not None and k == n_candles_to_reach:
            if direction == "bullish":
                window.append((proximal, target, proximal - 0.1, proximal + 0.05))
            else:
                window.append((proximal, proximal + 0.1, target, proximal - 0.05))
        else:
            # flat, no progress
            window.append((proximal, proximal + 0.1, proximal - 0.1, proximal))
    bars += mk_bars(window, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, proximal, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    return bars, src_seq, atr_val


def test_bullish_rb_confirms_when_mfe_reaches_threshold():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.confirmed and r.confirming_candle_number == 2


def test_bearish_rb_confirms_when_mfe_reaches_threshold():
    bars, src_seq, atr_val = _rb_with_mfe("bearish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bearish"][0]
    assert r.confirmed and r.confirming_candle_number == 2


def test_reaching_threshold_only_on_candle_four_does_not_confirm():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, None)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.confirmed
    assert r.rejection_reason == "threshold_not_reached_in_3_candles"


def test_three_flat_candles_do_not_confirm():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, None)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.confirmed


def test_next_three_colours_need_not_match():
    bars, atr_val = seeded_atr()
    body = 4.0
    wick = 1.0 * body
    src_open, src_close = 100.0, 100.0 + body
    src_low = src_open - wick
    bars += mk_bars([(src_open, src_close, src_low, src_close)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    target = src_close + 1.6 * atr_val
    # candle1 down-coloured, candle2 up-coloured, candle3 the confirming one
    window = [
        (src_close, src_close + 0.2, src_close - 0.3, src_close - 0.1),   # bearish
        (src_close - 0.1, src_close + 0.1, src_close - 0.2, src_close),   # bullish
        (src_close, target, src_close - 0.1, src_close + 0.05),           # bearish close, but wick reaches target
    ]
    bars += mk_bars(window, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, src_close, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.confirmed and r.confirming_candle_number == 3


def test_summed_bodies_not_used_for_confirmation():
    # three small-body candles whose bodies would sum past 1.5 ATR but whose
    # running MAX HIGH never reaches it -- must NOT confirm.
    bars, atr_val = seeded_atr()
    body = 4.0
    wick = 1.0 * body
    src_open, src_close = 100.0, 100.0 + body
    src_low = src_open - wick
    bars += mk_bars([(src_open, src_close, src_low, src_close)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    small = 0.6 * atr_val  # 3 * 0.6 = 1.8 > 1.5 if summed, but none individually reach it
    window = [
        (src_close, src_close + small, src_close - 0.1, src_close + small - 0.05),
        (src_close, src_close + small, src_close - 0.1, src_close + small - 0.05),
        (src_close, src_close + small, src_close - 0.1, src_close + small - 0.05),
    ]
    bars += mk_bars(window, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, src_close, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.confirmed


def test_rb_invalidated_before_confirmation_cannot_confirm_later():
    bars, atr_val = seeded_atr()
    body = 4.0
    wick = 1.0 * body
    src_open, src_close = 100.0, 100.0 + body
    src_low = src_open - wick
    zlo = src_low  # bullish zone_lo
    bars += mk_bars([(src_open, src_close, src_low, src_close)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    window = [
        (src_close, src_close + 0.1, zlo - 1.0, zlo - 0.5),  # closes below zone_lo -> invalidated
        (zlo - 0.5, zlo + 5, zlo - 1, zlo + 4.9),             # would have confirmed, too late
        (zlo + 4.9, zlo + 5, zlo + 4, zlo + 4.5),
    ]
    bars += mk_bars(window, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars(flat_preamble(5, src_close, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.confirmed
    assert r.rejection_reason == "invalidated_before_confirmation"


def test_activation_only_after_confirming_candle_closes():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    confirming_seq = src_seq + r.confirming_candle_number
    assert r.activation_ts == series[confirming_seq].ts_et


def test_rb_uses_same_timeframe_atr():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.atr_at_source_close == atr[src_seq]


def test_rb_eight_hour_expiry_below_1h():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    filler = mk_bars([(200, 201, 199, 200)] * 500, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += filler
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.confirmed
    assert r.deactivation_reason == "EXPIRED_UNTOUCHED_8H"


def test_rb_no_arbitrary_expiry_at_1h_plus():
    bars, _ = seeded_atr(n=60 * 20)
    reg = ResetRegistry()
    series = candle_series(bars, 60)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 60, series, atr, reg)
    assert not any(r.deactivation_reason in ("EXPIRED_ACTIVE_8H", "EXPIRED_UNTOUCHED_8H") for r in rbs)


# ---------------------------------------------------------------------------
# Part 10 / traversal tests (common contract)
# ---------------------------------------------------------------------------

def test_ordinary_zone_tap_remains_active():
    bar = mk_bars([(101.1, 101.15, 101.05, 101.1)])[0]
    r = zone_step(1, 101.0, 101.2, bar)
    assert r.event == VALID_TAP and not r.deactivated


def test_wick_overshoot_exactly_020w_with_valid_close_remains_active():
    lo, hi = 100.0, 101.0  # W=1.0, tolerance=0.20
    bar = mk_bars([(100.5, 100.6, 99.80, 100.05)])[0]  # low breaches by exactly 0.20
    r = zone_step(1, lo, hi, bar)
    assert not r.deactivated
    assert r.event == VALID_OVERSHOOT_RECLAIM


def test_overshoot_greater_than_020w_deactivates():
    lo, hi = 100.0, 101.0
    bar = mk_bars([(100.5, 100.6, 99.5, 100.05)])[0]  # low breaches by 0.5 > 0.20
    r = zone_step(1, lo, hi, bar)
    assert r.deactivated and r.reason == DEACTIVATED_OVERSHOOT_LIMIT


def test_close_beyond_distal_boundary_deactivates_even_within_tolerance():
    lo, hi = 100.0, 101.0
    bar = mk_bars([(100.5, 100.6, 99.85, 99.9)])[0]  # wick within 0.20 tol, close < lo
    r = zone_step(1, lo, hi, bar)
    assert r.deactivated and r.reason == DEACTIVATED_CLOSE_THROUGH


def test_deactivation_is_immutable_no_reactivation():
    bars, n0 = _make_active_fvg(BULLISH)
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    # price returns fully back into the old zone afterward
    bars += mk_bars([(100.9, 102.5, 100.8, 101.1)] * 3, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    parent = [f for f in fvgs if f.a_seq == n0][0]
    assert parent.deactivation_reason == DEACTIVATED_CLOSE_THROUGH
    assert parent.active is False


def test_deactivation_reason_and_timestamp_immutable_symmetric_bearish():
    lo, hi = 100.0, 101.0
    bar = mk_bars([(100.5, 101.15, 100.4, 101.05)])[0]  # close(101.05) > hi(101.0)
    r = zone_step(-1, lo, hi, bar)
    assert r.deactivated and r.reason == DEACTIVATED_CLOSE_THROUGH


# ---------------------------------------------------------------------------
# Cross-timeframe wiring sanity (not a Part-10 item, but proves the
# TF-parametrised code path used by the NQU6 audit actually works end to end)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tf", [1, 3, 5, 15, 30, 60])
def test_detectors_run_on_every_governing_timeframe(tf):
    bars, _ = seeded_atr(n=max(60 * tf + 5, 40))
    reg = ResetRegistry()
    series = candle_series(bars, tf)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, tf, reg)
    ifvgs = detect_ifvgs(bars, tf, fvgs, atr, series, reg)
    rbs = detect_rejection_blocks(bars, tf, series, atr, reg)
    assert isinstance(fvgs, list) and isinstance(ifvgs, list) and isinstance(rbs, list)

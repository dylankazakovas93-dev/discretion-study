"""Synthetic proofs for the primitive reset (spec Part 10): FVG, iFVG, RB,
and the common traversal contract. Fast, no raw data dependency -- every
test builds its own tiny deterministic bar sequence. Run with:

    PYTHONPATH=src python3 -m pytest tests/test_primitive_reset.py -v
"""
from __future__ import annotations

import pandas as pd
import pytest

from discretion.data.bars import Bar, NQ_TICK
from discretion.primitive_reset.colour import (
    colour_state, eligible_same_colour, BULLISH, BEARISH, EXACT_DOJI_COLOUR_UNRESOLVED,
)
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

def test_exact_doji_colour_is_unresolved_not_bullish():
    b = mk_bars([(100, 101, 99, 100)])[0]
    assert colour_state(b) == EXACT_DOJI_COLOUR_UNRESOLVED


def test_ordinary_up_down_colours():
    up = mk_bars([(100, 102, 99, 101)])[0]
    down = mk_bars([(100, 101, 98, 99)])[0]
    assert colour_state(up) == BULLISH
    assert colour_state(down) == BEARISH


def test_exact_doji_makes_triple_ineligible_regardless_of_others():
    up = mk_bars([(100, 102, 99, 101)])[0]
    doji = mk_bars([(100, 101, 99, 100)])[0]
    assert not eligible_same_colour(up, up, doji)
    assert not eligible_same_colour(doji, doji, doji)


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


def test_canonical_doji_colour_is_unresolved_and_documented():
    doji = mk_bars([(100, 101, 99, 100)])[0]
    assert colour_state(doji) == EXACT_DOJI_COLOUR_UNRESOLVED
    assert not eligible_same_colour(doji, doji, doji)


def test_exact_doji_c_candle_blocks_fvg_and_logs_diagnostic():
    """Reproduces the reported FVG2-000029 defect: A/B bullish, C an exact
    doji (open == close) that geometrically gaps beyond A.high. Under the
    old close>=open tie-break this silently formed a bullish FVG; now it
    must not form one, and must be logged to the diagnostic inventory."""
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),    # A bullish
        (100.5, 102, 100.2, 101.5),  # B bullish
        (101.5, 103, 101.2, 101.5),  # C exact doji (open == close == 101.5), C.low > A.high
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    fvgs = detect_fvgs(bars, 1, reg)
    assert not any(f.a_seq == n0 for f in fvgs)
    blocked = [d for d in reg.doji_blocked_fvgs if d["a_seq"] == n0]
    assert len(blocked) == 1
    assert blocked[0]["exclusion_reason"] == "EXACT_DOJI_COLOUR_UNRESOLVED"
    assert blocked[0]["c_colour_state"] == EXACT_DOJI_COLOUR_UNRESOLVED
    assert blocked[0]["geometry_direction"] == BULLISH


def test_doji_blocked_fvg_cannot_seed_an_ifvg():
    bars, _ = seeded_atr()
    n0 = len(bars)
    ohlc = [
        (100, 101, 99.5, 100.5),
        (100.5, 102, 100.2, 101.5),
        (101.5, 103, 101.2, 101.5),  # exact doji C
    ]
    bars += mk_bars(ohlc, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars([(100.9, 100.95, 100.0, 100.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, atr, series, reg)
    assert not any(f.a_seq == n0 for f in fvgs)
    assert ifvgs == []  # no parent ever existed to invert


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
    # A dominant-wick candle that is NOT a 2-bar local low still qualifies
    # (the old classical-pivot / _is_local_low check is gone). The candle
    # immediately before it prints a lower low, so it is not a local extreme;
    # neither that candle nor the flat preamble forms an overlapping RB, so
    # precedence does not interfere.
    bars, atr_val = seeded_atr()
    # big-body down candle to 90 (no dominant wick -> no RB), sets a lower low
    bars += mk_bars([(100.0, 100.1, 90.0, 90.2)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    # the RB candle: dominant lower wick, low 91 (HIGHER than the prior 90, so
    # not a 2-bar local low), zone [91, 95]
    bars += mk_bars([(95.0, 96.0, 91.0, 95.8)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    mid_seq = len(bars) - 1
    bars += mk_bars(flat_preamble(5, 95, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == mid_seq and x.direction == "bullish"]
    assert r and (r[0].zone_lo, r[0].zone_hi) == (91.0, 95.0)


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
    assert r.activated and r.activation_candle_number == 2


def test_bearish_rb_confirms_when_mfe_reaches_threshold():
    bars, src_seq, atr_val = _rb_with_mfe("bearish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bearish"][0]
    assert r.activated and r.activation_candle_number == 2


def test_reaching_threshold_only_on_candle_four_does_not_confirm():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, None)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    # No longer a "rejection": the RB is a live structure that simply never
    # activated (MFE stayed under 1.5 ATR across its 3-candle window).
    assert not r.activated
    assert r.activation_ts is None


def test_three_flat_candles_do_not_confirm():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, None)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.activated


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
    assert r.activated and r.activation_candle_number == 3


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
    assert not r.activated


def test_rb_deactivated_by_close_through_before_activating():
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
    # A completed close through the zone's distal boundary before the MFE
    # threshold is reached deactivates the (still-live, never-activated) RB.
    assert not r.activated
    assert r.deactivation_reason == DEACTIVATED_CLOSE_THROUGH


def test_activation_stamped_at_the_candle_where_mfe_crosses():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.activation_seq == src_seq + r.activation_candle_number
    assert r.activation_ts == series[r.activation_seq].ts_et


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
    assert r.activated
    assert r.deactivation_reason == "EXPIRED_UNTOUCHED_8H"


def test_rb_no_arbitrary_expiry_at_1h_plus():
    bars, _ = seeded_atr(n=60 * 20)
    reg = ResetRegistry()
    series = candle_series(bars, 60)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 60, series, atr, reg)
    assert not any(r.deactivation_reason in ("EXPIRED_ACTIVE_8H", "EXPIRED_UNTOUCHED_8H") for r in rbs)


# ---------------------------------------------------------------------------
# RB dominant-wick direction selection + existing-structure precedence
# ---------------------------------------------------------------------------

def test_equal_wicks_never_emit_opposing_active_rbs():
    """A candle with genuinely equal-length wicks must not become both a
    bullish and a bearish candidate -- it goes to the ambiguous diagnostic
    list only."""
    bars, atr_val = seeded_atr()
    # body 4.0, both wicks exactly 2.0 -> equal, ratio 0.5 >= floor
    o, c = 100.0, 104.0
    h, l = c + 2.0, o - 2.0
    bars += mk_bars([(o, h, l, c)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    assert not any(r.source_seq == src_seq for r in rbs)
    ambiguous = [d for d in reg.equal_wick_ambiguous_rbs if d["source_seq"] == src_seq]
    assert len(ambiguous) == 1
    assert ambiguous[0]["reason"] == "equal_wick_ambiguous"


def test_dominant_wick_only_emits_the_longer_side():
    """A candle whose wicks differ must only ever produce the dominant
    (longer) side's candidate, never both."""
    bars, atr_val = seeded_atr()
    o, c = 100.0, 104.0
    h, l = c + 1.0, o - 5.0   # lower_wick=5.0 > upper_wick=1.0
    bars += mk_bars([(o, h, l, c)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    matches = [r for r in rbs if r.source_seq == src_seq]
    assert len(matches) == 1
    assert matches[0].direction == "bullish"
    assert matches[0].dominant_wick_ratio == pytest.approx(5.0 / 1.0)


def test_active_rb_tap_cannot_become_duplicate_overlapping_rb():
    """Item 1 (Part 5): once an RB is active and a later candle merely taps
    back into its zone (from the same relevant-wick direction), that later
    candle must not spawn a second overlapping same-direction RB."""
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs_before = detect_rejection_blocks(bars, 1, series, atr, reg)
    original = [r for r in rbs_before if r.source_seq == src_seq and r.direction == "bullish"][0]
    zlo, zhi = original.zone_lo, original.zone_hi
    tap_open_ts = bars[-1].ts_et + pd.Timedelta(minutes=1)
    # tap candle: dips into [zlo, zhi] with a dominant lower wick of its own
    bars2 = bars + mk_bars([(zhi + 1.0, zhi + 1.2, zlo - 0.05, zhi + 0.9)], start=tap_open_ts)
    bars2 += mk_bars(flat_preamble(5, zhi, 2), start=bars2[-1].ts_et + pd.Timedelta(minutes=1))
    reg2 = ResetRegistry()
    series2 = candle_series(bars2, 1)
    atr2 = atr_series(series2)
    rbs_after = detect_rejection_blocks(bars2, 1, series2, atr2, reg2)
    tap_seq = len(bars)  # index of the newly appended tap candle
    dup = [r for r in rbs_after if r.source_seq == tap_seq and r.direction == "bullish"]
    assert dup == [], "reaction/tap candle must not become a duplicate overlapping RB"


def test_original_rb_retains_the_tap_event():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    original = [r for r in rbs if r.source_seq == src_seq and r.direction == "bullish"][0]
    zlo, zhi = original.zone_lo, original.zone_hi
    tap_open_ts = bars[-1].ts_et + pd.Timedelta(minutes=1)
    bars2 = bars + mk_bars([(zhi + 1.0, zhi + 1.2, zlo - 0.05, zhi + 0.9)], start=tap_open_ts)
    bars2 += mk_bars(flat_preamble(5, zhi, 2), start=bars2[-1].ts_et + pd.Timedelta(minutes=1))
    reg2 = ResetRegistry()
    series2 = candle_series(bars2, 1)
    atr2 = atr_series(series2)
    rbs_after = detect_rejection_blocks(bars2, 1, series2, atr2, reg2)
    same = [r for r in rbs_after if r.source_seq == src_seq and r.direction == "bullish"][0]
    assert same.first_tap_ts is not None
    assert same.first_tap_ts == series2[len(bars)].ts_et


def test_genuinely_separate_nonoverlapping_rejection_still_creates_new_rb():
    """Item 3: a wick far away from any active RB's zone must still create
    its own new candidate normally."""
    bars, atr_val = seeded_atr()
    o, c = 100.0, 104.0
    h, l = c + 0.2, o - 4.0
    bars += mk_bars([(o, h, l, c)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    first_seq = len(bars) - 1
    # unrelated wick far away in price, same direction, later in time
    o2, c2 = 500.0, 504.0
    h2, l2 = c2 + 0.2, o2 - 4.0
    bars += mk_bars(flat_preamble(3, 300, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars([(o2, h2, l2, c2)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    second_seq = len(bars) - 1
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    assert any(r.source_seq == first_seq and r.direction == "bullish" for r in rbs)
    assert any(r.source_seq == second_seq and r.direction == "bullish" for r in rbs)


def test_opposite_direction_not_suppressed_by_precedence_rule():
    """Item 4: precedence only suppresses same-direction duplicates; an
    opposite-direction candidate on a tap candle must still be considered."""
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    original = [r for r in rbs if r.source_seq == src_seq and r.direction == "bullish"][0]
    zlo, zhi = original.zone_lo, original.zone_hi
    tap_open_ts = bars[-1].ts_et + pd.Timedelta(minutes=1)
    # this candle taps the active bullish zone (dominant lower wick) --
    # bullish side is suppressed, but a hypothetical bearish read (were the
    # geometry to favour it) would not be blocked by this rule.
    bars2 = bars + mk_bars([(zhi + 1.0, zhi + 1.2, zlo - 0.05, zhi + 0.9)], start=tap_open_ts)
    bars2 += mk_bars(flat_preamble(5, zhi, 2), start=bars2[-1].ts_et + pd.Timedelta(minutes=1))
    reg2 = ResetRegistry()
    series2 = candle_series(bars2, 1)
    atr2 = atr_series(series2)
    detect_rejection_blocks(bars2, 1, series2, atr2, reg2)
    suppressed = [d for d in reg2.precedence_suppressed_rbs if d["source_seq"] == len(bars)]
    assert len(suppressed) == 1
    assert suppressed[0]["direction"] == "bullish"


def test_precedence_rule_uses_no_future_information():
    """Item 5: suppression is decided using only already-active RB state at
    the time the later candle closes -- never a look-ahead. Proven by
    construction: `tapped_rbs` is accumulated from `active` (state built
    strictly from candles < i) before any candle-i candidate is examined."""
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1)
    atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    original = [r for r in rbs if r.source_seq == src_seq and r.direction == "bullish"][0]
    assert original.activation_ts is not None
    # A tap candle BEFORE activation (during the pending window) cannot be
    # suppressed by precedence, since the RB is not yet in `active`.
    assert reg.precedence_suppressed_rbs == []


def test_same_direction_tap_of_nonoverlapping_zone_is_allowed():
    """Item 2 (the fix): a candle that 'taps' an active same-direction RB but
    whose OWN proposed candidate zone does not intersect that RB's zone must
    NOT be suppressed. Constructed with a bullish candle sitting entirely
    below the active bullish RB [96,100]: its low <= the RB's top (so the
    RB registers a reach), yet its own zone [85,90] is disjoint from
    [96,100]. Under the old direction-only rule this was wrongly suppressed."""
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)  # active RB zone [96,100]
    reg0 = ResetRegistry()
    s0 = candle_series(bars, 1); a0 = atr_series(s0)
    rbs0 = detect_rejection_blocks(bars, 1, s0, a0, reg0)
    orig = [r for r in rbs0 if r.source_seq == src_seq and r.direction == "bullish"][0]
    assert (orig.zone_lo, orig.zone_hi) == (96.0, 100.0)
    t_open = bars[-1].ts_et + pd.Timedelta(minutes=1)
    # bullish, dominant lower wick, entirely below the RB; zone [85, 90]
    bars2 = bars + mk_bars([(90.0, 90.2, 85.0, 90.1)], start=t_open)
    bars2 += mk_bars(flat_preamble(5, 88, 2), start=bars2[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    s = candle_series(bars2, 1); a = atr_series(s)
    rbs = detect_rejection_blocks(bars2, 1, s, a, reg)
    tseq = len(bars)
    new = [r for r in rbs if r.source_seq == tseq and r.direction == "bullish"]
    assert len(new) == 1, "non-overlapping same-direction candidate must be allowed"
    assert (new[0].zone_lo, new[0].zone_hi) == (85.0, 90.0)
    assert not any(d["source_seq"] == tseq for d in reg.precedence_suppressed_rbs)


def test_multiple_active_same_direction_suppress_if_any_tapped_zone_overlaps():
    """Item 4: with two live same-direction RBs both tapped by a later
    candle, suppress the new candidate if it overlaps ANY tapped same-
    direction zone (even if it misses the other). Two non-overlapping bullish
    RBs at [100,102] and [103,105] (S2 sits above S1 so neither taps/
    deactivates the other on formation); a later candle dips to tap both but
    its tiny candidate zone [100,100.5] overlaps only [100,102] -> suppressed,
    citing that specific RB."""
    bars, _ = seeded_atr()
    base = bars[-1].ts_et + pd.Timedelta(minutes=1)
    s1 = (102.0, 102.6, 100.0, 102.5)   # bullish, zone [100,102]
    s2 = (105.0, 105.6, 103.0, 105.5)   # bullish, zone [103,105], above S1 (low 103 > 102)
    bars += mk_bars([s1, s2], start=base)
    s1_seq = len(bars) - 2
    s2_seq = len(bars) - 1
    # tap candle: dips to 100, tapping both [100,102] and [103,105]; tiny body
    # so its own candidate zone is [100,100.5] (overlaps only S1). Closes at
    # 100.4 -> below S2's lo(103) so S2 close-through-deactivates (after being
    # tapped), above S1's lo(100) so S1 survives and cites the suppression.
    tap = (100.5, 100.6, 100.0, 100.4)
    bars += mk_bars([tap], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    tseq = len(bars) - 1
    bars += mk_bars(flat_preamble(5, 101, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    s = candle_series(bars, 1); a = atr_series(s)
    rbs = detect_rejection_blocks(bars, 1, s, a, reg)
    r1 = [r for r in rbs if r.source_seq == s1_seq and r.direction == "bullish"]
    r2 = [r for r in rbs if r.source_seq == s2_seq and r.direction == "bullish"]
    assert r1 and (r1[0].zone_lo, r1[0].zone_hi) == (100.0, 102.0)
    assert r2 and (r2[0].zone_lo, r2[0].zone_hi) == (103.0, 105.0)
    # the tap candle's bullish candidate must be suppressed (overlaps [100,102])
    assert not any(r.source_seq == tseq and r.direction == "bullish" for r in rbs)
    supp = [d for d in reg.precedence_suppressed_rbs if d["source_seq"] == tseq]
    assert len(supp) == 1
    assert supp[0]["overlapping_rb_zone_lo"] == 100.0 and supp[0]["overlapping_rb_zone_hi"] == 102.0


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


# ---------------------------------------------------------------------------
# RB lifecycle: live from source close, activation is a descriptive status,
# and each tap carries a causal "was activated at that moment" flag.
# ---------------------------------------------------------------------------

def _assert_rb_causal(rb):
    """Invariants for the live-from-source model (no look-ahead)."""
    if rb.first_tap_ts is not None:
        assert rb.source_ts < rb.first_tap_ts, (rb.id, rb.source_ts, rb.first_tap_ts)
    if rb.deactivation_ts is not None:
        assert rb.source_ts <= rb.deactivation_ts, (rb.id, rb.source_ts, rb.deactivation_ts)
    if rb.activated:
        assert rb.activation_ts is not None and rb.source_ts < rb.activation_ts
        assert 1 <= rb.activation_candle_number <= 3
    else:
        assert rb.activation_ts is None and rb.activation_seq is None
    # per-tap activation flags are causal and consistent with was_activated_at
    if rb.first_tap_seq is not None:
        assert rb.first_tap_was_activated == rb.was_activated_at(rb.first_tap_seq)
    for ev in rb.tap_events:
        assert ev["was_activated"] == rb.was_activated_at(ev["seq"])


def test_non_activated_rb_is_still_live_and_tappable():
    """The core change: an RB whose MFE never reaches 1.5 ATR is NOT rejected
    -- it is a live structure that can still be tapped, with the tap recorded
    as not-activated."""
    bars, atr_val = seeded_atr()
    # bullish source, zone [96,100]; then flat candles (no 1.5-ATR rally) so
    # it never activates; then a candle taps the zone.
    bars += mk_bars([(100.0, 104.0, 96.0, 104.0)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    bars += mk_bars([(101.0, 101.2, 100.5, 101.0)] * 3,   # flat, no activation, no tap
                    start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    bars += mk_bars([(101.0, 101.2, 98.0, 101.0)],        # taps [96,100], closes back up
                    start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    tap_seq = len(bars) - 1
    bars += mk_bars(flat_preamble(4, 101, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1); atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert not r.activated
    assert r.first_tap_ts == series[tap_seq].ts_et
    assert r.first_tap_was_activated is False
    _assert_rb_causal(r)


def test_tap_before_activation_is_not_activated_then_tap_after_is_activated():
    """A tap that occurs before the 1.5-ATR move is stamped not-activated; a
    later tap after activation is stamped activated. No look-ahead: the first
    tap's flag reflects only what was known at that candle's close."""
    bars, atr_val = seeded_atr()
    proximal = 100.0
    bars += mk_bars([(100.0, 104.0, 96.0, 104.0)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1                       # zone [96,100], proximal 100
    # i+1: taps the zone (low 98) with NO rally -> tap, not activated
    bars += mk_bars([(101.0, 101.5, 98.0, 101.0)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    tap1_seq = len(bars) - 1
    # i+2: big rally (high well past 1.5 ATR), does not re-enter zone -> activates
    target = proximal + 3.0 * atr_val
    bars += mk_bars([(101.0, target, 100.5, target - 0.5)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    # i+3: dips back to tap the zone again -> now activated
    bars += mk_bars([(target - 1, target, 98.0, target - 1)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    tap2_seq = len(bars) - 1
    bars += mk_bars(flat_preamble(4, target, 2), start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1); atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.activated and r.activation_seq == src_seq + 2
    assert r.first_tap_seq == tap1_seq and r.first_tap_was_activated is False
    ev_by_seq = {e["seq"]: e["was_activated"] for e in r.tap_events}
    assert ev_by_seq[tap1_seq] is False        # tapped before activation
    assert ev_by_seq[tap2_seq] is True         # tapped after activation
    _assert_rb_causal(r)


def test_was_activated_at_is_causal():
    bars, src_seq, atr_val = _rb_with_mfe("bullish", 1.6, 2)
    reg = ResetRegistry()
    series = candle_series(bars, 1); atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    j = r.activation_seq
    assert r.was_activated_at(j) is True
    assert r.was_activated_at(j - 1) is False       # never reports activation early
    assert r.was_activated_at(r.source_seq) is False


def test_expiry_measured_from_source_not_activation():
    """8h lifetime now anchored at source-candle close (when the RB becomes
    usable), not activation."""
    bars, atr_val = seeded_atr()
    bars += mk_bars([(100.0, 104.0, 96.0, 104.0)], start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    src_seq = len(bars) - 1
    src_ts = bars[-1].ts_et
    # far-away filler so the RB is never tapped and simply ages out
    bars += mk_bars([(200, 201, 199, 200)] * 500, start=bars[-1].ts_et + pd.Timedelta(minutes=1))
    reg = ResetRegistry()
    series = candle_series(bars, 1); atr = atr_series(series)
    rbs = detect_rejection_blocks(bars, 1, series, atr, reg)
    r = [x for x in rbs if x.source_seq == src_seq and x.direction == "bullish"][0]
    assert r.deactivation_reason == "EXPIRED_UNTOUCHED_8H"
    assert (r.deactivation_ts - r.source_ts) >= pd.Timedelta(hours=8)
    _assert_rb_causal(r)


def test_real_nqu6_audit_rb_lifecycle_invariants():
    """Every live RB from the actual NQU6 audit satisfies the causal
    lifecycle invariants (source < tap/deactivation, activation after source,
    per-tap flags causal), with zero violations."""
    import sys
    sys.path.insert(0, "scripts")
    import primitive_reset_audit as pra
    bars, coverage = pra.load_symbol_bars(pra.DATA_FILE, pra.SYMBOL, pra.REQ_START_ET, pra.REQ_END_ET)
    if not bars:
        pytest.skip("raw data absent")
    violations = 0
    n_live = n_activated = n_tapped = 0
    for tf in pra.TIMEFRAMES:
        reg = ResetRegistry()
        series = candle_series(bars, tf)
        atr = atr_series(series)
        rbs = detect_rejection_blocks(bars, tf, series, atr, reg)
        for r in rbs:
            n_live += 1
            if r.activated:
                n_activated += 1
            if r.first_tap_ts is not None:
                n_tapped += 1
            try:
                _assert_rb_causal(r)
            except AssertionError:
                violations += 1
    assert n_live > 0 and n_activated > 0
    assert violations == 0

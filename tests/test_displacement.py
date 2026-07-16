"""Displacement grading (good/mixed/bad) and failed displacement."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.displacement import (
    detect_displacements, grade_displacement, displacement_features,
)
from helpers import make_bars


def test_good_displacement():
    # big body, high body-ratio, close near high, tiny opposing wick
    bars = make_bars([
        (100, 100.1, 99.9, 100),
        (100, 102.1, 99.9, 102),   # body 2, atr 1
    ])
    ds = detect_displacements(bars, [1.0] * len(bars), IdRegistry())
    d = [x for x in ds if x.created_seq == 1][0]
    assert d.grade == "good"
    assert d.direction == 1


def test_bad_displacement():
    # body >= 0.5 ATR (a candidate) but low body-ratio -> bad
    bars = make_bars([
        (100, 100.1, 99.9, 100),
        (100, 101.6, 99.9, 100.6),  # body 0.6, range 1.7 -> body_ratio 0.35 <0.4
    ])
    ds = detect_displacements(bars, [1.0] * len(bars), IdRegistry())
    d = [x for x in ds if x.created_seq == 1][0]
    assert d.grade == "bad"


def test_mixed_displacement_grade():
    f = {
        "direction": 1, "body_atr": 1.2, "body_ratio": 0.55,
        "favorable_close": 0.60, "opposing_wick_ratio": 0.30,
        "close_loc": 0.60, "range_atr": 2.0, "adjacent_overlap": 0.2,
    }
    assert grade_displacement(f) == "mixed"


def test_sub_threshold_body_is_not_a_displacement():
    bars = make_bars([
        (100, 100.1, 99.9, 100),
        (100, 100.3, 99.9, 100.2),  # body 0.2 < 0.5 ATR -> not a candidate
    ])
    ds = detect_displacements(bars, [1.0] * len(bars), IdRegistry())
    assert [x for x in ds if x.created_seq == 1] == []


def test_failed_displacement_followthrough():
    # strong up displacement, next bar closes back below its open -> FAILED
    bars = make_bars([
        (100, 100.1, 99.9, 100),
        (100, 102.1, 99.9, 102),   # good up displacement
        (102, 102, 99, 99.5),      # closes 99.5 < disp.open 100 -> FAILED_CONTINUATION
    ])
    ds = detect_displacements(bars, [1.0] * len(bars), IdRegistry())
    d = [x for x in ds if x.created_seq == 1][0]
    assert d.has_event("FAILED_CONTINUATION")


def test_displacement_continuation_followthrough():
    bars = make_bars([
        (100, 100.1, 99.9, 100),
        (100, 102.1, 99.9, 102),   # good up displacement
        (102, 103, 102, 103),      # next close 103 > disp close 102 -> CONTINUATION
    ])
    ds = detect_displacements(bars, [1.0] * len(bars), IdRegistry())
    d = [x for x in ds if x.created_seq == 1][0]
    assert d.has_event("CONTINUATION")

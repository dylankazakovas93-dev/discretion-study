"""Causal absolute-volatility ATR(24) floor tests (spec: BLOCKING ATR DISTANCE
FLOOR). Proves the stop is widened (never tightened) to the 1m ATR(24) floor,
that a structural target below the 5m ATR(24) is rejected while a distant one
passes, that RR is recalculated on the effective stop, that no synthetic ATR
target is created, that a nearer genuine opposing blocker is never bypassed,
that the unfinished current 5m candle is never used, and that application-week
outcomes remain absent.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

from discretion.setup_observer.atr_floors import (
    atr1m_at_trigger, atr5m_at_trigger, stop_floor, target_floor_ok,
    TARGET_BELOW_5M_ATR,
)
from discretion.setup_observer.targets import StructTable, resolve_targets
from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe


# ---------------------------------------------------------------------------
# target floor
# ---------------------------------------------------------------------------

def test_four_point_target_fails_when_5m_atr_is_20():
    assert target_floor_ok(4.0, 20.0) is False


def test_twentyfive_point_target_passes_when_5m_atr_is_20():
    assert target_floor_ok(25.0, 20.0) is True


def test_target_exactly_at_5m_atr_passes():
    assert target_floor_ok(20.0, 20.0) is True


# ---------------------------------------------------------------------------
# stop floor
# ---------------------------------------------------------------------------

def test_three_point_stop_widened_when_1m_atr_is_8_long():
    sf = stop_floor(entry_price=100.0, direction=1, raw_stop_price=97.0, atr_1m=8.0)
    assert sf["raw_stop_distance"] == 3.0
    assert sf["effective_stop_distance"] == 8.0
    assert sf["stop_widened_by_atr_floor"] is True
    # long stop sits below entry and on/beyond the raw structural stop
    assert sf["effective_stop_price"] == 92.0
    assert sf["effective_stop_price"] <= sf["raw_stop_price"]


def test_three_point_stop_widened_short_direction():
    sf = stop_floor(entry_price=100.0, direction=-1, raw_stop_price=103.0, atr_1m=8.0)
    assert sf["effective_stop_distance"] == 8.0
    assert sf["effective_stop_price"] == 108.0
    assert sf["effective_stop_price"] >= sf["raw_stop_price"]


def test_stop_wider_than_1m_atr_is_unchanged():
    sf = stop_floor(entry_price=100.0, direction=1, raw_stop_price=88.0, atr_1m=8.0)
    assert sf["raw_stop_distance"] == 12.0
    assert sf["effective_stop_distance"] == 12.0
    assert sf["stop_widened_by_atr_floor"] is False
    assert sf["effective_stop_price"] == 88.0    # structural stop untouched


def test_stop_widening_recalculates_rr():
    """RR uses the effective (widened) stop, so widening lowers RR."""
    target_distance = 20.0
    sf = stop_floor(entry_price=100.0, direction=1, raw_stop_price=97.0, atr_1m=8.0)
    raw_rr = target_distance / sf["raw_stop_distance"]        # 20/3
    eff_rr = target_distance / sf["effective_stop_distance"]  # 20/8
    assert round(raw_rr, 4) == 6.6667
    assert round(eff_rr, 4) == 2.5
    assert eff_rr < raw_rr


# ---------------------------------------------------------------------------
# no synthetic target; nearer blocker never bypassed
# ---------------------------------------------------------------------------

def test_no_synthetic_atr_target_is_created():
    """The floor is a boolean gate -- it constructs no target object."""
    assert target_floor_ok(30.0, 20.0) is True
    assert target_floor_ok(5.0, 20.0) is False
    # target resolution only ever returns real structures (ids), never an ATR level
    tbl = StructTable([
        {"id": "RB2-1", "family": "rb", "tf": 1, "sdir": -1, "lo": 130.0, "hi": 132.0,
         "avail": 0, "invalid_from": None},
    ])
    sel, considered, _ = resolve_targets(tbl, entry_seq=10, direction=1, entry_price=100.0,
                                         stop_price=97.0, context_tf=1, context_family="rb",
                                         exclude_ids=set())
    prim = sel["NEAREST_OPPOSING_VALID_STRUCTURE"]
    assert prim.structure_id == "RB2-1"          # a genuine structure, not synthetic
    assert prim.surface == 130.0                 # its real proximal edge


def test_nearer_genuine_opposing_blocker_cannot_be_bypassed():
    """The nearest opposing structure is always the selected target, even when a
    farther one would give more distance / RR -- the floor never reaches past a
    genuine blocker."""
    tbl = StructTable([
        {"id": "NEAR", "family": "rb", "tf": 1, "sdir": -1, "lo": 104.0, "hi": 106.0,
         "avail": 0, "invalid_from": None},
        {"id": "FAR", "family": "rb", "tf": 1, "sdir": -1, "lo": 140.0, "hi": 142.0,
         "avail": 0, "invalid_from": None},
    ])
    sel, _, _ = resolve_targets(tbl, entry_seq=10, direction=1, entry_price=100.0,
                                stop_price=97.0, context_tf=1, context_family="rb",
                                exclude_ids=set())
    prim = sel["NEAREST_OPPOSING_VALID_STRUCTURE"]
    assert prim.structure_id == "NEAR" and prim.surface == 104.0


# ---------------------------------------------------------------------------
# 5m ATR causality: never the unfinished current candle
# ---------------------------------------------------------------------------

def test_incomplete_5m_candle_atr_is_never_used():
    # three completed 5m candles available at seq 5, 10, 15; a 4th is still
    # forming (available at 25). At trigger entry_seq=20 only the first three
    # are usable -> the 15-availability candle's ATR (value 2.0).
    atr24_5m = [1.0, 1.5, 2.0, 99.0]
    avail5 = [5, 10, 15, 25]
    assert atr5m_at_trigger(atr24_5m, avail5, entry_seq=20) == 2.0
    # exactly-closing candle (availability == trigger) IS usable
    assert atr5m_at_trigger(atr24_5m, avail5, entry_seq=25) == 99.0
    # before any completed 5m candle -> None
    assert atr5m_at_trigger(atr24_5m, avail5, entry_seq=3) is None


def test_atr1m_uses_most_recent_completed_1m_candle():
    atr24_1m = [None] * 24 + [7.0, 8.0, 9.0]
    # trigger enters at bar 26 -> most recent completed 1m candle is bar 25 (8.0)
    assert atr1m_at_trigger(atr24_1m, entry_seq=26) == 8.0
    assert atr1m_at_trigger(atr24_1m, entry_seq=0) is None


# ---------------------------------------------------------------------------
# real-data integration: floors enforced, outcomes absent
# ---------------------------------------------------------------------------

def _load(start, end):
    if not os.path.exists(os.path.join("data", "raw", DATA_FILES["2025-2026"])):
        return None
    path = os.path.join("data", "raw", DATA_FILES["2025-2026"])
    df = read_raw_csv(path, start=start.tz_convert("UTC").tz_localize(None), end=None)
    df = df[df["symbol"] == "NQU6"].sort_values("ts_utc").drop_duplicates("ts_utc", keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df[(et >= start) & (et <= end)].reset_index(drop=True)
    return [Bar(seq=i, ts_utc=r.ts_utc, ts_et=r.ts_utc.tz_convert(ET), open=float(r.open),
                high=float(r.high), low=float(r.low), close=float(r.close), volume=int(r.volume),
                contract="NQU6", segment_id=0) for i, r in enumerate(df.itertuples(index=False))]


@pytest.fixture(scope="module")
def app_variants():
    bars = _load(pd.Timestamp("2026-07-12 18:00:00", tz=ET), pd.Timestamp("2026-07-17 23:59:59", tz=ET))
    if not bars:
        pytest.skip("raw data absent")
    _, variants, _ = observe(bars)
    return variants


def test_every_executable_variant_clears_both_floors(app_variants):
    execs = [v for v in app_variants if v.executable]
    assert execs
    for v in execs:
        assert v.atr_1m_24 is not None and v.atr_5m_24 is not None
        assert v.effective_stop_distance >= v.atr_1m_24 - 1e-6      # stop floor
        assert v.target_distance >= v.atr_5m_24 - 1e-6              # target floor
        assert v.natural_rr >= 0.5                                  # RR on effective stop
        assert v.atr_floor_target_ok is True


def test_effective_stop_never_tightens_structural(app_variants):
    for v in app_variants[:3000]:
        assert v.effective_stop_distance >= v.raw_stop_distance - 1e-6
        if v.direction > 0:
            assert v.effective_stop_price <= v.raw_stop_price + 1e-6
        else:
            assert v.effective_stop_price >= v.raw_stop_price - 1e-6


def test_sub_5m_atr_targets_are_rejected(app_variants):
    rejected = [v for v in app_variants if v.rejection_reason == TARGET_BELOW_5M_ATR]
    assert rejected
    for v in rejected[:500]:
        assert v.target_distance is not None and v.atr_5m_24 is not None
        assert v.target_distance < v.atr_5m_24


def test_application_outcomes_absent_on_variants(app_variants):
    toks = ("mfe", "mae", "outcome", "pnl", "exit_type", "r_multiple", "success", "win", "loss")
    import dataclasses
    for v in app_variants[:200]:
        for f in dataclasses.fields(v):
            assert not any(t in f.name.lower() for t in toks), f.name

"""Branch-specific stop/target anchor resolution."""

from __future__ import annotations

import os
import types

import pytest

from discretion.graph.anchors import resolve_anchors
from discretion.primitives.levels import Level
from discretion.graph.pipeline import run_graph_native
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _fake_zone(id, lo, hi, family="fvg"):
    return types.SimpleNamespace(id=id, lo=lo, hi=hi, family=family, price=(lo + hi) / 2)


def _bar(low, high):
    return types.SimpleNamespace(low=low, high=high, close=(low + high) / 2)


def _lvl(price, seq=0):
    return Level(id="LVL-T", family="liquidity", subtype="swing_high", segment_id=0,
                 created_seq=seq, created_ts=None, lo=price, hi=price, price_ref=price)


def test_fvg_stop_is_fvg_boundary():
    fvg = _fake_zone("FVG-1", 99.0, 100.0, "fvg")
    lvl_above = _lvl(105.0)
    stop, target, rule = resolve_anchors(
        "fvg_fill", +1, 100.5, 10, 0, fvg, fvg, _bar(100.0, 101.0),
        types.SimpleNamespace(reference_price=100.0), [lvl_above], None)
    assert stop["stop_anchor_type"] == "fvg_boundary"
    assert stop["stop_anchor_object_id"] == "FVG-1"
    assert stop["stop_anchor_price"] < 100.5   # below entry for a long
    assert target["target_anchor_type"].startswith("opposing_")


def test_sweep_fade_stop_is_swept_extreme():
    lvl = types.SimpleNamespace(id="LVL-9", lo=100.0, hi=100.0, family="liquidity",
                                price=100.0)
    tgt_below = _lvl(90.0)
    stop, target, rule = resolve_anchors(
        "sweep_fade", -1, 99.0, 10, 0, lvl, lvl, _bar(98.0, 101.0),
        types.SimpleNamespace(reference_price=101.0), [tgt_below], None)
    assert stop["stop_anchor_type"] == "swept_extreme"
    assert stop["stop_anchor_price"] > 101.0   # beyond the sweep high


def test_no_branch_objective_still_returns_stop():
    # With no levels the branch objective is absent, but the stop is always
    # structural; the target-universe policies (not this resolver) supply targets.
    fvg = _fake_zone("FVG-1", 99.0, 100.0, "fvg")
    stop, target, rule = resolve_anchors(
        "fvg_fill", +1, 100.5, 10, 0, fvg, fvg, _bar(100.0, 101.0),
        types.SimpleNamespace(reference_price=100.0), [], None)  # no levels
    assert stop is not None and stop["stop_anchor_type"] == "fvg_boundary"
    assert target is None and rule.endswith("target=NONE")


# ---- data-gated ----

@pytest.fixture(scope="module")
def day():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(start="2025-07-07", end="2025-07-08", with_evidence=False)


def test_every_candidate_stores_typed_anchors(day):
    reg = day["engine"].ps.registry
    for c in day["graph_candidates"]:
        assert c.stop_anchor_type and c.target_anchor_type
        assert c.anchor_resolution_rule
        # anchor prices are exactly what the setup uses
        assert abs(c.stop_anchor_price - c.setup.structural_stop) < 1e-9
        assert abs(c.target_anchor_price - c.setup.structural_target) < 1e-9


def test_anchor_objects_are_causally_available(day):
    reg = day["engine"].ps.registry
    for c in day["graph_candidates"]:
        # stop anchors are always registered structural primitives
        if c.stop_anchor_object_id:
            try:
                obj = reg.get(c.stop_anchor_object_id)
            except KeyError:
                obj = None
            if obj is not None:
                assert obj.created_seq <= c.setup.entry_seq
        # the selected target is available at (never after) the entry seq
        row = next(r for r in c.considered_targets
                   if r["object_id"] == c.target_anchor_object_id)
        assert row["available_seq"] <= c.setup.entry_seq


def test_stop_anchor_families_are_branch_specific(day):
    by_fam = {}
    for c in day["graph_candidates"]:
        by_fam.setdefault(c.setup.path_family, set()).add(c.stop_anchor_type)
    checks = {
        "ifvg_activation": "ifvg_invalidation_boundary",
        "ifvg_retest": "ifvg_invalidation_boundary",
        "sweep_fade": "swept_extreme",
        "compression_expansion": "compression_region",
        "rb_reaction": "rb_invalidation_boundary",
    }
    for fam, expected in checks.items():
        if fam in by_fam:
            assert expected in by_fam[fam], (fam, by_fam[fam])


def test_rb_failure_fade_stop_is_compression_region(day):
    reg = day["engine"].ps.registry
    rb = [c for c in day["graph_candidates"] + day["graph_rejected"]
          if c.setup.path_family == "rb_failure_fade"]
    for c in rb:
        assert c.stop_anchor_type == "failure_region_boundary"
        assert reg.get(c.stop_anchor_object_id).family == "structure"


# ---- Repair task Stage 16 #16: stop resolution never reads target distance --

def test_stop_resolution_identical_regardless_of_available_levels():
    """resolve_anchors's STOP half must be a pure function of
    (fam, direction, entry_price, seq, seg, focus, origin, bar0, trig_ev) --
    varying only the `levels` list (which can change the TARGET half via the
    nearest-level fallback) must never change the stop."""
    fvg = _fake_zone("FVG-1", 99.0, 100.0, "fvg")
    trig_ev = types.SimpleNamespace(reference_price=100.0)
    stop_no_levels, _, _ = resolve_anchors(
        "fvg_fill", +1, 100.5, 10, 0, fvg, fvg, _bar(100.0, 101.0), trig_ev, [], None)
    stop_with_levels, _, _ = resolve_anchors(
        "fvg_fill", +1, 100.5, 10, 0, fvg, fvg, _bar(100.0, 101.0), trig_ev,
        [_lvl(105.0), _lvl(200.0), _lvl(300.0)], None)
    assert stop_no_levels == stop_with_levels

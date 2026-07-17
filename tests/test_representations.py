"""Deterministic setup representations: reduced graph + numeric features."""

from __future__ import annotations

import os

import pytest

from discretion.representations.signatures import reduce_graph, enrich_candidates
from discretion.primitives.engine import build_primitives
from discretion.episodes.branches import build_branches_and_candidates
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def test_reduce_graph_maps_and_collapses():
    exact = ("BULLISH_FVG_FORMED -> BULLISH_FVG_FIRST_TOUCH -> "
             "BULLISH_FVG_MIDPOINT -> NEXT_BAR_LONG_TRIGGER")
    # two consecutive GAP_FILL nodes collapse to one
    assert reduce_graph(exact) == "GAP_FORMATION -> GAP_FILL -> ENTRY_TRIGGER"


def test_reduce_graph_inversion_path():
    exact = ("BULLISH_FVG_FAILURE -> BEARISH_IFVG_ACTIVATION -> "
             "FORMATION_CLOSE_SHORT_TRIGGER")
    assert reduce_graph(exact) == "GAP_FAILURE -> INVERSION_ACTIVATION -> ENTRY_TRIGGER"


def test_reduce_graph_liquidity_sweep():
    exact = "SWING_HIGH_SWEEP_ABOVE -> FORMATION_CLOSE_SHORT_TRIGGER"
    assert reduce_graph(exact) == "LIQUIDITY_SWEEP -> ENTRY_TRIGGER"


def test_reduce_graph_is_deterministic():
    exact = "GOOD_BEARISH_DISPLACEMENT -> SWING_LOW_BREAK -> MIDPOINT_SHORT_TRIGGER"
    assert reduce_graph(exact) == reduce_graph(exact)
    assert reduce_graph(exact) == "STRONG_DISPLACEMENT -> LEVEL_BREAK -> ENTRY_TRIGGER"


@pytest.fixture(scope="module")
def enriched():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, start="2025-07-07T13:00", end="2025-07-07T18:00")
    ps = build_primitives(bars)
    R = build_branches_and_candidates(ps)
    enrich_candidates(R)
    return R


def test_features_are_causal_and_complete(enriched):
    for c in enriched["candidates"]:
        f = c.features
        assert f["direction"] in (-1, 1)
        assert f["source_timeframe"] == "1m"
        # dist_to_stop is a non-negative magnitude (direction-agnostic)
        if f["dist_to_stop_atr"] is not None:
            assert f["dist_to_stop_atr"] >= 0
        assert f["natural_rr"] >= 0.5  # coherent candidates only
        # htf feature explicitly marked as 1m-only, never a future value
        assert f["htf_alignment"] == "unknown_1m_only"


def test_vwap_side_is_direction_normalized(enriched):
    for c in enriched["candidates"]:
        vs = c.features["vwap_side"]
        assert vs in (None, -1, 1)


def test_reduced_graph_attached_to_every_candidate(enriched):
    for c in enriched["candidates"]:
        assert c.reduced_graph
        assert "ENTRY_TRIGGER" in c.reduced_graph or c.episode_id.startswith("EP-SYNTH")

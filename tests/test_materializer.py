"""Graph-native candidate materializer invariants."""

from __future__ import annotations

import os

import pytest

from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.graph.materializer import materialize_all, resolve_direction
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
WIN = dict(start="2025-07-07T13:00", end="2025-07-07T20:00")


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, **WIN)
    ps = build_primitives(bars)
    R = BranchEngine(ps).run()
    return materialize_all(R)


def test_candidate_ids_are_graph_native(result):
    for c in result["graph_candidates"] + result["graph_rejected"]:
        assert c.candidate_id.startswith("GNC-")


def test_every_candidate_has_valid_provenance(result):
    branch_ids = {b.branch_id for b in result["branches"]}
    episode_ids = {e.episode_id for e in result["episodes"]}
    log = result["log"]
    for c in result["graph_candidates"]:
        assert c.source_branch_id in branch_ids
        assert c.source_episode_id in episode_ids
        assert log.get(c.trigger_event_id) is not None
        assert len(c.ordered_transition_ids) >= 1
        assert c.relationship_evidence  # at least one structural relationship


def test_candidate_stored_before_outcome(result):
    # the materializer must not evaluate outcome
    for c in result["graph_candidates"]:
        assert c.setup.outcome == "UNEVALUATED"


def test_rr_policy(result):
    for c in result["graph_candidates"]:
        assert 0.5 <= c.setup.executed_rr <= 1.0
    assert any(abs(c.setup.executed_rr - 1.0) < 1e-9 for c in result["graph_candidates"])
    assert any(0.5 <= c.setup.executed_rr < 1.0 for c in result["graph_candidates"])
    assert any(c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR"
               for c in result["graph_rejected"])
    for c in result["graph_rejected"]:
        assert c.setup.rejection_reason in (
            "INSUFFICIENT_NATURAL_RR", "TARGET_WRONG_SIDE", "DEGENERATE_STOP")
        assert c.setup.executed_target == 0.0   # never given an executable target


def test_structural_stop_and_target_on_correct_side(result):
    for c in result["graph_candidates"]:
        s = c.setup
        if s.direction == "long":
            assert s.structural_stop < s.entry_price < s.structural_target
        else:
            assert s.structural_target < s.entry_price < s.structural_stop


def test_graph_native_generation_works_with_build_setups_disabled(monkeypatch):
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")

    def boom(*a, **k):
        raise RuntimeError("build_setups is disabled for graph-native generation")

    import discretion.setups.constructor as constructor
    monkeypatch.setattr(constructor, "build_setups", boom)

    bars = load_front_month(DATA, **WIN)
    ps = build_primitives(bars)
    R = materialize_all(BranchEngine(ps).run())
    assert len(R["graph_candidates"]) > 0  # graph-native pipeline is independent


def test_direction_resolution_never_zero(result):
    for c in result["graph_candidates"]:
        assert c.direction in ("long", "short")

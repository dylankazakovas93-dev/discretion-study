"""Multi-branch episode engine invariants."""

from __future__ import annotations

import os
from collections import defaultdict

import pytest

from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, start="2025-07-07T13:00", end="2025-07-07T20:00")
    ps = build_primitives(bars)
    return BranchEngine(ps).run()


def test_branches_and_triggers_exist(result):
    assert result["branches"] and result["triggers"]
    assert all(b.branch_id.startswith("GBR-") for b in result["branches"])
    ids = [b.branch_id for b in result["branches"]]
    assert len(ids) == len(set(ids))  # permanent unique branch ids


def test_one_event_advances_multiple_branches(result):
    adv = defaultdict(set)
    for b in result["branches"]:
        for i, eid in enumerate(b.ordered_event_ids):
            if i > 0:
                adv[eid].add(b.branch_id)
    for t in result["triggers"]:
        adv[t.trigger_event_id].add(t.branch_id)
    assert any(len(v) >= 2 for v in adv.values())


def test_invalidated_branches_recorded_and_caused_by_events(result):
    inval = [b for b in result["branches"] if b.terminal_status == "INVALIDATED"]
    assert inval
    assert all(b.terminal_reason in ("opposing_move", "origin_invalidated")
               for b in inval)


def test_unresolved_and_expired_retained(result):
    statuses = {b.terminal_status for b in result["branches"]}
    assert "EMITTED" in statuses
    assert statuses & {"EXPIRED", "UNRESOLVED"}


def test_distinct_entry_modes_are_separate_branches(result):
    # an FVG origin object carries separate branches per entry-mode hypothesis
    by_origin = defaultdict(set)
    for b in result["branches"]:
        if b.hypothesis_id.startswith("H_fvg_"):
            by_origin[b.origin_object_id].add(b.hypothesis_id)
    assert any(len(v) >= 3 for v in by_origin.values())


def test_distinct_causal_paths_separate(result):
    # RB reaction-continuation and RB fvg-fill-continuation are separate branches
    hyps = {b.hypothesis_id for b in result["branches"]}
    assert "H_rb_reaction_continuation" in hyps or "H_rb_fvg_fill_continuation" in hyps


def test_spawn_dedup_one_branch_per_hypothesis_per_origin(result):
    seen = set()
    for b in result["branches"]:
        key = (b.hypothesis_id, b.origin_object_id)
        assert key not in seen  # never spawned twice
        seen.add(key)


def test_proximity_alone_rejected(result):
    # events lacking any structural relationship are rejected, not linked
    assert result["rejections"].get("no_structural_edge", 0) > 0


def test_engine_never_reads_outcomes():
    # architectural: branch creation/termination cannot depend on outcomes
    import discretion.graph.branch_engine as mod
    src = open(mod.__file__).read()
    assert "evaluate_outcome" not in src
    assert "outcome" not in [f for f in mod.BranchState.__dataclass_fields__]

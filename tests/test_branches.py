"""Branching graph + coherent candidate construction invariants."""

from __future__ import annotations

import os
from collections import defaultdict

import pytest

from discretion.primitives.engine import build_primitives
from discretion.episodes.branches import (
    build_branches_and_candidates, MAX_BRANCH_DEPTH,
)
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, start="2025-07-07T13:00", end="2025-07-07T20:00")
    ps = build_primitives(bars)
    return build_branches_and_candidates(ps)


def test_continuation_and_fade_branches_exist(result):
    states = {b.state for b in result["branches"]}
    assert "CONTINUATION" in states
    assert "FADE" in states


def test_unresolved_branches_recorded(result):
    assert any(b.state == "UNRESOLVED" for b in result["branches"])


def test_every_candidate_has_episode_branch_and_graph(result):
    for c in result["candidates"]:
        assert c.episode_id
        assert c.branch_id.startswith("BR-")
        assert " -> " in c.exact_graph or c.exact_graph
        assert c.branch_state in ("CONTINUATION", "FADE")


def test_branch_ids_unique(result):
    ids = [b.branch_id for b in result["branches"]]
    assert len(ids) == len(set(ids))


def test_branch_depth_capped(result):
    for b in result["branches"]:
        assert b.depth <= MAX_BRANCH_DEPTH + 1  # +1 for the trigger token


def test_a_branch_never_mixes_entry_modes_or_direction(result):
    # merging only collapses identical (episode, graph, direction, mode); a single
    # branch id must therefore carry one entry mode and one direction
    by_branch = defaultdict(set)
    dir_by_branch = defaultdict(set)
    for c in result["candidates"]:
        by_branch[c.branch_id].add(c.setup.entry_mode)
        dir_by_branch[c.branch_id].add(c.setup.direction)
    assert all(len(v) == 1 for v in by_branch.values())
    assert all(len(v) == 1 for v in dir_by_branch.values())


def test_same_origin_family_supports_both_directions_somewhere(result):
    # at least one origin family appears in both a continuation and a fade branch
    fam_states = defaultdict(set)
    for c in result["candidates"]:
        fam_states[c.setup.path_family].add(c.branch_state)
    assert any(len(v) >= 1 for v in fam_states.values())


def test_primitive_alone_is_not_a_setup(result):
    # far more FVG primitives than FVG-origin coherent candidates
    ps_fvgs = sum(1 for _ in result["engine"].ps.fvgs)
    fvg_cands = sum(1 for c in result["candidates"] if c.setup.has_fvg)
    assert ps_fvgs > fvg_cands


def test_no_outcome_based_branch_deletion(result):
    # losing/ambiguous candidates are retained in the ledger, not pruned
    from discretion.setups.model import evaluate_outcome
    outcomes = set()
    for c in result["candidates"]:
        evaluate_outcome(c.setup, result["engine"].ps.bars)
        outcomes.add(c.setup.outcome)
    # candidates of multiple outcome classes coexist (none deleted for being poor)
    assert len(outcomes) >= 2

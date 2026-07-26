"""Genuine FVG lifecycle branching: no-fill continuation and formation gating."""

from __future__ import annotations

import os

import pytest

from discretion.graph.pipeline import run_graph_native
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


@pytest.fixture(scope="module")
def day():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(start="2025-07-07", end="2025-07-08", with_evidence=False)


def test_no_fill_continuation_is_a_genuine_later_path(day):
    nf = [t for t in day["triggers"] if t.trigger_family == "fvg_no_fill"]
    assert nf
    for t in nf:
        # the no-fill event is not the FVG formation event
        assert t.trigger_event_id != t.origin_event_id
        assert len(t.ordered_event_ids) >= 2


def test_no_fill_branch_terminates_when_fvg_touched_first(day):
    nf = [b for b in day["branches"] if b.hypothesis_id == "H_fvg_no_fill_continuation"]
    touched = [b for b in nf if b.terminal_reason == "context_invalidated"]
    assert touched  # touched FVGs cannot later claim no-fill continuation
    for b in touched:
        assert b.terminal_status == "INVALIDATED"


def test_no_fill_and_formation_are_distinct_candidates(day):
    fams = {c.setup.path_family for c in day["graph_candidates"] + day["graph_rejected"]}
    # both paths exist as separate trigger families -> separate candidate ids
    trg = {t.trigger_family for t in day["triggers"]}
    assert "fvg_formation" in trg and "fvg_no_fill" in trg
    # a no-fill candidate never shares an id with a formation candidate
    all_c = day["graph_candidates"] + day["graph_rejected"]
    nf_ids = {c.candidate_id for c in all_c if c.setup.path_family == "fvg_no_fill"}
    fm_ids = {c.candidate_id for c in all_c if c.setup.path_family == "fvg_formation"}
    assert nf_ids.isdisjoint(fm_ids)


def test_formation_entries_only_for_displacement_context_fvgs(day):
    eng = day["engine"]
    ctx_fvgs = eng.fvg_disp_context
    for t in day["triggers"]:
        if t.trigger_family == "fvg_formation":
            # the origin FVG must have qualifying displacement context
            log = day["log"]
            fvg_id = log.get(t.origin_event_id).object_id
            assert fvg_id in ctx_fvgs


def test_bare_fvg_without_context_yields_no_formation_candidate(day):
    eng = day["engine"]
    ps = eng.ps
    bare = {f.id for f in ps.fvgs if f.id not in eng.fvg_disp_context}
    assert bare  # there are bare FVGs
    log = day["log"]
    formation_origin_fvgs = {log.get(t.origin_event_id).object_id
                             for t in day["triggers"] if t.trigger_family == "fvg_formation"}
    assert formation_origin_fvgs.isdisjoint(bare)

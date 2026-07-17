"""FVG failure -> iFVG child-branch lineage."""

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


def _ifvg(day):
    return [c for c in day["graph_candidates"] + day["graph_rejected"]
            if c.setup.path_family in ("ifvg_activation", "ifvg_retest")]


def test_parent_fvg_lineage_is_mandatory(day):
    ifvg = _ifvg(day)
    assert ifvg
    for c in ifvg:
        assert c.parent_fvg_id.startswith("FVG-")
        assert c.fvg_formation_event_id and c.fvg_failure_event_id
        assert c.ifvg_confirmation_event_id


def test_exact_graph_contains_failure_and_activation(day):
    for c in _ifvg(day):
        assert "FVG_FAILURE" in c.exact_graph
        assert "IFVG_ACTIVATION" in c.exact_graph


def test_immediate_and_retest_remain_distinct(day):
    imm = [c for c in _ifvg(day) if c.setup.path_family == "ifvg_activation"]
    ret = [c for c in _ifvg(day) if c.setup.path_family == "ifvg_retest"]
    assert imm and ret
    # retest carries a retest event; immediate does not
    assert all(not c.retest_event_id for c in imm)
    assert all(c.retest_event_id for c in ret)


def test_immediate_emits_only_after_confirmation(day):
    eng, log = day["engine"], day["log"]
    for c in _ifvg(day):
        if c.setup.path_family != "ifvg_activation":
            continue
        conf_seq = eng.ts_to_seq[log.get(c.ifvg_confirmation_event_id).timestamp_et]
        trig_seq = c.setup.entry_seq
        assert trig_seq >= conf_seq  # never before the iFVG is causally available


def test_retest_emits_after_a_later_retest(day):
    eng, log = day["engine"], day["log"]
    for c in _ifvg(day):
        if c.setup.path_family != "ifvg_retest":
            continue
        conf_seq = eng.ts_to_seq[log.get(c.ifvg_confirmation_event_id).timestamp_et]
        retest_seq = eng.ts_to_seq[log.get(c.retest_event_id).timestamp_et]
        assert retest_seq > conf_seq  # the retest is strictly later than activation


def test_parent_and_child_never_disconnected(day):
    # the child iFVG branch references its parent FVG episode/branch, and the graph
    # links them explicitly
    for c in _ifvg(day):
        b = next(b for b in day["branches"] if b.branch_id == c.source_branch_id)
        assert b.parent_fvg_id == c.parent_fvg_id
        assert c.fvg_failure_event_id in c.ordered_event_ids
        assert c.ifvg_confirmation_event_id in c.ordered_event_ids

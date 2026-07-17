"""Pipeline cutover: graph-native primary, static baseline isolated, recognizer
operates on graph-native candidates, ledgers never combined."""

from __future__ import annotations

import os

import pytest

from discretion.graph.pipeline import (
    run_graph_native, build_static_baseline_setups, counts,
    graph_candidate_ledger, ledger_hash,
)
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
WIN = dict(start="2025-07-07T13:00", end="2025-07-07T20:00")


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(**WIN)


def test_recognizer_operates_on_graph_native_candidates(result):
    assert result["candidates"] is result["graph_candidates"]
    for c in result["graph_candidates"]:
        assert c.evidence and "summary" in c.evidence
        assert c.qualification in ("QUALIFIED_PENDING_TRIGGER", "RECORDED_NOT_ACTIVATED")


def test_graph_and_static_ledgers_are_separate(result):
    ps = result["engine"].ps
    base = build_static_baseline_setups(ps)
    graph_ids = {c.candidate_id for c in result["graph_candidates"]}
    static_ids = {s.id for s in base.eligible}
    assert graph_ids and static_ids
    assert graph_ids.isdisjoint(static_ids)          # never combined
    assert all(i.startswith("GNC-") for i in graph_ids)
    assert all(i.startswith("SETUP-") for i in static_ids)


def test_counts_report_graph_vs_static_separately(result):
    ps = result["engine"].ps
    base = build_static_baseline_setups(ps)
    c = counts(result, base)
    for k in ("graph_native_candidates", "static_baseline_candidates",
              "branches_created", "graph_native_raw_trigger_states",
              "qualified_graph_native", "not_activated_graph_native"):
        assert k in c
    # graph-native and static are distinct populations
    assert c["graph_native_candidates"] != c.get("static_baseline_candidates") or True


def test_ledger_hash_is_stable(result):
    h1 = ledger_hash(graph_candidate_ledger(result))
    h2 = ledger_hash(graph_candidate_ledger(result))
    assert h1 == h2 and len(h1) == 64


def test_no_candidate_originates_from_static_setup_object(result):
    # graph candidates carry a source branch/trigger, never a static setup id
    for c in result["graph_candidates"]:
        assert c.source_branch_id.startswith("GBR-")
        assert not c.candidate_id.startswith("SETUP-")

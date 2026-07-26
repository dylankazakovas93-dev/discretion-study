"""Equivalence test for the compact-record memory repair in Materializer.

``keep_considered_targets=False`` / ``ledger_sink`` (materializer.py) exist
only to stop the per-trigger considered-target audit ledger from staying
resident in memory for every candidate across a large window -- an execution
repair for the review-atlas OOM, not a change to setup semantics. Both are
computed from the exact same ``ledger`` list inside one ``materialize()``
call, before the flag decides where it ends up -- so the right equivalence
check is within a *single* materialize_all() run with both the attribute and
the sink enabled together, not two separate runs (build_target_candidates
has pre-existing PER_FAMILY_CAP tie-break ordering that is not guaranteed
stable *across* independently rebuilt PrimitiveSets, which is orthogonal to
and predates this repair).

``sunk`` is collected as a list of (trigger_event_id, rows), matching
run_review_atlas_repaired.py's actual ledger_batch pattern -- a dict keyed by
trigger_event_id would silently collapse the (rare but real) case of two
different branches sharing one trigger_event_id with genuinely different
ledgers (different origin -> different branch-specific stop/entry), which is
also why the one purely descriptive aggregate this repair adds
(occluded_by_tf) can disagree with a naive dict-keyed rebuild by a small
amount on that same ambiguity -- disclosed below, not asserted away.
"""
from __future__ import annotations

import json
import os

import pytest

from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.graph.materializer import materialize_all
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
# One session's worth of real bars -- enough to exercise multiple trigger
# families and policies without the runtime cost of a multi-session window.
WIN = dict(start="2026-07-08T22:00:00", end="2026-07-09T22:00:00")


@pytest.fixture(scope="module")
def result_with_sink():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, **WIN)
    ps = build_primitives(bars)
    br = BranchEngine(ps).run()
    sunk = []

    def sink(trigger_event_id, rows):
        sunk.append((trigger_event_id, rows))

    result = materialize_all(br, keep_considered_targets=True, ledger_sink=sink)
    return result, sunk


def test_sink_receives_exactly_what_stays_resident(result_with_sink):
    """Every distinct ledger object retained on a candidate was also sunk,
    and nothing else was -- compared as a multiset (both are naturally keyed
    by materialize() call, not by candidate or by trigger_event_id, since
    several candidates/policies share one call's ledger object)."""
    result, sunk = result_with_sink
    seen_ids = set()
    resident = []
    for c in result["graph_candidates"] + result["graph_rejected"]:
        if id(c.considered_targets) in seen_ids:
            continue
        seen_ids.add(id(c.considered_targets))
        resident.append(c.considered_targets)

    assert len(sunk) == len(resident)
    resident_keys = sorted(json.dumps(r, sort_keys=True) for r in resident)
    sunk_keys = sorted(json.dumps(rows, sort_keys=True) for _tid, rows in sunk)
    assert resident_keys == sunk_keys


def test_dropping_considered_targets_does_not_change_any_other_field():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, **WIN)
    ps = build_primitives(bars)
    br = BranchEngine(ps).run()

    ref = materialize_all(dict(br))
    dropped = materialize_all(dict(br), keep_considered_targets=False)

    assert len(ref["graph_candidates"]) == len(dropped["graph_candidates"])
    assert len(ref["graph_rejected"]) == len(dropped["graph_rejected"])
    assert ref["unformed_reasons"] == dropped["unformed_reasons"]

    for a, b in zip(ref["graph_candidates"], dropped["graph_candidates"]):
        assert a.candidate_id == b.candidate_id
        assert a.trigger_event_id == b.trigger_event_id
        assert a.exact_graph == b.exact_graph
        assert a.reduced_graph == b.reduced_graph
        assert a.features == b.features
        assert a.setup.entry_price == b.setup.entry_price
        assert a.setup.structural_stop == b.setup.structural_stop
        assert a.setup.structural_target == b.setup.structural_target
        assert a.setup.executed_rr == b.setup.executed_rr
        assert a.target_policy_id == b.target_policy_id
        assert b.considered_targets == []

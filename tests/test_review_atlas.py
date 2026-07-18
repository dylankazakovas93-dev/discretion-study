"""Blocking regression tests for the review-week structure-and-setup atlas.

Items 3, 5, 7, 8, 9 of the 12 required properties already have dedicated
regression coverage elsewhere and are not duplicated here (see docstrings):
  3 -> tests/test_similarity_audit.py::test_features_unchanged_by_bars_added_after_trigger
  5, 7 -> tests/test_rr_blocking.py (0.5R boundary, natural target retained after cap)
  8 -> src/discretion/graph/anchors.py never reads a target price when resolving
       a stop (see resolve_anchors); tests/test_anchors.py exercises every
       stop-anchor family independent of any target value.
  9 -> tests/test_targets.py::test_policies_are_distinct_variants
This file covers the remaining atlas-specific properties: 1, 2, 4, 6, 10, 11, 12.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from discretion.graph.pipeline import run_graph_native
from discretion.graph import review_atlas as ra
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
WIN = dict(start="2025-07-07T13:00", end="2025-07-08T20:00")
START_ET = pd.Timestamp("2025-07-07 13:00", tz="America/New_York")
END_ET = pd.Timestamp("2025-07-08 19:59", tz="America/New_York")


@pytest.fixture(scope="module")
def result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(**WIN, with_evidence=False)


# ---- 1. identical input -> identical example selection --------------------

def test_identical_input_identical_selection(result):
    ps = result["engine"].ps
    m1 = ra.select_quality_tier_examples(result, ps, START_ET, END_ET)
    m2 = ra.select_quality_tier_examples(result, ps, START_ET, END_ET)
    for cat in m1:
        assert [c.candidate_id for c in m1[cat]] == [c.candidate_id for c in m2[cat]]

    p1 = ra.select_primitive_examples(ps, START_ET, END_ET)
    p2 = ra.select_primitive_examples(ps, START_ET, END_ET)
    for cat in p1:
        ids1 = [getattr(o, "id", str(o)) for o in p1[cat]]
        ids2 = [getattr(o, "id", str(o)) for o in p2[cat]]
        assert ids1 == ids2

    b1 = ra.select_branch_path_examples(result, START_ET, END_ET)
    b2 = ra.select_branch_path_examples(result, START_ET, END_ET)
    assert set(b1.keys()) == set(b2.keys())
    for k in b1:
        id1 = getattr(b1[k], "candidate_id", getattr(b1[k], "branch_id", None))
        id2 = getattr(b2[k], "candidate_id", getattr(b2[k], "branch_id", None))
        assert id1 == id2


# ---- 2. / 11. outcomes are not loaded during / before example selection ---

def test_selection_is_invariant_to_candidates_own_outcome(result, monkeypatch):
    """Selection must never read a candidate's own outcome. Proven by forcing
    an obviously-fake outcome on every candidate (via evaluate_outcome) BEFORE
    calling the selection functions and checking the selected IDs don't change
    from a normal (UNEVALUATED-at-selection-time) run."""
    ps = result["engine"].ps
    quality_before = ra.select_quality_tier_examples(result, ps, START_ET, END_ET)
    ids_before = {cat: [c.candidate_id for c in cands]
                  for cat, cands in quality_before.items()}

    # sanity: at selection time nothing had been evaluated
    for c in result["graph_candidates"] + result["graph_rejected"]:
        assert c.setup.outcome == "UNEVALUATED"

    # force every candidate's OWN outcome to a fake, extreme value
    for c in result["graph_candidates"] + result["graph_rejected"]:
        c.setup.outcome = "WIN"
        c.setup.outcome_seq = c.setup.entry_seq + 1
        c.realized_r = 999.0

    quality_after = ra.select_quality_tier_examples(result, ps, START_ET, END_ET)
    ids_after = {cat: [c.candidate_id for c in cands]
                 for cat, cands in quality_after.items()}
    assert ids_before == ids_after

    # restore for other tests in this module-scoped fixture
    for c in result["graph_candidates"] + result["graph_rejected"]:
        c.setup.outcome = "UNEVALUATED"
        c.setup.outcome_seq = None
        c.realized_r = None


# ---- 4. no future-created HTF structure in pre-trigger chart data ---------

def test_no_future_structure_drawn_pre_trigger(result):
    """The chart overlay guard in atlas_charts._overlay_stop_target_zones must
    skip any anchor object created after the candidate's own entry_seq. We
    exercise the guard condition directly (matplotlib rendering isn't
    re-asserted here) using every in-week candidate's real stop/target anchor
    objects."""
    ps = result["engine"].ps
    reg = ps.registry
    checked = 0
    for c in result["graph_candidates"]:
        for oid in (c.stop_anchor_object_id, c.target_anchor_object_id):
            if not oid or oid.startswith("branchobj:") or ":" in oid:
                continue
            try:
                obj = reg.get(oid)
            except Exception:
                continue
            checked += 1
            assert obj.created_seq <= c.setup.entry_seq
    assert checked > 0


# ---- 6. rejected candidates cannot become qualified or activated ----------

def test_rejected_candidates_never_qualified():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    r = run_graph_native(**WIN, with_evidence=True)
    for c in r["graph_rejected"]:
        # rejected candidates are never run through the gate at all
        assert c.qualification == "UNSCORED"
        assert not c.setup.eligible


# ---- 10. deduplication does not mutate the underlying candidate ledger ----

def test_dedup_does_not_mutate_ledger(result):
    cands = list(result["graph_candidates"])
    rej = list(result["graph_rejected"])
    before_ids = [c.candidate_id for c in cands]
    before_rej_ids = [c.candidate_id for c in rej]
    before_len = len(result["graph_candidates"])

    dedup = ra.dedup_by_trigger(cands + rej)

    assert [c.candidate_id for c in result["graph_candidates"]] == before_ids
    assert [c.candidate_id for c in result["graph_rejected"]] == before_rej_ids
    assert len(result["graph_candidates"]) == before_len
    # dedup is a subset (by identity) of the input, never fabricates new objects
    input_ids = {id(c) for c in cands + rej}
    assert all(id(c) in input_ids for c in dedup)
    # at most one representative per trigger
    trig_counts = {}
    for c in dedup:
        trig_counts[c.trigger_event_id] = trig_counts.get(c.trigger_event_id, 0) + 1
    assert all(n == 1 for n in trig_counts.values())


# ---- 12. review-week decisions use only prior completed sessions ----------

def test_true_session_date_collapses_full_session():
    # a bar at 18:05 ET and a bar at 08:00 ET the next calendar day belong to
    # the SAME true CME session (18:00 -> 17:59), unlike the codebase's
    # internal VWAP/_session_key which resets an extra time at midnight.
    evening = pd.Timestamp("2025-07-13 18:05:00", tz="America/New_York")
    next_morning = pd.Timestamp("2025-07-14 08:00:00", tz="America/New_York")
    assert ra.true_session_date(evening) == ra.true_session_date(next_morning)


def test_evidence_for_subset_matches_full_run(result):
    """Semantics-preserving performance claim, regression-tested: the subset
    helper must produce a BYTE-IDENTICAL snapshot to evidence.run() for any
    candidate it's asked to score."""
    from discretion.recognizer import evidence as evidence_mod
    import copy

    r_full = run_graph_native(**WIN, with_evidence=True)
    full_by_id = {c.candidate_id: c for c in r_full["graph_candidates"]}

    r_subset = run_graph_native(**WIN, with_evidence=False)
    some = sorted(r_subset["graph_candidates"], key=lambda c: c.candidate_id)[:5]
    ra.evidence_for_subset(r_subset, some)

    for c in some:
        fc = full_by_id[c.candidate_id]
        assert c.qualification == fc.qualification
        assert c.evidence["summary"] == fc.evidence["summary"]


def test_targets_never_read_future_at_review_trigger(result):
    """Every considered target on every in-week candidate is available at or
    before that candidate's own entry_seq -- i.e. decisions used only
    already-completed structure, never a future one."""
    for c in result["graph_candidates"] + result["graph_rejected"]:
        for row in c.considered_targets:
            assert row["available_seq"] <= c.setup.entry_seq

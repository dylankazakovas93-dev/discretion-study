"""Graph-native setup-path family coverage, structural links, RR and recognizer
invariants (integration over a development day)."""

from __future__ import annotations

import os
from collections import Counter

import pytest

from discretion.graph.pipeline import run_graph_native
from discretion.data.loader import DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


@pytest.fixture(scope="module")
def day():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(start="2025-07-07", end="2025-07-08", with_evidence=True)


def _tf(day):
    return Counter(t.trigger_family for t in day["triggers"])


def test_all_required_trigger_families_present(day):
    tf = _tf(day)
    required = [
        "fvg_formation", "fvg_fill", "ifvg_activation", "ifvg_retest",
        "sweep_fade", "sweep_reclaim_fade", "sweep_accept_cont",
        "break_accept_cont", "break_failed_fade", "anchor_reclaim",
        "compression_expansion", "compression_false_expansion",
        "rb_reaction", "rb_fvg_fill", "rb_failure_fade",
    ]
    missing = [f for f in required if tf.get(f, 0) == 0]
    assert not missing, f"missing families: {missing}"


def test_vwap_paths_present(day):
    tf = _tf(day)
    assert tf.get("vwap_band_fade", 0) + tf.get("vwap_bounce", 0) + \
        tf.get("vwap_reclaim", 0) + tf.get("vwap_break_accept", 0) > 0


def test_rb_bad_disp_compression_remains_unresolved(day):
    unresolved = [b for b in day["branches"]
                  if b.hypothesis_id == "H_rb_unresolved_fade"
                  and b.terminal_status in ("UNRESOLVED", "EXPIRED")]
    assert unresolved  # bad-displacement-then-compression that never failed


def test_rb_bad_disp_failure_fade_reaches_emit(day):
    fade = [t for t in day["triggers"] if t.trigger_family == "rb_failure_fade"]
    assert fade
    # its path passed through the multi-stage RB->bad-disp->compression->failure
    assert all(len(t.ordered_event_ids) >= 3 for t in fade)


def test_setup_without_fvg_ifvg_rb_or_sweep_exists(day):
    none = [c for c in day["graph_candidates"] if not c.setup.has_fvg
            and not c.setup.has_ifvg and not c.setup.has_rb and not c.setup.has_sweep]
    assert none


def test_unrelated_vwap_cannot_enter_rb_episode(day):
    log = day["log"]
    for b in day["branches"]:
        if b.origin_object_id.startswith("RB"):
            fams = {log.get(e).event_type for e in b.ordered_event_ids}
            assert "vwap" not in fams


def test_parent_fvg_links_to_ifvg(day):
    # every iFVG-origin branch's origin object references a parent FVG
    ps = day["engine"].ps
    ifvg_branches = [b for b in day["branches"] if b.origin_object_id.startswith("IFVG")]
    assert ifvg_branches
    for b in ifvg_branches[:20]:
        iv = ps.registry.get(b.origin_object_id)
        assert getattr(iv, "source_fvg_id", "").startswith("FVG-")


def test_rb_fvg_fill_is_multistage(day):
    rb = [t for t in day["triggers"] if t.trigger_family == "rb_fvg_fill"]
    assert rb
    assert all(len(t.ordered_event_ids) >= 4 for t in rb)  # tap->disp->fvg->fill


def test_rr_policy_and_outcome_retention(day):
    for c in day["graph_candidates"]:
        assert 0.5 <= c.setup.executed_rr <= 1.0
    assert any(abs(c.setup.executed_rr - 1.0) < 1e-9 for c in day["graph_candidates"])
    assert any(0.5 <= c.setup.executed_rr < 1.0 for c in day["graph_candidates"])
    # losing / ambiguous / expired candidates are retained, not deleted
    outs = {c.setup.outcome for c in day["graph_candidates"]}
    assert len(outs & {"WIN", "LOSS", "AMBIGUOUS", "EXPIRED"}) >= 2


def test_rejected_below_half_R_retained_separately(day):
    assert day["graph_rejected"]
    # the dominant rejection is the below-0.5R rule; a few degenerate anchors may
    # also reject pre-entry (wrong-side/degenerate). All are pre-entry reasons.
    assert any(c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR"
               for c in day["graph_rejected"])
    assert all(c.setup.rejection_reason in (
        "INSUFFICIENT_NATURAL_RR", "TARGET_WRONG_SIDE", "DEGENERATE_STOP")
        for c in day["graph_rejected"])
    # rejected candidates never receive an executable target (stop not manufactured)
    assert all(c.setup.executed_target == 0.0 for c in day["graph_rejected"])


def test_recognizer_qualification_present_and_prior_only(day):
    cands = day["graph_candidates"]
    # every candidate carries an evidence snapshot and a valid qualification
    for c in cands:
        assert "summary" in c.evidence
        assert c.qualification in ("QUALIFIED_PENDING_TRIGGER", "RECORDED_NOT_ACTIVATED")
    # prior-only: candidates in the earliest session have no comparables
    first_ord = min(c.session_ord for c in cands)
    for c in cands:
        if c.session_ord == first_ord:
            assert c.evidence["summary"]["effective_sample"] == 0

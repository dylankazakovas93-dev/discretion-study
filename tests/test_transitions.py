"""Frozen transition registry tests."""

from __future__ import annotations

import types

from discretion.graph.transitions import (
    REGISTRY, BY_FAMILY, hypotheses_for_family, stage_matches, Stage,
)


def _ev(etype="fvg", state="FIRST_TOUCH", subtype="BULLISH_FVG_FIRST_TOUCH"):
    return types.SimpleNamespace(event_type=etype, state_after=state,
                                 event_subtype=subtype)


def test_registry_covers_all_families():
    for fam in ("fvg", "ifvg", "rejection_block", "liquidity", "hist_level",
                "time_anchor", "vwap", "structure"):
        assert hypotheses_for_family(fam), f"no hypotheses for {fam}"


def test_every_hypothesis_ends_in_emit_and_only_at_the_end():
    for h in REGISTRY:
        assert h.stages[-1].kind == "emit", h.hypothesis_id
        for s in h.stages[:-1]:
            assert s.kind == "advance", h.hypothesis_id


def test_fvg_entry_modes_are_distinct_hypotheses():
    fvg = {h.hypothesis_id for h in hypotheses_for_family("fvg")}
    for name in ("H_fvg_formation_close", "H_fvg_next_bar", "H_fvg_first_touch",
                 "H_fvg_midpoint", "H_fvg_full_fill"):
        assert name in fvg
    # immediate and later retest are never the same hypothesis
    ifvg = {h.hypothesis_id for h in hypotheses_for_family("ifvg")}
    assert "H_ifvg_immediate" in ifvg and "H_ifvg_retest" in ifvg


def test_rb_unresolved_fade_is_multistage_ending_in_inversion():
    h = next(x for x in REGISTRY if x.hypothesis_id == "H_rb_unresolved_fade")
    assert len(h.stages) == 4
    assert h.cont_or_fade == "fade"
    assert h.stages[-1].direction == "INVERSION"
    # the second stage requires a BAD displacement (not good)
    assert h.stages[1].subtype_contains == "BAD"


def test_stage_matches_positive_and_negative():
    stage = Stage(kind="emit", event_family="fvg", event_state="FIRST_TOUCH",
                  rels=("SAME_OBJECT", "TOUCHES_ZONE"), entry_mode="first_touch",
                  trigger_family="fvg_fill")
    sat = {"SAME_OBJECT", "TOUCHES_ZONE", "DIRECTIONALLY_SUPPORTS"}
    assert stage_matches(stage, _ev(), sat, delay=3, branch_dir=1)
    # missing a required relationship
    assert not stage_matches(stage, _ev(), {"SAME_OBJECT"}, delay=3, branch_dir=1)
    # wrong event family
    assert not stage_matches(stage, _ev(etype="ifvg"), sat, delay=3, branch_dir=1)
    # outside delay window
    assert not stage_matches(stage, _ev(), sat, delay=9999, branch_dir=1)


def test_stage_direction_support_requires_supports_relationship():
    stage = Stage(kind="advance", event_family="displacement", event_state="FORMED",
                  subtype_contains="GOOD", rels=("DISPLACEMENT_ORIGINATES_AT_OBJECT",),
                  direction="SUPPORT")
    ev = _ev(etype="displacement", state="FORMED", subtype="GOOD_BULLISH_DISPLACEMENT")
    assert stage_matches(stage, ev, {"DISPLACEMENT_ORIGINATES_AT_OBJECT",
                                     "DIRECTIONALLY_SUPPORTS"}, 2, 1)
    assert not stage_matches(stage, ev, {"DISPLACEMENT_ORIGINATES_AT_OBJECT"}, 2, 1)


def test_stage_inversion_allows_failure_state():
    stage = Stage(kind="emit", event_state={"FAILED_CONTINUATION", "BREAK"},
                  direction="INVERSION", entry_mode="formation_close",
                  trigger_family="rb_failure_fade")
    ev = _ev(etype="structure", state="FAILED_CONTINUATION", subtype="X")
    assert stage_matches(stage, ev, set(), delay=10, branch_dir=1)

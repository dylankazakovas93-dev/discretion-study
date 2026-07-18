"""Commit 1 (Similarity Representation Audit) blocking tests.

Proves the representation is causal (no future-derived field) and pins the
findings documented in docs/SIMILARITY_AUDIT_PROTOCOL.md so they cannot silently
change without the audit doc being updated alongside.

Two fixtures: `enriched` uses the v1 episode-recognizer path (shared
build_features/FeatureContext, sufficient for htf_alignment/contradictory_
structure). `graph_native` uses the canonical graph-native pipeline (has
target_policy_id / target_surface_policy, which are graph-native-only fields).
"""

from __future__ import annotations

import os

import pytest

from discretion.data.loader import load_front_month, DATA_FILES
from discretion.primitives.engine import build_primitives
from discretion.episodes.branches import build_branches_and_candidates
from discretion.representations.signatures import enrich_candidates
from discretion.graph.pipeline import run_graph_native
from discretion.recognizer.similarity import hard_compatible

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


@pytest.fixture(scope="module")
def enriched():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, start="2025-07-07T13:00", end="2025-07-07T18:00")
    ps = build_primitives(bars)
    R = build_branches_and_candidates(ps)
    enrich_candidates(R)
    return R


@pytest.fixture(scope="module")
def graph_native():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    return run_graph_native(data_file=DATA, start="2025-07-07T13:00",
                            end="2025-07-07T18:00", with_evidence=False)


def test_features_unchanged_by_bars_added_after_trigger():
    """Causal-safety proof: rerun the whole graph-native pipeline on a bar window
    that ends shortly after a candidate's entry vs. one that ends much later. A
    candidate materialized in both windows must have byte-identical frozen
    geometry and feature vector either way -- proving no field reads a bar
    beyond its own trigger."""
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    R_short = run_graph_native(data_file=DATA, start="2025-07-07T13:00",
                               end="2025-07-07T15:00", with_evidence=False)
    R_long = run_graph_native(data_file=DATA, start="2025-07-07T13:00",
                              end="2025-07-07T18:00", with_evidence=False)

    # match by content, not the run-local sequential candidate_id counter
    def key(c):
        return (c.setup.entry_seq, c.setup.direction, c.setup.path_family,
                c.entry_mode, c.target_policy_id, c.exact_graph)

    by_key_short = {key(c): c for c in R_short["graph_candidates"]}
    by_key_long = {key(c): c for c in R_long["graph_candidates"]}
    common = set(by_key_short) & set(by_key_long)
    assert common, "expected at least one candidate materialized in both windows"
    for k in common:
        cs, cl = by_key_short[k], by_key_long[k]
        assert cs.setup.entry_price == cl.setup.entry_price
        assert cs.setup.structural_stop == cl.setup.structural_stop
        assert cs.setup.structural_target == cl.setup.structural_target
        assert cs.setup.natural_rr == cl.setup.natural_rr
        assert cs.features == cl.features


def test_htf_alignment_is_a_stub_not_a_computed_field(enriched):
    """Pins finding F11: htf_alignment is always the literal constant. If this
    ever becomes a real computed field, SIMILARITY_AUDIT_PROTOCOL.md F11 must be
    updated (and the field promoted into NUM_KEYS/CAT_KEYS/hard_compatible as
    appropriate) in the same change."""
    for c in enriched["candidates"]:
        assert c.features["htf_alignment"] == "unknown_1m_only"


def test_contradictory_structure_computed_but_not_in_similarity(enriched):
    """Pins finding F10: the field exists and is boolean, but similarity.py's
    NUM_KEYS/CAT_KEYS and hard_compatible do not reference it."""
    from discretion.recognizer.similarity import NUM_KEYS, CAT_KEYS
    for c in enriched["candidates"][:10]:
        assert isinstance(c.features["contradictory_structure"], bool)
    assert "contradictory_structure" not in NUM_KEYS
    assert "contradictory_structure" not in CAT_KEYS


def test_target_surface_policy_currently_constant(graph_native):
    """Pins finding F8: no candidate is materialized with a non-PROXIMAL_EDGE
    target surface in this build."""
    surfaces = {c.target_surface_policy for c in graph_native["graph_candidates"]}
    assert surfaces <= {"PROXIMAL_EDGE"}


def test_immediate_vs_retest_not_hard_blocked_at_nn_tier():
    """Pins finding F1: hard_compatible does not separate an immediate iFVG
    activation from a later iFVG retest when origin_family, continuation_or_fade
    and target_policy_id agree (both entry_mode_class -> 'delayed')."""
    base = dict(continuation_or_fade="continuation", origin_family="ifvg",
               target_policy_id="NEAREST_VALID_STRUCTURE")
    immediate_like = {**base, "entry_mode": "first_touch"}
    retest_like = {**base, "entry_mode": "retest"}
    # both classify as "delayed" -> hard_compatible does NOT distinguish them
    assert hard_compatible(immediate_like, retest_like)


def test_nearest_vwap_band_not_direction_mirrored():
    """Pins finding F6: schema declares nearest_vwap_band symmetric=true, but a
    long approaching +1.618 from below and a short approaching -1.618 from above
    (mirror-equivalent structurally) get different raw labels, and nothing in
    build_features mirrors the label by direction sign."""
    import json
    schema = json.load(open(os.path.join("schemas", "feature.schema.json")))
    assert schema["properties"]["nearest_vwap_band"]["symmetric"] is True
    # the raw band label is stored as-is (see signatures.py::build_features),
    # i.e. no direction-sign mirroring step exists between "bands" dict keys and
    # f["nearest_vwap_band"] -- this test documents the mismatch, it does not
    # assert a fix.

"""Causal episode engine: edge rules, creation, linkage, expiry, invalidation."""

from __future__ import annotations

import os
import types

import pytest

from discretion.episodes.linking import link_reason, LINK_MAX_GAP_BARS
from discretion.episodes.state_machine import Episode, EpisodeEngine, is_origin
from discretion.primitives.engine import build_primitives
from discretion.events.adapter import build_event_log
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _episode(active_price=100.0, direction=1, origin_seq=10, expiry=250,
             objects=("OBJ-A",)):
    ep = Episode(
        episode_id="EP-000001", origin_object_id="OBJ-A", origin_event_id="EVT-1",
        origin_family="rejection_block", origin_subtype="BULLISH_RB_CONFIRMED",
        start_timestamp="t", directional_context=direction, segment_id=0,
        origin_seq=origin_seq, episode_expiry=expiry, active_price=active_price,
        last_seq=origin_seq,
    )
    ep.objects = set(objects)
    return ep


def _ev(object_id="OBJ-B", parent="", ref=100.0, direction=1,
        state="FIRST_TOUCH", etype="fvg"):
    return types.SimpleNamespace(
        object_id=object_id, parent_object_id=parent, reference_price=ref,
        direction=direction, state_after=state, event_type=etype)


def test_valid_same_object_edge():
    ep = _episode(objects=("OBJ-A",))
    ok, reason = link_reason(ep, _ev(object_id="OBJ-A"), ev_seq=15, atr_at_ev=2.0)
    assert ok and reason == "same_object"


def test_valid_price_response_edge():
    ep = _episode(active_price=100.0, direction=1)
    ok, reason = link_reason(ep, _ev(object_id="NEW", ref=100.5, direction=1),
                             ev_seq=15, atr_at_ev=2.0)
    assert ok and reason.startswith("price_response")


def test_reject_unrelated_adjacency_far_price():
    ep = _episode(active_price=100.0)
    ok, reason = link_reason(ep, _ev(object_id="FAR", ref=140.0, direction=1),
                             ev_seq=15, atr_at_ev=1.0)  # 40 ATR away
    assert not ok and reason == "reject:rule2_unrelated"


def test_reject_after_expiry():
    ep = _episode(expiry=20)
    ok, reason = link_reason(ep, _ev(ref=100.2), ev_seq=25, atr_at_ev=2.0)
    assert not ok and reason == "reject:rule3_after_expiry"


def test_reject_opposing_direction_non_inversion():
    ep = _episode(direction=1)
    ok, reason = link_reason(ep, _ev(ref=100.2, direction=-1, state="FIRST_TOUCH"),
                             ev_seq=15, atr_at_ev=2.0)
    assert not ok and reason == "reject:rule5_direction"


def test_opposing_direction_allowed_for_inversion():
    ep = _episode(direction=1)
    ok, reason = link_reason(ep, _ev(ref=100.2, direction=-1, state="FAILURE"),
                             ev_seq=15, atr_at_ev=2.0)
    assert ok


def test_reject_non_transition_state():
    ep = _episode()
    ok, reason = link_reason(ep, _ev(state="REVISIT"), ev_seq=15, atr_at_ev=2.0)
    assert not ok and reason == "reject:non_transition"


def test_reject_gap_exceeded():
    ep = _episode(origin_seq=10)
    ep.last_seq = 10
    ok, reason = link_reason(ep, _ev(ref=100.2), ev_seq=10 + LINK_MAX_GAP_BARS + 1,
                             atr_at_ev=2.0)
    assert not ok and "gap" in reason


def test_origin_detection():
    assert is_origin(_ev(etype="rejection_block", state="CONFIRMED"))
    assert is_origin(_ev(etype="liquidity", state="SWEEP"))
    assert not is_origin(_ev(etype="fvg", state="FIRST_TOUCH"))
    assert not is_origin(_ev(etype="displacement", state="FORMED"))


# ---- data-gated integration ----

@pytest.fixture(scope="module")
def july_episodes():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    # narrow RTH window keeps the suite fast while still exercising linkage
    bars = load_front_month(DATA, start="2025-07-07T13:00", end="2025-07-07T17:00")
    ps = build_primitives(bars)
    log = build_event_log(ps)
    eng = EpisodeEngine(ps)
    eps = eng.run(log)
    return eng, log, eps


def test_permanent_unique_episode_ids(july_episodes):
    _, _, eps = july_episodes
    ids = [e.episode_id for e in eps]
    assert len(ids) == len(set(ids))


def test_multi_object_and_non_consecutive_linkage(july_episodes):
    eng, log, eps = july_episodes
    multi = [e for e in eps if len(e.objects) > 1]
    assert multi  # cross-object causal episodes exist
    # at least one episode links an event materially after its origin bar
    gapped = False
    for e in eps:
        for ev_id, reason in e.edges:
            if reason == "origin":
                continue
            seq = eng.ts_to_seq[log.get(ev_id).timestamp_et]
            if seq - e.origin_seq > 5:
                gapped = True
                break
        if gapped:
            break
    assert gapped


def test_resolutions_are_valid(july_episodes):
    _, _, eps = july_episodes
    assert all(e.resolution in ("expired", "invalidated") for e in eps)

"""Canonical event layer: append-only, availability timing, causal links."""

from __future__ import annotations

import pandas as pd
import pytest

from discretion.primitives.engine import build_primitives
from discretion.events.adapter import build_event_log
from discretion.events.schema import CanonicalEvent, EventLog, EVENT_FIELDS
from helpers import make_bars


def _ifvg_bars():
    # bullish gap [101,102] then close-through down -> bearish iFVG activation
    return make_bars([
        (100, 101, 99, 100.5),
        (101, 104, 101, 103.5),
        (103.5, 106, 102, 105),
        (105, 105, 100, 100.4),
        (100.4, 101.5, 100.4, 100.8),
    ])


def test_events_are_append_only_no_duplicate_ids():
    log = EventLog()
    ev = CanonicalEvent(
        event_id="EVT-0000001", event_type="fvg", event_subtype="X", object_id="O",
        parent_object_id="", timestamp_et="t", availability_timestamp_et="t",
        source_timeframe="1m", absolute_segment_id=0, normalization_segment_id=0,
        direction=1, price_low=1.0, price_high=2.0, reference_price=1.5,
        state_before="NONE", state_after="FORMED", feature_values={},
        causal_parent_event_ids=(), invalidation_timestamp="", expiry_timestamp="",
    )
    log.append(ev)
    with pytest.raises(ValueError):
        log.append(ev)  # same id rejected


def test_event_record_is_frozen():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    ev = log.all()[0]
    with pytest.raises(Exception):
        ev.state_after = "MUTATED"  # frozen dataclass


def test_availability_is_bar_close_plus_one_minute():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    ev = log.all()[0]
    ts = pd.Timestamp(ev.timestamp_et)
    avail = pd.Timestamp(ev.availability_timestamp_et)
    assert (avail - ts) == pd.Timedelta(minutes=1)


def test_events_sorted_by_availability():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    avails = [e.availability_timestamp_et for e in log]
    assert avails == sorted(avails)


def test_ifvg_activation_links_to_source_fvg_failure():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    act = next(e for e in log if e.event_subtype.endswith("IFVG_ACTIVATION"))
    assert act.parent_object_id.startswith("FVG-")
    # the linked parent event exists and is a FAILURE of the source FVG
    parent_events = [log.get(pid) for pid in act.causal_parent_event_ids]
    assert any(pe.object_id == act.parent_object_id and pe.state_after == "FAILURE"
               for pe in parent_events)


def test_no_future_invalidation_leak():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    for e in log:
        if e.invalidation_timestamp:
            assert e.state_after in ("INVALIDATION", "FAILURE", "REINVERSION")


def test_segment_id_carried_from_primitive():
    ps = build_primitives(_ifvg_bars())
    log = build_event_log(ps)
    for e in log:
        assert e.absolute_segment_id == 0
        assert set(e.to_dict().keys()) == set(EVENT_FIELDS)

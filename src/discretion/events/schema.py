"""Canonical append-only event record + immutable event log.

A ``CanonicalEvent`` is the single typed unit the episode layer consumes. It is
frozen: a later state change on the same object emits a *new* event, never a
mutation of an earlier one. ``availability_timestamp_et`` (bar close) is the only
time the recognizer may treat the event as knowable — zero lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

DETECTOR_VERSION = "src_discretion@v1"

# Canonical field order (also the schema/CSV column order).
EVENT_FIELDS = [
    "event_id", "event_type", "event_subtype", "object_id", "parent_object_id",
    "timestamp_et", "availability_timestamp_et", "source_timeframe",
    "absolute_segment_id", "normalization_segment_id", "direction",
    "price_low", "price_high", "reference_price", "state_before", "state_after",
    "feature_values", "causal_parent_event_ids", "invalidation_timestamp",
    "expiry_timestamp", "source_detector_version",
]


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    event_type: str            # primitive family, e.g. "fvg"
    event_subtype: str         # canonical token, e.g. "BULLISH_FVG_FORMED"
    object_id: str             # permanent primitive id
    parent_object_id: str      # source object id, "" if none
    timestamp_et: str          # ET open of the producing bar
    availability_timestamp_et: str  # bar close = knowable time (+1 min)
    source_timeframe: str
    absolute_segment_id: int
    normalization_segment_id: int
    direction: int             # +1/-1/0
    price_low: float
    price_high: float
    reference_price: float
    state_before: str
    state_after: str
    feature_values: dict
    causal_parent_event_ids: tuple
    invalidation_timestamp: str
    expiry_timestamp: str
    source_detector_version: str = DETECTOR_VERSION

    @property
    def seq_key(self):
        return self.availability_timestamp_et

    def to_dict(self) -> dict:
        d = asdict(self)
        d["causal_parent_event_ids"] = list(self.causal_parent_event_ids)
        return d


class EventLog:
    """Append-only, ordered store of canonical events. No mutation or deletion."""

    def __init__(self) -> None:
        self._events: list[CanonicalEvent] = []
        self._by_id: dict[str, CanonicalEvent] = {}

    def append(self, ev: CanonicalEvent) -> None:
        if ev.event_id in self._by_id:
            raise ValueError(f"duplicate event_id {ev.event_id}")
        self._events.append(ev)
        self._by_id[ev.event_id] = ev

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self):
        return iter(self._events)

    def get(self, event_id: str) -> CanonicalEvent:
        return self._by_id[event_id]

    def all(self) -> list[CanonicalEvent]:
        return list(self._events)

    def by_type(self, event_type: str) -> list[CanonicalEvent]:
        return [e for e in self._events if e.event_type == event_type]

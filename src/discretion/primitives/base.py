"""Primitive base classes, permanent-ID registry, shared interaction vocabulary.

Every primitive occurrence gets a permanent, never-reused id from an
:class:`IdRegistry`. Occurrences are never deleted once created (losing,
expired, ambiguous and invalidated ones are retained), matching the study's
audit requirements. IDs are deterministic for a given chronological pass over
the data, so runs are reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class IdRegistry:
    """Assigns and retains permanent ids, one monotonic counter per family.

    ``FVG-000001``, ``FVG-000002``, ... never reused, never deleted.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._all: dict[str, object] = {}

    def new_id(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{n:06d}"

    def register(self, obj: "Primitive") -> None:
        if obj.id in self._all:
            raise ValueError(f"duplicate primitive id {obj.id}")
        self._all[obj.id] = obj

    def get(self, pid: str) -> object:
        return self._all[pid]

    def all(self) -> list["Primitive"]:
        return list(self._all.values())

    def by_family(self, family: str) -> list["Primitive"]:
        return [o for o in self._all.values() if o.family == family]


# Canonical interaction-event vocabulary shared across primitive families.
# These are *deterministic states*, each stamped with the bar seq at which the
# event became knowable (i.e. the completed bar that produced it).
INTERACTION_EVENTS = {
    "FORMED",
    "CONFIRMED",
    "FIRST_TOUCH",
    "EXACT_TOUCH",
    "FIRST_FILL",
    "MIDPOINT",  # consequent encroachment / 50%
    "FULL_FILL",
    "REVISIT",
    "SWEEP",
    "BREAK",
    "RECLAIM",
    "REJECTION",
    "ACCEPTANCE_ABOVE",
    "ACCEPTANCE_BELOW",
    "CONTINUATION",
    "FAILED_CONTINUATION",
    "INVALIDATION",
    "FAILURE",
    "REINVERSION",
    "COMPRESSION",
    "EXPANSION",
    "EXPIRY",
}


@dataclass
class Event:
    """One interaction event on a primitive, stamped with when it was knowable."""

    kind: str
    seq: int          # bar index (within segment) at which this became knowable
    ts_utc: object
    price: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in INTERACTION_EVENTS:
            raise ValueError(f"unknown interaction event {self.kind!r}")


@dataclass
class Primitive:
    """Base for all deterministic market primitives.

    Subclasses set ``family`` and add their own geometry. Zones use lo/hi;
    horizontal levels set lo==hi==price.
    """

    id: str
    family: str
    subtype: str          # e.g. "bullish", "bearish", "midnight_open"
    segment_id: int
    created_seq: int      # bar seq at which the primitive became knowable
    created_ts: object
    lo: float
    hi: float
    events: list[Event] = field(default_factory=list)
    invalidated_seq: int | None = None
    active: bool = True

    @property
    def price(self) -> float:
        """Representative price (midpoint for zones, the level for lines)."""
        return (self.lo + self.hi) / 2.0

    @property
    def is_zone(self) -> bool:
        return self.hi > self.lo

    def add_event(self, kind: str, seq: int, ts_utc, price=None, note="") -> Event:
        ev = Event(kind=kind, seq=seq, ts_utc=ts_utc, price=price, note=note)
        self.events.append(ev)
        return ev

    def has_event(self, kind: str) -> bool:
        return any(e.kind == kind for e in self.events)

    def first_event(self, kind: str) -> Event | None:
        for e in self.events:
            if e.kind == kind:
                return e
        return None

    def event_kinds(self) -> list[str]:
        return [e.kind for e in self.events]

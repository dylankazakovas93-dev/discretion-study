"""Causal episode state engine.

Consumes availability-ordered canonical events and groups them into episodes,
each anchored to one origin object/state. Events join via explicit causal edges
(see linking.py); the permitting reason is stored. Episodes may span
non-consecutive candles, expire at a session boundary (unless the origin is a
cross-session structural object), and resolve when their origin object is
invalidated. Permanent, deterministic episode ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .linking import link_reason, LINK_MAX_GAP_BARS

EPISODE_MAX_AGE_BARS = 240
SESSION_RESET_ET = (18, 0)
MAX_EPISODE_EVENTS = 16  # saturate an episode past this many linked transitions

# Which event states may open a new episode, per family. Displacement is a
# transition only (it links into episodes, it does not originate one).
ORIGIN_STATES = {
    "fvg": {"FORMED"},
    "ifvg": {"CONFIRMED"},
    "rejection_block": {"CONFIRMED"},
    "structure": {"COMPRESSION", "EXPANSION"},
    "time_anchor": {"FIRST_TOUCH", "SWEEP", "BREAK", "RECLAIM", "REJECTION"},
    "hist_level": {"SWEEP", "BREAK", "RECLAIM"},
    "liquidity": {"SWEEP"},
    "vwap": {"REJECTION", "RECLAIM", "BREAK"},
}


def is_origin(ev) -> bool:
    return ev.state_after in ORIGIN_STATES.get(ev.event_type, set())


@dataclass
class Episode:
    episode_id: str
    origin_object_id: str
    origin_event_id: str
    origin_family: str
    origin_subtype: str
    start_timestamp: str
    directional_context: int
    segment_id: int
    origin_seq: int
    episode_expiry: int
    active_price: float
    last_seq: int
    active_branch_ids: list = field(default_factory=list)
    primitive_event_ids: list = field(default_factory=list)
    current_object_states: dict = field(default_factory=dict)
    objects: set = field(default_factory=set)
    seen: set = field(default_factory=set)      # (object_id, state) dedup
    edges: list = field(default_factory=list)   # (event_id, reason)
    resolved_timestamp: str | None = None
    resolved_seq: int | None = None
    resolution: str | None = None               # invalidated | expired | None
    episode_version: int = 1

    def add_event(self, ev, seq, reason):
        self.primitive_event_ids.append(ev.event_id)
        self.objects.add(ev.object_id)
        self.seen.add((ev.object_id, ev.state_after))
        self.current_object_states[ev.object_id] = ev.state_after
        self.edges.append((ev.event_id, reason))
        self.active_price = ev.reference_price
        self.last_seq = seq
        self.episode_version += 1

    def can_accept(self, ev) -> bool:
        return (len(self.primitive_event_ids) < MAX_EPISODE_EVENTS
                and (ev.object_id, ev.state_after) not in self.seen)

    def resolve(self, kind, seq, ts):
        if self.resolution is None:
            self.resolution = kind
            self.resolved_seq = seq
            self.resolved_timestamp = ts


def _session_end_by_seq(bars) -> list[int]:
    """Last seq of the CME session (18:00 ET boundary) containing each bar."""
    def key(b):
        t = (b.ts_et.hour, b.ts_et.minute)
        d = b.ts_et.date()
        return (d, "next") if t >= SESSION_RESET_ET else (d, "same"), b.segment_id
    ends = [0] * len(bars)
    start = 0
    for i in range(1, len(bars) + 1):
        if i == len(bars) or key(bars[i]) != key(bars[start]):
            for j in range(start, i):
                ends[j] = i - 1
            start = i
    return ends


class EpisodeEngine:
    def __init__(self, ps):
        self.ps = ps
        self.bars = ps.bars
        self.atr = ps.atr
        self.ts_to_seq = {str(b.ts_et): i for i, b in enumerate(self.bars)}
        self.session_end = _session_end_by_seq(self.bars)
        self.seg_last = {}
        for i, b in enumerate(self.bars):
            self.seg_last[b.segment_id] = i
        self._n = 0

    def _expiry(self, ev, seq) -> int:
        base = seq + EPISODE_MAX_AGE_BARS
        seg_end = self.seg_last[ev.absolute_segment_id]
        cross_session = ev.event_type == "hist_level" and "PREV_" in ev.event_subtype
        if cross_session:
            return min(base, seg_end)
        return min(base, self.session_end[seq], seg_end)

    def run(self, log) -> list[Episode]:
        episodes: list[Episode] = []
        active: list[Episode] = []

        for ev in log:
            seq = self.ts_to_seq[ev.timestamp_et]
            atr_at = self.atr[seq] if seq < len(self.atr) else None

            # prune: expire episodes past their expiry or reach gap
            still = []
            for ep in active:
                if ep.resolution is not None:
                    continue
                if seq >= ep.episode_expiry:
                    ep.resolve("expired", ep.episode_expiry,
                               str(self.bars[min(ep.episode_expiry,
                                                 len(self.bars) - 1)].ts_et))
                    continue
                if seq - ep.last_seq > LINK_MAX_GAP_BARS:
                    ep.resolve("expired", ep.last_seq,
                               str(self.bars[ep.last_seq].ts_et))
                    continue
                still.append(ep)
            active = still

            # link to the single most price-proximate accepting episode
            best = None
            best_reason = None
            best_dist = float("inf")
            for ep in active:
                if ep.segment_id != ev.absolute_segment_id:
                    continue
                if not ep.can_accept(ev):
                    continue
                ok, reason = link_reason(ep, ev, seq, atr_at)
                if ok:
                    dist = abs(ev.reference_price - ep.active_price)
                    if dist < best_dist:
                        best, best_reason, best_dist = ep, reason, dist
            if best is not None:
                best.add_event(ev, seq, best_reason)
                # origin-object invalidation resolves the episode
                if (ev.object_id == best.origin_object_id
                        and ev.state_after in ("INVALIDATION", "REINVERSION")):
                    best.resolve("invalidated", seq, str(self.bars[seq].ts_et))

            # spawn a new episode when this event is an origin
            if is_origin(ev):
                self._n += 1
                ep = Episode(
                    episode_id=f"EP-{self._n:06d}",
                    origin_object_id=ev.object_id,
                    origin_event_id=ev.event_id,
                    origin_family=ev.event_type,
                    origin_subtype=ev.event_subtype,
                    start_timestamp=ev.timestamp_et,
                    directional_context=ev.direction,
                    segment_id=ev.absolute_segment_id,
                    origin_seq=seq,
                    episode_expiry=self._expiry(ev, seq),
                    active_price=ev.reference_price,
                    last_seq=seq,
                )
                ep.primitive_event_ids.append(ev.event_id)
                ep.objects.add(ev.object_id)
                ep.current_object_states[ev.object_id] = ev.state_after
                ep.edges.append((ev.event_id, "origin"))
                episodes.append(ep)
                active.append(ep)

        # close any still-open episodes at data end
        for ep in active:
            if ep.resolution is None:
                ep.resolve("expired", ep.last_seq, str(self.bars[ep.last_seq].ts_et))
        return episodes

"""Multi-branch episode engine.

Consumes availability-ordered canonical events. Each origin event opens an
Episode owning a set of hypothesis BranchStates (from the transition registry).
Every later event is evaluated against every active causally-compatible branch:
it may advance one, invalidate another, and reach an emit stage on a third —
recording a trigger state the materializer will turn into a candidate.

Growth is bounded without reference to outcomes: signature dedup, equivalent-state
merge, expiry, stage max-delay, inactivity and origin-object invalidation.
Branches are append-only records — terminal branches are retained, never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .relationships import RelCtx, evaluate, has_structural_edge, RejectionCounter
from .transitions import hypotheses_for_family, stage_matches, spawn_states
from ..events.adapter import build_event_log

MAX_INACTIVE_BARS = 120
SESSION_RESET_ET = (18, 0)
INVALIDATION_STATES = {"INVALIDATION", "REINVERSION"}


@dataclass
class BranchState:
    branch_id: str
    episode_id: str
    parent_branch_id: str | None
    branch_version: int
    origin_event_id: str
    origin_object_id: str
    hypothesis_id: str
    hypothesis_direction: int
    continuation_or_fade: str
    current_state: str
    ordered_event_ids: list
    ordered_transition_ids: list
    exact_graph_so_far: list
    current_structural_objects: list
    current_directional_state: int
    created_at: str
    last_advanced_at: str
    expiry: int
    invalidation_conditions: list
    unresolved_conditions: list
    emitted_candidate_ids: list
    terminal_status: str | None       # None (active) | EMITTED | INVALIDATED | EXPIRED | UNRESOLVED
    terminal_reason: str | None
    # runtime
    hypothesis: object = None
    stage_index: int = 0
    focus_object_id: str = ""
    origin_seq: int = 0
    last_advanced_seq: int = 0
    segment_id: int = 0

    @property
    def active(self) -> bool:
        return self.terminal_status is None

    def signature(self):
        return (self.hypothesis_id, self.focus_object_id, self.stage_index,
                tuple(self.ordered_event_ids))


@dataclass
class Episode:
    episode_id: str
    origin_event_id: str
    origin_object_id: str
    origin_family: str
    origin_subtype: str
    start_timestamp: str
    segment_id: int
    branch_ids: list = field(default_factory=list)


@dataclass
class TriggerState:
    trigger_id: str
    branch_id: str
    episode_id: str
    origin_event_id: str
    trigger_event_id: str
    hypothesis_id: str
    continuation_or_fade: str
    entry_mode: str
    trigger_family: str
    dir_rule: object
    focus_object_id: str
    ordered_event_ids: tuple
    ordered_transition_ids: tuple
    relationship_evidence: tuple
    seq: int


def _session_end_by_seq(bars):
    def key(b):
        t = (b.ts_et.hour, b.ts_et.minute)
        return ((b.ts_et.date(), 1) if t >= SESSION_RESET_ET
                else (b.ts_et.date(), 0)), b.segment_id
    ends = [0] * len(bars)
    start = 0
    for i in range(1, len(bars) + 1):
        if i == len(bars) or key(bars[i]) != key(bars[start]):
            for j in range(start, i):
                ends[j] = i - 1
            start = i
    return ends


class BranchEngine:
    def __init__(self, ps):
        self.ps = ps
        self.reg = ps.registry
        self.bars = ps.bars
        self.atr = ps.atr
        self.ts_to_seq = {str(b.ts_et): i for i, b in enumerate(self.bars)}
        self.session_end = _session_end_by_seq(self.bars)
        self._n_ep = 0
        self._n_br = 0
        self._n_trig = 0
        self.rejections = RejectionCounter()

    def _origin_dir(self, ev, dir_from_origin):
        base = ev.direction
        if base == 0:
            obj = self._obj(ev.object_id)
            base = getattr(obj, "direction", 0) if obj else 0
        if dir_from_origin in (1, -1):
            return base * dir_from_origin if base else 0
        return 0  # FROM_EVENT / FROM_SUBTYPE resolved at emit

    def _obj(self, oid):
        try:
            return self.reg.get(oid)
        except Exception:
            return None

    def _expiry(self, seq):
        return min(self.session_end[seq], seq + 240)

    def run(self, log=None):
        if log is None:
            log = build_event_log(self.ps)
        episodes: dict[str, Episode] = {}
        branches: list[BranchState] = []
        triggers: list[TriggerState] = []
        spawned: set = set()

        # active indices
        keyed: dict[str, list[BranchState]] = {}   # focus_object_id -> branches
        wildcard: list[BranchState] = []
        active_sigs: set = set()

        def stage_keyed(branch):
            st = branch.hypothesis.stages[branch.stage_index]
            return "SAME_OBJECT" in st.rels or "PARENT_CHILD_OBJECT" in st.rels \
                or "IFVG_CREATED_FROM_PARENT_FVG" in st.rels

        def index_branch(b):
            if not b.active:
                return
            if b.signature() in active_sigs:
                return  # equivalent-state merge
            active_sigs.add(b.signature())
            if stage_keyed(b):
                keyed.setdefault(b.focus_object_id, []).append(b)
            else:
                wildcard.append(b)

        def try_event_on_branch(b, ev, seq):
            if not b.active:
                return
            obj = self._obj(b.focus_object_id)
            ctx = RelCtx(atr=self.atr[seq] if seq < len(self.atr) else None,
                         ev_seq=seq, branch_dir=b.hypothesis_direction or b.current_directional_state,
                         branch_last_seq=b.last_advanced_seq, reg=self.reg)
            satisfied = evaluate(obj, ev, ctx)
            # origin-object invalidation
            if ev.object_id == b.origin_object_id and ev.state_after in INVALIDATION_STATES:
                b.terminal_status, b.terminal_reason = "INVALIDATED", "origin_invalidated"
                return
            if not has_structural_edge(satisfied):
                # opposing strong move can still invalidate a continuation branch
                if (b.continuation_or_fade == "continuation" and b.stage_index > 0
                        and "DIRECTIONALLY_INVALIDATES" in satisfied):
                    b.terminal_status, b.terminal_reason = "INVALIDATED", "opposing_move"
                else:
                    self.rejections.add("no_structural_edge")
                return
            stage = b.hypothesis.stages[b.stage_index]
            delay = seq - b.last_advanced_seq
            if not stage_matches(stage, ev, satisfied, delay, b.hypothesis_direction):
                if "DIRECTIONALLY_INVALIDATES" in satisfied and b.continuation_or_fade == "continuation":
                    b.terminal_status, b.terminal_reason = "INVALIDATED", "opposing_move"
                else:
                    self.rejections.add("stage_no_match")
                return
            # matched -> record and act (avoid re-recording an immediate origin=trigger)
            if not b.ordered_event_ids or b.ordered_event_ids[-1] != ev.event_id:
                b.ordered_event_ids.append(ev.event_id)
                b.exact_graph_so_far.append(ev.event_subtype)
            b.ordered_transition_ids.append(f"{b.hypothesis_id}:S{b.stage_index}")
            b.branch_version += 1
            b.last_advanced_at = ev.availability_timestamp_et
            b.last_advanced_seq = seq
            if stage.updates_focus and ev.object_id:
                b.focus_object_id = ev.object_id
                if ev.object_id not in b.current_structural_objects:
                    b.current_structural_objects.append(ev.object_id)
            rel_ev = tuple(sorted(satisfied))
            if stage.kind == "emit":
                self._n_trig += 1
                tid = f"TRG-{self._n_trig:06d}"
                triggers.append(TriggerState(
                    trigger_id=tid, branch_id=b.branch_id, episode_id=b.episode_id,
                    origin_event_id=b.origin_event_id, trigger_event_id=ev.event_id,
                    hypothesis_id=b.hypothesis_id, continuation_or_fade=b.continuation_or_fade,
                    entry_mode=stage.entry_mode, trigger_family=stage.trigger_family,
                    dir_rule=b.hypothesis.dir_from_origin, focus_object_id=b.focus_object_id,
                    ordered_event_ids=tuple(b.ordered_event_ids),
                    ordered_transition_ids=tuple(b.ordered_transition_ids),
                    relationship_evidence=rel_ev, seq=seq))
                b.terminal_status, b.terminal_reason = "EMITTED", stage.trigger_family
                b.current_state = f"{b.hypothesis_id}@EMITTED"
            else:
                b.stage_index += 1
                b.current_state = f"{b.hypothesis_id}@{b.stage_index}"

        for ev in log:
            seq = self.ts_to_seq[ev.timestamp_et]
            # prune (expiry / inactivity / stage delay) -> mark EXPIRED/UNRESOLVED
            def prune(lst):
                keep = []
                for b in lst:
                    if not b.active:
                        continue
                    if seq >= b.expiry or (seq - b.last_advanced_seq) > MAX_INACTIVE_BARS:
                        b.terminal_status = "EXPIRED" if b.stage_index == 0 else "UNRESOLVED"
                        b.terminal_reason = "expiry" if seq >= b.expiry else "inactive"
                        continue
                    keep.append(b)
                return keep
            wildcard = prune(wildcard)
            for k in list(keyed):
                keyed[k] = prune(keyed[k])
                if not keyed[k]:
                    del keyed[k]

            # advance matching active branches (keyed on this event's object + parent)
            targets = []
            targets += keyed.get(ev.object_id, [])
            if ev.parent_object_id:
                targets += keyed.get(ev.parent_object_id, [])
            targets += [b for b in wildcard if b.segment_id == ev.absolute_segment_id]
            for b in list(targets):
                try_event_on_branch(b, ev, seq)

            # rebuild indices from still-active branches touched this step is costly;
            # instead lazily drop terminals on next prune and re-key advanced branches
            # (advanced branches may have changed focus/stage -> re-index)
            for b in list(targets):
                if b.active:
                    # ensure it is indexed under its (possibly new) key
                    if stage_keyed(b):
                        lst = keyed.setdefault(b.focus_object_id, [])
                        if b not in lst:
                            lst.append(b)
                    elif b not in wildcard:
                        wildcard.append(b)

            # spawn new hypotheses if this is an origin event
            hyps = hypotheses_for_family(ev.event_type)
            for h in hyps:
                if ev.state_after not in spawn_states(h):
                    continue   # this event does not open this hypothesis
                if (h.hypothesis_id, ev.object_id) in spawned:
                    continue
                s0 = h.stages[0]
                # spawn only if the first stage can plausibly start here
                if s0.immediate:
                    # immediate hypotheses must match the origin event now
                    ctx = RelCtx(atr=self.atr[seq] if seq < len(self.atr) else None,
                                 ev_seq=seq, branch_dir=self._origin_dir(ev, h.dir_from_origin),
                                 branch_last_seq=seq, reg=self.reg)
                    sat = evaluate(self._obj(ev.object_id), ev, ctx)
                    if not (has_structural_edge(sat) and stage_matches(s0, ev, sat, 0,
                            self._origin_dir(ev, h.dir_from_origin))):
                        continue
                spawned.add((h.hypothesis_id, ev.object_id))
                self._n_br += 1
                if ev.object_id not in episodes:
                    self._n_ep += 1
                    ep = Episode(
                        episode_id=f"GEP-{self._n_ep:06d}", origin_event_id=ev.event_id,
                        origin_object_id=ev.object_id, origin_family=ev.event_type,
                        origin_subtype=ev.event_subtype,
                        start_timestamp=ev.timestamp_et, segment_id=ev.absolute_segment_id)
                    episodes[ev.object_id] = ep
                ep = episodes[ev.object_id]
                b = BranchState(
                    branch_id=f"GBR-{self._n_br:06d}", episode_id=ep.episode_id,
                    parent_branch_id=None, branch_version=1,
                    origin_event_id=ev.event_id, origin_object_id=ev.object_id,
                    hypothesis_id=h.hypothesis_id,
                    hypothesis_direction=self._origin_dir(ev, h.dir_from_origin),
                    continuation_or_fade=h.cont_or_fade,
                    current_state=f"{h.hypothesis_id}@0",
                    ordered_event_ids=[ev.event_id], ordered_transition_ids=[],
                    exact_graph_so_far=[ev.event_subtype],
                    current_structural_objects=[ev.object_id],
                    current_directional_state=self._origin_dir(ev, h.dir_from_origin),
                    created_at=ev.availability_timestamp_et,
                    last_advanced_at=ev.availability_timestamp_et,
                    expiry=self._expiry(seq), invalidation_conditions=[],
                    unresolved_conditions=[], emitted_candidate_ids=[],
                    terminal_status=None, terminal_reason=None,
                    hypothesis=h, stage_index=0, focus_object_id=ev.object_id,
                    origin_seq=seq, last_advanced_seq=seq,
                    segment_id=ev.absolute_segment_id)
                ep.branch_ids.append(b.branch_id)
                branches.append(b)
                if s0.immediate:
                    try_event_on_branch(b, ev, seq)   # emit now
                if b.active:
                    index_branch(b)

        # close out remaining active branches
        for b in branches:
            if b.active:
                b.terminal_status = "UNRESOLVED" if b.stage_index > 0 else "EXPIRED"
                b.terminal_reason = "data_end"
        return {"episodes": list(episodes.values()), "branches": branches,
                "triggers": triggers, "log": log, "engine": self,
                "rejections": dict(self.rejections.counts)}

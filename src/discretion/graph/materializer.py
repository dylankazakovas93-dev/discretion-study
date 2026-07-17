"""Graph-native candidate materializer.

Consumes a completed branch TriggerState and freezes a candidate: direction,
entry, structural stop, structural target, expiry and RR — all chosen from the
branch state, never by calling build_setups and never by peeking at future bars.
It reuses only generic utilities: the frozen RR policy (apply_rr_policy), nearest
structural-level helpers, and the causal feature builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from ..setups.model import Setup, apply_rr_policy
from ..setups.structural import nearest_level_above, nearest_level_below, STOP_BUFFER
from ..representations.signatures import FeatureContext, build_features, reduce_graph

EXPIRY_BARS = 120


@dataclass
class GraphNativeCandidate:
    candidate_id: str
    source_branch_id: str
    source_episode_id: str
    trigger_event_id: str
    exact_graph: str
    reduced_graph: str
    ordered_event_ids: tuple
    ordered_transition_ids: tuple
    relationship_evidence: tuple
    direction: str
    entry_mode: str
    setup: object                 # Setup: frozen entry/stop/target/RR + outcome
    features: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)     # Phase 6
    qualification: str = "UNSCORED"                  # Phase 6
    # FVG->iFVG lineage (empty for non-iFVG candidates)
    parent_fvg_id: str = ""
    fvg_formation_event_id: str = ""
    fvg_failure_event_id: str = ""
    ifvg_confirmation_event_id: str = ""
    retest_event_id: str = ""
    # convenience mirrors
    session_ord: int | None = None
    completion_ord: int | None = None
    realized_r: float | None = None


def _dir_from_subtype(sub: str) -> int:
    if any(t in sub for t in ("_ABOVE", "_UP", "BULLISH")):
        return 1
    if any(t in sub for t in ("_BELOW", "_DOWN", "BEARISH")):
        return -1
    return 0


def resolve_direction(trigger, branch, trig_ev, focus, bar) -> int:
    fam = trigger.trigger_family
    d = branch.hypothesis_direction
    if d:
        return d
    # acceptance-based continuation reads the acceptance side
    if trig_ev.state_after == "ACCEPTANCE_ABOVE":
        return 1
    if trig_ev.state_after == "ACCEPTANCE_BELOW":
        return -1
    if fam == "vwap_band_fade":
        # upper-band reject -> short; lower-band reject -> long
        return -1 if "REJECT_P" in trig_ev.event_subtype else 1
    sub_dir = _dir_from_subtype(trig_ev.event_subtype)
    if sub_dir:
        return sub_dir
    if trig_ev.direction:
        return trig_ev.direction
    # last resort: side of the trigger close vs the focus reference
    ref = focus.price if focus is not None else bar.close
    side = 1 if bar.close >= ref else -1
    return -side if trigger.continuation_or_fade == "fade" else side


class Materializer:
    def __init__(self, ps):
        self.ps = ps
        self.reg = ps.registry
        self.bars = ps.bars
        self.levels = ps.all_levels
        self.fctx = FeatureContext(ps)
        self._n = 0
        self.seg_last = {}
        for i, b in enumerate(self.bars):
            self.seg_last[b.segment_id] = i

    def _entry(self, entry_mode, seq, trig_ev):
        if entry_mode in ("formation_close", "no_fill_continuation"):
            return seq, self.bars[seq].close
        if entry_mode == "next_bar":
            nb = seq + 1
            if nb <= self.seg_last[self.bars[seq].segment_id]:
                return nb, self.bars[nb].open
            return seq, self.bars[seq].close
        # touch/fill/midpoint/full_fill/retest -> the event's structural price
        return seq, trig_ev.reference_price

    def materialize(self, trigger, branch, log):
        trig_ev = log.get(trigger.trigger_event_id)
        seq0 = self._seq(trig_ev)
        focus = self._obj(trigger.focus_object_id)
        origin = self._obj(branch.origin_object_id)
        bar0 = self.bars[seq0]
        direction = resolve_direction(trigger, branch, trig_ev, focus, bar0)
        if direction == 0:
            return None, "UNRESOLVED_DIRECTION"

        entry_seq, entry_price = self._entry(trigger.entry_mode, seq0, trig_ev)
        seg = self.bars[entry_seq].segment_id
        # structural stop: object boundary or the trigger-bar extreme (frozen)
        flo = focus.lo if focus is not None else entry_price
        fhi = focus.hi if focus is not None else entry_price
        if direction > 0:
            stop = min(flo, bar0.low) - STOP_BUFFER
            tlvl = nearest_level_above(entry_price, entry_seq, seg, self.levels)
        else:
            stop = max(fhi, bar0.high) + STOP_BUFFER
            tlvl = nearest_level_below(entry_price, entry_seq, seg, self.levels)
        if tlvl is None:
            return None, "NO_STRUCTURAL_TARGET"
        target = tlvl.price_ref

        self._n += 1
        cid = f"GNC-{self._n:06d}"
        subtypes = [log.get(e).event_subtype for e in trigger.ordered_event_ids]
        trig_tok = f"{trigger.entry_mode.upper()}_{'LONG' if direction>0 else 'SHORT'}_TRIGGER"
        exact = " -> ".join(subtypes + [trig_tok])
        prim_ids = []
        for e in trigger.ordered_event_ids:
            oid = log.get(e).object_id
            if oid not in prim_ids:
                prim_ids.append(oid)
        has_fvg = any(log.get(e).event_type == "fvg" for e in trigger.ordered_event_ids)
        has_ifvg = any(log.get(e).event_type == "ifvg" for e in trigger.ordered_event_ids)
        has_rb = any(log.get(e).event_type == "rejection_block" for e in trigger.ordered_event_ids)
        has_sweep = "SWEEP" in exact

        s = Setup(
            id=cid, direction="long" if direction > 0 else "short",
            path_family=trigger.trigger_family, graph=exact,
            entry_mode=trigger.entry_mode, origin_id=branch.origin_object_id,
            transition_ids=list(trigger.ordered_transition_ids),
            primitive_ids=prim_ids, context_conditions=list(trigger.relationship_evidence)[:3],
            entry_seq=entry_seq, entry_ts=self.bars[entry_seq].ts_utc,
            entry_price=float(entry_price), structural_stop=float(stop),
            structural_target=float(target),
            expiry_seq=min(entry_seq + EXPIRY_BARS, self.seg_last[seg]),
            expiry_rule=f"{EXPIRY_BARS}_bars_or_segment_end", segment_id=seg,
            has_fvg=has_fvg, has_ifvg=has_ifvg, has_rb=has_rb, has_sweep=has_sweep,
            continuation_or_fade=trigger.continuation_or_fade,
        )
        apply_rr_policy(s)
        feats = build_features(SimpleNamespace(setup=s), self.fctx)
        cand = GraphNativeCandidate(
            candidate_id=cid, source_branch_id=trigger.branch_id,
            source_episode_id=trigger.episode_id, trigger_event_id=trigger.trigger_event_id,
            exact_graph=exact, reduced_graph=reduce_graph(exact),
            ordered_event_ids=trigger.ordered_event_ids,
            ordered_transition_ids=trigger.ordered_transition_ids,
            relationship_evidence=trigger.relationship_evidence,
            direction=s.direction, entry_mode=trigger.entry_mode, setup=s, features=feats,
            parent_fvg_id=branch.parent_fvg_id,
            fvg_formation_event_id=branch.fvg_formation_event_id,
            fvg_failure_event_id=branch.fvg_failure_event_id,
            ifvg_confirmation_event_id=branch.ifvg_confirmation_event_id,
            retest_event_id=branch.retest_event_id)
        branch.emitted_candidate_ids.append(cid)
        reason = s.rejection_reason if s.rejected else None
        return cand, reason

    def _seq(self, ev):
        if not hasattr(self, "_smap"):
            self._smap = {str(b.ts_et): i for i, b in enumerate(self.bars)}
        return self._smap[ev.timestamp_et]

    def _obj(self, oid):
        try:
            return self.reg.get(oid)
        except Exception:
            return None


def materialize_all(result):
    """Materialize graph-native candidates from every trigger state.

    Returns dict with `candidates` (eligible, RR-valid), `rejected` (formed but
    <0.5R / wrong side), and `unformed_reasons` (could not form entry/target).
    """
    ps = result["engine"].ps
    log = result["log"]
    branch_by_id = {b.branch_id: b for b in result["branches"]}
    mat = Materializer(ps)
    candidates, rejected = [], []
    unformed = {}
    for trig in result["triggers"]:
        b = branch_by_id[trig.branch_id]
        cand, reason = mat.materialize(trig, b, log)
        if cand is None:
            unformed[reason] = unformed.get(reason, 0) + 1
            continue
        if cand.setup.eligible:
            candidates.append(cand)
        else:
            rejected.append(cand)
    result["graph_candidates"] = candidates
    result["graph_rejected"] = rejected
    result["unformed_reasons"] = unformed
    return result

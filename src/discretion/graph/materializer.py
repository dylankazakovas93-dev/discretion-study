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
from ..representations.signatures import FeatureContext, build_features, reduce_graph
from .anchors import resolve_anchors
from .targets import (TargetInventory, build_target_candidates, select_target,
                      TARGET_POLICIES)

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
    # branch-specific stop/target anchors
    stop_anchor_type: str = ""
    stop_anchor_object_id: str = ""
    stop_anchor_price: float = 0.0
    target_anchor_type: str = ""
    target_anchor_object_id: str = ""
    target_anchor_price: float = 0.0
    anchor_resolution_rule: str = ""
    # target-candidate universe + policy (Commit 5)
    target_policy_id: str = ""
    target_surface_policy: str = "PROXIMAL_EDGE"
    target_anchor_timeframe: object = None
    target_prominence_grade: str | None = None
    selected_target_rank: int = 0
    selection_rule_id: str = ""
    considered_targets: list = field(default_factory=list)
    # convenience mirrors
    session_ord: int | None = None
    completion_ord: int | None = None
    realized_r: float | None = None


def _target_row(t) -> dict:
    """Compact considered-target ledger row for the audit."""
    return {
        "object_id": t.object_id, "family": t.family, "subtype": t.subtype,
        "timeframe": t.timeframe, "surface": t.target_surface, "price": t.price,
        "available_seq": t.availability_seq, "fresh": t.fresh,
        "prominence": t.prominence_grade, "distance_atr": t.distance_atr,
        "natural_rr": t.natural_rr, "eligible": t.eligible,
        "frontmost": t.frontmost, "occluded_by": t.occluded_by_object_id,
        "rejection_reasons": list(t.rejection_reasons),
    }


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
    def __init__(self, ps, keep_considered_targets=True, ledger_sink=None):
        """``keep_considered_targets=False`` drops the (large, per-trigger)
        considered-target audit rows from each retained candidate instead of
        holding them live for the whole run -- a compact-record memory repair
        for large windows, not a semantics change: the same rows are still
        computed and, if ``ledger_sink`` is given, streamed to it (called as
        ``ledger_sink(trigger_event_id, rows)``) so the full audit ledger
        stays reproducible on disk. ``occluded_by_tf`` still accumulates the
        per-timeframe occlusion counts review_atlas needs, regardless of
        whether the rows themselves are retained in memory.
        """
        self.ps = ps
        self.reg = ps.registry
        self.bars = ps.bars
        self.levels = ps.all_levels
        self.fctx = FeatureContext(ps)
        self.inv = TargetInventory(ps)
        self._n = 0
        self.seg_last = {}
        for i, b in enumerate(self.bars):
            self.seg_last[b.segment_id] = i
        self.keep_considered_targets = keep_considered_targets
        self.ledger_sink = ledger_sink
        self.occluded_by_tf = {5: 0, 15: 0, 30: 0, 60: 0}
        # Different branches can share one trigger_event_id with genuinely
        # different considered-target ledgers (different origin -> different
        # branch-specific stop/entry); review_atlas's reference scan dedupes
        # by trigger_event_id over graph_candidates+graph_rejected (eligible-
        # first order), so on that rare ambiguity it can pick a different
        # branch's ledger than this tally (which dedupes in trigger-processing
        # order). Both are single well-defined rules; they can disagree by a
        # small amount on this purely descriptive count (objects_occluded_in_
        # considered_ledger in review_atlas's htf_inventory) only -- it is
        # never read by evidence/qualification/grading.
        self._occluded_tally_seen = set()

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
        # branch-specific STOP anchor (frozen, keyed by trigger family). The
        # branch objective (target_a) feeds only the BRANCH_SEMANTIC policy.
        vwap_val = focus.value_at(entry_seq) if (focus is not None
                                                 and focus.family == "vwap") else None
        stop_a, target_a, rule = resolve_anchors(
            trigger.trigger_family, direction, entry_price, entry_seq, seg,
            focus, origin, bar0, trig_ev, self.levels, vwap_val)
        if stop_a is None:
            return [], rule
        stop = stop_a["stop_anchor_price"]

        # ---- target-candidate universe at the trigger moment (causal) ----
        atr = self.ps.atr[entry_seq] or 0.0
        branch_target = None
        branch_obj_id = None
        if target_a is not None:
            branch_obj_id = (target_a["target_anchor_object_id"]
                             or f"branchobj:{trigger.trigger_event_id}")
            branch_target = (branch_obj_id, target_a["target_anchor_type"],
                             target_a["target_anchor_price"])
        considered = build_target_candidates(
            self.inv, direction, entry_price, entry_seq, seg, stop, atr,
            branch_target)
        ledger = [_target_row(t) for t in considered]
        stored_ledger = ledger if self.keep_considered_targets else []

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

        variants = []
        for policy in TARGET_POLICIES:
            sel = select_target(considered, policy, branch_obj_id)
            if sel is None:
                continue
            tgt_c, rank = sel
            self._n += 1
            cid = f"GNC-{self._n:06d}"
            s = Setup(
                id=cid, direction="long" if direction > 0 else "short",
                path_family=trigger.trigger_family, graph=exact,
                entry_mode=trigger.entry_mode, origin_id=branch.origin_object_id,
                transition_ids=list(trigger.ordered_transition_ids),
                primitive_ids=prim_ids,
                context_conditions=list(trigger.relationship_evidence)[:3],
                entry_seq=entry_seq, entry_ts=self.bars[entry_seq].ts_utc,
                entry_price=float(entry_price), structural_stop=float(stop),
                structural_target=float(tgt_c.price),
                expiry_seq=min(entry_seq + EXPIRY_BARS, self.seg_last[seg]),
                expiry_rule=f"{EXPIRY_BARS}_bars_or_segment_end", segment_id=seg,
                has_fvg=has_fvg, has_ifvg=has_ifvg, has_rb=has_rb, has_sweep=has_sweep,
                continuation_or_fade=trigger.continuation_or_fade,
            )
            apply_rr_policy(s)
            feats = build_features(SimpleNamespace(setup=s), self.fctx)
            feats["target_policy_id"] = policy
            feats["target_family"] = tgt_c.family
            feats["target_timeframe"] = str(tgt_c.timeframe)
            feats["target_prominence"] = tgt_c.prominence_grade
            feats["target_surface_policy"] = tgt_c.target_surface
            sel_rule = f"{policy}|{tgt_c.family}|rank={rank}"
            target_a_fields = {
                "target_anchor_type": tgt_c.family,
                "target_anchor_object_id": tgt_c.object_id,
                "target_anchor_price": float(tgt_c.price)}
            cand = GraphNativeCandidate(
                candidate_id=cid, source_branch_id=trigger.branch_id,
                source_episode_id=trigger.episode_id,
                trigger_event_id=trigger.trigger_event_id,
                exact_graph=exact, reduced_graph=reduce_graph(exact),
                ordered_event_ids=trigger.ordered_event_ids,
                ordered_transition_ids=trigger.ordered_transition_ids,
                relationship_evidence=trigger.relationship_evidence,
                direction=s.direction, entry_mode=trigger.entry_mode, setup=s,
                features=feats, parent_fvg_id=branch.parent_fvg_id,
                fvg_formation_event_id=branch.fvg_formation_event_id,
                fvg_failure_event_id=branch.fvg_failure_event_id,
                ifvg_confirmation_event_id=branch.ifvg_confirmation_event_id,
                retest_event_id=branch.retest_event_id,
                anchor_resolution_rule=f"{rule}|policy={policy}",
                target_policy_id=policy, target_surface_policy=tgt_c.target_surface,
                target_anchor_timeframe=tgt_c.timeframe,
                target_prominence_grade=tgt_c.prominence_grade,
                selected_target_rank=rank, selection_rule_id=sel_rule,
                considered_targets=stored_ledger, **stop_a, **target_a_fields)
            branch.emitted_candidate_ids.append(cid)
            variants.append(cand)

        if not variants:
            return [], "NO_STRUCTURAL_TARGET"
        # Tallied/sunk only for triggers that actually produced a candidate --
        # matching what review_atlas's reference scan sees (it dedupes over
        # graph_candidates/graph_rejected, which never include a trigger whose
        # policies all failed to select a target).
        if trigger.trigger_event_id not in self._occluded_tally_seen:
            self._occluded_tally_seen.add(trigger.trigger_event_id)
            for r in ledger:
                if r["timeframe"] in self.occluded_by_tf and r["occluded_by"]:
                    self.occluded_by_tf[r["timeframe"]] += 1
        if self.ledger_sink is not None:
            self.ledger_sink(trigger.trigger_event_id, ledger)
        return variants, None

    def _seq(self, ev):
        if not hasattr(self, "_smap"):
            self._smap = {str(b.ts_et): i for i, b in enumerate(self.bars)}
        return self._smap[ev.timestamp_et]

    def _obj(self, oid):
        try:
            return self.reg.get(oid)
        except Exception:
            return None


def materialize_all(result, keep_considered_targets=True, ledger_sink=None):
    """Materialize graph-native candidates from every trigger state.

    Returns dict with `candidates` (eligible, RR-valid), `rejected` (formed but
    <0.5R / wrong side), and `unformed_reasons` (could not form entry/target).
    ``keep_considered_targets=False`` / ``ledger_sink`` are the same
    compact-record memory repair as ``Materializer.__init__`` -- default
    behaviour (full in-memory ledger) is unchanged.
    """
    ps = result["engine"].ps
    log = result["log"]
    branch_by_id = {b.branch_id: b for b in result["branches"]}
    mat = Materializer(ps, keep_considered_targets=keep_considered_targets,
                       ledger_sink=ledger_sink)
    candidates, rejected = [], []
    unformed = {}
    for trig in result["triggers"]:
        b = branch_by_id[trig.branch_id]
        variants, reason = mat.materialize(trig, b, log)
        if not variants:
            unformed[reason] = unformed.get(reason, 0) + 1
            continue
        for cand in variants:
            if cand.setup.eligible:
                candidates.append(cand)
            else:
                rejected.append(cand)
    result["graph_candidates"] = candidates
    result["graph_rejected"] = rejected
    result["unformed_reasons"] = unformed
    result["occluded_by_tf"] = mat.occluded_by_tf
    return result

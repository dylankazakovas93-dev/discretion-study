"""Chronological structure-and-setup atlas for a single review week.

Produces a deterministic, causal, chronological visual review of what the
graph-native recognizer saw during a specific week: primitive detection, HTF
structure, episode/branch construction, coherent setups (strong/weak/rejected/
unresolved), structural stop/target placement, RR-based rejection, and the
current recognizer's provisional prior-only evidence. Outcomes are attached
*after* the example manifest is frozen and hashed, and never influence which
examples are selected. This is a visual/causal review, not a profitability
study, an optimizer, or a forward/edge claim.

Architecture note (disclosed): the continuous graph-native engine (BranchEngine
+ Materializer) is O(bars) per session but with a per-day constant large enough
that a single continuous multi-month run is not tractable in one session. This
module does not alter BranchEngine/Materializer in any way; it only decides how
much continuous history to feed them (a data/config choice, not an engine
change) and provides a *disclosed*, non-default helper (`evidence_for_subset`)
that computes adaptive-evidence snapshots only for the review-week candidates
instead of every candidate in the pool -- it calls the exact same unmodified
`evidence.build_snapshot`/`gate.qualify` for each one, so a review-week
candidate's snapshot is byte-identical to what `evidence.run()` would produce
for it; the only thing skipped is building (and discarding) snapshots for
candidates nobody asked to inspect. This equivalence is regression-tested.
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from ..setups.model import evaluate_outcome
from ..data.cme_session import session_date as true_session_date
from ..data.cme_session import distinct_session_dates as count_true_sessions
from ..recognizer import evidence as evidence_mod
from ..recognizer.gate import qualify
from .targets import TARGET_POLICIES

ET = "America/New_York"
SESSION_OPEN = (18, 0)  # true CME session open, ET -- see data.cme_session

# --------------------------------------------------------------------------
# session / window utilities
#
# `true_session_date`/`count_true_sessions` are re-exports of the single
# canonical `discretion.data.cme_session` implementation (also used by the
# evidence engine) -- kept as names here only so existing call sites in this
# module and its tests don't need to change.
# --------------------------------------------------------------------------


def in_window(ts_et, start_et, end_et) -> bool:
    return start_et <= ts_et <= end_et


# --------------------------------------------------------------------------
# deduplication (Stage 1: one-trigger/one-policy diagnostic view)
# --------------------------------------------------------------------------

def dedup_by_trigger(candidates):
    """One representative candidate per `trigger_event_id`, chosen by a frozen
    policy-priority order (TARGET_POLICIES tuple order: BRANCH_SEMANTIC first).
    Pure filter -- never mutates the input candidates or the underlying ledger.
    """
    by_trigger: dict[str, list] = {}
    for c in candidates:
        by_trigger.setdefault(c.trigger_event_id, []).append(c)
    rank = {p: i for i, p in enumerate(TARGET_POLICIES)}
    out = []
    for trig, group in by_trigger.items():
        group_sorted = sorted(group, key=lambda c: (rank.get(c.target_policy_id, 99),
                                                     c.candidate_id))
        out.append(group_sorted[0])
    out.sort(key=lambda c: (c.setup.entry_seq, c.candidate_id))
    return out


# --------------------------------------------------------------------------
# Stage 3: binary structural validity (not a graded tier). Pure function of
# existing frozen fields -- never invents a HIGH/MEDIUM/LOW label.
# --------------------------------------------------------------------------

STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
STRUCTURALLY_REJECTED = "STRUCTURALLY_REJECTED"
UNRESOLVED = "UNRESOLVED"


def candidate_structural_state(cand) -> str:
    """A materialized candidate is either binary state; there is no tier."""
    return STRUCTURALLY_VALID if cand.setup.eligible else STRUCTURALLY_REJECTED


def branch_structural_state(branch) -> str:
    """A branch that never emitted a candidate is UNRESOLVED regardless of
    whether its `terminal_status` is None/active, EXPIRED, or INVALIDATED --
    "the grammar has not yet produced the required trigger" applies to all
    three (docs/ADAPTIVE_GRADING_REPAIR_PROTOCOL.md Sec 3). A branch that DID
    emit has no single state of its own: each emitted candidate carries its
    own `candidate_structural_state` independently."""
    return None if branch.emitted_candidate_ids else UNRESOLVED


# --------------------------------------------------------------------------
# structural quality view (Stage 4A) -- descriptive component vector only.
# NOT used to rank/grade candidates (Problem 4 repair): displacement grade,
# graph length, etc. are branch-identity/similarity features, never a
# structural-quality ranking. The grade is historical evidence (Stage 12C).
# --------------------------------------------------------------------------

def structural_quality_vector(cand, ps) -> dict:
    """The existing frozen pre-outcome component fields, verbatim from the
    candidate's own `features` dict (built once at materialization by
    `representations.signatures.build_features`) plus a handful of anchor/RR
    fields already stored on the candidate. Nothing here is a new or
    manufactured field -- fields the frozen feature vector does not carry
    (e.g. no single "structural score"; no standalone compression-state/
    duration feature, see docs/SIMILARITY_AUDIT_PROTOCOL.md gap F5; no
    overlap or close-quality feature at all, not even as a documented gap)
    are reported as absent (None), never invented. See
    structural_quality_key() / atlas_report.md for the documented deterministic
    lexicographic ordering built from this vector.
    """
    s = cand.setup
    f = cand.features
    return {
        "graph_completeness_steps": len(cand.ordered_event_ids),
        "displacement_grade": f.get("displacement_grade"),
        "displacement_body_atr": f.get("displacement_body_atr"),
        "path_body_ratio": f.get("path_body_ratio"),
        "favorable_close": f.get("favorable_close"),
        "origin_age_bars": f.get("origin_age_bars"),
        "zone_width_atr": f.get("zone_width_atr"),
        "revisit_number": f.get("revisit_number"),
        "level_family": f.get("level_family"),
        "sweep_state": f.get("sweep_state"),
        "vwap_side": f.get("vwap_side"),
        "nearest_vwap_band": f.get("nearest_vwap_band"),
        "session": f.get("session"),
        "target_family": cand.target_anchor_type,
        "target_timeframe": cand.target_anchor_timeframe,
        "target_surface": cand.target_surface_policy,
        "target_policy": cand.target_policy_id,
        "stop_anchor_family": cand.stop_anchor_type,
        "natural_rr": round(s.natural_rr, 4),
        "executed_rr": round(s.executed_rr, 4),
        "structural_state": candidate_structural_state(cand),
        "rejection_reason": s.rejection_reason or None,
        # explicitly-absent frozen fields (documented gaps, not manufactured):
        "compression_state": None,     # no frozen field exists (protocol gap)
        "overlap": None,               # no frozen field exists (protocol gap)
        "close_quality": None,         # no frozen field exists (protocol gap)
    }

# NOTE (Problem 4 repair): the prior `structural_quality_key` lexicographic
# ranking (graph length -> displacement label -> natural RR -> executed RR ->
# target presence) has been REMOVED. It graded candidates by structural/visual
# resemblance, which docs/ADAPTIVE_GRADING_REPAIR_PROTOCOL.md's governing
# principle explicitly forbids: displacement grade, graph length, RR magnitude
# beyond the 0.5R feasibility gate, etc. are branch-identity/similarity
# features, never a quality ranking. `structural_quality_vector` above is
# retained ONLY as the descriptive component view (Stage 4A/7's "descriptive
# context"); the setup grade is the historical evidence table (Stage 12C).


# --------------------------------------------------------------------------
# adaptive-evidence view (Stage 4B) -- semantics-preserving subset evidence
# --------------------------------------------------------------------------

def evidence_for_subset(result, target_candidates):
    """Attach the SAME `evidence.build_snapshot`/`gate.qualify` outputs that
    `evidence.run(result)` would attach, but only to `target_candidates`.

    Semantics-preserving performance measure (disclosed): `evidence.prepare`
    (which evaluates every candidate's own outcome so it can serve as a
    comparable for *later* candidates) still runs over the FULL candidate pool
    exactly as `evidence.run` does -- nothing about the comparable pool is
    changed. The only thing skipped is calling `build_snapshot` for candidates
    outside `target_candidates`, which is pure, side-effect-free per candidate:
    computing (or not computing) candidate X's own snapshot cannot change the
    pool `Comp` tuples used for candidate Y's snapshot (those come only from
    `prepare()`'s outcome evaluation, independent of whether a snapshot was
    built). Regression-tested for byte-identical output vs `evidence.run` on a
    smaller window in tests/test_review_atlas.py.

    `result["candidates"]` is the same alias `pipeline.run_graph_native` sets
    (`= result["graph_candidates"]`) before calling `evidence.run`; it is set
    here too so this helper also works against a bare `materialize_all(result)`
    result (as produced by `scripts/run_review_atlas.py`, which never goes
    through `run_graph_native`).
    """
    result.setdefault("candidates", result["graph_candidates"])
    evidence_mod.prepare(result)
    cands = sorted(result["candidates"], key=lambda c: (c.setup.entry_seq, c.setup.id))
    resolved = [c for c in cands if c.completion_ord is not None]
    by_completion: dict[int, list] = {}
    for c in resolved:
        by_completion.setdefault(c.completion_ord, []).append(
            evidence_mod.Comp(c.completion_ord, c.setup.outcome, c.realized_r,
                              c.setup.executed_rr, c.exact_graph, c.reduced_graph,
                              c.features))
    targets = set(id(c) for c in target_candidates)
    pool: list = []
    pool_upto = -1
    for c in cands:
        while pool_upto < c.session_ord - 1:
            pool_upto += 1
            pool.extend(by_completion.get(pool_upto, []))
        if id(c) in targets:
            snap = evidence_mod.build_snapshot(c.features, c.exact_graph,
                                               c.reduced_graph, pool, c.session_ord)
            c.evidence = snap
            c.qualification = qualify(snap)
    return result


def adaptive_evidence_view(cand) -> dict:
    ev = cand.evidence or {}
    summary = ev.get("summary", {})
    levels = ev.get("levels", {})

    def occ(level):
        return levels.get(level, {}).get("ALL", {}).get("occurrences")

    return {
        "qualification_state": cand.qualification,
        "exact_match_count": occ("exact"),
        "reduced_match_count": occ("reduced"),
        "nn_count": occ("nn"),
        "unique_prior_sessions": summary.get("unique_sessions"),
        "effective_sample_size": summary.get("effective_sample"),
        "shrunk_expected_R": summary.get("shrunk_expected_R"),
        "uncertainty": summary.get("uncertainty"),
        "gate_reasons": ev.get("gate_fails", []),
        "target_policy": cand.target_policy_id,
        "provisional_note": "prior-only, untuned; the broad collision/"
                             "calibration audit is not yet complete -- "
                             "illustrative of mechanism, not a measured edge",
    }


# --------------------------------------------------------------------------
# outcome attachment (Stage 7) -- only after manifest freeze
# --------------------------------------------------------------------------

def attach_outcome(cand, bars) -> dict:
    s = cand.setup
    if s.outcome == "UNEVALUATED":
        evaluate_outcome(s, bars)
    first_hit = None
    if s.outcome == "WIN":
        first_hit = "executed_target"
    elif s.outcome == "LOSS":
        first_hit = "structural_stop"
    elif s.outcome == "AMBIGUOUS":
        first_hit = "both_same_bar"
    return {
        "outcome": s.outcome,
        "outcome_seq": s.outcome_seq,
        "realized_r": (s.executed_rr if s.outcome == "WIN"
                       else (-1.0 if s.outcome == "LOSS" else None)),
        "first_hit": first_hit,
        "natural_target_diagnostic": s.structural_target,
    }


# --------------------------------------------------------------------------
# Stage 2: weekly inventory
# --------------------------------------------------------------------------

# plain-English category -> event_subtype substrings/prefixes that satisfy it.
# Built directly from events/adapter.py:canonical_subtype's token grammar
# (dw=BULLISH/BEARISH/NEUTRAL prefix, k=primitive event kind suffix).
PRIMITIVE_EVENT_CATEGORIES = {
    "fvg_formed": ("_FVG_FORMED",),
    "fvg_first_touch": ("_FVG_FIRST_TOUCH",),
    "fvg_partial_fill": ("_FVG_FIRST_FILL",),
    "fvg_midpoint": ("_FVG_MIDPOINT",),
    "fvg_full_fill": ("_FVG_FULL_FILL",),
    "fvg_failure": ("_FVG_FAILURE",),
    "fvg_continuation_no_fill": ("_FVG_CONTINUATION",),
    "ifvg_activation": ("_IFVG_ACTIVATION",),
    "ifvg_reinversion": ("_IFVG_REINVERSION",),
    "rejection_block_formed": ("_RB_FORMED",),
    "rb_tap": ("_RB_TAP",),
    "good_displacement": ("GOOD_",),
    "mixed_displacement": ("MIXED_",),
    "bad_displacement": ("BAD_",),
    "compression": ("COMPRESSION",),
    "expansion": ("_EXPANSION",),
    "confirmed_swing": ("SWING_HIGH_CONFIRMED", "SWING_LOW_CONFIRMED"),
    "equal_high_low": ("EQUAL_HIGHS_CONFIRMED", "EQUAL_LOWS_CONFIRMED"),
    "sweep": ("_SWEEP",),
    "reclaim": ("_RECLAIM",),
    "break": ("_BREAK",),
    "accepted_break_or_level": ("ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW",
                                "STRUCT_CONTINUATION"),
    "failed_break": ("STRUCT_FAILED_CONTINUATION",),
    # events/adapter.py:canonical_subtype's vwap branch always emits
    # f"VWAP_{note.upper()...}" -- every center-vwap interaction note (bounce/
    # reclaim/break/acceptance/continuation) therefore starts "VWAP_VWAP_..." and
    # every band interaction note starts "VWAP_BAND_REJECT_...".
    "vwap_center_interaction": ("VWAP_VWAP",),
    "vwap_band_1p618": ("VWAP_BAND_REJECT_P1_618", "VWAP_BAND_REJECT_M1_618"),
    "vwap_band_2p618": ("VWAP_BAND_REJECT_P2_618", "VWAP_BAND_REJECT_M2_618"),
    "vwap_band_3p618": ("VWAP_BAND_REJECT_P3_618", "VWAP_BAND_REJECT_M3_618"),
    "time_anchor_interaction": ("ANCHOR_",),
}
# iFVG path distinction is graph-level (not a single primitive event), pulled
# from candidate.setup.path_family separately.


def _event_ts(ev):
    return pd.Timestamp(ev.timestamp_et)


def weekly_inventory(result, start_et, end_et):
    """Counts by true CME session and by day, for every canonical event in the
    review week, plus the HTF and graph-object inventories. Returns a dict with
    `raw_crosstab` (the full, ungrouped event_type/event_subtype ground truth --
    "do not use 'eligible setup' as an umbrella term") and `mapped_categories`
    (the task's plain-English category list, computed from that same ground
    truth via PRIMITIVE_EVENT_CATEGORIES, never a separate re-implementation).
    """
    ps = result["engine"].ps
    log = result["log"]

    raw_rows = []
    mapped_counts: dict[tuple, int] = {}
    for ev in log:
        ts = _event_ts(ev)
        if not in_window(ts, start_et, end_et):
            continue
        sess = true_session_date(ts)
        day = ts.date()
        raw_rows.append({"session": str(sess), "day": str(day),
                         "event_type": ev.event_type, "event_subtype": ev.event_subtype})
        for cat, needles in PRIMITIVE_EVENT_CATEGORIES.items():
            if any(n in ev.event_subtype for n in needles):
                key = (str(sess), str(day), cat)
                mapped_counts[key] = mapped_counts.get(key, 0) + 1

    # iFVG immediate vs retest path (graph-level, from candidates in-week)
    cands_in_week = [c for c in result["graph_candidates"] + result["graph_rejected"]
                     if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    for c in cands_in_week:
        if c.setup.path_family == "ifvg_activation":
            sess = true_session_date(c.setup.entry_ts.tz_convert(ET))
            day = c.setup.entry_ts.tz_convert(ET).date()
            key = (str(sess), str(day), "ifvg_immediate_path")
            mapped_counts[key] = mapped_counts.get(key, 0) + 1
        elif c.setup.path_family == "ifvg_retest":
            sess = true_session_date(c.setup.entry_ts.tz_convert(ET))
            day = c.setup.entry_ts.tz_convert(ET).date()
            key = (str(sess), str(day), "ifvg_retest_path")
            mapped_counts[key] = mapped_counts.get(key, 0) + 1

    mapped_rows = [{"session": s, "day": d, "category": c, "count": n}
                   for (s, d, c), n in sorted(mapped_counts.items())]

    htf = htf_inventory(result, start_et, end_et)
    graph_obj = graph_object_inventory(result, start_et, end_et)
    return {"raw_crosstab": raw_rows, "mapped_categories": mapped_rows,
            "htf_inventory": htf, "graph_object_inventory": graph_obj}


def htf_inventory(result, start_et, end_et):
    ps = result["engine"].ps
    out = {}
    for tf in (5, 15, 30, 60):
        candles = [c for c in ps.htf.get(tf, [])
                  if in_window(pd.Timestamp(c.close_ts), start_et, end_et)]
        wicks = [w for w in ps.wicks if w.timeframe == tf
                and in_window(pd.Timestamp(w.availability_ts), start_et, end_et)]
        fvgs = [f for f in ps.htf_fvgs if f.timeframe == tf
               and in_window(pd.Timestamp(f.availability_ts), start_et, end_et)]
        ifvgs = [iv for iv in ps.htf_ifvgs if iv.timeframe == tf
                and in_window(pd.Timestamp(iv.created_ts), start_et, end_et)]
        selected = [c for c in result["graph_candidates"]
                   if c.target_anchor_timeframe == tf
                   and in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
        occluded = 0
        seen_trig = set()
        for c in result["graph_candidates"] + result["graph_rejected"]:
            if c.trigger_event_id in seen_trig:
                continue
            seen_trig.add(c.trigger_event_id)
            for r in c.considered_targets:
                if r.get("timeframe") == tf and r.get("occluded_by"):
                    occluded += 1
        out[tf] = {
            "completed_candles": len(candles),
            "wick_objects_by_grade": {g: sum(1 for w in wicks if w.prominence_grade == g)
                                      for g in ("HIGH", "MEDIUM", "LOW")},
            "fresh_htf_fvgs": sum(1 for f in fvgs if f.failed_seq is None),
            "htf_fvg_failures": sum(1 for f in fvgs if f.failed_seq is not None),
            "htf_ifvgs": len(ifvgs),
            "objects_occluded_in_considered_ledger": occluded,
            "objects_selected_as_target": len(selected),
        }
    return out


def graph_object_inventory(result, start_et, end_et):
    log_in_week = sum(1 for ev in result["log"] if in_window(_event_ts(ev), start_et, end_et))
    episodes_in_week = sum(
        1 for e in result["episodes"]
        if in_window(pd.Timestamp(e.start_timestamp), start_et, end_et))
    branches_in_week = [
        b for b in result["branches"]
        if b.ordered_event_ids and in_window(
            _event_ts(result["log"].get(b.ordered_event_ids[0])), start_et, end_et)]
    triggers_in_week = [
        t for t in result["triggers"]
        if in_window(_event_ts(result["log"].get(t.trigger_event_id)), start_et, end_et)]
    cands_in_week = [c for c in result["graph_candidates"]
                     if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    rej_in_week = [c for c in result["graph_rejected"]
                  if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    dedup = dedup_by_trigger(cands_in_week + rej_in_week)
    return {
        "primitive_events": log_in_week,
        "active_episodes": episodes_in_week,
        "branches_created": len(branches_in_week),
        "branches_forked": sum(1 for b in branches_in_week if b.parent_branch_id),
        "unresolved_branches": sum(1 for b in branches_in_week
                                   if b.terminal_status == "UNRESOLVED"),
        "invalidated_branches": sum(1 for b in branches_in_week
                                    if b.terminal_status == "INVALIDATED"),
        "triggered_graph_native_candidates": len(triggers_in_week),
        "structurally_valid_candidates": len(cands_in_week),
        "sub_0p5R_rejected_candidates": sum(
            1 for c in rej_in_week if c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR"),
        # Real (unmodified evidence.build_snapshot/gate.qualify) qualification,
        # but only over whichever candidates were actually scored this run
        # (see bounded_qualification_scan) -- scoring literally every in-week
        # candidate proved computationally impractical (45+ min, aborted; see
        # atlas_report.md). These two counts are over the SCORED subset only,
        # never a silent full-week estimate; n_scored/n_total make the scope
        # explicit rather than presenting a partial count as the true total.
        "qualified_candidates_scored_subset": sum(
            1 for c in cands_in_week if c.qualification == "QUALIFIED_PENDING_TRIGGER"),
        "recorded_not_activated_candidates_scored_subset": sum(
            1 for c in cands_in_week if c.qualification == "RECORDED_NOT_ACTIVATED"),
        "qualification_n_scored": sum(1 for c in cands_in_week
                                      if c.qualification != "UNSCORED"),
        "qualification_n_total_in_week": len(cands_in_week),
        "deduplicated_trigger_groups": len(dedup),
        "target_policy_variants": len(cands_in_week) + len(rej_in_week),
    }


# --------------------------------------------------------------------------
# Stage 3: deterministic pre-outcome example selection
# --------------------------------------------------------------------------
# Generic recipe (documented, applied uniformly): filter candidates/objects
# using only frozen pre-outcome attributes -> sort by the documented key ->
# take the first N -> freeze the IDs. A missing category is reported absent,
# never fabricated or relabelled.

def _in_week_objs(objs, start_et, end_et, ts_attr="created_ts"):
    out = []
    for o in objs:
        ts = getattr(o, ts_attr, None)
        if ts is None:
            continue
        try:
            t = pd.Timestamp(ts)
        except Exception:
            continue
        if in_window(t, start_et, end_et):
            out.append(o)
    return sorted(out, key=lambda o: o.created_seq)


def _first_n_distinct(objs, key_fn, n):
    """First N objects chronologically, preferring distinct `key_fn` values
    before repeating one (documented diversity rule, not outcome-based)."""
    seen = set()
    picked, rest = [], []
    for o in objs:
        k = key_fn(o)
        if k not in seen:
            picked.append(o)
            seen.add(k)
        else:
            rest.append(o)
        if len(picked) >= n:
            return picked
    picked.extend(rest[: n - len(picked)])
    return picked[:n]


def fvg_is_no_fill_continuation(f):
    """Problem 7 repair: a genuine no-fill continuation is proven by the
    CONTINUATION event's own existence -- fvg.py only ever stamps it when
    `not fvg.touched` AS OF that event's own seq (evaluated inline, in
    forward causal order, at detection time), never retroactively. The
    object's FINAL end-of-window `.touched` flag is a different, later
    snapshot that a subsequent touch can flip True without invalidating
    the earlier, already-causally-proven continuation -- so it must NOT
    gate this predicate (previously `and not f.touched` wrongly excluded
    genuine continuations that were touched only after continuing)."""
    return f.has_event("CONTINUATION")


def proven_fvg_to_ifvg_lineage(iv, reg):
    """Problem 7 repair: strict lineage proof, not `failed_seq is not
    None`. Requires: the parent FVG object resolves; its FORMED and
    FAILURE events both exist; the child iFVG's own activation
    (CONFIRMED) event exists; and causal ordering holds (parent formed
    seq <= parent failure seq == child activation seq)."""
    if not iv.source_fvg_id:
        return None
    try:
        parent = reg.get(iv.source_fvg_id)
    except Exception:
        return None
    formed = parent.first_event("FORMED")
    failure = parent.first_event("FAILURE")
    activated = iv.first_event("CONFIRMED")
    if not (formed and failure and activated):
        return None
    if not (formed.seq <= failure.seq == activated.seq == iv.created_seq):
        return None
    return {
        "parent_fvg_id": parent.id, "parent_formation_event_seq": formed.seq,
        "parent_failure_event_seq": failure.seq, "child_ifvg_id": iv.id,
        "child_activation_event_seq": activated.seq,
    }


def select_primitive_examples(ps, start_et, end_et):
    """Stage 3 'required primitive examples'. Returns {category: [objects]}."""
    rbs = _in_week_objs(ps.rbs, start_et, end_et)
    fvgs = _in_week_objs(ps.fvgs, start_et, end_et)
    disps = _in_week_objs(ps.displacements, start_et, end_et)
    structs = _in_week_objs(ps.structures, start_et, end_et)
    vwaps = ps.vwaps  # sessions; filtered per-event below
    anchors = _in_week_objs(ps.anchors, start_et, end_et)
    wicks_5_60 = sorted(
        [w for w in ps.wicks
         if in_window(pd.Timestamp(w.availability_ts), start_et, end_et)
         and w.prominence_grade in ("HIGH", "MEDIUM")],
        key=lambda w: w.created_seq)
    equal_lv = _in_week_objs(ps.equal_levels, start_et, end_et)

    def fvg_lifecycle_sig(f):
        return tuple(e.kind for e in f.events if e.kind != "FORMED")

    ifvgs = _in_week_objs(ps.ifvgs, start_et, end_et)
    lineage_proven = [(iv, proven_fvg_to_ifvg_lineage(iv, ps.registry)) for iv in ifvgs]
    lineage_proven = [(iv, p) for iv, p in lineage_proven if p is not None]

    out = {
        "rejection_blocks": _first_n_distinct(rbs, lambda r: r.subtype, 3),
        "fvgs_distinct_lifecycle": _first_n_distinct(fvgs, fvg_lifecycle_sig, 3),
        "fvg_continuation_no_fill": [f for f in fvgs if fvg_is_no_fill_continuation(f)][:2],
        # each entry is (child_ifvg, lineage_proof_dict), never a bare FVG
        "fvg_failure_to_ifvg": lineage_proven[:2],
        "ifvg_retest": [iv for iv in ifvgs if iv.has_event("REVISIT")][:2],
        "prominent_upper_wick": [w for w in wicks_5_60 if w.side == "upper"][:2],
        "prominent_lower_wick": [w for w in wicks_5_60 if w.side == "lower"][:2],
        "equal_level_or_liquidity": equal_lv[:2],
        "good_displacement": [d for d in disps if d.grade == "good"][:2],
        "mixed_displacement": [d for d in disps if d.grade == "mixed"][:2],
        "bad_displacement": [d for d in disps if d.grade == "bad"][:2],
        "compression": [z for z in structs if z.subtype == "compression"][:2],
        "expansion": [z for z in structs if z.subtype == "expansion"][:2],
        "time_anchor_interaction": [a for a in anchors if len(a.events) > 1][:2],
    }
    # VWAP interactions: pick 2 (session, seq) pairs with a REJECTION/ACCEPTANCE
    # event whose timestamp falls in-week
    vwap_hits = []
    for vs in vwaps:
        for e in vs.events:
            if e.kind in ("REJECTION", "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW"):
                if in_window(pd.Timestamp(e.ts_utc).tz_convert(ET) if
                            pd.Timestamp(e.ts_utc).tzinfo else pd.Timestamp(e.ts_utc),
                            start_et, end_et):
                    vwap_hits.append((e.seq, vs, e))
    vwap_hits.sort(key=lambda t: t[0])
    out["vwap_interaction"] = vwap_hits[:2]
    return out


# path_family -> required branch/path category label (Stage 3)
BRANCH_PATH_CATEGORIES = {
    "rb_reaction": "rb_tap_good_displacement_continuation",
    "rb_fvg_fill": "rb_tap_good_displacement_continuation",
    "rb_failure_fade": "rb_tap_bad_displacement_compression_fade",
    "fvg_formation": "contextual_fvg_immediate_entry",
    "fvg_fill": "fvg_first_touch_response",
    "fvg_no_fill": "genuine_fvg_no_fill_continuation",
    "ifvg_activation": "fvg_failure_immediate_ifvg",
    "ifvg_retest": "fvg_failure_later_ifvg_retest",
    "sweep_fade": "sweep_reclaim_fade",
    "sweep_reclaim_fade": "sweep_reclaim_fade",
    "sweep_accept_cont": "sweep_acceptance_continuation",
    "break_accept_cont": "accepted_break",
    "break_failed_fade": "failed_break",
    "anchor_reclaim": "time_anchor_setup_without_fvg",
    "vwap_bounce": "vwap_continuation",
    "vwap_reclaim": "vwap_continuation",
    "vwap_break_accept": "vwap_continuation",
    "vwap_band_fade": "vwap_fade",
    "compression_expansion": "compression_expansion",
    "compression_false_expansion": "false_expansion_fade",
}


# Stage 11 repair: `path_family` alone is already grammar-guaranteed to imply
# these graph conditions (verified by direct inspection of graph/transitions.py
# -- e.g. H_rb_reaction_continuation's own hypothesis definition REQUIRES a
# rejection-block FIRST_TOUCH advance stage followed by a displacement FORMED
# stage with `subtype_contains="GOOD"` before it may even emit; a candidate
# cannot be materialized with path_family=="rb_reaction" without having passed
# through exactly that sequence). This dict is an EXTRA, cheap, code-level
# proof beyond that trust -- every selected example's own `exact_graph` string
# must also literally contain the required causal tokens, so a future grammar
# change that silently weakened a hypothesis could not slip an unproven
# example past this selector without the atlas test suite catching it.
REQUIRED_GRAPH_TOKENS = {
    "rb_tap_good_displacement_continuation": ("RB_TAP", "GOOD"),
    "rb_tap_bad_displacement_compression_fade": ("RB_TAP", "BAD", "COMPRESSION"),
    "genuine_fvg_no_fill_continuation": ("FVG_CONTINUATION",),
    "fvg_failure_immediate_ifvg": ("FVG_FAILURE", "IFVG_ACTIVATION"),
    # retest is IFVG_ACTIVATION (confirmation) followed by a LATER
    # IFVG_FIRST_TOUCH (the retest trigger itself) -- events/adapter.py's
    # canonical_subtype maps ifvg CONFIRMED -> "..._IFVG_ACTIVATION" and any
    # other kind (incl. the retest's own FIRST_TOUCH) -> "..._IFVG_{kind}";
    # there is no literal "IFVG_RETEST" token anywhere in an exact_graph.
    "fvg_failure_later_ifvg_retest": ("FVG_FAILURE", "IFVG_ACTIVATION", "IFVG_FIRST_TOUCH"),
    "accepted_break": ("ACCEPTANCE",),
    "failed_break": ("FAILED",),
}


def _graph_contains_required_tokens(exact_graph, label):
    needles = REQUIRED_GRAPH_TOKENS.get(label)
    if needles is None:
        return True   # no additional token proof defined for this label
    return all(n in exact_graph for n in needles)


def select_branch_path_examples(result, start_et, end_et):
    """Stage 3 'required branch/path examples'. One chronologically-first
    candidate (eligible or rejected -- the graph path is what's being shown,
    not eligibility) per required category label, additionally verified to
    literally contain the label's required causal tokens in its own
    exact_graph (see REQUIRED_GRAPH_TOKENS); 'rb_tap_bad_displacement_
    unresolved' comes from branches (correctly never emitted a trigger)."""
    cands = sorted(result["graph_candidates"] + result["graph_rejected"],
                   key=lambda c: (c.setup.entry_seq, c.candidate_id))
    cands_in_week = [c for c in cands
                     if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    by_label: dict[str, object] = {}
    for c in cands_in_week:
        label = BRANCH_PATH_CATEGORIES.get(c.setup.path_family)
        if label and label not in by_label and _graph_contains_required_tokens(
                c.exact_graph, label):
            by_label[label] = c

    # RB tap -> bad displacement -> unresolved (never triggered; from branches)
    unresolved = sorted(
        [b for b in result["branches"]
         if b.hypothesis_id == "H_rb_unresolved_fade"
         and b.terminal_status in ("UNRESOLVED", "EXPIRED")
         and b.ordered_event_ids
         and in_window(_event_ts(result["log"].get(b.ordered_event_ids[0])),
                       start_et, end_et)],
        key=lambda b: b.branch_id)
    if unresolved:
        by_label["rb_tap_bad_displacement_unresolved"] = unresolved[0]
    return by_label


ALL_BRANCH_PATH_LABELS = sorted(set(BRANCH_PATH_CATEGORIES.values())) + \
    ["rb_tap_bad_displacement_unresolved"]


# --------------------------------------------------------------------------
# Stage 12 D: structurally rejected examples + frozen-RR-bucket/dedup/policy-
# pair examples. These are pre-evidence, pre-outcome, non-graded filters on
# frozen fields only -- NOT a quality ranking (Problem 4: the former
# strongest_5/middle_5/weakest_5 structural-quality-ranked categories were
# removed; the setup grade is now the evidence-ranked pack, Section C below).
# Selection never reads setup.outcome/realized_r/outcome_seq.
# --------------------------------------------------------------------------

def select_structural_examples(result, ps, start_et, end_et):
    cands = [c for c in result["graph_candidates"]
            if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    rej = [c for c in result["graph_rejected"]
          if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]

    unresolved = sorted(
        [b for b in result["branches"]
         if branch_structural_state(b) == UNRESOLVED and b.ordered_event_ids
         and in_window(_event_ts(result["log"].get(b.ordered_event_ids[0])),
                       start_et, end_et)],
        key=lambda b: b.branch_id)[:3]

    rej_chrono = sorted(rej, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    insufficient_rr = [c for c in rej_chrono
                       if c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR"][:3]
    # every other material rejection reason, one example each (Section D)
    other_rejected: dict[str, object] = {}
    for c in rej_chrono:
        r = c.setup.rejection_reason
        if r and r != "INSUFFICIENT_NATURAL_RR" and r not in other_rejected:
            other_rejected[r] = c

    cands_chrono = sorted(cands, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    natural_ge1 = [c for c in cands_chrono if c.setup.natural_rr >= 1.0][:2]
    natural_half_to_1 = [c for c in cands_chrono
                         if 0.5 <= c.setup.natural_rr < 1.0][:2]

    # policy-variant pairs on the same trigger (chronological first trigger with
    # >=2 distinct policies producing eligible variants)
    by_trig: dict[str, list] = {}
    for c in cands_chrono:
        by_trig.setdefault(c.trigger_event_id, []).append(c)
    policy_pairs = []
    for trig in sorted(by_trig, key=lambda t: min(c.setup.entry_seq for c in by_trig[t])):
        group = by_trig[trig]
        if len({c.target_policy_id for c in group}) >= 2:
            policy_pairs = sorted(group, key=lambda c: c.candidate_id)[:2]
            break

    dedup = dedup_by_trigger(cands + rej)
    dedup_examples = sorted(dedup, key=lambda c: (c.setup.entry_seq, c.candidate_id))[:2]

    return {
        "rejected_5": rej_chrono[:5],
        "rejected_by_reason": other_rejected,
        "unresolved_3": unresolved,
        "insufficient_rr_3": insufficient_rr,
        "natural_rr_ge1_capped_2": natural_ge1,
        "natural_rr_half_to_1_2": natural_half_to_1,
        "policy_variant_pair_2": policy_pairs,
        "dedup_examples_2": dedup_examples,
    }


# --------------------------------------------------------------------------
# Stage 12 C: evidence-ranked examples -- the setup grade. Every category is
# a frozen, deterministic, pre-outcome rule reading ONLY `cand.evidence`/
# `cand.qualification` (never `setup.outcome`/`realized_r`/`outcome_seq`).
# `cands_scored` must already have real evidence attached (see
# run_indexed_one_trigger_one_policy / bounded_qualification_scan). "recent"
# short horizon = 5 sessions, "medium/longer" = 20 sessions (both members of
# the frozen HORIZONS set); this pairing is fixed here, not tuned per result.
# --------------------------------------------------------------------------

SHORT_HORIZON, MEDIUM_HORIZON = "5", "20"


def _mean_r(cand, tier, horizon):
    lv = (cand.evidence or {}).get("levels", {}).get(tier, {}).get(horizon)
    if not lv or lv["occurrences"] == 0:
        return None
    return lv["mean_R"]


def _occ(cand, tier, horizon="ALL"):
    lv = (cand.evidence or {}).get("levels", {}).get(tier, {}).get(horizon)
    return lv["occurrences"] if lv else 0


def select_evidence_ranked_examples(cands_scored):
    """`cands_scored` = the one-trigger/one-policy candidates that actually
    received real evidence this run (a subset of the review week when a
    compute bound applies -- see the report's disclosed scope)."""
    from ..recognizer.gate import DEFAULT_POLICY

    chrono = sorted(cands_scored, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    scored = [c for c in chrono if c.evidence]

    def top(key_fn, filt, n=3):
        pool = [c for c in scored if filt(c)]
        pool.sort(key=lambda c: (key_fn(c), c.candidate_id), reverse=True)
        return pool[:n]

    strongest_exact = top(lambda c: _mean_r(c, "exact", SHORT_HORIZON),
                          lambda c: _mean_r(c, "exact", SHORT_HORIZON) is not None
                          and _mean_r(c, "exact", SHORT_HORIZON) > 0)
    strongest_reduced = top(lambda c: _mean_r(c, "reduced", SHORT_HORIZON),
                            lambda c: _mean_r(c, "reduced", SHORT_HORIZON) is not None
                            and _mean_r(c, "reduced", SHORT_HORIZON) > 0)
    strongest_qualified = top(
        lambda c: c.evidence["summary"]["shrunk_expected_R"],
        lambda c: c.qualification == "QUALIFIED_PENDING_TRIGGER")

    def _best_tier_pair(c):
        for tier in ("exact", "reduced", "nn"):
            s, m = _mean_r(c, tier, SHORT_HORIZON), _mean_r(c, tier, MEDIUM_HORIZON)
            if s is not None and m is not None:
                return s, m
        return None, None

    conflicting = []
    positive_short_negative_long = []
    negative_recent = []
    for c in chrono:
        s, m = _best_tier_pair(c)
        if s is None:
            continue
        if s > 0 and m is not None and m < 0:
            conflicting.append(c)
            positive_short_negative_long.append(c)
        elif s < 0:
            negative_recent.append(c)

    insufficient_sample = [c for c in scored
                           if c.evidence["summary"]["effective_sample"]
                           < DEFAULT_POLICY.min_effective_sample][:3]
    high_uncertainty = [c for c in scored if "uncertainty" in c.evidence.get("gate_fails", [])][:3]
    exact_unavail_reduced_present = [
        c for c in scored if _occ(c, "exact") == 0 and _occ(c, "reduced") > 0][:2]
    reduced_unavail_nn_present = [
        c for c in scored if _occ(c, "reduced") == 0 and _occ(c, "nn") > 0][:2]
    recorded_not_activated = [c for c in chrono
                              if c.qualification == "RECORDED_NOT_ACTIVATED"][:3]

    by_trig: dict[str, list] = {}
    for c in scored:
        by_trig.setdefault(c.trigger_event_id, []).append(c)
    diff_policy_evidence = []
    for trig in sorted(by_trig, key=lambda t: min(c.setup.entry_seq for c in by_trig[t])):
        group = by_trig[trig]
        if len({c.target_policy_id for c in group}) >= 2:
            qualifications = {c.qualification for c in group}
            ers = {c.evidence["summary"]["shrunk_expected_R"] for c in group}
            if len(qualifications) >= 2 or len(ers) >= 2:
                diff_policy_evidence = sorted(group, key=lambda c: c.candidate_id)[:2]
                break

    return {
        "strongest_positive_recent_exact": strongest_exact,
        "strongest_positive_recent_reduced": strongest_reduced,
        "strongest_qualified": strongest_qualified,
        "conflicting_short_vs_medium_horizon": conflicting[:2],
        "positive_short_negative_long": positive_short_negative_long[:2],
        "negative_recent_evidence": negative_recent[:3],
        "insufficient_sample_evidence": insufficient_sample,
        "high_uncertainty_evidence": high_uncertainty,
        "exact_unavailable_reduced_present": exact_unavail_reduced_present,
        "reduced_unavailable_nn_present": reduced_unavail_nn_present,
        "recorded_not_activated_examples": recorded_not_activated,
        "different_target_policy_evidence_pair": diff_policy_evidence,
    }


def select_qualification_examples(cands_in_week):
    """Must run AFTER evidence has been annotated on `cands_in_week` (whatever
    subset was actually scored -- see `bounded_qualification_scan`). Reads
    only `qualification`/`reduced_graph` -- never `setup.outcome`/
    `realized_r`/`outcome_seq`. Candidates that were never scored keep the
    dataclass default `qualification == "UNSCORED"` and are simply excluded.

    Problem 6 repair: `not_activated_similar_graph_2` is populated ONLY from
    not-activated candidates whose reduced graph genuinely matches a qualified
    example's reduced graph. If no candidate qualifies (or no matching reduced
    graph exists among the not-activated pool), that category is [] -- it is
    NEVER backfilled with unrelated not-activated candidates under the same
    label. A separately, honestly named `chronological_not_activated_examples`
    category (first not-activated candidates, no similarity claim) is always
    populated when any exist, so the atlas still has *something* to show
    without ever mislabeling it."""
    chrono = sorted(cands_in_week, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    qualified = [c for c in chrono if c.qualification == "QUALIFIED_PENDING_TRIGGER"][:2]
    not_activated_chrono = [c for c in chrono
                            if c.qualification == "RECORDED_NOT_ACTIVATED"]
    qual_reduced = {c.reduced_graph for c in qualified}
    similar_not_activated = [
        c for c in not_activated_chrono if c.reduced_graph in qual_reduced][:2]
    return {
        "qualified_2": qualified,
        "not_activated_similar_graph_2": similar_not_activated,
        "chronological_not_activated_examples": not_activated_chrono[:2],
    }


def bounded_qualification_scan(result, cands_in_week, max_scan=500):
    """Compute real (unmodified evidence.build_snapshot/gate.qualify) evidence
    for a bounded chronological prefix of `cands_in_week`, not the whole week.

    Disclosed compute-budget measure: `evidence.build_snapshot`'s Gower-distance
    pass over the prior-only pool costs roughly O(pool size) per candidate
    scored, and scoring literally every in-week candidate (tens of thousands
    here) did not complete in this environment within any practical bound (a
    full-week attempt ran 45+ minutes without finishing and was aborted). This
    function computes byte-identical, unmodified evidence/qualification for
    only the first `max_scan` in-week candidates in chronological order --
    each one's snapshot is exactly what `evidence.run`/`evidence_for_subset`
    would have produced for it (same pool, same function calls); nothing about
    HOW any individual candidate's evidence is computed is changed, only how
    MANY candidates are scored. Returns the scanned subset and how many of
    `cands_in_week` were actually covered, so counts derived from it can be
    honestly labeled as partial.
    """
    prefix = sorted(cands_in_week, key=lambda c: (c.setup.entry_seq, c.candidate_id))[:max_scan]
    evidence_for_subset(result, prefix)
    return prefix, len(prefix), len(cands_in_week)


# --------------------------------------------------------------------------
# manifest hashing
# --------------------------------------------------------------------------

def manifest_hash(manifest: dict) -> str:
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest()

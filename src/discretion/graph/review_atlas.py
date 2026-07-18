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
from ..recognizer import evidence as evidence_mod
from ..recognizer.gate import qualify
from .targets import TARGET_POLICIES

ET = "America/New_York"
SESSION_OPEN = (18, 0)  # true CME session open, ET


# --------------------------------------------------------------------------
# session / window utilities
# --------------------------------------------------------------------------

def true_session_date(ts_et) -> "pd.Timestamp.date":
    """The single true CME-session opening date (18:00 ET) a timestamp belongs
    to. Unlike the codebase's internal `_session_key` (used only for VWAP reset
    and evidence session-ordinals, which intentionally/artifactually also
    resets at midnight ET), this collapses a full continuous 18:00->17:59
    session into ONE key, for honest session counting in this atlas's reports.
    """
    t = (ts_et.hour, ts_et.minute)
    d = ts_et.date()
    if t >= SESSION_OPEN:
        return d
    return d - pd.Timedelta(days=1)


def count_true_sessions(bars, before_date=None):
    """Distinct true CME sessions present in `bars`, optionally only those
    opening strictly before `before_date`."""
    seen = set()
    for b in bars:
        sd = true_session_date(b.ts_et)
        if before_date is None or sd < before_date:
            seen.add(sd)
    return sorted(seen)


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
# structural quality view (Stage 4A) -- no invented composite score
# --------------------------------------------------------------------------

DISPLACEMENT_RANK = {"good": 2, "mixed": 1, "bad": 0}


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
        "structural_state": ("REJECTED:" + s.rejection_reason) if s.rejected else "VALID",
        "rejection_reason": s.rejection_reason or None,
        # explicitly-absent frozen fields (documented gaps, not manufactured):
        "compression_state": None,     # no frozen field exists (protocol gap)
        "overlap": None,               # no frozen field exists (protocol gap)
        "close_quality": None,         # no frozen field exists (protocol gap)
    }


def structural_quality_key(cand, ps):
    """Frozen deterministic lexicographic ordering documented in
    atlas_report.md. Higher tuple = structurally 'stronger' by this ordering.
    Every component is fixed at materialization time (none read outcome).
    """
    v = structural_quality_vector(cand, ps)
    return (
        v["graph_completeness_steps"],
        DISPLACEMENT_RANK.get(v["displacement_grade"], -1),
        v["natural_rr"],
        v["executed_rr"],
        v["target_family"] is not None,
    )


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

    def fvg_is_no_fill_continuation(f):
        return f.has_event("CONTINUATION") and not f.touched

    def fvg_failed_to_ifvg(f):
        return f.failed_seq is not None

    ifvgs = _in_week_objs(ps.ifvgs, start_et, end_et)

    out = {
        "rejection_blocks": _first_n_distinct(rbs, lambda r: r.subtype, 3),
        "fvgs_distinct_lifecycle": _first_n_distinct(fvgs, fvg_lifecycle_sig, 3),
        "fvg_continuation_no_fill": [f for f in fvgs if fvg_is_no_fill_continuation(f)][:2],
        "fvg_failure_to_ifvg": [f for f in fvgs if fvg_failed_to_ifvg(f)][:2],
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


def select_branch_path_examples(result, start_et, end_et):
    """Stage 3 'required branch/path examples'. One chronologically-first
    candidate (eligible or rejected -- the graph path is what's being shown,
    not eligibility) per required category label; 'rb_tap_bad_displacement_
    unresolved' comes from branches (correctly never emitted a trigger)."""
    cands = sorted(result["graph_candidates"] + result["graph_rejected"],
                   key=lambda c: (c.setup.entry_seq, c.candidate_id))
    cands_in_week = [c for c in cands
                     if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    by_label: dict[str, object] = {}
    for c in cands_in_week:
        label = BRANCH_PATH_CATEGORIES.get(c.setup.path_family)
        if label and label not in by_label:
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
# Stage 4 quality-tier setup pack (structural view only; see structural_
# quality_key). Selection never reads setup.outcome/realized_r/outcome_seq.
# --------------------------------------------------------------------------

def select_quality_tier_examples(result, ps, start_et, end_et):
    cands = [c for c in result["graph_candidates"]
            if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    rej = [c for c in result["graph_rejected"]
          if in_window(c.setup.entry_ts.tz_convert(ET), start_et, end_et)]
    cands_sorted = sorted(cands, key=lambda c: structural_quality_key(c, ps),
                          reverse=True)
    n = len(cands_sorted)
    mid_start = max(0, n // 2 - 2)

    unresolved = sorted(
        [b for b in result["branches"]
         if b.terminal_status == "UNRESOLVED" and b.ordered_event_ids
         and in_window(_event_ts(result["log"].get(b.ordered_event_ids[0])),
                       start_et, end_et)],
        key=lambda b: b.branch_id)[:3]

    rej_chrono = sorted(rej, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    insufficient_rr = [c for c in rej_chrono
                       if c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR"][:3]

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
        "strongest_5": cands_sorted[:5],
        "middle_5": cands_sorted[mid_start:mid_start + 5],
        "weakest_5": list(reversed(cands_sorted[-5:])) if len(cands_sorted) >= 5
                     else list(reversed(cands_sorted)),
        "rejected_5": rej_chrono[:5],
        "unresolved_3": unresolved,
        "insufficient_rr_3": insufficient_rr,
        "natural_rr_ge1_capped_2": natural_ge1,
        "natural_rr_half_to_1_2": natural_half_to_1,
        "policy_variant_pair_2": policy_pairs,
        "dedup_examples_2": dedup_examples,
        # qualified / not-activated-similar-graph filled in separately once
        # evidence_for_subset has annotated qualification (still pre-outcome:
        # selection reads only c.qualification/c.evidence, never c.setup.outcome)
    }


def select_qualification_examples(cands_in_week):
    """Must run AFTER evidence has been annotated on `cands_in_week` (whatever
    subset was actually scored -- see `bounded_qualification_scan`). Reads
    only `qualification`/`reduced_graph` -- never `setup.outcome`/
    `realized_r`/`outcome_seq`. Candidates that were never scored keep the
    dataclass default `qualification == "UNSCORED"` and are simply excluded."""
    chrono = sorted(cands_in_week, key=lambda c: (c.setup.entry_seq, c.candidate_id))
    qualified = [c for c in chrono if c.qualification == "QUALIFIED_PENDING_TRIGGER"][:2]
    # not-activated examples whose reduced graph matches some qualified example
    # (superficially similar graph, different qualification)
    qual_reduced = {c.reduced_graph for c in qualified}
    similar_not_activated = [
        c for c in chrono
        if c.qualification == "RECORDED_NOT_ACTIVATED" and c.reduced_graph in qual_reduced
    ][:2]
    if len(similar_not_activated) < 2:
        # fall back to first not-activated examples if no reduced-graph overlap
        # exists this week (documented fallback, not a substitution of category)
        extra = [c for c in chrono if c.qualification == "RECORDED_NOT_ACTIVATED"
                and c not in similar_not_activated][:2 - len(similar_not_activated)]
        similar_not_activated += extra
    return {"qualified_2": qualified, "not_activated_similar_graph_2": similar_not_activated}


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

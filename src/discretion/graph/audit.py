"""Development audit pack for the graph-native engine.

Deterministic (chronological, never profit-selected) 25-example review pack plus
counts, ledgers and a reproducibility manifest. Large ledgers are gzipped and
gitignored; the compact candidate ledger and manifest (hashes + row counts) are
committed.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os

import pandas as pd

from ..review.charts import render_setup_chart, render_primitive_chart
from ..graph.relationships import RelCtx, evaluate, has_structural_edge
from .pipeline import (
    run_graph_native, build_static_baseline_setups, counts,
    graph_candidate_ledger, ledger_hash,
)

OUT = os.path.join("artifacts", "graph_native")
CHART_DIR = os.path.join(OUT, "charts")


def _sha(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def _origin_family(ps, oid):
    try:
        return ps.registry.get(oid).family
    except Exception:
        return "unknown"


def _first(seq, pred):
    for x in seq:
        if pred(x):
            return x
    return None


def select_examples(result):
    ps = result["engine"].ps
    log = result["log"]
    cands = sorted(result["graph_candidates"], key=lambda c: (c.setup.entry_seq, c.candidate_id))
    # some rare paths are generated (trigger states exist) but reject on RR; fall
    # back to the rejected ledger so the causal path is still demonstrated
    cands_all = sorted(result["graph_candidates"] + result["graph_rejected"],
                       key=lambda c: (c.setup.entry_seq, c.candidate_id))
    branches = result["branches"]
    of = lambda c: _origin_family(ps, c.setup.origin_id)

    # one event advancing multiple branches
    from collections import defaultdict
    adv = defaultdict(set)
    for b in branches:
        for i, e in enumerate(b.ordered_event_ids):
            if i > 0:
                adv[e].add(b.branch_id)
    for t in result["triggers"]:
        adv[t.trigger_event_id].add(t.branch_id)
    multi_ev = next((e for e, s in sorted(adv.items()) if len(s) >= 2), None)

    # an unrelated near-price event correctly rejected from an RB episode
    rej_example = _find_rejected_near_edge(result)

    S = []
    S.append(("01_rb_good_disp_continuation", "candidate",
              _first(cands_all, lambda c: c.setup.path_family == "rb_reaction")))
    S.append(("02_rb_bad_disp_unresolved", "branch",
              _first(sorted(branches, key=lambda b: b.branch_id),
                     lambda b: b.hypothesis_id == "H_rb_unresolved_fade"
                     and b.terminal_status in ("UNRESOLVED", "EXPIRED")
                     and len(b.ordered_event_ids) >= 3)))
    S.append(("03_rb_bad_disp_failure_fade", "candidate",
              _first(cands_all, lambda c: c.setup.path_family == "rb_failure_fade")))
    S.append(("04_fvg_immediate_formation", "candidate",
              _first(cands, lambda c: c.setup.path_family == "fvg_formation"
                     and c.entry_mode == "formation_close")))
    S.append(("05_fvg_continuation_without_fill", "candidate",
              _first(cands, lambda c: c.setup.path_family == "fvg_formation"
                     and "FVG_FIRST_TOUCH" not in c.exact_graph)))
    S.append(("06_fvg_first_touch", "candidate",
              _first(cands, lambda c: c.setup.path_family == "fvg_fill"
                     and c.entry_mode == "first_touch")))
    S.append(("07_fvg_midpoint", "candidate",
              _first(cands, lambda c: c.entry_mode == "midpoint")))
    S.append(("08_fvg_failure_ifvg_immediate", "candidate",
              _first(cands, lambda c: c.setup.path_family == "ifvg_activation")))
    S.append(("09_fvg_failure_ifvg_retest", "candidate",
              _first(cands, lambda c: c.setup.path_family == "ifvg_retest")))
    S.append(("10_sweep_reclaim_fade", "candidate",
              _first(cands, lambda c: c.setup.path_family == "sweep_reclaim_fade")))
    S.append(("11_sweep_acceptance_continuation", "candidate",
              _first(cands, lambda c: c.setup.path_family == "sweep_accept_cont")))
    S.append(("12_time_anchor_reclaim_no_fvg", "candidate",
              _first(cands_all, lambda c: c.setup.path_family == "anchor_reclaim"
                     and not c.setup.has_fvg)))
    S.append(("13_time_anchor_rejection_fade", "candidate",
              _first(cands, lambda c: of(c) == "time_anchor"
                     and c.setup.continuation_or_fade == "fade")))
    S.append(("14_vwap_continuation", "candidate",
              _first(cands_all, lambda c: c.setup.path_family in ("vwap_bounce", "vwap_reclaim",
                     "vwap_break_accept"))))
    S.append(("15_vwap_fade", "candidate",
              _first(cands_all, lambda c: c.setup.path_family == "vwap_band_fade")))
    S.append(("16_compression_expansion", "candidate",
              _first(cands, lambda c: c.setup.path_family == "compression_expansion")))
    S.append(("17_false_expansion_fade", "candidate",
              _first(cands, lambda c: c.setup.path_family == "compression_false_expansion")))
    S.append(("18_one_event_advances_multiple_branches", "event_multi",
              (multi_ev, sorted(adv.get(multi_ev, set())) if multi_ev else [])))
    S.append(("19_unrelated_event_rejected", "rejection", rej_example))
    S.append(("20_graph_native_not_in_static", "candidate",
              _first(cands_all, lambda c: c.setup.path_family in ("rb_fvg_fill", "rb_reaction",
                     "rb_failure_fade"))))
    S.append(("21_rejected_below_half_R", "rejected",
              _first(sorted(result["graph_rejected"], key=lambda c: c.setup.entry_seq),
                     lambda c: True)))
    S.append(("22_natural_half_to_1R", "candidate",
              _first(cands, lambda c: 0.5 <= c.setup.executed_rr < 1.0)))
    S.append(("23_capped_1R", "candidate",
              _first(cands, lambda c: abs(c.setup.executed_rr - 1.0) < 1e-9)))
    S.append(("24_sufficient_prior_evidence", "candidate",
              _first(cands, lambda c: c.qualification == "QUALIFIED_PENDING_TRIGGER")))
    S.append(("25_recorded_not_activated", "candidate",
              _first(cands, lambda c: c.qualification == "RECORDED_NOT_ACTIVATED")))
    return S


def _find_rejected_near_edge(result):
    """Deterministically find an event within ATR proximity of an active RB branch
    that had no structural edge, so it was rejected (proximity != causal edge)."""
    eng = result["engine"]
    ps = eng.ps
    log_events = list(result["log"])
    rb_branches = [b for b in result["branches"] if b.origin_object_id.startswith("RB")]
    ts_to_seq = eng.ts_to_seq
    for b in sorted(rb_branches, key=lambda x: x.branch_id):
        obj = None
        try:
            obj = ps.registry.get(b.origin_object_id)
        except Exception:
            continue
        for ev in log_events:
            if ev.event_type != "vwap":
                continue
            seq = ts_to_seq.get(ev.timestamp_et)
            if seq is None or not (b.origin_seq < seq <= b.expiry):
                continue
            atr = ps.atr[seq] if seq < len(ps.atr) else None
            ctx = RelCtx(atr=atr, ev_seq=seq, branch_dir=b.hypothesis_direction,
                         branch_last_seq=b.last_advanced_seq, reg=ps.registry)
            sat = evaluate(obj, ev, ctx)
            if "WITHIN_SUPPORTING_ATR_PROXIMITY" in sat and not has_structural_edge(sat):
                return {"rb_branch_id": b.branch_id, "rb_object": b.origin_object_id,
                        "rejected_event_id": ev.event_id,
                        "rejected_event_subtype": ev.event_subtype,
                        "relationships_satisfied": sorted(sat),
                        "reason": "within ATR proximity but no structural edge -> "
                                  "rejected (price proximity alone is not a causal edge)"}
    return None


def _cand_detail(result, c):
    ps = result["engine"].ps
    s = c.setup
    b = next((x for x in result["branches"] if x.branch_id == c.source_branch_id), None)
    lineage = []
    if b is not None:
        node = b
        while node is not None and node.parent_branch_id:
            lineage.append(node.parent_branch_id)
            node = next((x for x in result["branches"]
                         if x.branch_id == node.parent_branch_id), None)
    return {
        "candidate_id": c.candidate_id, "branch_id": c.source_branch_id,
        "episode_id": c.source_episode_id, "trigger_event_id": c.trigger_event_id,
        "branch_lineage_parents": lineage,
        "exact_graph": c.exact_graph, "reduced_graph": c.reduced_graph,
        "ordered_event_ids": list(c.ordered_event_ids),
        "ordered_transition_ids": list(c.ordered_transition_ids),
        "relationship_evidence": list(c.relationship_evidence),
        "timestamp_et": str(s.entry_ts.tz_convert("America/New_York")),
        "direction": s.direction, "entry_mode": c.entry_mode,
        "trigger_family": s.path_family, "continuation_or_fade": s.continuation_or_fade,
        "entry": s.entry_price, "stop": s.structural_stop,
        "natural_target": s.structural_target, "natural_rr": round(s.natural_rr, 4),
        "executed_target": s.executed_target, "executed_rr": round(s.executed_rr, 4),
        "stop_anchor": {"type": c.stop_anchor_type, "object": c.stop_anchor_object_id,
                        "price": c.stop_anchor_price},
        "target_anchor": {"type": c.target_anchor_type, "object": c.target_anchor_object_id,
                          "price": c.target_anchor_price},
        "anchor_rule": c.anchor_resolution_rule,
        "parent_fvg_lineage": ({"parent_fvg": c.parent_fvg_id,
                                "fvg_formation": c.fvg_formation_event_id,
                                "fvg_failure": c.fvg_failure_event_id,
                                "ifvg_confirmation": c.ifvg_confirmation_event_id,
                                "retest": c.retest_event_id} if c.parent_fvg_id else None),
        "expiry_rule": s.expiry_rule,
        "evidence_summary": c.evidence.get("summary") if c.evidence else None,
        "qualification": c.qualification,
        "outcome_shown_separately": s.outcome,
    }


def _chart(result, name, kind, obj):
    ps = result["engine"].ps
    path = os.path.join(CHART_DIR, f"{name}.png")
    if kind in ("candidate", "rejected"):
        s = obj.setup
        if s.executed_target == 0.0:
            s.executed_target = s.structural_target
        render_setup_chart(ps.bars, s, path, f"{name}  {obj.candidate_id}")
        return os.path.join("charts", f"{name}.png")
    oid = None
    if kind == "branch":
        oid = obj.origin_object_id
    elif kind == "event_multi" and obj[0]:
        oid = result["log"].get(obj[0]).object_id
    elif kind == "rejection" and obj:
        oid = obj["rb_object"]
    if oid:
        try:
            prim = ps.registry.get(oid)
            render_primitive_chart(ps.bars, prim, path, f"{name}  {oid}")
            return os.path.join("charts", f"{name}.png")
        except Exception:
            return None
    return None


def generate(result, out=OUT):
    os.makedirs(CHART_DIR, exist_ok=True)
    ps = result["engine"].ps
    baseline = build_static_baseline_setups(ps)
    cts = counts(result, baseline)

    manifest = {"counts": cts, "artifacts": []}

    # committed compact candidate ledger
    cl = graph_candidate_ledger(result)
    cl_path = os.path.join(out, "candidates_graph_native.csv")
    pd.DataFrame(cl).to_csv(cl_path, index=False)
    manifest["candidate_ledger_hash"] = ledger_hash(cl)
    manifest["artifacts"].append({"path": cl_path, "rows": len(cl),
                                  "sha256": _sha(cl), "gitignored": False})

    # gzipped large ledgers (gitignored) with hash + rows
    events = [e.to_dict() for e in result["log"]]
    _write_gz(os.path.join(out, "events.jsonl.gz"),
              "\n".join(json.dumps(e, default=str) for e in events))
    manifest["artifacts"].append({"path": os.path.join(out, "events.jsonl.gz"),
                                  "rows": len(events), "sha256": _sha(events),
                                  "gitignored": True})
    brs = [{"branch_id": b.branch_id, "episode_id": b.episode_id,
            "parent_branch_id": b.parent_branch_id, "hypothesis_id": b.hypothesis_id,
            "continuation_or_fade": b.continuation_or_fade,
            "terminal_status": b.terminal_status, "terminal_reason": b.terminal_reason,
            "n_events": len(b.ordered_event_ids)} for b in result["branches"]]
    _write_gz_csv(os.path.join(out, "branches.csv.gz"), brs)
    manifest["artifacts"].append({"path": os.path.join(out, "branches.csv.gz"),
                                  "rows": len(brs), "sha256": _sha(brs), "gitignored": True})
    rej = [{"candidate_id": c.candidate_id, "branch_id": c.source_branch_id,
            "reason": c.setup.rejection_reason, "natural_rr": round(c.setup.natural_rr, 4)}
           for c in result["graph_rejected"]]
    _write_gz_csv(os.path.join(out, "rejected_graph.csv.gz"), rej)
    manifest["artifacts"].append({"path": os.path.join(out, "rejected_graph.csv.gz"),
                                  "rows": len(rej), "sha256": _sha(rej), "gitignored": True})

    # 25 examples
    examples = []
    md = ["# Development Audit Pack — Graph-Native Candidate Engine (v2)", "",
          "July 2025 development data (contaminated). Examples selected "
          "chronologically, never by profit. Candidates are materialized by episode "
          "branches (not build_setups). Outcome shown separately; qualification uses "
          "prior sessions only.", ""]
    for name, kind, obj in select_examples(result):
        md.append(f"## {name}")
        if obj is None or (kind == "event_multi" and not obj[0]):
            md.append("_No qualifying occurrence in the dev window._\n")
            examples.append({"category": name, "example": None})
            continue
        chart_rel = _chart(result, name, kind, obj)
        if kind in ("candidate", "rejected"):
            det = _cand_detail(result, obj)
        elif kind == "branch":
            det = {"branch_id": obj.branch_id, "episode_id": obj.episode_id,
                   "hypothesis_id": obj.hypothesis_id,
                   "terminal_status": obj.terminal_status,
                   "terminal_reason": obj.terminal_reason,
                   "ordered_event_ids": list(obj.ordered_event_ids),
                   "exact_graph_so_far": obj.exact_graph_so_far,
                   "note": "recorded UNRESOLVED branch: bad displacement then "
                           "compression, no failure event -> not a setup"}
        elif kind == "event_multi":
            det = {"event_id": obj[0], "advanced_branch_ids": obj[1],
                   "note": "one event advanced multiple compatible branches"}
        else:  # rejection
            det = obj
        for k, v in det.items():
            md.append(f"- {k}: {v}")
        if chart_rel:
            md.append(f"\n![{name}]({chart_rel})")
        md.append("")
        examples.append({"category": name, "chart": chart_rel, "example": det})

    with open(os.path.join(out, "audit_pack.md"), "w") as fh:
        fh.write("\n".join(md))
    with open(os.path.join(out, "audit_pack.json"), "w") as fh:
        json.dump(examples, fh, indent=2, default=str)
    with open(os.path.join(out, "counts.json"), "w") as fh:
        json.dump(cts, fh, indent=2, default=str)
    manifest["n_examples_populated"] = sum(1 for e in examples if e["example"])
    with open(os.path.join(out, "reproducibility.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest, examples


def _write_gz(path, text):
    with gzip.open(path, "wt") as fh:
        fh.write(text)


def _write_gz_csv(path, rows):
    with gzip.open(path, "wt") as fh:
        pd.DataFrame(rows).to_csv(fh, index=False)

"""Development audit pack: 25 deterministic examples + ledgers + repro manifest.

Examples are selected chronologically (earliest qualifying), never by profit.
Large ledgers (events/episodes/branches) are written gzipped and gitignored; the
compact candidate ledger is committed. Every artifact's path, sha256 and row
count go into a committed reproducibility manifest.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os

import pandas as pd

from ..review.charts import render_setup_chart, render_primitive_chart
from .pipeline import candidate_ledger, ledger_hash

OUT = os.path.join("artifacts", "recognizer")
CHART_DIR = os.path.join(OUT, "charts")


def _origin_primitive(ps, oid):
    try:
        return ps.registry.get(oid)
    except Exception:
        return None


def _first(cands, pred):
    for c in cands:
        if pred(c):
            return c
    return None


def select_examples(result):
    ps = result["engine"].ps
    cands = sorted(result["candidates"], key=lambda c: (c.setup.entry_seq, c.setup.id))
    branches = result["branches"]
    episodes = {e.episode_id: e for e in result["episodes"]}
    log = result["log"]
    ledger = result["ledger"]

    def has(tok, c):
        return tok in c.exact_graph

    S = []  # (name, kind, obj)
    S.append(("01_rb_tap_good_disp_continuation", "candidate", _first(cands,
        lambda c: c.setup.path_family != "fade" and "RB_" in c.exact_graph
        and "GOOD_" in c.exact_graph)))
    # 02: unresolved RB/bad-disp/compression branch
    br2 = next((b for b in branches if b.state == "UNRESOLVED"
                and any("BAD_" in x or x == "COMPRESSION" for x in b.node_subtypes)), None)
    S.append(("02_rb_bad_disp_compression_unresolved", "branch", br2))
    ep_subs = {e.episode_id: [log.get(x).event_subtype for x in e.primitive_event_ids]
               for e in result["episodes"]}

    def ep_has(c, *needles):
        subs = ep_subs.get(c.episode_id, [])
        return all(any(n in s for s in subs) for n in needles)

    S.append(("03_rb_bad_disp_failure_fade", "candidate", _first(cands,
        lambda c: c.branch_state == "FADE" and ep_has(c, "RB_")
        and (ep_has(c, "BAD_") or ep_has(c, "FAILED_CONTINUATION"))
        and (ep_has(c, "FAILURE") or ep_has(c, "REINVERSION") or ep_has(c, "INVALIDATION")))))
    S.append(("04_fvg_formation_immediate_continuation", "candidate", _first(cands,
        lambda c: c.setup.has_fvg and c.setup.entry_mode in ("formation_close", "next_bar")
        and c.branch_state == "CONTINUATION" and "IFVG" not in c.exact_graph)))
    S.append(("05_fvg_formation_continuation_without_fill", "candidate", _first(cands,
        lambda c: c.setup.has_fvg and c.setup.entry_mode in ("formation_close", "next_bar")
        and "FVG_FIRST_TOUCH" not in c.exact_graph and "IFVG" not in c.exact_graph)))
    S.append(("06_fvg_first_touch_continuation", "candidate", _first(cands,
        lambda c: c.setup.has_fvg and c.setup.entry_mode == "first_touch"
        and c.branch_state == "CONTINUATION")))
    S.append(("07_fvg_failure_ifvg_immediate", "candidate", _first(cands,
        lambda c: c.setup.has_ifvg and c.setup.entry_mode in ("formation_close", "next_bar"))))
    S.append(("08_sweep_ifvg_activation", "candidate", _first(cands,
        lambda c: c.setup.has_ifvg and "SWEEP" in c.exact_graph)))
    # sweep-and-fade: the reject/close-back (reclaim within the sweep bar) fades it
    S.append(("09_sweep_reclaim_fade", "candidate", _first(cands,
        lambda c: c.branch_state == "FADE" and c.setup.has_sweep
        and "sweep" in c.setup.graph)))
    # level break -> acceptance -> retest -> continuation
    S.append(("10_sweep_acceptance_continuation", "candidate", _first(cands,
        lambda c: c.branch_state == "CONTINUATION" and "accept" in c.setup.graph)))
    S.append(("11_time_anchor_reclaim_no_fvg", "candidate", _first(cands,
        lambda c: "ANCHOR" in c.exact_graph and "RECLAIM" in c.exact_graph and not c.setup.has_fvg)))
    S.append(("12_time_anchor_rejection_fade", "candidate", _first(cands,
        lambda c: "ANCHOR" in c.exact_graph and c.branch_state == "FADE")))
    S.append(("13_vwap_continuation", "candidate", _first(cands,
        lambda c: c.features.get("origin_family") == "vwap" and c.branch_state == "CONTINUATION")))
    S.append(("14_vwap_fade", "candidate", _first(cands,
        lambda c: c.features.get("origin_family") == "vwap" and c.branch_state == "FADE")))
    S.append(("15_compression_to_expansion", "candidate", _first(cands,
        lambda c: "COMPRESSION" in c.exact_graph or c.features.get("origin_family") == "structure")))
    S.append(("16_false_expansion_fade", "candidate", _first(cands,
        lambda c: c.branch_state == "FADE" and ("EXPANSION" in c.exact_graph
        or "failed_break" in c.setup.graph))))
    S.append(("17_setup_without_fvg_or_ifvg", "candidate", _first(cands,
        lambda c: not c.setup.has_fvg and not c.setup.has_ifvg)))
    # 18: a primitive event correctly NOT a setup (lone FVG formation, never a candidate origin)
    cand_origins = {c.setup.origin_id for c in cands}
    ev18 = next((e for e in log if e.event_subtype.endswith("FVG_FORMED")
                 and e.object_id not in cand_origins), None)
    S.append(("18_primitive_not_a_setup", "event", ev18))
    # 19: multiple raw events merged into one episode
    ep19 = max(result["episodes"], key=lambda e: len(e.primitive_event_ids))
    S.append(("19_events_merged_one_episode", "episode", ep19))
    # 20: one episode with multiple branches
    from collections import Counter
    bcount = Counter(b.episode_id for b in branches)
    multi_ep = next((eid for eid, n in bcount.most_common() if n > 1), None)
    S.append(("20_episode_multiple_branches", "episode", episodes.get(multi_ep)))
    # 21: coherent candidate rejected below 0.5R (from the rejected ledger)
    rej = next((s for s in sorted(ledger.rejected, key=lambda s: s.entry_seq)
                if s.rejection_reason == "INSUFFICIENT_NATURAL_RR"), None)
    S.append(("21_rejected_below_half_R", "rejected_setup", rej))
    S.append(("22_natural_half_to_1R", "candidate", _first(cands,
        lambda c: 0.5 <= c.setup.executed_rr < 1.0)))
    S.append(("23_capped_1R", "candidate", _first(cands,
        lambda c: abs(c.setup.executed_rr - 1.0) < 1e-9)))
    S.append(("24_sufficient_prior_evidence", "candidate", _first(cands,
        lambda c: c.qualification == "QUALIFIED_PENDING_TRIGGER")))
    S.append(("25_recorded_not_activated", "candidate", _first(cands,
        lambda c: c.qualification == "RECORDED_NOT_ACTIVATED"
        and c.evidence["summary"]["effective_sample"] < 4)))
    return S


def _detail(result, kind, obj):
    ps = result["engine"].ps
    log = result["log"]
    if obj is None:
        return None
    if kind in ("candidate",):
        s = obj.setup
        branch = result.get("_branch_by_id", {}).get(obj.branch_id)
        node_ids = list(branch.node_event_ids) if branch else []
        return {
            "kind": kind, "candidate_id": s.id, "episode_id": obj.episode_id,
            "branch_id": obj.branch_id, "primitive_event_ids": node_ids,
            "exact_graph": obj.exact_graph, "reduced_graph": obj.reduced_graph,
            "edge_reasons": [list(e) for e in obj.edge_reasons][:12],
            "timestamp_et": str(s.entry_ts.tz_convert("America/New_York")),
            "direction": s.direction, "trigger": s.entry_mode,
            "entry": s.entry_price, "stop": s.structural_stop,
            "natural_target": s.structural_target, "natural_rr": round(s.natural_rr, 4),
            "executed_target": s.executed_target, "executed_rr": round(s.executed_rr, 4),
            "expiry_rule": s.expiry_rule,
            "evidence_summary": obj.evidence.get("summary"),
            "qualification": obj.qualification,
            "outcome_shown_separately": s.outcome,
        }
    if kind == "rejected_setup":
        s = obj
        return {"kind": kind, "candidate_id": s.id, "exact_or_graph": s.graph,
                "direction": s.direction, "trigger": s.entry_mode,
                "entry": s.entry_price, "stop": s.structural_stop,
                "natural_target": s.structural_target,
                "natural_rr": round(s.natural_rr, 4),
                "rejection_reason": s.rejection_reason, "qualification": "REJECTED_PRE_ENTRY"}
    if kind == "branch":
        return {"kind": kind, "branch_id": obj.branch_id, "episode_id": obj.episode_id,
                "state": obj.state, "exact_graph": obj.exact_signature,
                "primitive_event_ids": list(obj.node_event_ids),
                "depth": obj.depth, "terminated_reason": obj.terminated_reason}
    if kind == "episode":
        return {"kind": kind, "episode_id": obj.episode_id,
                "origin": obj.origin_subtype, "n_objects": len(obj.objects),
                "n_events": len(obj.primitive_event_ids),
                "primitive_event_ids": list(obj.primitive_event_ids)[:16],
                "edge_reasons": [list(e) for e in obj.edges][:12],
                "resolution": obj.resolution}
    if kind == "event":
        return {"kind": kind, "event_id": obj.event_id, "event_subtype": obj.event_subtype,
                "object_id": obj.object_id, "timestamp_et": obj.timestamp_et,
                "note": "primitive event only; no coherent causal path completed the "
                        "six-part setup structure, so it is not a setup"}
    return None


def _chart(result, name, kind, obj):
    ps = result["engine"].ps
    path = os.path.join(CHART_DIR, f"{name}.png")
    title = f"{name}"
    if kind == "candidate":
        render_setup_chart(ps.bars, obj.setup, path, title + f"  {obj.setup.id}")
    elif kind == "rejected_setup":
        # rejected setups have no executed target; use the structural target for
        # display only (the setup is never executed)
        if obj.executed_target == 0.0:
            obj.executed_target = obj.structural_target
        render_setup_chart(ps.bars, obj, path, title + "  (rejected <0.5R)")
    else:
        oid = None
        if kind == "branch":
            oid = result_engine_origin(result, obj.episode_id)
        elif kind == "episode":
            oid = obj.origin_object_id
        elif kind == "event":
            oid = obj.object_id
        prim = _origin_primitive(ps, oid) if oid else None
        if prim is not None:
            render_primitive_chart(ps.bars, prim, path, title + f"  {oid}")
        else:
            return None
    return os.path.join("charts", f"{name}.png")


def result_engine_origin(result, episode_id):
    for e in result["episodes"]:
        if e.episode_id == episode_id:
            return e.origin_object_id
    return None


def _sha_rows(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def generate(result, out=OUT):
    os.makedirs(CHART_DIR, exist_ok=True)
    manifest = {"artifacts": [], "stats": dict(result["stats"])}

    # --- compact candidate ledger (committed) ---
    cl = candidate_ledger(result)
    cl_path = os.path.join(out, "candidates_ledger.csv")
    pd.DataFrame(cl).to_csv(cl_path, index=False)
    manifest["artifacts"].append({"path": cl_path, "rows": len(cl),
                                  "sha256": _sha_rows(cl), "gitignored": False,
                                  "schema": "compact candidate ledger"})
    manifest["candidate_ledger_hash"] = ledger_hash(cl)

    # --- large ledgers (gitignored) with hash + row count committed ---
    events = [e.to_dict() for e in result["log"]]
    ev_path = os.path.join(out, "events.jsonl.gz")
    with gzip.open(ev_path, "wt") as fh:
        for e in events:
            fh.write(json.dumps(e, default=str) + "\n")
    manifest["artifacts"].append({"path": ev_path, "rows": len(events),
                                  "sha256": _sha_rows(events), "gitignored": True,
                                  "schema": "schemas/event.schema.json"})

    eps = [{"episode_id": e.episode_id, "origin_family": e.origin_family,
            "origin_subtype": e.origin_subtype, "n_events": len(e.primitive_event_ids),
            "n_objects": len(e.objects), "resolution": e.resolution,
            "directional_context": e.directional_context} for e in result["episodes"]]
    eps_path = os.path.join(out, "episodes.csv.gz")
    with gzip.open(eps_path, "wt") as fh:
        pd.DataFrame(eps).to_csv(fh, index=False)
    manifest["artifacts"].append({"path": eps_path, "rows": len(eps),
                                  "sha256": _sha_rows(eps), "gitignored": True,
                                  "schema": "episode summary"})

    brs = [{"branch_id": b.branch_id, "episode_id": b.episode_id, "state": b.state,
            "direction": b.direction, "exact_signature": b.exact_signature,
            "depth": b.depth, "terminated_reason": b.terminated_reason}
           for b in result["branches"]]
    br_path = os.path.join(out, "branches.csv.gz")
    with gzip.open(br_path, "wt") as fh:
        pd.DataFrame(brs).to_csv(fh, index=False)
    manifest["artifacts"].append({"path": br_path, "rows": len(brs),
                                  "sha256": _sha_rows(brs), "gitignored": True,
                                  "schema": "branch summary"})

    # --- 25 audit examples ---
    result["_branch_by_id"] = {b.branch_id: b for b in result["branches"]}
    examples = []
    md = ["# Development Audit Pack — Causal Episode Recognizer v1",
          "",
          "July 2025 development data (contaminated). Examples selected "
          "chronologically, never by profit. Outcome shown separately from the "
          "frozen candidate; qualification uses prior sessions only.", ""]
    for name, kind, obj in select_examples(result):
        det = _detail(result, kind, obj)
        md.append(f"## {name}")
        if det is None:
            md.append("_No qualifying occurrence in the dev window._\n")
            examples.append({"category": name, "example": None})
            continue
        chart_rel = _chart(result, name, kind, obj)
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
    manifest["artifacts"].append({"path": os.path.join(out, "audit_pack.json"),
                                  "rows": len(examples), "gitignored": False,
                                  "schema": "audit examples"})
    manifest["n_examples_populated"] = sum(1 for e in examples if e["example"])

    with open(os.path.join(out, "reproducibility.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest, examples

"""Stages 2-7 orchestrator for the review-week structure-and-setup atlas.

Reads the Stage 1 checkpoint (frozen, pre-outcome materialized candidates),
builds the weekly inventory, the deterministic pre-outcome example manifest
(hashed before any candidate's own outcome is read for selection), attaches
outcomes only afterward, renders charts, and writes every required artifact
under artifacts/review_week_atlas_2025_07_14_18/.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import pickle
import sys

import pandas as pd

sys.path.insert(0, "src")

from discretion.graph import review_atlas as ra
from discretion.graph import atlas_charts as ac
from discretion.graph.pipeline import graph_candidate_row

OUT = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
CHART_DIR = os.path.join(OUT, "charts")
CKPT = os.path.join(OUT, "_checkpoint_result.pkl")

START_ET = pd.Timestamp("2025-07-14 00:00:00", tz="America/New_York")
END_ET = pd.Timestamp("2025-07-18 23:59:59", tz="America/New_York")


def load_checkpoint():
    with open(CKPT, "rb") as fh:
        return pickle.load(fh)


def _cand_id_row(c):
    return {
        "candidate_id": c.candidate_id, "branch_id": c.source_branch_id,
        "episode_id": c.source_episode_id, "trigger_event_id": c.trigger_event_id,
        "entry_seq": c.setup.entry_seq, "target_policy_id": c.target_policy_id,
        "path_family": c.setup.path_family, "eligible": c.setup.eligible,
        "rejection_reason": c.setup.rejection_reason,
    }


def build_manifest_part1(result, ps):
    """Every category that never needs qualification/evidence. Runs before any
    evaluate_outcome call anywhere in the process (verified below)."""
    n_uneval = sum(1 for c in result["graph_candidates"] + result["graph_rejected"]
                   if c.setup.outcome == "UNEVALUATED")
    n_total = len(result["graph_candidates"]) + len(result["graph_rejected"])
    assert n_uneval == n_total, "outcomes were evaluated before manifest part 1"

    prim = ra.select_primitive_examples(ps, START_ET, END_ET)
    branch = ra.select_branch_path_examples(result, START_ET, END_ET)
    quality = ra.select_quality_tier_examples(result, ps, START_ET, END_ET)

    manifest = {"primitive_examples": {}, "branch_path_examples": {}, "quality_tier": {}}
    for cat, objs in prim.items():
        rows = []
        for o in objs:
            if isinstance(o, tuple):  # vwap hits: (seq, session, event)
                rows.append({"object_id": o[1].id, "seq": o[0], "note": o[2].note})
            else:
                rows.append({"object_id": o.id, "family": o.family,
                            "created_seq": o.created_seq})
        manifest["primitive_examples"][cat] = rows
    for label, obj in branch.items():
        if hasattr(obj, "candidate_id"):
            manifest["branch_path_examples"][label] = _cand_id_row(obj)
        else:
            manifest["branch_path_examples"][label] = {
                "branch_id": obj.branch_id, "episode_id": obj.episode_id,
                "hypothesis_id": obj.hypothesis_id,
                "terminal_status": obj.terminal_status,
                "terminal_reason": obj.terminal_reason}
    for cat, cands in quality.items():
        manifest["quality_tier"][cat] = [
            _cand_id_row(c) if hasattr(c, "candidate_id") else
            {"branch_id": c.branch_id, "hypothesis_id": c.hypothesis_id,
             "terminal_status": c.terminal_status}
            for c in cands]
    return manifest, prim, branch, quality


def all_selected_candidates(quality, branch):
    out = []
    for k, v in quality.items():
        out.extend(c for c in v if hasattr(c, "candidate_id"))  # skip BranchState (unresolved_3)
    for k, v in branch.items():
        if hasattr(v, "candidate_id"):
            out.append(v)
    # de-dup by candidate_id, keep object identity
    seen = {}
    for c in out:
        seen[c.candidate_id] = c
    return list(seen.values())


def main():
    print("loading checkpoint...", flush=True)
    result = load_checkpoint()
    ps = result["engine"].ps

    print("building pre-outcome manifest part 1 (structural/branch/quality)...", flush=True)
    manifest1, prim, branch, quality = build_manifest_part1(result, ps)

    # Evidence is computed once for every in-week ELIGIBLE candidate (a superset
    # of every example category that can carry qualification -- rejected
    # candidates are never in result["candidates"], so passing them here is a
    # harmless no-op, see review_atlas.evidence_for_subset docstring). This
    # single pass covers both Stage 2's weekly qualified/not-activated counts
    # and every Stage 4B/qualification-dependent example category.
    subset = all_selected_candidates(quality, branch)
    cands_in_week = [c for c in result["graph_candidates"]
                     if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), START_ET, END_ET)]
    print(f"computing evidence for {len(cands_in_week)} in-week candidates "
          f"(covers {len(subset)} selected examples + weekly qualification "
          f"counts in one pass)...", flush=True)
    ra.evidence_for_subset(result, cands_in_week)
    qual_examples = ra.select_qualification_examples(cands_in_week)

    manifest = dict(manifest1)
    manifest["qualification_examples"] = {
        cat: [_cand_id_row(c) for c in cands] for cat, cands in qual_examples.items()}
    manifest["window"] = {"start_et": str(START_ET), "end_et": str(END_ET)}

    pre_hash = ra.manifest_hash(manifest)
    print(f"pre-outcome manifest hash: {pre_hash}", flush=True)

    os.makedirs(CHART_DIR, exist_ok=True)
    with open(os.path.join(OUT, "example_manifest_pre_outcome.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    with open(os.path.join(OUT, "example_manifest_pre_outcome.sha256"), "w") as fh:
        fh.write(pre_hash + "\n")

    # ---------------- Stage 7: outcome attachment (after freeze+hash) --------
    print("attaching outcomes...", flush=True)
    with_outcomes = {"quality_tier": {}, "branch_path_examples": {},
                     "qualification_examples": {}}
    for cat, cands in quality.items():
        rows = []
        for c in cands:
            if not hasattr(c, "candidate_id"):
                # unresolved_3 holds BranchState objects: never triggered, so
                # there is no setup/outcome/evidence to attach.
                rows.append({"branch_id": c.branch_id, "episode_id": c.episode_id,
                            "hypothesis_id": c.hypothesis_id,
                            "terminal_status": c.terminal_status,
                            "terminal_reason": c.terminal_reason,
                            "outcome": "N/A (never triggered)"})
                continue
            row = _cand_id_row(c)
            row.update(ra.attach_outcome(c, ps.bars))
            row["structural_quality"] = ra.structural_quality_vector(c, ps)
            row["adaptive_evidence"] = ra.adaptive_evidence_view(c) if c.evidence else None
            rows.append(row)
        with_outcomes["quality_tier"][cat] = rows
    for label, obj in branch.items():
        if hasattr(obj, "candidate_id"):
            row = _cand_id_row(obj)
            row.update(ra.attach_outcome(obj, ps.bars))
            with_outcomes["branch_path_examples"][label] = row
        else:
            with_outcomes["branch_path_examples"][label] = {
                "branch_id": obj.branch_id, "terminal_status": obj.terminal_status,
                "terminal_reason": obj.terminal_reason}
    for cat, cands in qual_examples.items():
        rows = []
        for c in cands:
            row = _cand_id_row(c)
            row.update(ra.attach_outcome(c, ps.bars))
            row["adaptive_evidence"] = ra.adaptive_evidence_view(c)
            rows.append(row)
        with_outcomes["qualification_examples"][cat] = rows

    with open(os.path.join(OUT, "example_manifest_with_outcomes.json"), "w") as fh:
        json.dump(with_outcomes, fh, indent=2, default=str)

    # ---------------- Stage 2: weekly inventory -------------------------------
    print("building weekly inventory...", flush=True)
    inv = ra.weekly_inventory(result, START_ET, END_ET)
    with open(os.path.join(OUT, "primitive_inventory.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["session", "day", "event_type", "event_subtype"])
        w.writeheader()
        # aggregate raw crosstab to counts
        from collections import Counter
        cnt = Counter((r["session"], r["day"], r["event_type"], r["event_subtype"])
                      for r in inv["raw_crosstab"])
        for (sess, day, et, es), n in sorted(cnt.items()):
            w.writerow({"session": sess, "day": day,
                       "event_type": f"{et}", "event_subtype": f"{es} x{n}"})
    with open(os.path.join(OUT, "mapped_categories.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["session", "day", "category", "count"])
        w.writeheader()
        w.writerows(inv["mapped_categories"])
    with open(os.path.join(OUT, "htf_inventory.json"), "w") as fh:
        json.dump(inv["htf_inventory"], fh, indent=2, default=str)

    # ---------------- ledgers --------------------------------------------------
    print("writing ledgers...", flush=True)
    cands_all = [c for c in result["graph_candidates"]
                if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), START_ET, END_ET)]
    rej_all = [c for c in result["graph_rejected"]
              if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), START_ET, END_ET)]
    rows = [graph_candidate_row(c) for c in cands_all]
    rows.sort(key=lambda r: (r["entry_seq"], r["candidate_id"]))
    with gzip.open(os.path.join(OUT, "candidate_ledger.csv.gz"), "wt", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    dedup = ra.dedup_by_trigger(cands_all + rej_all)
    with open(os.path.join(OUT, "deduplicated_candidates.csv"), "w", newline="") as fh:
        drows = [graph_candidate_row(c) for c in dedup]
        drows.sort(key=lambda r: r["entry_seq"])
        if drows:
            w = csv.DictWriter(fh, fieldnames=list(drows[0].keys()))
            w.writeheader()
            w.writerows(drows)

    with open(os.path.join(OUT, "rejected_candidates.csv"), "w", newline="") as fh:
        rrows = [graph_candidate_row(c) for c in rej_all]
        rrows.sort(key=lambda r: r["entry_seq"])
        if rrows:
            w = csv.DictWriter(fh, fieldnames=list(rrows[0].keys()))
            w.writeheader()
            w.writerows(rrows)

    unresolved = [b for b in result["branches"]
                 if b.terminal_status in ("UNRESOLVED", "EXPIRED") and b.ordered_event_ids
                 and ra.in_window(ra._event_ts(result["log"].get(b.ordered_event_ids[0])),
                                  START_ET, END_ET)]
    with open(os.path.join(OUT, "unresolved_branches.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["branch_id", "episode_id", "hypothesis_id",
                                           "terminal_status", "terminal_reason",
                                           "n_events"])
        w.writeheader()
        for b in unresolved:
            w.writerow({"branch_id": b.branch_id, "episode_id": b.episode_id,
                       "hypothesis_id": b.hypothesis_id,
                       "terminal_status": b.terminal_status,
                       "terminal_reason": b.terminal_reason,
                       "n_events": len(b.ordered_event_ids)})

    episode_rows = [{"episode_id": e.episode_id, "origin_family": e.origin_family,
                     "origin_subtype": e.origin_subtype,
                     "start_timestamp": e.start_timestamp, "segment_id": e.segment_id,
                     "n_branches": len(e.branch_ids)}
                    for e in result["episodes"]
                    if ra.in_window(pd.Timestamp(e.start_timestamp), START_ET, END_ET)]
    with open(os.path.join(OUT, "episode_inventory.csv"), "w", newline="") as fh:
        if episode_rows:
            w = csv.DictWriter(fh, fieldnames=list(episode_rows[0].keys()))
            w.writeheader()
            w.writerows(episode_rows)

    branch_rows = [{"branch_id": b.branch_id, "episode_id": b.episode_id,
                    "parent_branch_id": b.parent_branch_id,
                    "hypothesis_id": b.hypothesis_id,
                    "continuation_or_fade": b.continuation_or_fade,
                    "terminal_status": b.terminal_status,
                    "terminal_reason": b.terminal_reason,
                    "n_events": len(b.ordered_event_ids)}
                   for b in result["branches"] if b.ordered_event_ids
                   and ra.in_window(ra._event_ts(result["log"].get(b.ordered_event_ids[0])),
                                    START_ET, END_ET)]
    with open(os.path.join(OUT, "branch_inventory.csv"), "w", newline="") as fh:
        if branch_rows:
            w = csv.DictWriter(fh, fieldnames=list(branch_rows[0].keys()))
            w.writeheader()
            w.writerows(branch_rows)

    # ---------------- Stage 5: charts + Stage 6: coherence table --------------
    print("rendering charts...", flush=True)
    coherence_rows = []
    chart_n = 0

    def add_chart(chart_id, kind, obj, sel_rule):
        nonlocal chart_n
        chart_n += 1
        fname = f"{chart_n:03d}_{chart_id}.png"
        path = os.path.join(CHART_DIR, fname)
        ok = True
        if kind == "candidate":
            ac.render_candidate_chart(ps.bars, obj, ps, path, chart_id)
        elif kind == "branch":
            ok = ac.render_branch_chart(ps.bars, obj, result["log"], path, chart_id)
        elif kind == "primitive":
            ac.render_primitive_object_chart(ps.bars, obj, path, chart_id, sel_rule)
        if not ok:
            return
        row = {
            "chart_id": chart_id, "file": os.path.join("charts", fname),
            "example_selection_rule": sel_rule,
            "pre_outcome_manifest_hash": pre_hash,
        }
        if kind == "candidate":
            s = obj.setup
            row.update({
                "candidate_or_branch_id": obj.candidate_id,
                "timestamp": str(s.entry_ts), "primitive_family": s.path_family,
                "graph_path": obj.exact_graph,
                "structural_relationship_proof": "; ".join(obj.relationship_evidence[:3]),
                "stop_anchor": obj.stop_anchor_type, "target_anchor": obj.target_anchor_type,
                "target_policy": obj.target_policy_id, "natural_rr": round(s.natural_rr, 4),
                "structural_state": "VALID" if s.eligible else f"REJECTED:{s.rejection_reason}",
                "qualification_state": obj.qualification,
                "outcome_attached_after_selection": s.outcome,
                "potential_audit_concern": "",
            })
        elif kind == "branch":
            row.update({
                "candidate_or_branch_id": obj.branch_id,
                "timestamp": str(result["log"].get(obj.ordered_event_ids[-1]).timestamp_et),
                "primitive_family": obj.hypothesis_id, "graph_path": " -> ".join(obj.exact_graph_so_far),
                "structural_relationship_proof": "", "stop_anchor": "", "target_anchor": "",
                "target_policy": "", "natural_rr": "",
                "structural_state": obj.terminal_status, "qualification_state": "",
                "outcome_attached_after_selection": "N/A (never triggered)",
                "potential_audit_concern": "",
            })
        elif kind == "primitive":
            row.update({
                "candidate_or_branch_id": obj.id, "timestamp": str(obj.created_ts),
                "primitive_family": obj.family, "graph_path": "", "structural_relationship_proof": "",
                "stop_anchor": "", "target_anchor": "", "target_policy": "", "natural_rr": "",
                "structural_state": "OBJECT", "qualification_state": "",
                "outcome_attached_after_selection": "N/A (primitive object)",
                "potential_audit_concern": "",
            })
        coherence_rows.append(row)

    for cat, objs in prim.items():
        for o in objs:
            if isinstance(o, tuple):
                seq, vs, ev = o
                chart_n += 1
                fname = f"{chart_n:03d}_primitive_{cat}.png"
                cpath = os.path.join(CHART_DIR, fname)
                ac.render_vwap_interaction_chart(ps.bars, vs, ev, cpath,
                                                 f"primitive_{cat}")
                coherence_rows.append({
                    "chart_id": f"primitive_{cat}", "file": os.path.join("charts", fname),
                    "example_selection_rule": f"first_distinct:{cat}",
                    "pre_outcome_manifest_hash": pre_hash,
                    "candidate_or_branch_id": vs.id, "timestamp": str(ev.ts_utc),
                    "primitive_family": "vwap", "graph_path": "",
                    "structural_relationship_proof": "", "stop_anchor": "",
                    "target_anchor": "", "target_policy": "", "natural_rr": "",
                    "structural_state": ev.kind, "qualification_state": "",
                    "outcome_attached_after_selection": "N/A (primitive object)",
                    "potential_audit_concern": "",
                })
                continue
            add_chart(f"primitive_{cat}", "primitive", o, f"first_distinct:{cat}")

    for label, obj in branch.items():
        kind = "candidate" if hasattr(obj, "candidate_id") else "branch"
        add_chart(f"path_{label}", kind, obj, f"first_in_category:{label}")

    for cat, cands in quality.items():
        for c in cands:
            if hasattr(c, "candidate_id"):
                add_chart(f"quality_{cat}_{c.candidate_id}", "candidate", c,
                          f"structural_quality_key:{cat}")
            else:  # unresolved_3 holds BranchState objects, not candidates
                add_chart(f"quality_{cat}_{c.branch_id}", "branch", c,
                          f"structural_quality_key:{cat}")

    for cat, cands in qual_examples.items():
        for c in cands:
            add_chart(f"qual_{cat}_{c.candidate_id}", "candidate", c,
                      f"qualification_state:{cat}")

    with open(os.path.join(OUT, "manual_review_sheet.csv"), "w", newline="") as fh:
        fields = ["chart_id", "file", "candidate_or_branch_id", "timestamp",
                  "graph_path", "coherent", "questionable", "incorrect_primitive",
                  "incorrect_causal_relationship", "stop_too_tight", "stop_too_wide",
                  "target_not_genuine", "missed_setup", "false_setup", "wrong_grade",
                  "wrong_similarity", "other_notes"]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in coherence_rows:
            w.writerow({"chart_id": r["chart_id"], "file": r["file"],
                       "candidate_or_branch_id": r["candidate_or_branch_id"],
                       "timestamp": r["timestamp"], "graph_path": r["graph_path"],
                       "coherent": "", "questionable": "", "incorrect_primitive": "",
                       "incorrect_causal_relationship": "", "stop_too_tight": "",
                       "stop_too_wide": "", "target_not_genuine": "", "missed_setup": "",
                       "false_setup": "", "wrong_grade": "", "wrong_similarity": "",
                       "other_notes": ""})

    with open(os.path.join(OUT, "coherence_table.json"), "w") as fh:
        json.dump(coherence_rows, fh, indent=2, default=str)

    # ---------------- reproducibility.json -------------------------------------
    true_sessions_before = ra.count_true_sessions(
        ps.bars, before_date=pd.Timestamp("2025-07-13").date())
    repro = {
        "pre_outcome_manifest_hash": pre_hash,
        "n_charts": chart_n,
        "n_candidates_in_week": len(cands_all),
        "n_rejected_in_week": len(rej_all),
        "n_dedup_triggers_in_week": len(dedup),
        "true_prior_sessions_before_review_week": len(true_sessions_before),
        "window": {"start": str(START_ET), "end": str(END_ET)},
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(repro, fh, indent=2, default=str)

    print(json.dumps(repro, indent=2, default=str))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()

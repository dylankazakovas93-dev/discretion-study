"""Graph-native pipeline (primary) + isolated static baseline + counts.

The graph-native path is the source of candidates: primitives -> canonical events
-> multi-branch engine -> materializer -> prior-only recognizer. The old setup
builders are reachable ONLY through ``build_static_baseline_setups`` and produce a
separate ledger that is never combined with the graph-native one.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from ..data.loader import load_front_month, DATA_FILES
from ..primitives.engine import build_primitives
from .branch_engine import BranchEngine
from .materializer import materialize_all
from ..recognizer import evidence as evidence_mod


def run_graph_native(data_file=None, start=None, end=None, with_evidence=True):
    import os
    data_file = data_file or os.path.join("data", "raw", DATA_FILES["2025-2026"])
    bars = load_front_month(data_file, start=start, end=end)
    ps = build_primitives(bars)
    result = BranchEngine(ps).run()
    materialize_all(result)
    # the recognizer operates on graph-native candidates only
    result["candidates"] = result["graph_candidates"]
    if with_evidence:
        evidence_mod.run(result)
    return result


def build_static_baseline_setups(ps):
    """Diagnostic-only baseline. NOT a source of graph-native candidates. Imported
    lazily so the graph-native pipeline never depends on the old builders."""
    from ..setups.constructor import build_setups
    return build_setups(ps)


def graph_candidate_row(c) -> dict:
    s = c.setup
    ev = c.evidence.get("summary", {}) if c.evidence else {}
    return {
        "candidate_id": c.candidate_id, "source_branch_id": c.source_branch_id,
        "source_episode_id": c.source_episode_id, "trigger_event_id": c.trigger_event_id,
        "direction": s.direction, "entry_mode": c.entry_mode,
        "continuation_or_fade": s.continuation_or_fade,
        "trigger_family": s.path_family,
        "exact_graph": c.exact_graph, "reduced_graph": c.reduced_graph,
        "entry_seq": s.entry_seq, "entry_price": s.entry_price,
        "structural_stop": s.structural_stop, "structural_target": s.structural_target,
        "natural_rr": round(s.natural_rr, 4), "executed_rr": round(s.executed_rr, 4),
        "effective_sample": ev.get("effective_sample"),
        "shrunk_expected_R": ev.get("shrunk_expected_R"),
        "qualification": c.qualification, "outcome": s.outcome,
    }


def graph_candidate_ledger(result) -> list[dict]:
    rows = [graph_candidate_row(c) for c in result["graph_candidates"]]
    rows.sort(key=lambda r: (r["entry_seq"], r["candidate_id"]))
    return rows


def ledger_hash(rows) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def counts(result, baseline_ledger=None) -> dict:
    branches = result["branches"]
    bstatus = Counter(b.terminal_status for b in branches)
    bcf = Counter(b.continuation_or_fade for b in branches)
    cands = result["graph_candidates"]
    quals = Counter(c.qualification for c in cands)
    out = {
        "primitive_events": len(result["log"]),
        "episodes": len(result["episodes"]),
        "branches_created": len(branches),
        "branches_forked": sum(1 for b in branches if b.parent_branch_id),
        "branches_merged": result.get("n_merged", 0),
        "branches_unresolved": bstatus.get("UNRESOLVED", 0),
        "branches_expired": bstatus.get("EXPIRED", 0),
        "branches_invalidated": bstatus.get("INVALIDATED", 0),
        "branches_emitted": bstatus.get("EMITTED", 0),
        "branches_by_cont_fade": dict(bcf),
        "graph_native_raw_trigger_states": len(result["triggers"]),
        "graph_native_candidates": len(cands),
        "graph_native_rejected_below_0p5R": len(result["graph_rejected"]),
        "graph_native_unformed": result.get("unformed_reasons", {}),
        "graph_candidates_by_trigger_mode": dict(Counter(c.entry_mode for c in cands)),
        "graph_candidates_by_cont_fade": dict(Counter(
            c.setup.continuation_or_fade for c in cands)),
        "qualified_graph_native": quals.get("QUALIFIED_PENDING_TRIGGER", 0),
        "not_activated_graph_native": quals.get("RECORDED_NOT_ACTIVATED", 0),
    }
    if baseline_ledger is not None:
        out["static_baseline_candidates"] = len(baseline_ledger.eligible)
        out["static_baseline_rejected"] = len(baseline_ledger.rejected)
    return out

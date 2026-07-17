"""Reproducible end-to-end recognizer pipeline + compact ledger serialization.

One entry point that chains: primitives -> canonical events -> episodes ->
branches/candidates -> representations -> prior-only evidence + gate. Also builds
a compact, deterministic candidate ledger and a content hash for reproducibility
manifests (the large raw ledgers may be gitignored; their hash/row-count are not).
"""

from __future__ import annotations

import hashlib
import json

from ..data.loader import load_front_month, DATA_FILES
from ..primitives.engine import build_primitives
from ..episodes.branches import build_branches_and_candidates
from ..representations.signatures import enrich_candidates
from . import evidence as evidence_mod


def run_recognizer(data_file=None, start=None, end=None):
    import os
    data_file = data_file or os.path.join("data", "raw", DATA_FILES["2025-2026"])
    bars = load_front_month(data_file, start=start, end=end)
    ps = build_primitives(bars)
    result = build_branches_and_candidates(ps)
    enrich_candidates(result)
    evidence_mod.run(result)
    return result


def candidate_row(c) -> dict:
    s = c.setup
    ev = c.evidence.get("summary", {}) if c.evidence else {}
    return {
        "candidate_id": s.id,
        "episode_id": c.episode_id,
        "branch_id": c.branch_id,
        "branch_state": c.branch_state,
        "direction": s.direction,
        "entry_mode": s.entry_mode,
        "continuation_or_fade": s.continuation_or_fade,
        "exact_graph": c.exact_graph,
        "reduced_graph": c.reduced_graph,
        "entry_seq": s.entry_seq,
        "entry_price": s.entry_price,
        "structural_stop": s.structural_stop,
        "structural_target": s.structural_target,
        "natural_rr": round(s.natural_rr, 4),
        "executed_rr": round(s.executed_rr, 4),
        "effective_sample": ev.get("effective_sample"),
        "unique_sessions": ev.get("unique_sessions"),
        "shrunk_expected_R": ev.get("shrunk_expected_R"),
        "uncertainty": ev.get("uncertainty"),
        "qualification": c.qualification,
        "outcome": s.outcome,   # shown separately; never feeds qualification
    }


def candidate_ledger(result) -> list[dict]:
    rows = [candidate_row(c) for c in result["candidates"]]
    rows.sort(key=lambda r: (r["entry_seq"], r["candidate_id"]))
    return rows


def ledger_hash(rows: list[dict]) -> str:
    payload = json.dumps(rows, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()

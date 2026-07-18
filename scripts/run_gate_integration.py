"""Adaptive-gate integration check on a bounded development sub-window.

Confirms the graph-native target-policy candidates flow through the prior-only
recognizer/gate without error. Bounded window (fits one pass); the qualification
counts are mechanical integration output only — NOT an edge or forward claim.

Usage: PYTHONPATH=src python3 scripts/run_gate_integration.py
"""

from __future__ import annotations

import json
from collections import Counter

from discretion.graph.pipeline import run_graph_native

WINDOW = dict(start="2025-07-07", end="2025-07-09")   # 2 dev days, end-exclusive


def main():
    r = run_graph_native(**WINDOW, with_evidence=True)
    cands = r["graph_candidates"]
    qual = Counter(c.qualification for c in cands)
    by_policy_qual = Counter((c.target_policy_id, c.qualification) for c in cands)
    out = {
        "window": "2025-07-07 .. 2025-07-08 UTC (end-exclusive 2025-07-09)",
        "candidates": len(cands),
        "qualification": dict(qual),
        "qualification_by_policy": {f"{p}|{q}": n
                                    for (p, q), n in sorted(by_policy_qual.items())},
        "note": "gate ran without error over policy-tagged candidates; "
                "development data only; not an edge claim",
    }
    print(json.dumps(out, indent=2))
    import os
    os.makedirs("artifacts/mtf_targets", exist_ok=True)
    with open("artifacts/mtf_targets/gate_integration.json", "w") as fh:
        json.dump(out, fh, indent=2)


if __name__ == "__main__":
    main()

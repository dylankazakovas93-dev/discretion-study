"""Development rerun + multi-timeframe target audit pack.

Development (contaminated) window only: 2025-07-06 through 2025-07-11 UTC, NQU5
front month (end-exclusive 2025-07-12). Not July 2026. Nothing here is tuned from
outcomes and nothing is a forward or edge claim; the adaptive gate is run only to
confirm integration.

Usage: PYTHONPATH=src python3 scripts/run_mtf_audit.py
"""

from __future__ import annotations

import json

from discretion.graph.pipeline import run_graph_native
from discretion.graph.mtf_audit import generate_mtf

WINDOW = dict(start="2025-07-06", end="2025-07-12")   # end-exclusive: 06..11 UTC
LABEL = "2025-07-06T00:00Z .. 2025-07-11T23:59:59Z (NQU5, end-exclusive 2025-07-12)"


def main():
    # Target-layer artifacts do not need the adaptive gate; gate integration is
    # confirmed separately (scripts/run_gate_integration.py + recognizer test
    # suite). Running without evidence keeps the 6-day replay inside one pass.
    result = run_graph_native(**WINDOW, with_evidence=False)
    manifest, examples = generate_mtf(result, LABEL)
    print(json.dumps(manifest["counts"], indent=2, default=str))
    print("\nhashes:")
    for k in ("candidate_ledger_hash", "considered_targets_hash", "htf_candle_hash",
              "wick_hash", "htf_fvg_hash"):
        print(f"  {k}: {manifest[k]}")
    print(f"\nexamples populated: {manifest['n_examples_populated']}/25")


if __name__ == "__main__":
    main()

"""Stage 1 runner for the review-week structure-and-setup atlas.

Window (disclosed, see atlas_report.md "Compute budget" section): the
continuous graph-native engine run is bounded by a demonstrated, non-linear
per-session cost in BranchEngine (empirically: a ~2-week continuous window did
not finish BranchEngine within 10+ minutes, while a ~5-6 session window
completes the full graph-native pipeline in well under that). Rather than
silently truncate history without saying so, this script uses the largest
continuous window empirically proven tractable in this environment and the
atlas report states the exact number of true prior CME sessions obtained,
marking adaptive evidence as underpowered exactly as the task instructs for
this situation. No engine code is modified to "make it faster" -- the window
size is a data/config choice only.

Checkpoints the frozen (pre-outcome) materialized result to
artifacts/review_week_atlas_2025_07_14_18/_checkpoint_result.pkl immediately
after materialize_all, before anything reads or evaluates any outcome, so nothing
downstream is lost to an interruption and Stage 3's "before outcome" invariant
is trivially auditable (re-open the checkpoint and confirm every
`setup.outcome == "UNEVALUATED"`).
"""
from __future__ import annotations

import os
import pickle
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

from discretion.data.loader import load_front_month, DATA_FILES
from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.graph.materializer import materialize_all

OUT_DIR = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
CKPT = os.path.join(OUT_DIR, "_checkpoint_result.pkl")

# committed continuous window: 2025-07-11 (Fri, immediate prior-session buffer)
# through the review week end (2025-07-18 23:59:59 ET = 2025-07-19T04:00 UTC,
# end-exclusive). See atlas_report.md for why this is smaller than the
# requested 40 prior sessions.
WINDOW = dict(start="2025-07-11", end="2025-07-19T04:00:00")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data_file = os.path.join("data", "raw", DATA_FILES["2025-2026"])
    t0 = time.time()
    bars = load_front_month(data_file, **WINDOW)
    print(f"load {round(time.time()-t0,1)}s bars={len(bars)}", flush=True)

    t = time.time()
    ps = build_primitives(bars)
    print(f"build_primitives {round(time.time()-t,1)}s", flush=True)

    t = time.time()
    result = BranchEngine(ps).run()
    print(f"branch_engine {round(time.time()-t,1)}s triggers={len(result['triggers'])} "
          f"episodes={len(result['episodes'])} branches={len(result['branches'])}",
          flush=True)

    t = time.time()
    materialize_all(result)
    print(f"materialize {round(time.time()-t,1)}s "
          f"candidates={len(result['graph_candidates'])} "
          f"rejected={len(result['graph_rejected'])}", flush=True)

    # sanity: nothing has evaluated any outcome yet
    n_unevaluated = sum(1 for c in result["graph_candidates"] + result["graph_rejected"]
                        if c.setup.outcome == "UNEVALUATED")
    n_total = len(result["graph_candidates"]) + len(result["graph_rejected"])
    print(f"pre-outcome check: {n_unevaluated}/{n_total} UNEVALUATED", flush=True)

    with open(CKPT, "wb") as fh:
        pickle.dump(result, fh)
    print(f"checkpoint written: {CKPT} ({os.path.getsize(CKPT)} bytes)", flush=True)
    print(f"TOTAL {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    main()

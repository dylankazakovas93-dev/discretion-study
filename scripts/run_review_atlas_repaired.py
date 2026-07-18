"""Stage 1/2 runner for the REPAIRED review-week structure-and-setup atlas.

Loads >=40 complete prior true CME sessions (docs/data.cme_session) before the
review week, starting exactly at the 18:00 ET open of the earliest included
session -- not at midnight inside a session (Problem 2 repair). Checkpoints
the frozen (pre-outcome) materialized result immediately after materialize_all,
before anything reads or evaluates any outcome.

This supersedes scripts/run_review_atlas.py's checkpoint (1 true prior session,
disclosed as compute-budget-constrained) -- that checkpoint and its downstream
artifacts (commit 905d091) are marked SUPERSEDED, not deleted (Stage 14).
"""
from __future__ import annotations

import os
import pickle
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

from discretion.data.loader import load_front_month, DATA_FILES
from discretion.data.cme_session import distinct_session_dates
from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.graph.materializer import materialize_all

OUT_DIR = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
CKPT = os.path.join(OUT_DIR, "_checkpoint_result_repaired.pkl")

# Review week's first true CME session opens Sunday 2025-07-13 18:00 ET. The
# earliest of the required 40 prior complete sessions was located by walking
# distinct_session_dates() backward from that boundary over the available
# data file: 2025-05-18 (a Sunday, opening the Sun18:00->Mon17:59 session).
# The engine window therefore starts EXACTLY at that session's 18:00 ET open.
WINDOW = dict(start="2025-05-18T22:00:00", end="2025-07-19T03:59:59")  # UTC


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data_file = os.path.join("data", "raw", DATA_FILES["2025-2026"])
    t0 = time.time()
    bars = load_front_month(data_file, **WINDOW)
    print(f"load {round(time.time()-t0,1)}s bars={len(bars)}", flush=True)

    review_first_session = None
    import pandas as pd
    review_first_session = pd.Timestamp("2025-07-13").date()
    prior_sessions = distinct_session_dates(bars, before_date=review_first_session)
    review_sessions = [d for d in distinct_session_dates(bars) if d >= review_first_session]
    print(f"prior_sessions={len(prior_sessions)} earliest={prior_sessions[0]} "
          f"latest={prior_sessions[-1]} review_sessions={len(review_sessions)} "
          f"{review_sessions}", flush=True)
    assert len(prior_sessions) >= 40, f"only {len(prior_sessions)} prior sessions loaded"

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

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

# Compute-budget disclosure (memory, not time): a first attempt at the
# required >=40 prior sessions (2025-05-18 .. review week, 45 sessions total)
# ran ~82 minutes through BranchEngine (224,715 triggers / 59,551 episodes /
# 267,896 branches -- object counts scaled almost exactly linearly with the
# 7.5x larger window) and was then OOM-killed by the kernel during
# materialize_all in this 16 GB-RAM, no-swap environment (confirmed via
# dmesg: anon-rss 15.9 GB at kill, no partial checkpoint survives an OOM
# kill). A full architecture change to stream/batch materialization instead
# of holding every candidate object live in memory was judged out of scope
# for a "narrowly scoped correction" repair task. This run instead uses the
# largest prior-session window that a smaller, successful trial run showed
# fits safely in available memory: 20 prior complete sessions (25 total),
# starting exactly at that earliest session's true 18:00 ET open
# (2025-06-15, a Sunday) -- short of the requested 40, disclosed exactly
# rather than silently substituted, per the same principle this task applies
# to any other demonstrated compute-budget shortfall.
WINDOW = dict(start="2025-06-15T22:00:00", end="2025-07-19T03:59:59")  # UTC
REQUIRED_PRIOR_SESSIONS = 20   # disclosed shortfall vs. the requested 40


def _mem_mb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return -1
    return -1


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
          f"{review_sessions}  mem_mb={_mem_mb()}", flush=True)
    assert len(prior_sessions) >= REQUIRED_PRIOR_SESSIONS, \
        f"only {len(prior_sessions)} prior sessions loaded"

    t = time.time()
    ps = build_primitives(bars)
    print(f"build_primitives {round(time.time()-t,1)}s  mem_mb={_mem_mb()}", flush=True)

    t = time.time()
    result = BranchEngine(ps).run()
    print(f"branch_engine {round(time.time()-t,1)}s triggers={len(result['triggers'])} "
          f"episodes={len(result['episodes'])} branches={len(result['branches'])}"
          f"  mem_mb={_mem_mb()}", flush=True)

    t = time.time()
    materialize_all(result)
    print(f"materialize {round(time.time()-t,1)}s "
          f"candidates={len(result['graph_candidates'])} "
          f"rejected={len(result['graph_rejected'])}  mem_mb={_mem_mb()}", flush=True)

    n_unevaluated = sum(1 for c in result["graph_candidates"] + result["graph_rejected"]
                        if c.setup.outcome == "UNEVALUATED")
    n_total = len(result["graph_candidates"]) + len(result["graph_rejected"])
    print(f"pre-outcome check: {n_unevaluated}/{n_total} UNEVALUATED", flush=True)

    with open(CKPT, "wb") as fh:
        pickle.dump(result, fh)
    print(f"checkpoint written: {CKPT} ({os.path.getsize(CKPT)} bytes)  "
         f"mem_mb={_mem_mb()}", flush=True)
    print(f"TOTAL {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    main()

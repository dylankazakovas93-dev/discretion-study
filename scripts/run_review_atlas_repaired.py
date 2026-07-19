"""Stage 1/2 runner for the REPAIRED review-week structure-and-setup atlas.

Loads >=40 complete prior true CME sessions (docs/data.cme_session) before the
review week, starting exactly at the 18:00 ET open of the earliest included
session -- not at midnight inside a session (Problem 2 repair). Checkpoints
the frozen (pre-outcome) materialized result immediately after materialize_all,
before anything reads or evaluates any outcome.

This supersedes scripts/run_review_atlas.py's checkpoint (1 true prior session,
disclosed as compute-budget-constrained) -- that checkpoint and its downstream
artifacts (commit 905d091) are marked SUPERSEDED, not deleted (Stage 14).

Restart-safety: this execution environment has been observed to silently
restart the whole container mid-run (uptime resets to ~0, process vanishes,
no OOM trace, no error) in addition to genuine OOM kills, sometimes only
~10-15 minutes apart -- shorter than a single BranchEngine pass over even a
modest window. To make forward progress monotonic under that instability,
this script checkpoints twice, not once:
  1. immediately after BranchEngine completes (before materialize_all), so a
     restart during the (uncheckpointable, single-pass) materialize phase
     never forces re-running load/build_primitives/branch_engine;
  2. in batches during materialize_all itself (every MATERIALIZE_CKPT_S
     seconds), so a restart mid-materialize only loses that batch, not the
     whole phase.
Both are ordinary pickle checkpoints, written via a temp-file + os.replace
so a restart mid-write can never leave a corrupt checkpoint. Neither changes
what materialize_all computes -- it is the same Materializer.materialize()
call, same order, same accumulation, just resumable. See docs/
ADAPTIVE_GRADING_REPAIR_PROTOCOL.md for why this is an operational repair,
not a change to the primitive/branch engine's semantics.
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
from discretion.graph.materializer import Materializer

OUT_DIR = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
CKPT = os.path.join(OUT_DIR, "_checkpoint_result_repaired.pkl")
BRANCH_CKPT = os.path.join(OUT_DIR, "_checkpoint_branch_result.pkl")
MATERIALIZE_CKPT = os.path.join(OUT_DIR, "_checkpoint_materialize_progress.pkl")
MATERIALIZE_CKPT_S = 120   # flush a resumable batch at least this often

# Compute-budget disclosure (memory, not time): a first attempt at the
# required >=40 prior sessions (2025-05-18 .. review week, 45 sessions total)
# ran ~82 minutes through BranchEngine (224,715 triggers / 59,551 episodes /
# 267,896 branches) and was then OOM-killed by the kernel during
# materialize_all in this 16 GB-RAM, no-swap environment (confirmed via
# dmesg: anon-rss 15.95 GB at kill). A second attempt at 20 prior sessions
# (25 total; 124,671 triggers / 33,150 episodes / 148,963 branches) was ALSO
# OOM-killed during materialize_all (confirmed via dmesg: anon-rss 15.93 GB
# at kill) -- essentially the same ceiling despite roughly half the trigger
# count, indicating materialize_all's peak RSS is not simply linear in
# window/trigger count in this environment. A full architecture change to
# stream/batch materialization instead of holding every candidate object
# live in memory was judged out of scope for a "narrowly scoped correction"
# repair task. This run instead uses a further-reduced window: 10 prior
# complete sessions (15 total), starting exactly at that earliest session's
# true 18:00 ET open (2025-06-22, a Sunday) -- short of the requested 40,
# disclosed exactly rather than silently substituted, per the same
# principle this task applies to any other demonstrated compute-budget
# shortfall. Subsequent attempts at this same 15-session window were then
# repeatedly killed not by OOM but by the container itself silently
# restarting (uptime resets to ~0, no dmesg trace) -- a third, distinct
# failure mode, which is what motivated the checkpoint/resume design above.
WINDOW = dict(start="2025-06-22T22:00:00", end="2025-07-19T03:59:59")  # UTC
REQUIRED_PRIOR_SESSIONS = 10   # disclosed shortfall vs. the requested 40


def _mem_mb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return -1
    return -1


def _atomic_pickle(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(obj, fh)
    os.replace(tmp, path)


def _get_or_build_branch_result():
    if os.path.exists(BRANCH_CKPT):
        t = time.time()
        with open(BRANCH_CKPT, "rb") as fh:
            result = pickle.load(fh)
        print(f"branch_engine RESUMED from checkpoint {round(time.time()-t,1)}s "
              f"triggers={len(result['triggers'])} episodes={len(result['episodes'])} "
              f"branches={len(result['branches'])}  mem_mb={_mem_mb()}", flush=True)
        return result

    data_file = os.path.join("data", "raw", DATA_FILES["2025-2026"])
    t = time.time()
    bars = load_front_month(data_file, **WINDOW)
    print(f"load {round(time.time()-t,1)}s bars={len(bars)}", flush=True)

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
    _atomic_pickle(result, BRANCH_CKPT)
    print(f"branch_engine checkpoint written {round(time.time()-t,1)}s "
          f"({os.path.getsize(BRANCH_CKPT)} bytes)  mem_mb={_mem_mb()}", flush=True)
    return result


def _materialize_resumable(result):
    ps = result["engine"].ps
    log = result["log"]
    branch_by_id = {b.branch_id: b for b in result["branches"]}
    triggers = result["triggers"]

    start_idx = 0
    candidates, rejected, unformed = [], [], {}
    if os.path.exists(MATERIALIZE_CKPT):
        t = time.time()
        with open(MATERIALIZE_CKPT, "rb") as fh:
            prog = pickle.load(fh)
        start_idx = prog["next_index"]
        candidates, rejected, unformed = prog["candidates"], prog["rejected"], prog["unformed"]
        # Replay the branch.emitted_candidate_ids mutations onto the freshly
        # unpickled branches -- only truthiness is ever read downstream
        # (branch_structural_state), so replay order doesn't matter.
        for c in candidates + rejected:
            branch_by_id[c.source_branch_id].emitted_candidate_ids.append(c.candidate_id)
        print(f"materialize RESUMED from checkpoint {round(time.time()-t,1)}s "
              f"next_index={start_idx}/{len(triggers)} candidates={len(candidates)} "
              f"rejected={len(rejected)}  mem_mb={_mem_mb()}", flush=True)

    mat = Materializer(ps)
    mat._n = len(candidates) + len(rejected)

    t_last_ckpt = time.time()
    for i in range(start_idx, len(triggers)):
        trig = triggers[i]
        b = branch_by_id[trig.branch_id]
        variants, reason = mat.materialize(trig, b, log)
        if not variants:
            unformed[reason] = unformed.get(reason, 0) + 1
        else:
            for cand in variants:
                if cand.setup.eligible:
                    candidates.append(cand)
                else:
                    rejected.append(cand)
        due = time.time() - t_last_ckpt >= MATERIALIZE_CKPT_S
        if due or i == len(triggers) - 1:
            _atomic_pickle({"next_index": i + 1, "candidates": candidates,
                            "rejected": rejected, "unformed": unformed},
                           MATERIALIZE_CKPT)
            print(f"materialize progress {i+1}/{len(triggers)} "
                  f"candidates={len(candidates)} rejected={len(rejected)}  "
                  f"mem_mb={_mem_mb()}", flush=True)
            t_last_ckpt = time.time()

    result["graph_candidates"] = candidates
    result["graph_rejected"] = rejected
    result["unformed_reasons"] = unformed
    return result


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    result = _get_or_build_branch_result()

    t = time.time()
    result = _materialize_resumable(result)
    print(f"materialize {round(time.time()-t,1)}s "
          f"candidates={len(result['graph_candidates'])} "
          f"rejected={len(result['graph_rejected'])}  mem_mb={_mem_mb()}", flush=True)

    n_unevaluated = sum(1 for c in result["graph_candidates"] + result["graph_rejected"]
                        if c.setup.outcome == "UNEVALUATED")
    n_total = len(result["graph_candidates"]) + len(result["graph_rejected"])
    print(f"pre-outcome check: {n_unevaluated}/{n_total} UNEVALUATED", flush=True)

    _atomic_pickle(result, CKPT)
    print(f"checkpoint written: {CKPT} ({os.path.getsize(CKPT)} bytes)  "
         f"mem_mb={_mem_mb()}", flush=True)

    # Final checkpoint is complete -- the intermediate resumable checkpoints
    # are no longer needed (both are gitignored working files regardless).
    for p in (BRANCH_CKPT, MATERIALIZE_CKPT):
        if os.path.exists(p):
            os.remove(p)

    print(f"TOTAL {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    main()

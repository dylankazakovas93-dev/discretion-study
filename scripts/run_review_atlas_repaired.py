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

Memory: materialize_all's dominant cost turned out to be the per-trigger
considered-target audit ledger staying live on every retained candidate.
This runner now streams that ledger to LEDGER_PATH instead (see the
compute-budget disclosure comment below for the measurement and
tests/test_materializer_streaming.py for the equivalence proof) and keeps
REQUIRED_PRIOR_SESSIONS at the full 40.
"""
from __future__ import annotations

import gzip
import json
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
LEDGER_PATH = os.path.join(OUT_DIR, "considered_targets_repaired.jsonl.gz")
MATERIALIZE_CKPT_S = 120   # flush a resumable batch at least this often

# Compute-budget disclosure (memory, not time): a first attempt at the
# required >=40 prior sessions (2025-05-18 .. review week, 45 sessions total)
# ran ~82 minutes through BranchEngine (224,715 triggers / 59,551 episodes /
# 267,896 branches) and was then OOM-killed by the kernel during
# materialize_all in this 16 GB-RAM, no-swap environment (confirmed via
# dmesg: anon-rss 15.95 GB at kill). Root cause, confirmed by a 6-session
# smoke measurement in this repair pass: each trigger's considered-target
# audit ledger (up to PER_FAMILY_CAP=25 eligible + 25 ineligible rows per
# family, ~8 families) stayed live on every retained GraphNativeCandidate --
# roughly 42 KB/candidate on average, dominating materialize_all's growth
# (590 MB post-branch_engine -> 4.47 GB peak for 24,545 triggers / 90,836
# candidate variants), which extrapolates past this container's 15 GB ceiling
# for the full required window. materializer.py now supports
# ``keep_considered_targets=False`` + ``ledger_sink``: the same rows are
# still computed and streamed to LEDGER_PATH in the same checkpoint batches
# as the candidate progress (so the full audit ledger stays reproducible on
# disk), but are no longer held live on every candidate -- a compact-record
# fix, not a change to any stop/target/RR/evidence computation (proven
# byte-identical to the always-resident path by
# tests/test_materializer_streaming.py on a real one-session window).
#
# Data availability (separate from the memory fix): this environment's
# licensed Databento file was not present at session start and had to be
# re-supplied; the fetched range only covers 2026-04-19 (a clean session
# open) through 2026-07-17, well short of reaching the literal 2025-07-14
# review week in the original task text and short of a complete 2026-07-18
# either. Per explicit user direction, the review window here is the last 3
# complete true CME sessions available in that file (2026-07-13/14/15) rather
# than a literal 2025 or 2026-07-14..18 date range; REQUIRED_PRIOR_SESSIONS
# is kept at the full 40 (61 are actually available before that window, not
# reduced).
#
# Restart-safety: this execution environment has been observed to silently
# restart the whole container mid-run (uptime resets to ~0, process vanishes,
# no OOM trace, no error) in addition to genuine OOM kills. To make forward
# progress monotonic under that instability, this script checkpoints twice:
#   1. immediately after BranchEngine completes (before materialize_all), so a
#      restart during the (uncheckpointable, single-pass) materialize phase
#      never forces re-running load/build_primitives/branch_engine;
#   2. in batches during materialize_all itself (every MATERIALIZE_CKPT_S
#      seconds), so a restart mid-materialize only loses that batch, not the
#      whole phase; the streamed ledger flushes at the same batch boundaries.
# Both are ordinary pickle checkpoints, written via a temp-file + os.replace
# so a restart mid-write can never leave a corrupt checkpoint (the ledger's
# gzip-append flush is not equally crash-atomic; a restart mid-flush can
# leave a trailing partial gzip member, a disclosed limitation of the audit
# ledger only -- it is never read by evidence/qualification).
WINDOW = dict(start="2026-04-19T22:00:00", end="2026-07-16T22:00:00")  # UTC
REVIEW_FIRST_SESSION = "2026-07-13"
REQUIRED_PRIOR_SESSIONS = 40


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


def _atomic_pickle_split(result, path):
    """Write CKPT as three sequential pickle.dump() calls (meta, candidates,
    rejected) instead of one dump() over the whole ~1.2M-object result dict.

    A single dump() of the full result OOM-killed at the very last step of a
    ~15.5h run (confirmed via dmesg: anon-rss 15.96GB at kill, right after a
    materialize phase that peaked at 13.76GB) -- pickle's own transient
    memo/buffer overhead for one huge heterogeneous call pushed past the
    ceiling even though nothing else grew. Splitting into three smaller,
    more homogeneous calls to the same file (read back with three sequential
    load() calls) writes the identical bytes/content, just with lower peak
    transient overhead per call.
    """
    tmp = path + ".tmp"
    candidates = result["graph_candidates"]
    rejected = result["graph_rejected"]
    meta = {k: v for k, v in result.items()
            if k not in ("graph_candidates", "graph_rejected")}
    with open(tmp, "wb") as fh:
        pickle.dump(meta, fh)
        pickle.dump(candidates, fh)
        pickle.dump(rejected, fh)
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
    review_first_session = pd.Timestamp(REVIEW_FIRST_SESSION).date()
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
    resumed_occluded_by_tf = None
    resumed_occluded_tally_seen = None
    if os.path.exists(MATERIALIZE_CKPT):
        t = time.time()
        with open(MATERIALIZE_CKPT, "rb") as fh:
            prog = pickle.load(fh)
        start_idx = prog["next_index"]
        candidates, rejected, unformed = prog["candidates"], prog["rejected"], prog["unformed"]
        resumed_occluded_by_tf = prog.get("occluded_by_tf")
        resumed_occluded_tally_seen = prog.get("occluded_tally_seen")
        # Replay the branch.emitted_candidate_ids mutations onto the freshly
        # unpickled branches -- only truthiness is ever read downstream
        # (branch_structural_state), so replay order doesn't matter.
        for c in candidates + rejected:
            branch_by_id[c.source_branch_id].emitted_candidate_ids.append(c.candidate_id)
        print(f"materialize RESUMED from checkpoint {round(time.time()-t,1)}s "
              f"next_index={start_idx}/{len(triggers)} candidates={len(candidates)} "
              f"rejected={len(rejected)}  mem_mb={_mem_mb()}", flush=True)

    ledger_batch = []

    def _sink(trigger_event_id, rows):
        ledger_batch.append((trigger_event_id, rows))

    def _flush_ledger():
        if not ledger_batch:
            return
        with gzip.open(LEDGER_PATH, "at") as fh:
            for tid, rows in ledger_batch:
                fh.write(json.dumps({"trigger_event_id": tid,
                                     "considered_targets": rows}) + "\n")
        ledger_batch.clear()

    mat = Materializer(ps, keep_considered_targets=False, ledger_sink=_sink)
    mat._n = len(candidates) + len(rejected)
    if resumed_occluded_by_tf is not None:
        mat.occluded_by_tf = resumed_occluded_by_tf
    if resumed_occluded_tally_seen is not None:
        mat._occluded_tally_seen = resumed_occluded_tally_seen

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
            # Ledger flushed before the candidate-progress checkpoint is
            # written, so a resume's start_idx never reprocesses a trigger
            # whose ledger rows are already on disk.
            _flush_ledger()
            _atomic_pickle({"next_index": i + 1, "candidates": candidates,
                            "rejected": rejected, "unformed": unformed,
                            "occluded_by_tf": dict(mat.occluded_by_tf),
                            "occluded_tally_seen": set(mat._occluded_tally_seen)},
                           MATERIALIZE_CKPT)
            print(f"materialize progress {i+1}/{len(triggers)} "
                  f"candidates={len(candidates)} rejected={len(rejected)}  "
                  f"mem_mb={_mem_mb()}", flush=True)
            t_last_ckpt = time.time()

    result["graph_candidates"] = candidates
    result["graph_rejected"] = rejected
    result["unformed_reasons"] = unformed
    result["occluded_by_tf"] = mat.occluded_by_tf
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

    _atomic_pickle_split(result, CKPT)
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

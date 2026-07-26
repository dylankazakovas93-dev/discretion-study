"""Stage A -- candidate-side finalization, loading ONLY the materialize
checkpoint (never the branch checkpoint).

Root cause this repairs: a single-process pickle of the full branch_engine
graph AND all 1.193M materialized candidates OOM-killed a ~15.5h run at the
very last step (dmesg-confirmed, anon-rss 15.96GB at kill, right after
materialize itself peaked at a safe 13.76GB). The two checkpoints that
survived that kill (_checkpoint_branch_result.pkl,
_checkpoint_materialize_progress.pkl) are read-only inputs here; neither is
modified, deleted, or recreated as one combined pickle.

The ONLY operation that genuinely needs the full 1.193M-candidate universe
resident at once is prior-only evidence scoring itself (the comparable pool
for a review-week candidate spans every prior session's candidates, not just
the review week's few thousand) -- everything else downstream (ledgers,
example selection, manifest, charts, inventories) only ever reads the
review-week-scoped subset, confirmed by reading every consumer in
review_atlas.py/build_review_atlas_repaired.py before writing this split.
So Stage A does exactly that one expensive step and hands off the small
scored subset (a few thousand candidates, not 1.193M) to finalize_stage_b.py,
which loads the branch checkpoint and does everything else.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time

import pandas as pd

sys.path.insert(0, "src")
sys.stdout.reconfigure(line_buffering=True)

from discretion.graph import review_atlas as ra
from discretion.recognizer.evidence import run_indexed_one_trigger_one_policy

OLD_OUT = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
OUT = os.path.join("artifacts", "review_week_atlas_2025_07_14_18_repaired")
MATERIALIZE_CKPT = os.path.join(OLD_OUT, "_checkpoint_materialize_progress.pkl")
BRANCH_LIGHT = os.path.join(OLD_OUT, "_branch_light.pkl")   # bars only (1st object)
RUN_METADATA = os.path.join(OLD_OUT, "_run_metadata.json")
HANDOFF = os.path.join(OUT, "_stage_a_handoff.pkl")

EXPECTED_NEXT_INDEX = 312920
EXPECTED_CANDIDATES = 777801
EXPECTED_REJECTED = 415320
EXPECTED_TOTAL = 1193121


def _mem_mb():
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return -1


class _BarsOnlyPs:
    """The only attribute evidence.prepare()/attach_outcome() read off
    result["engine"].ps in this stage: .bars. Everything else in a real
    PrimitiveSet (registry, wicks, htf structures, ...) lives in the branch
    checkpoint and is intentionally not reconstructed here."""
    def __init__(self, bars):
        self.bars = bars


class _BarsOnlyEngine:
    def __init__(self, bars):
        self.ps = _BarsOnlyPs(bars)


def load_materialize_checkpoint():
    t = time.time()
    with open(MATERIALIZE_CKPT, "rb") as fh:
        prog = pickle.load(fh)
    print(f"loaded MATERIALIZE_CKPT {round(time.time()-t,1)}s mem_mb={_mem_mb()}",
         flush=True)
    return prog


def load_bars():
    with open(BRANCH_LIGHT, "rb") as fh:
        return pickle.load(fh)   # first pickled object is bars; rest ignored


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(RUN_METADATA) as fh:
        meta = json.load(fh)
    start_et = pd.Timestamp(meta["review_start_et"], tz=ra.ET)
    end_et = pd.Timestamp(meta["review_end_et"], tz=ra.ET)

    prog = load_materialize_checkpoint()
    assert prog["next_index"] == EXPECTED_NEXT_INDEX, prog["next_index"]
    candidates, rejected = prog["candidates"], prog["rejected"]
    assert len(candidates) == EXPECTED_CANDIDATES, len(candidates)
    assert len(rejected) == EXPECTED_REJECTED, len(rejected)
    assert len(candidates) + len(rejected) == EXPECTED_TOTAL
    n_uneval = sum(1 for c in candidates + rejected if c.setup.outcome == "UNEVALUATED")
    assert n_uneval == EXPECTED_TOTAL, \
        f"expected all {EXPECTED_TOTAL} UNEVALUATED pre-outcome, got {n_uneval}"
    print(f"verified: candidates={len(candidates)} rejected={len(rejected)} "
         f"total={EXPECTED_TOTAL} all UNEVALUATED  mem_mb={_mem_mb()}", flush=True)

    bars = load_bars()
    print(f"loaded bars={len(bars)}  mem_mb={_mem_mb()}", flush=True)

    result = {
        "graph_candidates": candidates, "graph_rejected": rejected,
        "unformed_reasons": prog["unformed"],
        "occluded_by_tf": prog.get("occluded_by_tf", {}),
        "candidates": candidates,        # pipeline.py's alias evidence.prepare() reads
        "engine": _BarsOnlyEngine(bars),
    }

    cands_in_week = [c for c in result["graph_candidates"]
                     if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), start_et, end_et)]
    print(f"scoring the full one-trigger/one-policy review-week universe "
         f"({len(cands_in_week)} candidate rows before dedup) against the full "
         f"{EXPECTED_TOTAL}-candidate prior-only comparable pool...", flush=True)
    t = time.time()
    result, scored_set = run_indexed_one_trigger_one_policy(result, restrict_to=cands_in_week)
    print(f"scored {len(scored_set)} one-trigger/one-policy review-week candidates "
         f"{round(time.time()-t,1)}s  mem_mb={_mem_mb()}", flush=True)

    rej_in_week = [c for c in result["graph_rejected"]
                  if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), start_et, end_et)]

    # Hand off ONLY the review-week-scoped subset (a few thousand candidates,
    # already scored) plus the one full-population aggregate Stage B needs
    # (occluded_by_tf, already reduced to 4 numbers) -- never the full
    # 1.193M-candidate universe.
    handoff = {
        "cands_in_week": cands_in_week, "rej_in_week": rej_in_week,
        "occluded_by_tf": result["occluded_by_tf"],
        "n_one_trigger_one_policy_scored": len(scored_set),
    }
    tmp = HANDOFF + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(handoff, fh)
    os.replace(tmp, HANDOFF)
    print(f"handoff written: {HANDOFF} ({os.path.getsize(HANDOFF)} bytes) "
         f"mem_mb={_mem_mb()}", flush=True)
    print("STAGE_A_DONE", flush=True)


if __name__ == "__main__":
    main()

"""Stage A0 -- extract only what candidate-side finalization needs from the
branch checkpoint (bars, branches, log) into a small separate file, so Stage A
never has to load the full BRANCH_CKPT (episodes/triggers/engine/ps/registry/
wicks/htf structures) alongside the 1.19M-candidate materialize checkpoint in
the same process. Loads ONLY _checkpoint_branch_result.pkl -- never touches
_checkpoint_materialize_progress.pkl. Exits immediately after writing.
"""
from __future__ import annotations

import os
import pickle
import sys
import time

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = os.path.join("artifacts", "review_week_atlas_2025_07_14_18")
BRANCH_CKPT = os.path.join(OUT_DIR, "_checkpoint_branch_result.pkl")
BRANCH_LIGHT = os.path.join(OUT_DIR, "_branch_light.pkl")


def _mem_mb():
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return -1


def main():
    t0 = time.time()
    with open(BRANCH_CKPT, "rb") as fh:
        result = pickle.load(fh)
    print(f"loaded BRANCH_CKPT {round(time.time()-t0,1)}s mem_mb={_mem_mb()}", flush=True)

    bars = result["engine"].ps.bars
    branches = result["branches"]
    log = result["log"]
    print(f"extracted bars={len(bars)} branches={len(branches)} "
          f"log_events={len(log)}", flush=True)

    tmp = BRANCH_LIGHT + ".tmp"
    t = time.time()
    with open(tmp, "wb") as fh:
        pickle.dump(bars, fh)
        pickle.dump(branches, fh)
        pickle.dump(log, fh)
    os.replace(tmp, BRANCH_LIGHT)
    print(f"branch_light written {round(time.time()-t,1)}s "
          f"({os.path.getsize(BRANCH_LIGHT)} bytes) mem_mb={_mem_mb()}", flush=True)
    print(f"TOTAL {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    main()

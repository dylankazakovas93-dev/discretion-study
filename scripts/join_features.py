"""Join Stage-1 causal features onto the candidate stream at DECISION TIME.

For each candidate the feature row is taken at index (entry_bar_index - 1):
the last fully completed 1m bar strictly before the decision bar. The decision
bar itself is never read. Development years only.
"""
from __future__ import annotations
import pickle, os, glob, numpy as np, json
from collections import defaultdict

DEV_YEARS = (2018, 2025)
OUT = "artifacts/broad_discovery"
CK = "artifacts/multiyear_validation_v2/checkpoints"

def seg_index_from_gvid(g): return int(g.split("::")[0][3:6])

if __name__ == "__main__":
    cands = []
    ckpts = sorted(glob.glob(os.path.join(CK, "*.pkl")))
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("mv2", "scripts/multiyear_validation_v2.py")
    m = importlib.util.module_from_spec(spec); sys.modules["mv2"] = m; sys.modules["__main__"] = m
    spec.loader.exec_module(m)
    for p in ckpts:
        ck = pickle.load(open(p, "rb"))
        orec = {x.gvid: x for x in ck["orecs"]}
        for v in ck["vrecs"]:
            o = orec.get(v.gvid)
            if o is None or o.r_multiple == 0: continue
            if not (DEV_YEARS[0] <= v.session_date.year <= DEV_YEARS[1]): continue
            risk = abs(o.points / o.r_multiple)
            if risk <= 0: continue
            cands.append({"gvid": v.gvid, "sd": v.session_date, "entry_ts": v.entry_ts,
                          "exit_ts": o.exit_ts, "fkey": v.fkey, "r": o.r_multiple,
                          "points": o.points, "risk": risk, "session": v.session,
                          "entry_variant": v.entry_variant, "direction": v.direction,
                          "exit_type": o.exit_type, "lane": v.lane,
                          "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
                          "natural_rr": v.natural_rr, "target_family": v.target_family,
                          "reaction_state": v.reaction_state})
    print(f"candidates (dev years): {len(cands):,}", flush=True)
    by_seg = defaultdict(list)
    for c in cands: by_seg[seg_index_from_gvid(c["gvid"])].append(c)

    FE = ["vwap_", "vwsd_", "vwslope_", "ema21_", "emaslope_", "adx_", "pdi_", "ndi_"]
    joined, missing, leak_guard = [], 0, 0
    for si, group in sorted(by_seg.items()):
        fp = os.path.join(OUT, f"feat_{si:03d}.pkl")
        if not os.path.exists(fp): missing += len(group); continue
        D = pickle.load(open(fp, "rb"))
        if D.get("empty"): missing += len(group); continue
        F, tsi = D["feat"], D["ts_index"]
        for c in group:
            i = tsi.get(c["entry_ts"])
            if i is None or i < 1: missing += 1; continue
            j = i - 1                       # CAUSAL SHIFT: last completed bar
            leak_guard += 1
            row = dict(c)
            px = float(F["close"][j])
            row["_px"] = px
            for k, arr in F.items():
                if any(k.startswith(pfx) for pfx in FE):
                    row[k] = float(arr[j])
            joined.append(row)
    print(f"joined: {len(joined):,}   missing feature row: {missing:,}", flush=True)
    print(f"causal shift applied to every joined row: {leak_guard:,}", flush=True)
    pickle.dump(joined, open(os.path.join(OUT, "candidates_with_features.pkl"), "wb"))
    ex = joined[0]
    print("\nsample joined candidate (decision-time features):")
    for k in sorted(ex):
        if k.startswith(("vwap_CASH", "ema21_", "adx_")) or k in ("gvid", "entry_ts", "_px"):
            print(f"   {k}: {ex[k]}")

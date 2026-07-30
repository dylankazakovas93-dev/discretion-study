"""
Parallel SIM run: 4 workers across segcache segments.
Produces AUDIT_SIM_RESULTS.csv. Skips reconciliation entirely.
Uses 1.25RR_BE30 (best from fast sweep) as the base parameter.
After this finishes, fast_rr_sweep.py re-simulates at all other RR in seconds.
"""
from __future__ import annotations

import csv
import dataclasses
import importlib.util
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "src")

SEG_DIR  = "artifacts/multiyear_validation_v2/segcache"
OUT_DIR  = "artifacts"
MAXH     = 480
TARGET_WINDOW = 600
VWAP_Z   = 1.0
SESSION  = "NY_AM"
FAMILY   = "rb"
CTFS     = (1, 3, 5)
TP_K     = 1.5          # best from fast sweep
SL_K     = 1.5 / 1.25
BE_BAR   = 30
N_WORKERS = 3           # conservative: avoids OOM on 15GB box with 4 CPUs


def _worker(seg_idx):
    """Run in a child process. Returns list of trade dicts."""
    import sys, os, dataclasses, importlib.util, pickle, time
    import numpy as np
    sys.path.insert(0, "src")

    from discretion.setup_observer.observer import observe
    from discretion.execution.simulator import simulate_trade

    fe_spec = importlib.util.spec_from_file_location(
        "feature_engine", "scripts/feature_engine.py")
    FE = importlib.util.module_from_spec(fe_spec)
    fe_spec.loader.exec_module(FE)

    with open(os.path.join(SEG_DIR, "manifest.json")) as f:
        import json
        manifest = json.load(f)

    contract = manifest["contracts"][seg_idx]
    pkl = os.path.join(SEG_DIR, f"seg{seg_idx:03d}.pkl")
    sbars = pickle.load(open(pkl, "rb"))

    year = sbars[0].ts_et.year if sbars else 0
    if year >= 2026:
        print(f"  seg{seg_idx:03d} {contract} ({year}): skip 2026", flush=True)
        return []

    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n = len(local)

    t0 = time.time()
    _ev, variants, _diag = observe(local, target_window=TARGET_WINDOW)
    F = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    h_ = np.array([b.high  for b in local])
    l_ = np.array([b.low   for b in local])
    o_ = np.array([b.open  for b in local])
    c_ = np.array([b.close for b in local])
    ts_ = [b.ts_et for b in local]

    def wilder_atr24(h, l, c):
        nn = len(h)
        tr = np.empty(nn); tr[0] = h[0]-l[0]
        for i in range(1, nn):
            tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        atr = np.empty(nn); atr[0] = tr[0]; k = 1/24
        for i in range(1, nn):
            atr[i] = atr[i-1]*(1-k)+tr[i]*k
        return atr

    atr24 = wilder_atr24(h_, l_, c_)
    trades = []

    for v in variants:
        if not v.executable: continue
        if getattr(v, "session", None) != SESSION: continue
        if getattr(v, "context_family", None) != FAMILY: continue
        if getattr(v, "context_tf", None) not in CTFS: continue

        i = ti.get(v.entry_ts, -1)
        if i < 1: continue

        px = float(F["close"][i-1])
        vw = float(F["vwap_CASH_0930"][i-1])
        sd = max(float(F["vwsd_CASH_0930"][i-1]), 1e-9)
        if abs((px - vw) / sd) >= VWAP_Z: continue

        risk = float(atr24[i-1])
        if risk <= 0: continue

        d  = v.direction
        ep = float(o_[i])
        sl = ep - d * SL_K * risk
        tp_pts = TP_K * risk

        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE") if v.targets else None
        if prim is None: continue

        xt, bar_off, xp, r = simulate_trade(
            local[i:], ep=ep, direction=d, tp_pts=tp_pts, sl_orig=sl,
            be_bar=BE_BAR, max_hold=MAXH)
        xts = ts_[min(i + bar_off, n - 1)]

        trades.append({
            "episode_id":    v.episode_id,
            "variant_id":    v.variant_id,
            "entry_variant": v.entry_variant,
            "direction":     d,
            "entry_ts":      str(v.entry_ts),
            "exit_ts":       str(xts),
            "exit_type":     xt,
            "ep":            ep,
            "sl":            sl,
            "risk":          risk,
            "tp_pts":        tp_pts,
            "exit_price":    xp,
            "pts":           r * risk,
            "r":             r,
            "context_family": v.context_family,
            "context_tf":    getattr(v, "context_tf", None),
            "trigger_tf":    getattr(v, "trigger_tf", None),
            "context_id":    getattr(v, "context_id", None),
            "context_zone_lo": v.context_zone[0] if v.context_zone else None,
            "context_zone_hi": v.context_zone[1] if v.context_zone else None,
            "contract":      contract,
        })

    elapsed = round(time.time() - t0, 1)
    print(f"  seg{seg_idx:03d} {contract}: {len(variants):,} variants → "
          f"{len(trades)} trades  [{elapsed}s]", flush=True)
    return trades


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(SEG_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    n_segs = manifest["n_segments"]

    print(f"Parallel SIM: {n_segs} segments, {N_WORKERS} workers", flush=True)
    print(f"Params: TP={TP_K}R  SL={SL_K:.4f}R  BE={BE_BAR}  |z|<{VWAP_Z}", flush=True)
    t_start = time.time()

    with Pool(processes=N_WORKERS) as pool:
        results = pool.map(_worker, range(n_segs))

    all_trades = [t for seg in results for t in seg]
    print(f"\nTotal raw trades: {len(all_trades)}  "
          f"[{round(time.time()-t_start,1)}s total]", flush=True)

    # Occupancy filter
    all_trades.sort(key=lambda t: (t["entry_ts"], t["episode_id"]))
    occ = []
    until = None
    for t in all_trades:
        if until is not None and t["entry_ts"] < until:
            continue
        occ.append(t)
        until = t["exit_ts"]

    # Summary
    r_arr = np.array([t["r"] for t in occ])
    gp = r_arr[r_arr > 0].sum()
    lp = -r_arr[r_arr <= 0].sum()
    pf  = gp / lp if lp > 0 else float("inf")
    win = (r_arr > 0).mean()
    print(f"After occupancy: {len(occ)} trades  PF={pf:.4f}  "
          f"net={r_arr.sum():+.1f}R  win={win*100:.1f}%", flush=True)

    # Year breakdown
    from collections import defaultdict
    by_year = defaultdict(list)
    for t in occ:
        y = t["entry_ts"][:4]
        by_year[y].append(t["r"])
    print(f"\n{'Year':>4}  {'n':>5}  {'PF':>8}  {'net':>9}  {'win%':>6}")
    for y in sorted(by_year):
        r_y = np.array(by_year[y])
        gp_y = r_y[r_y>0].sum(); lp_y = -r_y[r_y<=0].sum()
        pf_y = gp_y/lp_y if lp_y>0 else float("inf")
        print(f"  {y}  {len(r_y):>5}  {pf_y:>8.4f}  {r_y.sum():>+9.1f}R  "
              f"{100*(r_y>0).mean():>5.1f}%")

    # Write CSV
    sim_path = os.path.join(OUT_DIR, "AUDIT_SIM_RESULTS.csv")
    fields = ["episode_id","variant_id","entry_variant","direction",
              "entry_ts","exit_ts","exit_type","ep","sl","risk",
              "tp_pts","exit_price","pts","r","context_family",
              "context_tf","trigger_tf","context_id",
              "context_zone_lo","context_zone_hi","contract"]
    with open(sim_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(occ)
    print(f"\nWrote {sim_path}", flush=True)
    print("Done.", flush=True)

"""
Parameter sweep: test multiple TP/SL combinations in one pass.
observe() runs once per segment; simulation reruns cheaply per param set.
Filters: executable + NY_AM + rb + ctf{1,3,5} + |VWAP z|<1.0

Parameter grid:
  label        TP_K   SL_K    RR_gross   BE_bar
  0.7RR_BE30   1.5    2.143   0.700      30
  1.0RR_BE30   1.5    1.5     1.000      30
  1.25RR_BE30  1.5    1.2     1.250      30
  2.0RR_BE30   2.0    1.0     2.000      30
  0.7RR_NOBE   1.5    2.143   0.700      9999  (BE never triggers within 480 bars)
  1.0RR_NOBE   1.5    1.5     1.000      9999
"""
from __future__ import annotations

import csv
import dataclasses
import importlib.util
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, "src")

from discretion.setup_observer.observer import observe
from discretion.execution.simulator import simulate_trade, occupancy_filter

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

SEG_DIR = "artifacts/multiyear_validation_v2/segcache"
OUT_DIR  = "artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

MAXH   = 480
TARGET_WINDOW = 600
VWAP_Z = 1.0
SESSION = "NY_AM"
FAMILY  = "rb"
CTFS    = (1, 3, 5)

PARAMS = [
    {"label": "0.7RR_BE30",  "tp": 1.5, "sl": 1.5/0.7,  "be": 30},
    {"label": "1.0RR_BE30",  "tp": 1.5, "sl": 1.5,       "be": 30},
    {"label": "1.25RR_BE30", "tp": 1.5, "sl": 1.5/1.25,  "be": 30},
    {"label": "2.0RR_BE30",  "tp": 2.0, "sl": 1.0,       "be": 30},
    {"label": "0.7RR_NOBE",  "tp": 1.5, "sl": 1.5/0.7,   "be": 9999},
    {"label": "1.0RR_NOBE",  "tp": 1.5, "sl": 1.5,       "be": 9999},
]

import json
with open(os.path.join(SEG_DIR, "manifest.json")) as f:
    manifest = json.load(f)
n_segs = manifest["n_segments"]
contracts = manifest["contracts"]


def wilder_atr24(h, l, c):
    n = len(h)
    tr = np.empty(n); tr[0] = h[0]-l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    atr = np.empty(n); atr[0] = tr[0]; k = 1/24
    for i in range(1, n):
        atr[i] = atr[i-1]*(1-k) + tr[i]*k
    return atr


# accumulate raw (pre-occupancy) trades per param label
raw = {p["label"]: [] for p in PARAMS}

for seg_idx in range(n_segs):
    contract = contracts[seg_idx]
    pkl = os.path.join(SEG_DIR, f"seg{seg_idx:03d}.pkl")
    t0 = time.time()
    sbars = pickle.load(open(pkl, "rb"))
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n = len(local)

    year = local[0].ts_et.year
    # skip 2026 partial year
    if year >= 2026:
        print(f"  seg{seg_idx:03d} {contract} ({year}): skipped (2026 partial)", flush=True)
        continue

    _ev, variants, _diag = observe(local, target_window=TARGET_WINDOW)
    F = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    h_ = np.array([b.high  for b in local])
    l_ = np.array([b.low   for b in local])
    o_ = np.array([b.open  for b in local])
    c_ = np.array([b.close for b in local])
    ts_ = [b.ts_et for b in local]
    atr24 = wilder_atr24(h_, l_, c_)

    seg_n = 0
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

        d = v.direction
        ep = float(o_[i])
        bars_slice = local[i:]

        for p in PARAMS:
            sl = ep - d * p["sl"] * risk
            tp_pts = p["tp"] * risk
            xt, bar_off, xp, r = simulate_trade(
                bars_slice, ep=ep, direction=d,
                tp_pts=tp_pts, sl_orig=sl,
                be_bar=p["be"], max_hold=MAXH)
            xts = ts_[min(i + bar_off, n - 1)]
            raw[p["label"]].append({
                "e": v.entry_ts, "xts": xts, "r": r,
                "xt": xt, "sd": v.session_date_et,
                "episode_id": v.episode_id,
            })
        seg_n += 1

    elapsed = round(time.time() - t0, 1)
    print(f"  seg{seg_idx:03d} {contract}: {len(variants):,} variants  "
          f"cands={seg_n}  [{elapsed}s]", flush=True)


print("\n" + "="*65)
print("PARAMETER SWEEP RESULTS  2018-2025  NY_AM RB ctf{1,3,5}  |z|<1")
print("="*65)
print(f"{'Label':<16} {'raw':>5}  {'occ':>5}  {'PF':>8}  {'netR':>9}  {'win%':>6}  "
      f"{'T':>5}  {'S':>5}  {'t':>5}")
print("-"*75)

summary_rows = []
for p in PARAMS:
    trades = raw[p["label"]]
    occ = occupancy_filter(trades)
    if not occ:
        print(f"  {p['label']:<14}  no trades", flush=True)
        continue
    r_arr = np.array([t["r"] for t in occ])
    gp = r_arr[r_arr > 0].sum()
    lp = -r_arr[r_arr <= 0].sum()
    pf = gp / lp if lp > 0 else float("inf")
    net_r = r_arr.sum()
    win = (r_arr > 0).mean()
    xt_counts = defaultdict(int)
    for t in occ: xt_counts[t["xt"]] += 1

    # year-by-year
    yrs = sorted(set(t["sd"].year for t in occ))
    green = sum(1 for y in yrs
                if np.array([t["r"] for t in occ if t["sd"].year == y]).sum() > 0)

    print(f"  {p['label']:<14}  {len(trades):>5}  {len(occ):>5}  {pf:>8.4f}  "
          f"{net_r:>+9.1f}R  {win*100:>5.1f}%  "
          f"{xt_counts['TARGET']:>5}  {xt_counts['STOP']:>5}  {xt_counts['TIME']:>5}  "
          f"  green={green}/{len(yrs)}", flush=True)

    summary_rows.append({
        "label": p["label"], "tp_k": p["tp"], "sl_k": round(p["sl"], 4),
        "be_bar": p["be"], "raw_trades": len(trades), "occ_trades": len(occ),
        "pf": round(pf, 4), "net_r": round(net_r, 2), "win_pct": round(win*100, 2),
        "green_years": green, "total_years": len(yrs),
        "TARGET": xt_counts["TARGET"], "STOP": xt_counts["STOP"], "TIME": xt_counts["TIME"],
    })

    # year breakdown
    for y in yrs:
        sub = [t for t in occ if t["sd"].year == y]
        r_y = np.array([t["r"] for t in sub])
        gp_y = r_y[r_y>0].sum(); lp_y = -r_y[r_y<=0].sum()
        pf_y = gp_y/lp_y if lp_y>0 else float("inf")
        print(f"    {y}  n={len(sub):>4}  PF={pf_y:.3f}  net={r_y.sum():+.1f}R  "
              f"win={100*(r_y>0).mean():.1f}%", flush=True)

sweep_path = os.path.join(OUT_DIR, "AUDIT_PARAM_SWEEP.csv")
if summary_rows:
    with open(sweep_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)
    print(f"\nSweep CSV: {sweep_path}", flush=True)

print("\nDone.", flush=True)

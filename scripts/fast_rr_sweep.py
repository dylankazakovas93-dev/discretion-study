"""
Fast RR sweep: re-simulate existing AUDIT_SIM_RESULTS.csv trades under
multiple TP/SL/BE combinations. No observe() call — runs in seconds.

Params tested:
  label          TP_K   SL_K     RR_gross  BE_bar
  0.7RR_BE30     1.5    2.143    0.700     30
  1.0RR_BE30     1.5    1.5      1.000     30
  1.25RR_BE30    1.5    1.200    1.250     30
  2.0RR_BE30     2.0    1.000    2.000     30
  0.7RR_NOBE     1.5    2.143    0.700     9999
  1.0RR_NOBE     1.5    1.5      1.000     9999
  1.25RR_NOBE    1.5    1.200    1.250     9999
  2.0RR_NOBE     2.0    1.000    2.000     9999
"""
from __future__ import annotations

import csv
import dataclasses
import json
import os
import pickle
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, "src")

from discretion.execution.simulator import simulate_trade, occupancy_filter

SEG_DIR = "artifacts/multiyear_validation_v2/segcache"
SIM_CSV = "artifacts/AUDIT_SIM_RESULTS.csv"
OUT_DIR = "artifacts"
MAXH = 480

PARAMS = [
    {"label": "0.7RR_BE30",  "tp": 1.5, "sl": 1.5/0.7,   "be": 30},
    {"label": "1.0RR_BE30",  "tp": 1.5, "sl": 1.5,        "be": 30},
    {"label": "1.25RR_BE30", "tp": 1.5, "sl": 1.5/1.25,   "be": 30},
    {"label": "2.0RR_BE30",  "tp": 2.0, "sl": 1.0,        "be": 30},
    {"label": "0.7RR_NOBE",  "tp": 1.5, "sl": 1.5/0.7,    "be": 9999},
    {"label": "1.0RR_NOBE",  "tp": 1.5, "sl": 1.5,        "be": 9999},
    {"label": "1.25RR_NOBE", "tp": 1.5, "sl": 1.5/1.25,   "be": 9999},
    {"label": "2.0RR_NOBE",  "tp": 2.0, "sl": 1.0,        "be": 9999},
]

print(f"Loading {SIM_CSV}...", flush=True)
df = pd.read_csv(SIM_CSV)
df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
print(f"  {len(df)} trades, contracts: {sorted(df['contract'].unique())}", flush=True)

with open(os.path.join(SEG_DIR, "manifest.json")) as f:
    manifest = json.load(f)
contract_to_seg = {c: i for i, c in enumerate(manifest["contracts"])}

# raw[label] = list of trade result dicts (pre-occupancy)
raw = {p["label"]: [] for p in PARAMS}
n_matched = 0
n_missed = 0

for contract, group in df.groupby("contract"):
    seg_idx = contract_to_seg.get(contract)
    if seg_idx is None:
        print(f"  WARNING: {contract} not in manifest", flush=True)
        n_missed += len(group)
        continue

    sbars = pickle.load(open(os.path.join(SEG_DIR, f"seg{seg_idx:03d}.pkl"), "rb"))
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    tz = local[0].ts_et.tzinfo
    ti = {b.ts_et: i for i, b in enumerate(local)}
    ts_ = [b.ts_et for b in local]
    n = len(local)

    for _, trade in group.iterrows():
        # Align timestamp timezone
        ets = trade["entry_ts"].tz_convert(tz)
        i = ti.get(ets)
        if i is None:
            n_missed += 1
            continue

        ep   = float(trade["ep"])
        d    = int(trade["direction"])
        risk = float(trade["risk"])
        sd   = pd.Timestamp(trade["entry_ts"]).tz_convert(tz).date()
        ep_id = str(trade.get("episode_id", ""))

        for p in PARAMS:
            tp_pts = p["tp"] * risk
            sl     = ep - d * p["sl"] * risk
            xt, bar_off, xp, r = simulate_trade(
                local[i:], ep=ep, direction=d,
                tp_pts=tp_pts, sl_orig=sl,
                be_bar=p["be"], max_hold=MAXH)
            xts = ts_[min(i + bar_off, n - 1)]
            raw[p["label"]].append({
                "e": ets, "xts": xts, "r": r,
                "xt": xt, "sd": sd, "episode_id": ep_id,
            })
        n_matched += 1

    print(f"  {contract}: {len(group)} trades matched", flush=True)

print(f"\nMatched: {n_matched}  Missed: {n_missed}", flush=True)

# ── Results ──────────────────────────────────────────────────────────────────
print("\n" + "="*80)
print("FAST RR SWEEP  2018-2025  NY_AM RB ctf{1,3,5}  |z|<1  "
      f"(base candidates: {n_matched})")
print("="*80)
print(f"{'Label':<16} {'occ':>5}  {'PF':>8}  {'netR':>9}  {'win%':>6}  "
      f"{'T':>5}  {'S':>5}  {'t':>5}  {'green':>7}")
print("-"*80)

summary_rows = []
best_pf = 0.0
best_label = ""

for p in PARAMS:
    trades = raw[p["label"]]
    occ = occupancy_filter(trades)
    if not occ:
        print(f"  {p['label']:<14}  no trades")
        continue

    r_arr = np.array([t["r"] for t in occ])
    gp = r_arr[r_arr > 0].sum()
    lp = -r_arr[r_arr <= 0].sum()
    pf  = gp / lp if lp > 0 else float("inf")
    net_r = r_arr.sum()
    win   = (r_arr > 0).mean()
    xc = defaultdict(int)
    for t in occ:
        xc[t["xt"]] += 1

    yrs = sorted(set(t["sd"].year for t in occ))
    green = sum(1 for y in yrs
                if np.array([t["r"] for t in occ if t["sd"].year == y]).sum() > 0)

    flag = " ◄" if pf > best_pf else ""
    if pf > best_pf:
        best_pf = pf; best_label = p["label"]

    print(f"  {p['label']:<16} {len(occ):>5}  {pf:>8.4f}  {net_r:>+9.1f}R  "
          f"{win*100:>5.1f}%  {xc['TARGET']:>5}  {xc['STOP']:>5}  {xc['TIME']:>5}  "
          f"  {green}/{len(yrs)}{flag}", flush=True)

    summary_rows.append({
        "label": p["label"], "tp_k": p["tp"], "sl_k": round(p["sl"], 4),
        "be_bar": p["be"], "occ_trades": len(occ),
        "pf": round(pf, 4), "net_r": round(net_r, 2),
        "win_pct": round(win*100, 2), "green_years": green,
    })

# ── Year breakdown for best config ───────────────────────────────────────────
print(f"\nYear breakdown — {best_label}:")
print(f"  {'Year':>4}  {'n':>5}  {'PF':>8}  {'net':>9}  {'win%':>6}")
trades_best = raw[best_label]
occ_best = occupancy_filter(trades_best)
yrs = sorted(set(t["sd"].year for t in occ_best))
for y in yrs:
    sub = [t for t in occ_best if t["sd"].year == y]
    r_y = np.array([t["r"] for t in sub])
    gp_y = r_y[r_y > 0].sum(); lp_y = -r_y[r_y <= 0].sum()
    pf_y = gp_y / lp_y if lp_y > 0 else float("inf")
    print(f"  {y}  {len(sub):>5}  {pf_y:>8.4f}  {r_y.sum():>+9.1f}R  "
          f"{100*(r_y>0).mean():>5.1f}%")

# ── Write CSV ─────────────────────────────────────────────────────────────────
out_path = os.path.join(OUT_DIR, "AUDIT_FAST_RR_SWEEP.csv")
with open(out_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
    w.writeheader()
    w.writerows(summary_rows)
print(f"\nSweep CSV: {out_path}", flush=True)
print("Done.", flush=True)

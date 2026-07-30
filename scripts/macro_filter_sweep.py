"""
Macro filter sweep: given AUDIT_SIM_RESULTS.csv, simulate a weekly directional
bias overlay at success rates of 20/40/60/80%.

Model:
  - Each ISO week (Mon-Fri) has an actual direction: sign(last_close - first_open)
    computed from the NY_AM session bars for that week.
  - Before each week, the trader forms a bias. At accuracy A, they call the
    correct direction A% of weeks and the wrong direction (1-A)%.
  - Aligned trades = trade direction matches actual week direction.
  - Misaligned trades = trade direction opposes actual week direction.
  - For each week, occupancy filter is applied independently on the aligned
    subset and the misaligned subset.
  - Expected R at accuracy A (deterministic expectation over weeks):
      E[R] = sum_W [ A * R_aligned(W) + (1-A) * R_misaligned(W) ]
  - This is exact given that occupancy within one week doesn't affect another
    (max_hold=480 bars ≈ 8h; each session ≈ 150 bars; trades rarely span days).
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
from discretion.execution.simulator import occupancy_filter

SEG_DIR = "artifacts/multiyear_validation_v2/segcache"
SIM_CSV = "artifacts/AUDIT_SIM_RESULTS.csv"
OUT_DIR = "artifacts"
ACCURACY_LEVELS = [0.20, 0.40, 0.60, 0.80]


def iso_week_key(ts):
    """Return (iso_year, iso_week) for a timestamp."""
    d = pd.Timestamp(ts).date()
    iso = d.isocalendar()
    return (iso[0], iso[1])


def compute_week_directions(sbars):
    """Return dict: (iso_year, iso_week) -> +1 or -1.
    Direction = sign(last_close - first_open) over NY_AM bars in that week.
    """
    by_week = defaultdict(list)
    for b in sbars:
        wk = iso_week_key(b.ts_et)
        by_week[wk].append(b)
    dirs = {}
    for wk, bars in by_week.items():
        bars_sorted = sorted(bars, key=lambda b: b.ts_et)
        diff = bars_sorted[-1].close - bars_sorted[0].open
        dirs[wk] = 1 if diff >= 0 else -1
    return dirs


print(f"Loading {SIM_CSV}...", flush=True)
df = pd.read_csv(SIM_CSV)
df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
print(f"  {len(df)} trades, contracts: {sorted(df['contract'].unique())}", flush=True)

with open(os.path.join(SEG_DIR, "manifest.json")) as f:
    manifest = json.load(f)
contract_to_seg = {c: i for i, c in enumerate(manifest["contracts"])}

# Build per-week aligned/misaligned trade lists across all contracts
# week_trades[(iso_year, iso_week)] = {"aligned": [...], "misaligned": [...]}
week_trades = defaultdict(lambda: {"aligned": [], "misaligned": []})

n_matched = 0
n_missed = 0

for contract, group in df.groupby("contract"):
    seg_idx = contract_to_seg.get(contract)
    if seg_idx is None:
        n_missed += len(group)
        continue

    sbars = pickle.load(open(os.path.join(SEG_DIR, f"seg{seg_idx:03d}.pkl"), "rb"))
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    tz = local[0].ts_et.tzinfo
    week_dirs = compute_week_directions(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    ts_ = [b.ts_et for b in local]
    n = len(local)

    for _, trade in group.iterrows():
        ets = trade["entry_ts"].tz_convert(tz)
        i = ti.get(ets)
        if i is None:
            n_missed += 1
            continue

        wk = iso_week_key(ets)
        wdir = week_dirs.get(wk)
        if wdir is None:
            n_missed += 1
            continue

        d = int(trade["direction"])
        r = float(trade["r"])
        xts = pd.Timestamp(trade["exit_ts"]).tz_convert(tz) if trade["exit_ts"] else ets
        xt = trade["exit_type"]
        ep_id = str(trade.get("episode_id", ""))

        row = {"e": ets, "xts": xts, "r": r, "xt": xt,
               "sd": ets.date(), "episode_id": ep_id}

        if d == wdir:
            week_trades[wk]["aligned"].append(row)
        else:
            week_trades[wk]["misaligned"].append(row)
        n_matched += 1

print(f"Matched: {n_matched}  Missed: {n_missed}", flush=True)
print(f"Weeks with trades: {len(week_trades)}", flush=True)

# Per-week: occupancy filter aligned and misaligned subsets independently
week_stats = {}
for wk, sides in sorted(week_trades.items()):
    al = occupancy_filter(sides["aligned"]) if sides["aligned"] else []
    mis = occupancy_filter(sides["misaligned"]) if sides["misaligned"] else []
    r_al = sum(t["r"] for t in al)
    r_mis = sum(t["r"] for t in mis)
    gp_al = sum(t["r"] for t in al if t["r"] > 0)
    lp_al = -sum(t["r"] for t in al if t["r"] <= 0)
    gp_mis = sum(t["r"] for t in mis if t["r"] > 0)
    lp_mis = -sum(t["r"] for t in mis if t["r"] <= 0)
    week_stats[wk] = {
        "n_al": len(al), "r_al": r_al, "gp_al": gp_al, "lp_al": lp_al,
        "n_mis": len(mis), "r_mis": r_mis, "gp_mis": gp_mis, "lp_mis": lp_mis,
        "year": wk[0],
    }

# Baseline: no macro filter (all trades, occupancy globally)
all_trades = []
for sides in week_trades.values():
    all_trades.extend(sides["aligned"])
    all_trades.extend(sides["misaligned"])
occ_base = occupancy_filter(all_trades)
r_base = np.array([t["r"] for t in occ_base])
gp_b = r_base[r_base > 0].sum()
lp_b = -r_base[r_base <= 0].sum()
pf_b = gp_b / lp_b if lp_b > 0 else float("inf")

print("\n" + "="*72)
print("MACRO DIRECTIONAL FILTER SWEEP  2018-2025  NY_AM RB ctf{1,3,5}  |z|<1")
print("="*72)
print(f"  Baseline (no filter): {len(occ_base)} trades  PF={pf_b:.4f}  "
      f"net={r_base.sum():+.1f}R  win={100*(r_base>0).mean():.1f}%")
print()

# 100% aligned oracle (you always call the week correctly)
n_al_total = sum(s["n_al"] for s in week_stats.values())
r_al_total = sum(s["r_al"] for s in week_stats.values())
gp_al_total = sum(s["gp_al"] for s in week_stats.values())
lp_al_total = sum(s["lp_al"] for s in week_stats.values())
pf_al = gp_al_total / lp_al_total if lp_al_total > 0 else float("inf")
win_al = (gp_al_total / (gp_al_total + lp_al_total + 1e-9)) if (gp_al_total + lp_al_total) > 0 else 0

# 0% aligned (you always call it wrong)
n_mis_total = sum(s["n_mis"] for s in week_stats.values())
r_mis_total = sum(s["r_mis"] for s in week_stats.values())
gp_mis_total = sum(s["gp_mis"] for s in week_stats.values())
lp_mis_total = sum(s["lp_mis"] for s in week_stats.values())
pf_mis = gp_mis_total / lp_mis_total if lp_mis_total > 0 else float("inf")

print(f"{'Accuracy':>10}  {'E[trades]':>10}  {'PF':>8}  {'E[netR]':>9}  {'win%':>6}")
print("-"*55)

# Oracle (100%)
print(f"  {'100% (oracle)':>12}  {n_al_total:>10}  {pf_al:>8.4f}  {r_al_total:>+9.1f}R  "
      f"{win_al*100:>5.1f}%")

summary_rows = []
for acc in reversed(ACCURACY_LEVELS):
    e_n   = acc * n_al_total   + (1 - acc) * n_mis_total
    e_r   = acc * r_al_total   + (1 - acc) * r_mis_total
    e_gp  = acc * gp_al_total  + (1 - acc) * gp_mis_total
    e_lp  = acc * lp_al_total  + (1 - acc) * lp_mis_total
    e_pf  = e_gp / e_lp if e_lp > 0 else float("inf")
    e_win = e_gp / (e_gp + e_lp + 1e-9) if (e_gp + e_lp) > 0 else 0
    print(f"  {int(acc*100):>3d}%            {e_n:>10.0f}  {e_pf:>8.4f}  {e_r:>+9.1f}R  "
          f"{e_win*100:>5.1f}%")
    summary_rows.append({
        "accuracy_pct": int(acc * 100), "e_trades": round(e_n, 1),
        "pf": round(e_pf, 4), "e_net_r": round(e_r, 2),
        "e_win_pct": round(e_win * 100, 2),
    })

print(f"  {'0% (anti-oracle)':>18}  {n_mis_total:>10}  {pf_mis:>8.4f}  {r_mis_total:>+9.1f}R  "
      f"  n/a")

# Year breakdown at 60%
acc_show = 0.60
print(f"\nYear breakdown at {int(acc_show*100)}% accuracy:")
print(f"  {'Year':>4}  {'E[n]':>6}  {'PF':>8}  {'E[netR]':>9}")
by_year_al  = defaultdict(lambda: {"n": 0, "gp": 0, "lp": 0, "r": 0})
by_year_mis = defaultdict(lambda: {"n": 0, "gp": 0, "lp": 0, "r": 0})
for wk, s in week_stats.items():
    y = s["year"]
    by_year_al[y]["n"]  += s["n_al"];  by_year_al[y]["gp"]  += s["gp_al"]
    by_year_al[y]["lp"] += s["lp_al"]; by_year_al[y]["r"]   += s["r_al"]
    by_year_mis[y]["n"]  += s["n_mis"]; by_year_mis[y]["gp"] += s["gp_mis"]
    by_year_mis[y]["lp"] += s["lp_mis"]; by_year_mis[y]["r"] += s["r_mis"]

for y in sorted(set(by_year_al) | set(by_year_mis)):
    al = by_year_al[y]; mis = by_year_mis[y]
    e_n  = acc_show * al["n"]  + (1 - acc_show) * mis["n"]
    e_gp = acc_show * al["gp"] + (1 - acc_show) * mis["gp"]
    e_lp = acc_show * al["lp"] + (1 - acc_show) * mis["lp"]
    e_r  = acc_show * al["r"]  + (1 - acc_show) * mis["r"]
    e_pf = e_gp / e_lp if e_lp > 0 else float("inf")
    print(f"  {y}  {e_n:>6.0f}  {e_pf:>8.4f}  {e_r:>+9.1f}R")

# Write CSV
out_path = os.path.join(OUT_DIR, "AUDIT_MACRO_FILTER_SWEEP.csv")
with open(out_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
    w.writeheader()
    w.writerows(summary_rows)
print(f"\nWrote {out_path}", flush=True)
print("Done.", flush=True)

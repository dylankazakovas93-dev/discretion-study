"""
Macro filter sweep: weekly and daily directional bias overlay at 20/40/60/80%.

Re-simulates each base candidate at 0.7RR_BE30 (best config from fast RR sweep).

Weekly: direction = sign(last_close - first_open) of all NY_AM bars in Mon-Fri week.
Daily:  direction = sign(last_close - first_open) of all NY_AM bars that session day.

For each accuracy A, expected R = sum over periods of:
    A * R_aligned(period) + (1-A) * R_misaligned(period)
Occupancy filter applied independently per period per side.
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
ACCURACY_LEVELS = [0.20, 0.40, 0.60, 0.80]
MAXH = 480
TP_K = 1.5
SL_K = 1.5 / 0.7
BE_BAR = 30


def compute_period_directions(sbars, mode):
    """Return dict: period_key -> +1 or -1.
    mode='week': ISO (year, week). mode='day': date object.
    Direction = sign(last_close - first_open) of bars in that period.
    """
    by_period = defaultdict(list)
    for b in sbars:
        ts = pd.Timestamp(b.ts_et)
        if mode == "week":
            iso = ts.date().isocalendar()
            key = (iso[0], iso[1])
        else:
            key = ts.date()
        by_period[key].append(b)
    dirs = {}
    for k, bars in by_period.items():
        bars_sorted = sorted(bars, key=lambda b: b.ts_et)
        diff = bars_sorted[-1].close - bars_sorted[0].open
        dirs[k] = 1 if diff >= 0 else -1
    return dirs


def period_key_fn(ts, mode):
    t = pd.Timestamp(ts)
    if mode == "week":
        iso = t.date().isocalendar()
        return (iso[0], iso[1])
    return t.date()


def year_of_key(k, mode):
    return k[0] if mode == "week" else k.year


def run_sweep(trades_by_period, mode_label, baseline_occ):
    """Print sweep table and return summary rows."""
    # Per-period occupancy filter on aligned and misaligned subsets
    period_stats = {}
    for pk, sides in sorted(trades_by_period.items()):
        al  = occupancy_filter(sides["aligned"])  if sides["aligned"]  else []
        mis = occupancy_filter(sides["misaligned"]) if sides["misaligned"] else []
        period_stats[pk] = {
            "n_al":  len(al),  "r_al":  sum(t["r"] for t in al),
            "gp_al": sum(t["r"] for t in al  if t["r"] > 0),
            "lp_al": -sum(t["r"] for t in al if t["r"] <= 0),
            "n_mis":  len(mis), "r_mis":  sum(t["r"] for t in mis),
            "gp_mis": sum(t["r"] for t in mis if t["r"] > 0),
            "lp_mis": -sum(t["r"] for t in mis if t["r"] <= 0),
            "year": year_of_key(pk, mode_label),
        }

    r_base = np.array([t["r"] for t in baseline_occ])
    gp_b = r_base[r_base > 0].sum(); lp_b = -r_base[r_base <= 0].sum()
    pf_b = gp_b / lp_b if lp_b > 0 else float("inf")

    print("\n" + "="*72)
    print(f"{'DAILY' if mode_label=='day' else 'WEEKLY'} DIRECTIONAL FILTER  "
          f"2018-2025  NY_AM RB ctf{{1,3,5}}  |z|<1")
    print("="*72)
    print(f"  Baseline (no filter): {len(baseline_occ)} trades  PF={pf_b:.4f}  "
          f"net={r_base.sum():+.1f}R  win={100*(r_base>0).mean():.1f}%")
    print()

    n_al  = sum(s["n_al"]  for s in period_stats.values())
    r_al  = sum(s["r_al"]  for s in period_stats.values())
    gp_al = sum(s["gp_al"] for s in period_stats.values())
    lp_al = sum(s["lp_al"] for s in period_stats.values())
    pf_al = gp_al / lp_al if lp_al > 0 else float("inf")
    win_al = gp_al / (gp_al + lp_al + 1e-9)

    n_mis  = sum(s["n_mis"]  for s in period_stats.values())
    r_mis  = sum(s["r_mis"]  for s in period_stats.values())
    gp_mis = sum(s["gp_mis"] for s in period_stats.values())
    lp_mis = sum(s["lp_mis"] for s in period_stats.values())
    pf_mis = gp_mis / lp_mis if lp_mis > 0 else float("inf")

    print(f"{'Accuracy':>10}  {'E[trades]':>10}  {'PF':>8}  {'E[netR]':>9}  {'win%':>6}")
    print("-"*55)
    print(f"  {'100% (oracle)':>12}  {n_al:>10}  {pf_al:>8.4f}  {r_al:>+9.1f}R  "
          f"{win_al*100:>5.1f}%")

    summary_rows = []
    for acc in reversed(ACCURACY_LEVELS):
        e_n  = acc * n_al  + (1 - acc) * n_mis
        e_gp = acc * gp_al + (1 - acc) * gp_mis
        e_lp = acc * lp_al + (1 - acc) * lp_mis
        e_r  = acc * r_al  + (1 - acc) * r_mis
        e_pf = e_gp / e_lp if e_lp > 0 else float("inf")
        e_win = e_gp / (e_gp + e_lp + 1e-9)
        print(f"  {int(acc*100):>3d}%            {e_n:>10.0f}  {e_pf:>8.4f}  {e_r:>+9.1f}R  "
              f"{e_win*100:>5.1f}%")
        summary_rows.append({
            "mode": mode_label, "accuracy_pct": int(acc * 100),
            "e_trades": round(e_n, 1), "pf": round(e_pf, 4),
            "e_net_r": round(e_r, 2), "e_win_pct": round(e_win * 100, 2),
        })

    print(f"  {'0% (anti-oracle)':>18}  {n_mis:>10}  {pf_mis:>8.4f}  {r_mis:>+9.1f}R")

    # Year breakdown at 60%
    acc_show = 0.60
    print(f"\nYear breakdown at {int(acc_show*100)}% accuracy:")
    print(f"  {'Year':>4}  {'E[n]':>6}  {'PF':>8}  {'E[netR]':>9}")
    by_yr_al  = defaultdict(lambda: {"n": 0, "gp": 0.0, "lp": 0.0, "r": 0.0})
    by_yr_mis = defaultdict(lambda: {"n": 0, "gp": 0.0, "lp": 0.0, "r": 0.0})
    for pk, s in period_stats.items():
        y = s["year"]
        by_yr_al[y]["n"]  += s["n_al"];  by_yr_al[y]["gp"]  += s["gp_al"]
        by_yr_al[y]["lp"] += s["lp_al"]; by_yr_al[y]["r"]   += s["r_al"]
        by_yr_mis[y]["n"]  += s["n_mis"]; by_yr_mis[y]["gp"] += s["gp_mis"]
        by_yr_mis[y]["lp"] += s["lp_mis"]; by_yr_mis[y]["r"] += s["r_mis"]
    for y in sorted(set(by_yr_al) | set(by_yr_mis)):
        al = by_yr_al[y]; mis = by_yr_mis[y]
        e_gp = acc_show * al["gp"] + (1 - acc_show) * mis["gp"]
        e_lp = acc_show * al["lp"] + (1 - acc_show) * mis["lp"]
        e_r  = acc_show * al["r"]  + (1 - acc_show) * mis["r"]
        e_n  = acc_show * al["n"]  + (1 - acc_show) * mis["n"]
        e_pf = e_gp / e_lp if e_lp > 0 else float("inf")
        print(f"  {y}  {e_n:>6.0f}  {e_pf:>8.4f}  {e_r:>+9.1f}R")

    return summary_rows


# ── Load and re-simulate ──────────────────────────────────────────────────────
print(f"Loading {SIM_CSV}...", flush=True)
df = pd.read_csv(SIM_CSV)
df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
print(f"  {len(df)} trades", flush=True)

with open(os.path.join(SEG_DIR, "manifest.json")) as f:
    manifest = json.load(f)
contract_to_seg = {c: i for i, c in enumerate(manifest["contracts"])}

week_trades = defaultdict(lambda: {"aligned": [], "misaligned": []})
day_trades  = defaultdict(lambda: {"aligned": [], "misaligned": []})
all_resim   = []
n_missed = 0

for contract, group in df.groupby("contract"):
    seg_idx = contract_to_seg.get(contract)
    if seg_idx is None:
        n_missed += len(group); continue

    sbars = pickle.load(open(os.path.join(SEG_DIR, f"seg{seg_idx:03d}.pkl"), "rb"))
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    tz = local[0].ts_et.tzinfo
    week_dirs = compute_period_directions(local, "week")
    day_dirs  = compute_period_directions(local, "day")
    ti = {b.ts_et: i for i, b in enumerate(local)}
    ts_ = [b.ts_et for b in local]
    n = len(local)

    for _, trade in group.iterrows():
        ets = trade["entry_ts"].tz_convert(tz)
        i = ti.get(ets)
        if i is None:
            n_missed += 1; continue

        d    = int(trade["direction"])
        ep   = float(trade["ep"])
        risk = float(trade["risk"])
        ep_id = str(trade.get("episode_id", ""))

        sl     = ep - d * SL_K * risk
        tp_pts = TP_K * risk
        xt, bar_off, xp, r = simulate_trade(
            local[i:], ep=ep, direction=d, tp_pts=tp_pts,
            sl_orig=sl, be_bar=BE_BAR, max_hold=MAXH)
        xts = ts_[min(i + bar_off, n - 1)]

        row = {"e": ets, "xts": xts, "r": r, "xt": xt,
               "sd": ets.date(), "episode_id": ep_id}
        all_resim.append(row)

        wk  = period_key_fn(ets, "week")
        wdir = week_dirs.get(wk)
        dk   = period_key_fn(ets, "day")
        ddir = day_dirs.get(dk)

        if wdir is not None:
            side = "aligned" if d == wdir else "misaligned"
            week_trades[wk][side].append(row)
        if ddir is not None:
            side = "aligned" if d == ddir else "misaligned"
            day_trades[dk][side].append(row)

print(f"Re-simulated: {len(all_resim)}  Missed: {n_missed}", flush=True)

baseline_occ = occupancy_filter(all_resim)

# ── Run both sweeps ───────────────────────────────────────────────────────────
all_rows = []
all_rows += run_sweep(week_trades, "week", baseline_occ)
all_rows += run_sweep(day_trades,  "day",  baseline_occ)

out_path = os.path.join(OUT_DIR, "AUDIT_MACRO_FILTER_SWEEP.csv")
with open(out_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
    w.writeheader()
    w.writerows(all_rows)
print(f"\nWrote {out_path}", flush=True)
print("Done.", flush=True)

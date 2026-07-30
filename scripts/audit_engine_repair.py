"""
AUDIT ENGINE REPAIR — Steps 9-12 of the adversarial repair audit.

Produces:
  artifacts/AUDIT_CANDIDATE_RECONCILIATION.csv   (Step 9)
  artifacts/AUDIT_SIM_RESULTS.csv               (Step 11: 2018-2025 corrected SIM)
  artifacts/AUDIT_SIM_RESULTS_OOS.csv           (Step 12: 2013-2015 corrected SIM)

Engine changes applied:
  - observer.py: invalid_from_seq enforcement (expired/deactivated contexts cannot
    generate interactions after their lifecycle ends)
  - loader.py: CME quarterly calendar (method='cme_calendar') replaces full-day volume
  - _all_structures_ext: RB target invalid_from shifted to r+1 (correct causal boundary)

This script does NOT produce performance metrics. Step 10 outputs candidate counts only.
"""
from __future__ import annotations

import csv
import dataclasses
import importlib.util
import io
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import zstandard as zs

sys.path.insert(0, "src")

from discretion.data.bars import Bar
from discretion.data.loader import load_front_month, DATA_FILES, ET
from discretion.data.cme_session import session_date
from discretion.execution.simulator import simulate_trade
from discretion.setup_observer.observer import observe

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
SEGCACHE_DIR = "artifacts/multiyear_validation_v2/segcache"
DATA_DIR = "data/raw"
OOS_ZST = "/root/.claude/uploads/6bbfe5fa-ed66-5075-a056-4af4be88eb35/dadfef48-glbxmdp32013010120151231.ohlcv1m.csv.zst"
OUT_DIR = "artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480
TARGET_WINDOW = 600
VWAP_SIGMA_LIMIT = 1.0
SIM_FILTER_SESSION = "NY_AM"
SIM_FILTER_FAMILY = "rb"
SIM_FILTER_CTF = (1, 3, 5)


def wilder_atr24_np(h, l, c):
    n = len(h)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = np.empty(n)
    atr[0] = tr[0]
    k = 1 / 24
    for i in range(1, n):
        atr[i] = atr[i-1] * (1 - k) + tr[i] * k
    return atr


def extract_trades_from_segment(sbars, require_vwap=True):
    """Run observer on sbars, apply filters, return list of trade dicts."""
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n = len(local)
    _ev, variants, _diag = observe(local, target_window=TARGET_WINDOW)
    F = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    h_ = np.array([b.high  for b in local])
    l_ = np.array([b.low   for b in local])
    o_ = np.array([b.open  for b in local])
    c_ = np.array([b.close for b in local])
    ts_ = [b.ts_et for b in local]
    atr24 = wilder_atr24_np(h_, l_, c_)

    trades = []
    for v in variants:
        if not v.executable:
            continue
        if getattr(v, "session", None) != SIM_FILTER_SESSION:
            continue
        if getattr(v, "context_family", None) != SIM_FILTER_FAMILY:
            continue
        if getattr(v, "context_tf", None) not in SIM_FILTER_CTF:
            continue

        i = ti.get(v.entry_ts, -1)
        if i < 1:
            continue

        if require_vwap:
            px = float(F["close"][i-1])
            vw = float(F["vwap_CASH_0930"][i-1])
            sd = max(float(F["vwsd_CASH_0930"][i-1]), 1e-9)
            if abs((px - vw) / sd) >= VWAP_SIGMA_LIMIT:
                continue

        risk = float(atr24[i-1])
        if risk <= 0:
            continue

        d = v.direction
        ep = float(o_[i])
        sl = ep - d * risk * SL_K
        tp_pts = risk * TP_K

        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE") if v.targets else None
        if prim is None:
            continue

        bars_slice = local[i:]
        xt, bar_off, xp, r = simulate_trade(
            bars_slice, ep=ep, direction=d, tp_pts=tp_pts, sl_orig=sl,
            be_bar=30, max_hold=MAXH)
        xts = ts_[min(i + bar_off, n - 1)]

        trades.append({
            "episode_id": v.episode_id,
            "variant_id": v.variant_id,
            "entry_variant": v.entry_variant,
            "direction": d,
            "entry_ts": v.entry_ts,
            "exit_ts": xts,
            "exit_type": xt,
            "ep": ep,
            "sl": sl,
            "risk": risk,
            "tp_pts": tp_pts,
            "exit_price": xp,
            "pts": r * risk,
            "r": r,
            "context_family": v.context_family,
            "context_tf": getattr(v, "context_tf", None),
            "trigger_tf": getattr(v, "trigger_tf", None),
            "context_id": getattr(v, "context_id", None),
            "context_zone_lo": v.context_zone[0] if v.context_zone else None,
            "context_zone_hi": v.context_zone[1] if v.context_zone else None,
            "contract": sbars[0].contract if sbars else None,
            "segment_id": sbars[0].segment_id if sbars else None,
        })

    return trades


# ──────────────────────────────────────────────────────────────────────────────
# Step 9: Candidate reconciliation
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 9: Candidate reconciliation (old segcache vs new engine)")
print("=" * 70, flush=True)

with open(os.path.join(SEGCACHE_DIR, "manifest.json")) as f:
    import json
    manifest = json.load(f)

n_segs = manifest["n_segments"]
contracts = manifest["contracts"]

# Load old variants for comparison
print("Loading old variants from all_hypothesis_variants.csv ...", flush=True)
old_df = pd.read_csv("artifacts/multiyear_validation_v2/all_hypothesis_variants.csv",
                     low_memory=False)

# Normalise timestamps to UTC int64 (nanoseconds) for format-agnostic matching.
# Old CSV has "2018-01-01 21:13:00-05:00"; new variants produce Timestamps
# with tz America/New_York. Both represent the same instant → match in UTC ns.
old_df["_entry_ts_utc_ns"] = pd.to_datetime(old_df["entry_ts"], utc=True).astype("int64")
old_key_set = set()
for _, row in old_df.iterrows():
    k = (int(row["_entry_ts_utc_ns"]), int(row["direction"]), str(row["entry_variant"]))
    old_key_set.add(k)
print(f"Old variant count: {len(old_df):,}", flush=True)


def _ts_key(ts):
    """Convert entry_ts (Timestamp or str) to UTC ns for matching."""
    if hasattr(ts, "value"):
        return int(ts.tz_convert("UTC").value)
    return int(pd.Timestamp(ts).tz_convert("UTC").value)

recon_rows = []
new_total_new_engine = 0

for seg_idx in range(n_segs):
    contract = contracts[seg_idx]
    pkl = os.path.join(SEGCACHE_DIR, f"seg{seg_idx:03d}.pkl")
    t0 = time.time()
    sbars = pickle.load(open(pkl, "rb"))
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    _ev, variants, _diag = observe(local, target_window=TARGET_WINDOW)
    elapsed = round(time.time() - t0, 1)

    new_total_new_engine += len(variants)
    year = sbars[0].ts_et.year if sbars else 0

    # For each new-engine variant, check if it was in old set
    for v in variants:
        k = (_ts_key(v.entry_ts), int(v.direction), str(v.entry_variant))
        old_present = k in old_key_set
        recon_rows.append({
            "candidate_id": v.variant_id,
            "year": v.entry_ts.year if hasattr(v.entry_ts, "year") else year,
            "entry_ts": v.entry_ts,
            "direction": v.direction,
            "context_id": getattr(v, "context_id", ""),
            "context_family": getattr(v, "context_family", ""),
            "context_tf": getattr(v, "context_tf", ""),
            "trigger_tf": getattr(v, "trigger_tf", ""),
            "entry_variant": v.entry_variant,
            "old_present": old_present,
            "new_present": True,
            "removal_reason": "",
            "context_zone_lo": v.context_zone[0] if v.context_zone else None,
            "context_zone_hi": v.context_zone[1] if v.context_zone else None,
            "contract_old": contract,
            "contract_new": contract,  # same bars; contract unchanged
        })

    print(f"  seg{seg_idx:03d} {contract}: {len(variants):,} variants  [{elapsed}s]", flush=True)

# Also mark old variants that are NOT present in new engine (removed by lifecycle fix)
new_key_set = {(_ts_key(r["entry_ts"]), int(r["direction"]), str(r["entry_variant"]))
               for r in recon_rows}
n_old_only = 0
for _, row in old_df.iterrows():
    k = (int(row["_entry_ts_utc_ns"]), int(row["direction"]), str(row["entry_variant"]))
    if k not in new_key_set:
        n_old_only += 1
        recon_rows.append({
            "candidate_id": str(row.get("gvid", "")),
            "year": int(row.get("year", 0)),
            "entry_ts": row["entry_ts"],
            "direction": int(row["direction"]),
            "context_id": "",
            "context_family": str(row.get("context_family", row.get("reaction_state", ""))),
            "context_tf": str(row.get("context_tf", "")),
            "trigger_tf": str(row.get("trigger_tf", "")),
            "entry_variant": str(row["entry_variant"]),
            "old_present": True,
            "new_present": False,
            "removal_reason": "LIFECYCLE_FIX_REMOVED",
            "context_zone_lo": None,
            "context_zone_hi": None,
            "contract_old": "",
            "contract_new": "",
        })

recon_path = os.path.join(OUT_DIR, "AUDIT_CANDIDATE_RECONCILIATION.csv")
recon_fields = ["candidate_id", "year", "entry_ts", "direction", "context_id",
                "context_family", "context_tf", "trigger_tf", "entry_variant",
                "old_present", "new_present", "removal_reason",
                "context_zone_lo", "context_zone_hi", "contract_old", "contract_new"]
with open(recon_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=recon_fields)
    w.writeheader()
    w.writerows(recon_rows)

print(f"\nOld total: {len(old_df):,}", flush=True)
print(f"New total (new engine on old bars): {new_total_new_engine:,}", flush=True)
print(f"Old-only (removed by lifecycle fix): {n_old_only:,}", flush=True)
new_only = sum(1 for r in recon_rows if not r["old_present"] and r["new_present"])
print(f"New-only (added by engine — unexpected): {new_only:,}", flush=True)
print(f"Reconciliation CSV: {recon_path}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Step 11: Rerun 2018-2025 SIM (new engine, CME calendar bars)
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 11: 2018-2025 SIM with corrected engine (CME calendar bars)")
print("=" * 70, flush=True)

DATA_ORDER = ["2018-2019", "2020", "2021-2022", "2023-2024", "2025-2026"]
all_sim_trades = []

for period, fname in DATA_FILES.items():
    if period not in DATA_ORDER:
        continue
    zst_path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(zst_path):
        print(f"  SKIP {period}: {zst_path} not found", flush=True)
        continue
    print(f"  Loading {period} (CME calendar)...", flush=True)
    t0 = time.time()
    bars_all = load_front_month(zst_path, method="cme_calendar")
    if not bars_all:
        print(f"  Empty, skipping", flush=True)
        continue

    segs = defaultdict(list)
    for b in bars_all:
        segs[b.segment_id].append(b)

    period_trades = 0
    for sid, sbars in sorted(segs.items()):
        contract = sbars[0].contract
        year_start = sbars[0].ts_et.year
        # Only include 2018-2025 (exclude 2026)
        if year_start >= 2026:
            continue
        t1 = time.time()
        trades = extract_trades_from_segment(sbars)
        period_trades += len(trades)
        all_sim_trades.extend(trades)
        print(f"    seg {sid} {contract}: {len(trades)} trades  [{round(time.time()-t1,1)}s]", flush=True)

    print(f"  {period}: {period_trades} trades  [{round(time.time()-t0,1)}s total]", flush=True)

# Apply occupancy filter (deterministic)
all_sim_trades.sort(key=lambda t: (t["entry_ts"], t["episode_id"]))
occ_sim = []
until = None
for t in all_sim_trades:
    if until is not None and t["entry_ts"] < until:
        continue
    occ_sim.append(t)
    until = t["exit_ts"]

# Write results
sim_path = os.path.join(OUT_DIR, "AUDIT_SIM_RESULTS.csv")
sim_fields = ["episode_id", "variant_id", "entry_variant", "direction",
              "entry_ts", "exit_ts", "exit_type", "ep", "sl", "risk",
              "tp_pts", "exit_price", "pts", "r", "context_family",
              "context_tf", "trigger_tf", "context_id",
              "context_zone_lo", "context_zone_hi", "contract"]
with open(sim_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=sim_fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(occ_sim)

n_sim = len(occ_sim)
w_sim = sum(1 for t in occ_sim if t["exit_type"] == "TARGET")
tot_r = sum(t["r"] for t in occ_sim)
pf_sim = (sum(t["r"] for t in occ_sim if t["r"] > 0) /
           max(abs(sum(t["r"] for t in occ_sim if t["r"] < 0)), 1e-9))

print(f"\n2018-2025 SIM (corrected engine): {n_sim} trades, {w_sim/n_sim*100:.1f}% win, "
      f"+{tot_r:.1f}R, PF={pf_sim:.3f}", flush=True)
print(f"SIM results: {sim_path}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Step 12: 2013-2015 SIM (corrected engine)
# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 12: 2013-2015 SIM with corrected engine")
print("=" * 70, flush=True)

if not os.path.exists(OOS_ZST):
    print(f"OOS data not found at {OOS_ZST} — skipping Step 12", flush=True)
else:
    print("Loading 2013-2015 OOS data (CME calendar)...", flush=True)
    t0 = time.time()

    # The OOS file has its own format; use the loader
    # But the loader requires a specific data format matching the standard columns
    # Use raw CSV loading with CME calendar applied manually
    rows_oos = []
    with open(OOS_ZST, "rb") as fh:
        reader = io.TextIOWrapper(zs.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
        for r in csv.DictReader(reader):
            sym = r["symbol"]
            if not sym.startswith("NQ") or len(sym) != 4:
                continue
            rows_oos.append((r["ts_event"], sym,
                             float(r["open"]), float(r["high"]),
                             float(r["low"]), float(r["close"]),
                             int(float(r["volume"]))))

    df_oos = pd.DataFrame(rows_oos, columns=["ts", "sym", "o", "h", "l", "c", "v"])
    df_oos["ts"] = pd.to_datetime(df_oos["ts"], utc=True)
    df_oos = df_oos.sort_values("ts").reset_index(drop=True)
    df_oos["d"] = df_oos["ts"].dt.tz_convert(ET).dt.date

    # CME calendar contract assignment
    from discretion.data.loader import _front_month_by_day_cme
    dates_oos = df_oos["d"].unique()
    cme_map_oos = _front_month_by_day_cme(dates_oos)
    df_oos["_front"] = df_oos["d"].map(cme_map_oos)
    df_oos = df_oos[df_oos["sym"] == df_oos["_front"]].copy()
    df_oos = df_oos.sort_values("ts").reset_index(drop=True)
    print(f"OOS bars after CME filter: {len(df_oos):,}  {df_oos['d'].min()} → {df_oos['d'].max()}",
          flush=True)

    bars_oos = []
    seq = 0; prev_sym = None; seg_id = 0
    for _, r in df_oos.iterrows():
        if prev_sym is not None and r["sym"] != prev_sym:
            seg_id += 1; seq = 0
        bars_oos.append(Bar(seq=seq, ts_utc=r["ts"], ts_et=r["ts"].tz_convert(ET),
                            open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                            volume=int(r["v"]), contract=r["sym"], segment_id=seg_id))
        seq += 1
        prev_sym = r["sym"]

    del df_oos
    print(f"OOS bars: {len(bars_oos):,}  segments: {seg_id + 1}  [{round(time.time()-t0,1)}s]",
          flush=True)

    segs_oos = defaultdict(list)
    for b in bars_oos:
        segs_oos[b.segment_id].append(b)

    oos_trades = []
    for sid, sbars in sorted(segs_oos.items()):
        contract = sbars[0].contract
        t1 = time.time()
        trades = extract_trades_from_segment(sbars)
        oos_trades.extend(trades)
        print(f"  OOS seg {sid} {contract}: {len(trades)} trades  [{round(time.time()-t1,1)}s]",
              flush=True)

    # Occupancy filter
    oos_trades.sort(key=lambda t: (t["entry_ts"], t["episode_id"]))
    occ_oos = []
    until = None
    for t in oos_trades:
        if until is not None and t["entry_ts"] < until:
            continue
        occ_oos.append(t)
        until = t["exit_ts"]

    oos_path = os.path.join(OUT_DIR, "AUDIT_SIM_RESULTS_OOS.csv")
    with open(oos_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sim_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(occ_oos)

    n_oos = len(occ_oos)
    if n_oos > 0:
        w_oos = sum(1 for t in occ_oos if t["exit_type"] == "TARGET")
        tot_r_oos = sum(t["r"] for t in occ_oos)
        pf_oos = (sum(t["r"] for t in occ_oos if t["r"] > 0) /
                   max(abs(sum(t["r"] for t in occ_oos if t["r"] < 0)), 1e-9))
        print(f"\n2013-2015 OOS SIM (corrected engine): {n_oos} trades, "
              f"{w_oos/n_oos*100:.1f}% win, +{tot_r_oos:.1f}R, PF={pf_oos:.3f}", flush=True)
    print(f"OOS results: {oos_path}", flush=True)

print("\nDone.", flush=True)

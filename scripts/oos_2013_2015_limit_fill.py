"""
OOS 2013-2015 limit-fill comparison.
Simulates two fill methods side by side:
  SIM  - bar open (what previous scripts used)
  LIM  - limit at zone boundary (zone_hi for long, zone_lo for short)
         gap-through fills at bar open (never worse than sim)
Full rule set: |z|<1.0 VWAP, BE30, all RB origins, 0.7RR gross.
"""
import sys, io, dataclasses
import numpy as np
import pandas as pd
import zstandard as zs
from collections import defaultdict
import csv as _csv
import importlib.util

sys.path.insert(0, "src")

from discretion.data.bars import Bar
from discretion.data.loader import ET
from discretion.setup_observer.observer import observe
from discretion.execution.simulator import (
    simulate_trade, limit_fill_long, limit_fill_short, occupancy_filter,
)

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

SRC  = "/root/.claude/uploads/6bbfe5fa-ed66-5075-a056-4af4be88eb35/dadfef48-glbxmdp32013010120151231.ohlcv1m.csv.zst"
TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480


def wilder_atr24(h, l, c):
    n = len(h)
    tr = np.empty(n); tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    atr = np.empty(n); atr[0] = tr[0]; k = 1/24
    for i in range(1, n):
        atr[i] = atr[i-1]*(1-k) + tr[i]*k
    return atr


print("Loading 2013-2015 data...", flush=True)
rows = []
with open(SRC, "rb") as fh:
    reader = io.TextIOWrapper(zs.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
    for r in _csv.DictReader(reader):
        sym = r["symbol"]
        if not sym.startswith("NQ") or len(sym) != 4: continue
        rows.append((r["ts_event"], sym,
                     float(r["open"]), float(r["high"]),
                     float(r["low"]),  float(r["close"]),
                     int(float(r["volume"]))))

df = pd.DataFrame(rows, columns=["ts", "sym", "o", "h", "l", "c", "v"])
df["ts"] = pd.to_datetime(df["ts"], utc=True)
df = df.sort_values("ts").reset_index(drop=True)
df["d"] = df["ts"].dt.tz_convert(ET).dt.date
vol = df.groupby(["d", "sym"])["v"].sum().reset_index()
front = vol.sort_values("v").groupby("d").tail(1).set_index("d")["sym"].to_dict()
df = df[df.apply(lambda r: front.get(r["d"]) == r["sym"], axis=1)].reset_index(drop=True)
print(f"Front-month rows: {len(df):,}  {df['d'].min()} → {df['d'].max()}", flush=True)

bars_all = []
seq = 0; prev_sym = None; seg_id = 0
for _, r in df.iterrows():
    if prev_sym is not None and r["sym"] != prev_sym:
        seg_id += 1; seq = 0
    bars_all.append(Bar(seq=seq, ts_utc=r["ts"], ts_et=r["ts"].tz_convert(ET),
                        open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                        volume=int(r["v"]), contract=r["sym"], segment_id=seg_id))
    seq += 1; prev_sym = r["sym"]
print(f"Bars: {len(bars_all):,}  segments: {seg_id+1}", flush=True)
del df

segs = defaultdict(list)
for b in bars_all: segs[b.segment_id].append(b)

all_sim  = []   # fill at bar open
all_lim  = []   # fill at zone boundary (limit order)

for sid, sbars in sorted(segs.items()):
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n = len(local)
    _ev, variants, _disc = observe(local, target_window=600)
    F  = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    h_ = np.array([b.high  for b in local])
    l_ = np.array([b.low   for b in local])
    o_ = np.array([b.open  for b in local])
    c_ = np.array([b.close for b in local])
    ts_= [b.ts_et for b in local]
    atr24 = wilder_atr24(h_, l_, c_)

    seg_n = 0
    for v in variants:
        if not v.executable: continue
        if v.session != "NY_AM": continue
        if v.context_family != "rb": continue
        if v.context_tf not in (1, 3, 5): continue

        i = ti.get(v.entry_ts, -1)
        if i < 1: continue

        px = float(F["close"][i-1])
        vw = float(F["vwap_CASH_0930"][i-1])
        sd = max(float(F["vwsd_CASH_0930"][i-1]), 1e-9)
        if abs((px - vw) / sd) >= 1.0: continue

        risk = float(atr24[i-1])
        if risk <= 0: continue

        d = v.direction
        zone_lo, zone_hi = v.context_zone
        tp_pts = TP_K * risk

        # ── SIM fill: always at bar open ──────────────────────────────
        ep_sim = float(o_[i])
        sl_sim = ep_sim - d * SL_K * risk
        xt_s, off_s, _, r_s = simulate_trade(
            local[i:], ep=ep_sim, direction=d, tp_pts=tp_pts, sl_orig=sl_sim,
            be_bar=30, max_hold=MAXH, skip_first_bar=False)
        xts_sim = ts_[min(i + off_s, n - 1)]
        pts_sim = r_s * risk

        # ── LIMIT fill: zone boundary; skip if bar never touched limit ─
        if d > 0:
            res_lim = limit_fill_long(float(o_[i]), float(h_[i]), float(l_[i]), zone_hi)
        else:
            res_lim = limit_fill_short(float(o_[i]), float(h_[i]), float(l_[i]), zone_lo)
        if res_lim is None:
            continue
        ep_lim, fill_mode = res_lim
        sl_lim = ep_lim - d * SL_K * risk
        skip_first = (fill_mode == "INTRABAR_TOUCH")
        xt_l, off_l, _, r_l = simulate_trade(
            local[i:], ep=ep_lim, direction=d, tp_pts=tp_pts, sl_orig=sl_lim,
            be_bar=30, max_hold=MAXH, skip_first_bar=skip_first)
        xts_lim = ts_[min(i + off_l, n - 1)]
        pts_lim = r_l * risk

        base = {"sd": v.session_date_et, "e": v.entry_ts, "risk": risk}
        all_sim.append({**base, "xts": xts_sim, "pts": pts_sim, "xt": xt_s,
                        "ep": ep_sim, "fill_diff": ep_lim - ep_sim})
        all_lim.append({**base, "xts": xts_lim, "pts": pts_lim, "xt": xt_l,
                        "ep": ep_lim, "fill_diff": ep_lim - ep_sim})
        seg_n += 1

    print(f"  seg{sid:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}"
          f"  bars={n:>7,}  cands={seg_n:>4}  total_sim={len(all_sim):>5}", flush=True)

print(f"\nRaw trades (pre-occupancy): {len(all_sim):,}", flush=True)


ch_sim = occupancy_filter(all_sim)
ch_lim = occupancy_filter(all_lim)
print(f"After occupancy: sim={len(ch_sim)}  lim={len(ch_lim)}\n", flush=True)


def report(ch, label):
    yrs = sorted(set(t["sd"].year for t in ch))
    wk  = (ch[-1]["sd"] - ch[0]["sd"]).days / 7 if ch else 1
    all_r = []
    green = 0
    print(f"\n{'Year':>5}  {'n':>5}  {'PF':>8}  {'net':>9}  {'win%':>6}")
    for y in yrs:
        sub = [t for t in ch if t["sd"].year == y]
        r = np.array([t["pts"]/t["risk"] for t in sub])
        all_r.extend(r)
        gp = r[r>0].sum(); lp = -r[r<=0].sum()
        pf = gp/lp if lp > 0 else float("inf")
        if pf > 1.0: green += 1
        print(f"  {y}  {len(sub):>5}  {pf:>8.4f}  {r.sum():>+9.1f}R  {100*(r>0).mean():>5.1f}%")
    all_r = np.array(all_r)
    gp = all_r[all_r>0].sum(); lp = -all_r[all_r<=0].sum()
    pf = gp/lp if lp > 0 else float("inf")
    eq = np.cumsum(all_r); mdd = (eq - np.maximum.accumulate(eq)).min()
    xt_ = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1
    print("-" * 50)
    print(f"  TOTAL {len(ch):>5}  {pf:>8.4f}  {all_r.sum():>+9.1f}R  {100*(all_r>0).mean():>5.1f}%")
    print(f"  /wk={len(ch)/wk:.1f}  MDD={mdd:.1f}R  green={green}/{len(yrs)}"
          f"  T={xt_['TARGET']}  S={xt_['STOP']}  t={xt_['TIME']}")
    return all_r.sum()


print("=" * 60)
print(f"FILL COMPARISON  OOS 2013-2015  BE30  |z|<1  0.7RR  GROSS")
print("=" * 60)

print(f"\n{'─'*60}")
print("A) SIM FILL  (bar open — conservative baseline)")
print(f"{'─'*60}")
net_sim = report(ch_sim, "SIM")

print(f"\n{'─'*60}")
print("B) LIMIT FILL  (zone_hi for long, zone_lo for short)")
print(f"{'─'*60}")
net_lim = report(ch_lim, "LIM")

# ── Fill difference analysis ──────────────────────────────────────────────
diffs_sim  = [t["fill_diff"] * (-1 if t["fill_diff"] != 0 else 0)
              for t in ch_sim]   # positive = limit better
# For long (d>0): limit_ep < sim_ep → sim_ep - limit_ep = improvement in pts
# We stored fill_diff = ep_lim - ep_sim, which is negative for long (limit lower = better)
# Gain in pts for long: sim_ep - lim_ep = -(fill_diff)
# Gain in pts for short: lim_ep - sim_ep = fill_diff

# Recompute cleanly
fill_gains = []
for ts, tl in zip(ch_sim, ch_lim):
    # pts gain from using limit (positive = limit better)
    # risk_normed
    g = (ts["ep"] - tl["ep"]) if ts["pts"] > 0 or True else 0
    # For long: ts["ep"] > tl["ep"] usually → g > 0 (better entry)
    # For short: ts["ep"] < tl["ep"] usually → g < 0... need direction
    # Actually: R improvement = (ts_ep_minus_lim_ep) * d / risk
    # We don't have d here; use net R improvement
    # Simpler: lim net R - sim net R per trade
    r_gain = tl["pts"]/tl["risk"] - ts["pts"]/ts["risk"]
    fill_gains.append({"pts_diff": tl["ep"] - ts["ep"],
                       "r_gain": r_gain})

pts_diffs = [f["pts_diff"] for f in fill_gains]
r_gains   = [f["r_gain"]   for f in fill_gains]

trades_with_better_fill = sum(1 for x in pts_diffs if abs(x) > 0.01)
avg_pts_improvement = np.mean([abs(x) for x in pts_diffs if abs(x) > 0.01])

print(f"\n{'─'*60}")
print("FILL ANALYSIS")
print(f"{'─'*60}")
print(f"  Trades where fills differ:  {trades_with_better_fill} / {len(ch_sim)}"
      f"  ({100*trades_with_better_fill/len(ch_sim):.1f}%)")
print(f"  Avg improvement when differ: {avg_pts_improvement:.2f} pts"
      f"  ({avg_pts_improvement/20:.2f} NQ ticks)")
print(f"  Net R gain over full period: {sum(r_gains):+.1f}R")
print(f"  Net R difference:  lim={net_lim:+.1f}R  sim={net_sim:+.1f}R"
      f"  Δ={net_lim-net_sim:+.1f}R")
print(f"  Per-trade avg R gain: {np.mean(r_gains):+.4f}R")

print("\nDone.", flush=True)

"""
Dev 2018-2025 limit-fill vs sim-fill comparison.
Re-runs observe() on segcache bars to access v.context_zone.
Same rule set: |z|<1 VWAP, BE30, 0.7RR gross, all RB origins, NY_AM.
"""
import sys, pickle, dataclasses, importlib.util
import numpy as np
from collections import defaultdict

sys.path.insert(0, "src")

from discretion.setup_observer.observer import observe
from discretion.execution.simulator import (
    simulate_trade, limit_fill_long, limit_fill_short, occupancy_filter,
)

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

SEG  = "artifacts/multiyear_validation_v2/segcache"
TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480


def wilder_atr24(bars):
    h = np.array([b.high  for b in bars])
    l = np.array([b.low   for b in bars])
    c = np.array([b.close for b in bars])
    n = len(h)
    tr = np.empty(n); tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    atr = np.empty(n); atr[0] = tr[0]; k = 1/24
    for i in range(1, n):
        atr[i] = atr[i-1]*(1-k) + tr[i]*k
    return atr


all_sim = []
all_lim = []

for si in range(34):
    try:
        bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl", "rb"))
    except FileNotFoundError:
        continue

    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]
    n = len(local)
    print(f"seg{si:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}  bars={n:,}", flush=True)

    _ev, variants, _disc = observe(local, target_window=600)
    F  = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}
    h_ = np.array([b.high  for b in local])
    l_ = np.array([b.low   for b in local])
    o_ = np.array([b.open  for b in local])
    c_ = np.array([b.close for b in local])
    ts_= [b.ts_et for b in local]
    atr24 = wilder_atr24(local)

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

        # SIM fill: bar open
        ep_sim = float(o_[i])
        sl_sim = ep_sim - d * SL_K * risk
        xt_s, off_s, _, r_s = simulate_trade(
            local[i:], ep=ep_sim, direction=d, tp_pts=tp_pts, sl_orig=sl_sim,
            be_bar=30, max_hold=MAXH, skip_first_bar=False)
        xts_sim = ts_[min(i + off_s, n - 1)]

        # LIMIT fill: zone boundary; skip if no fill
        if d > 0:
            res_lim = limit_fill_long(float(o_[i]), float(h_[i]), float(l_[i]), zone_hi)
        else:
            res_lim = limit_fill_short(float(o_[i]), float(h_[i]), float(l_[i]), zone_lo)
        if res_lim is None:
            continue
        ep_lim, fill_mode = res_lim
        sl_lim = ep_lim - d * SL_K * risk
        xt_l, off_l, _, r_l = simulate_trade(
            local[i:], ep=ep_lim, direction=d, tp_pts=tp_pts, sl_orig=sl_lim,
            be_bar=30, max_hold=MAXH, skip_first_bar=(fill_mode == "INTRABAR_TOUCH"))
        xts_lim = ts_[min(i + off_l, n - 1)]

        base = {"sd": v.session_date_et, "e": v.entry_ts, "risk": risk}
        all_sim.append({**base, "xts": xts_sim, "pts": r_s * risk, "xt": xt_s, "ep": ep_sim})
        all_lim.append({**base, "xts": xts_lim, "pts": r_l * risk, "xt": xt_l, "ep": ep_lim})
        seg_n += 1

    print(f"  → {seg_n} cands  total_sim={len(all_sim)}", flush=True)

print(f"\nRaw (pre-occupancy): {len(all_sim):,}", flush=True)


ch_sim = occupancy_filter(all_sim)
ch_lim = occupancy_filter(all_lim)
print(f"After occupancy: sim={len(ch_sim)}  lim={len(ch_lim)}\n", flush=True)


def report(ch, label):
    yrs = sorted(set(t["sd"].year for t in ch))
    wk  = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    all_r = []; green = 0
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
    print("-" * 55)
    print(f"  TOTAL {len(ch):>5}  {pf:>8.4f}  {all_r.sum():>+9.1f}R  {100*(all_r>0).mean():>5.1f}%")
    print(f"  /wk={len(ch)/wk:.1f}  MDD={mdd:.1f}R  green={green}/{len(yrs)}"
          f"  T={xt_['TARGET']}  S={xt_['STOP']}  t={xt_['TIME']}")
    return float(all_r.sum())


print("=" * 65)
print(f"NQ DEV 2018-2025  TP={TP_K}R  SL={SL_K:.4f}R  BE30  |z|<1  GROSS")
print("=" * 65)

print("\n── A) SIM FILL  (bar open) ────────────────────────────")
net_sim = report(ch_sim, "SIM")

print("\n── B) LIMIT FILL  (zone boundary) ────────────────────")
net_lim = report(ch_lim, "LIM")

pts_diffs = [abs(tl["ep"] - ts["ep"]) for ts, tl in zip(ch_sim, ch_lim)]
r_gains   = [tl["pts"]/tl["risk"] - ts["pts"]/ts["risk"]
             for ts, tl in zip(ch_sim, ch_lim)]
improved  = sum(1 for x in pts_diffs if x > 0.01)

print(f"\n── FILL ANALYSIS ──────────────────────────────────────")
print(f"  Trades with different fill:   {improved}/{len(ch_sim)} ({100*improved/len(ch_sim):.1f}%)")
if improved:
    print(f"  Avg improvement when differs: {np.mean([x for x in pts_diffs if x > 0.01]):.2f} pts")
print(f"  Total R gain from limit fill: {sum(r_gains):+.1f}R")
print(f"  Per-trade avg R gain:         {np.mean(r_gains):+.4f}R")
print(f"  Net R: sim={net_sim:+.1f}  lim={net_lim:+.1f}  Δ={net_lim-net_sim:+.1f}R")

print("\nDone.", flush=True)

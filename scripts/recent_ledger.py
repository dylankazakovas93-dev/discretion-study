"""Quick ledger: 2025 and 2026 trades from dev segcache. No observe() needed — fast."""
import sys, pickle, random
import numpy as np
from collections import defaultdict

sys.path.insert(0, "src")

SEG  = "artifacts/multiyear_validation_v2/segcache"
TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480

random.seed(7)

seg_data = {}
for si in range(34):
    try:
        bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl", "rb"))
        seg_data[si] = (
            np.array([b.open  for b in bars]),
            np.array([b.high  for b in bars]),
            np.array([b.low   for b in bars]),
            [b.ts_et for b in bars],
            {b.ts_et: i for i, b in enumerate(bars)},
        )
    except FileNotFoundError:
        pass

ALL_C = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl", "rb"))
ALL_C = [c for c in ALL_C
         if c["session"] == "NY_AM" and c["fkey"][2] == "rb"
         and c["context_tf"] in (1, 3, 5) and c["sd"].year >= 2025]
px_ = np.array([c["_px"]            for c in ALL_C])
vw_ = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_ - vw_) / sd_) if abs(z) < 1.0]
print(f"Candidates 2025+: {len(ALL_C)}", flush=True)

trades = []
for c in ALL_C:
    si = int(c["gvid"].split("::")[0][3:6])
    if si not in seg_data: continue
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    n = len(o_)
    d = c["direction"]; ep = float(o_[i]); risk = c["risk"]
    tp_pts = TP_K * risk; sl_pts = SL_K * risk
    tgt = ep + d * tp_pts; stp = ep - d * sl_pts
    end = min(n - 1, i + MAXH)
    sb = False; xt = None
    for s in range(i, end + 1):
        hs = (l_[s] <= stp) if d > 0 else (h_[s] >= stp)
        ht = (h_[s] >= tgt) if d > 0 else (l_[s] <= tgt)
        if hs and ht: sb = True; xt = ("STOP",   -sl_pts, ts_[s]); break
        if hs:        xt = ("STOP",   -sl_pts, ts_[s]); break
        if ht:        xt = ("TARGET",  tp_pts, ts_[s]); break
    if xt is None:
        xt = ("TIME", (o_[end] - ep) * d, ts_[end])
    trades.append({
        "year": c["sd"].year,
        "date": c["sd"],
        "entry_ts": c["entry_ts"],
        "time": c["entry_ts"].strftime("%H:%M"),
        "dir":  "LONG" if d > 0 else "SHORT",
        "entry": ep,
        "tp_dist": round(tp_pts, 2),
        "sl_dist": round(sl_pts, 2),
        "hit":  xt[0],
        "pnl_r": round(xt[1] / risk, 2),
        "atr":  round(risk, 2),
        "xts":  xt[2],
        "sb":   sb,
    })

# Correct occupancy: compare full entry timestamp vs exit timestamp
def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["entry_ts"], str(z["dir"])))
    ch = []; until = None
    for t in tr:
        if until and t["entry_ts"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

ch = occupancy_filter(trades)

by_year = defaultdict(list)
for t in ch: by_year[t["year"]].append(t)

print(f"\n2025 trades after occupancy: {len(by_year.get(2025,[]))}")
print(f"2026 trades after occupancy: {len(by_year.get(2026,[]))}\n")

sample = []
for yr in sorted(by_year):
    picks = random.sample(by_year[yr], min(8, len(by_year[yr])))
    sample.extend(sorted(picks, key=lambda x: x["entry_ts"]))

print("=" * 88)
print(f"{'Year':<5} {'Date':<12} {'Time':<6} {'Dir':<6} {'Entry':>9} {'TP dist':>8} {'SL dist':>8} {'Hit':<8} {'PnL R':>6} {'ATR':>7}")
print("-" * 88)
for t in sample:
    sb_flag = " *" if t["sb"] else ""
    print(f"{t['year']:<5} {str(t['date']):<12} {t['time']:<6} {t['dir']:<6} {t['entry']:>9.2f} "
          f"{t['tp_dist']:>8.2f} {t['sl_dist']:>8.2f} {t['hit']:<8} {t['pnl_r']:>+6.2f}R {t['atr']:>7.2f}{sb_flag}")
print("=" * 88)
print("* = same-bar TP+SL conflict → STOP applied")
print("\nDone.", flush=True)

"""
RR sweep: TP fixed at 1.5× ATR(24) 1m, SL varies to produce target RR ratios.

RR = TP/SL (reward-to-risk). TP is always 1.5R.
  2.0RR → SL = 0.75R
  1.5RR → SL = 1.00R
  1.0RR → SL = 1.50R  (current best, symmetric)
  0.7RR → SL = 1.5/0.7 ≈ 2.143R
  0.5RR → SL = 3.00R

Dev data:  candidates_with_features.pkl (2018-2025)
2026 data: oos_clean_candidates.pkl, NY_AM RB-K1 subset, entries in seg033 only
"""
import sys, pickle, numpy as np
from collections import defaultdict
sys.path.insert(0, "src")

SEG  = "artifacts/multiyear_validation_v2/segcache"
MAXH = 480

TP_K = 1.5
# RR = TP/SL → SL = TP/RR
RR_CONFIGS = [
    (2.0, TP_K / 2.0),
    (1.5, TP_K / 1.5),
    (1.0, TP_K / 1.0),
    (0.7, TP_K / 0.7),
    (0.5, TP_K / 0.5),
]

# ── Load segcache ─────────────────────────────────────────────────────────────
print("Loading segcache...", flush=True)
seg_data = {}
for si in range(34):   # seg000 – seg033
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
print(f"  {len(seg_data)} segments loaded", flush=True)

# ── Load dev candidates (2018-2025) ──────────────────────────────────────────
print("Loading dev candidates...", flush=True)
ALL_C = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl", "rb"))
ALL_C = [c for c in ALL_C
         if c["risk"] >= 12.0 and c["session"] == "NY_AM"
         and c["fkey"][2] == "rb" and c["context_tf"] in (1, 3, 5)]
px_ = np.array([c["_px"]            for c in ALL_C])
vw_ = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_ - vw_) / sd_) if abs(z) < 1.0]
print(f"  Dev candidates: {len(ALL_C):,}", flush=True)

# Index dev candidates
dev_cands = []
for c in ALL_C:
    si = int(c["gvid"].split("::")[0][3:6])
    if si not in seg_data: continue
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    dev_cands.append({"sd": c["sd"], "e": c["entry_ts"], "si": si, "i": i,
                      "ep": float(o_[i]), "d": c["direction"], "risk": c["risk"],
                      "fk": c["fkey"]})
print(f"  {len(dev_cands):,} dev candidates indexed", flush=True)

# ── Load 2026 OOS candidates (seg033 subset only) ────────────────────────────
print("Loading 2026 OOS candidates...", flush=True)
oos_all = pickle.load(open("artifacts/rb_refinement/oos_clean_candidates.pkl", "rb"))
oos_rbk1 = [x for x in oos_all
             if x["sess"] == "NY_AM" and x["cf"] == "rb"
             and x["ctf"] in (1, 3, 5) and abs(x["z"]) < 1.0
             and x["risk"] >= 12.0]

si33 = 33
o33, h33, l33, ts33, ti33 = seg_data[si33]

oos_cands = []
for c in oos_rbk1:
    i = ti33.get(c["e"], -1)
    if i < 0: continue  # entry not in seg033 range
    d = c["fk"][1]  # direction from fkey tuple
    oos_cands.append({"sd": c["sd"], "e": c["e"], "si": si33, "i": i,
                      "ep": float(o33[i]), "d": d, "risk": c["risk"],
                      "fk": c["fk"]})
print(f"  {len(oos_cands)} 2026 OOS candidates in seg033 range", flush=True)

# ── Simulate one RR config ───────────────────────────────────────────────────
def simulate(cands_in, sl_k):
    trades = []
    for rec in cands_in:
        si = rec["si"]; i = rec["i"]; ep = rec["ep"]
        d = rec["d"]; risk = rec["risk"]
        o_, h_, l_, ts_, _ = seg_data[si]
        tp_pts = TP_K  * risk
        sl_pts = sl_k  * risk
        tgt = ep + d * tp_pts
        stp = ep - d * sl_pts
        end = min(len(o_) - 1, i + MAXH)
        xt = None
        for s in range(i, end + 1):
            if d > 0: hs = l_[s] <= stp; ht = h_[s] >= tgt
            else:     hs = h_[s] >= stp; ht = l_[s] <= tgt
            if hs and ht: xt = ("STOP",   -sl_pts, ts_[s]); break
            if hs:        xt = ("STOP",   -sl_pts, ts_[s]); break
            if ht:        xt = ("TARGET",  tp_pts, ts_[s]); break
        if xt is None:
            xt = ("TIME", (o_[end] - ep) * d, ts_[end])
        trades.append({"sd": rec["sd"], "e": rec["e"], "xts": xt[2],
                       "pts": xt[1], "risk": risk, "fk": rec["fk"], "xt": xt[0]})
    return trades

def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], str(z["fk"])))
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

def per_year(trades):
    ch = occupancy_filter(trades)
    if not ch: return {}
    out = {}
    yrs = sorted(set(t["sd"].year for t in ch))
    for y in yrs:
        sub = [t for t in ch if t["sd"].year == y]
        r2 = np.array([(t["pts"] - 2.0) / t["risk"] for t in sub])
        gp = r2[r2 > 0].sum(); lp = -r2[r2 <= 0].sum()
        out[y] = {"n": len(sub), "pf2": gp/lp if lp > 0 else float("inf"),
                  "net2": r2.sum(), "win": 100*(r2>0).mean()}
    return out

def summary(trades, rr, sl_k):
    ch = occupancy_filter(trades)
    if not ch: return None
    wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    r2 = np.array([(t["pts"] - 2.0) / t["risk"] for t in ch])
    r1 = np.array([(t["pts"] - 1.0) / t["risk"] for t in ch])
    gp2 = r2[r2>0].sum(); lp2 = -r2[r2<=0].sum()
    gp1 = r1[r1>0].sum(); lp1 = -r1[r1<=0].sum()
    pf2 = gp2/lp2 if lp2>0 else float("inf")
    pf1 = gp1/lp1 if lp1>0 else float("inf")
    eq  = np.cumsum(r2); mdd = (eq - np.maximum.accumulate(eq)).min()
    win = 100*(r2>0).mean()
    yv  = per_year(trades)
    green = sum(1 for v in yv.values() if v["pf2"] > 1.0)
    xt_ = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1
    be_win = (sl_k + 2.0/20) / (TP_K - 2.0/20 + sl_k + 2.0/20) * 100
    return {
        "rr": rr, "sl_k": sl_k, "n": len(ch), "wk": wk,
        "pf1": pf1, "pf2": pf2, "net2": r2.sum(), "mdd": mdd,
        "win": win, "green": green, "total_yrs": len(yv),
        "target": xt_["TARGET"], "stop": xt_["STOP"], "time": xt_["TIME"],
        "yv": yv, "be_win": be_win,
    }

# ── Run sweeps ────────────────────────────────────────────────────────────────
print("\nRunning RR sweep on dev candidates (2018-2025)...", flush=True)
dev_results = []
for rr, sl_k in RR_CONFIGS:
    t = simulate(dev_cands, sl_k)
    s = summary(t, rr, sl_k)
    dev_results.append(s)
    print(f"  RR={rr:.1f}  SL={sl_k:.3f}R  n={s['n']}  PF@2={s['pf2']:.4f}  net@2={s['net2']:+.1f}  win={s['win']:.1f}%  green={s['green']}/{s['total_yrs']}  MDD={s['mdd']:.1f}", flush=True)

print("\nRunning RR sweep on 2026 OOS (seg033 window only)...", flush=True)
oos_results = []
for rr, sl_k in RR_CONFIGS:
    t = simulate(oos_cands, sl_k)
    s = summary(t, rr, sl_k)
    oos_results.append(s)
    if s:
        print(f"  RR={rr:.1f}  SL={sl_k:.3f}R  n={s['n']}  PF@2={s['pf2']:.4f}  net@2={s['net2']:+.1f}  win={s['win']:.1f}%", flush=True)

# ── Print tables ──────────────────────────────────────────────────────────────
print("\n" + "="*90)
print("RR SWEEP — TP fixed at 1.5R, SL varies   (dev 2018-2025)")
print("="*90)
print(f"{'RR':>5}  {'SL':>6}  {'n':>5}  {'/wk':>4}  {'PF@1':>7}  {'PF@2':>7}  {'net@2':>8}  {'MDD@2':>7}  {'win%':>6}  {'green':>6}  {'BE%':>5}  T/S/t")
print("-"*90)
for s in dev_results:
    t_s_t = f"{s['target']}/{s['stop']}/{s['time']}"
    print(f"  {s['rr']:>3.1f}  {s['sl_k']:>6.3f}R  {s['n']:>5}  {s['n']/s['wk']:>4.1f}  "
          f"{s['pf1']:>7.4f}  {s['pf2']:>7.4f}  {s['net2']:>+8.1f}  {s['mdd']:>7.1f}  "
          f"{s['win']:>5.1f}%  {s['green']:>2}/{s['total_yrs']:>2}    "
          f"{s['be_win']:>4.1f}%  {t_s_t}")

print("\n" + "="*90)
print("RR SWEEP — TP fixed at 1.5R, SL varies   (2026 OOS, seg033 window only)")
print("="*90)
print(f"{'RR':>5}  {'SL':>6}  {'n':>4}  {'PF@2':>7}  {'net@2':>8}  {'win%':>6}")
print("-"*50)
for s in oos_results:
    if s:
        print(f"  {s['rr']:>3.1f}  {s['sl_k']:>6.3f}R  {s['n']:>4}  {s['pf2']:>7.4f}  {s['net2']:>+8.1f}  {s['win']:>5.1f}%")

# ── Year-by-year for 1.0RR (current best) ────────────────────────────────────
print("\n── YEAR-BY-YEAR: 1.0RR (TP=1.5R, SL=1.5R) ──────────────────────────────")
print(f"{'Year':>5}  {'n':>5}  {'PF@2':>7}  {'net@2':>8}  {'win%':>6}")
s10 = dev_results[2]  # 1.0RR is index 2
for y, v in sorted(s10["yv"].items()):
    print(f"  {y}  {v['n']:>5}  {v['pf2']:>7.4f}  {v['net2']:>+8.1f}  {v['win']:>5.1f}%")
s26 = oos_results[2]
if s26 and s26["yv"]:
    for y, v in sorted(s26["yv"].items()):
        print(f"  {y}* {v['n']:>5}  {v['pf2']:>7.4f}  {v['net2']:>+8.1f}  {v['win']:>5.1f}%  (2026 OOS partial)")

# ── Year-by-year for all RR configs ──────────────────────────────────────────
print("\n── YEAR-BY-YEAR ALL RR CONFIGS ──────────────────────────────────────────")
all_years = sorted(set(y for s in dev_results for y in s["yv"]))
header = f"{'Year':>5}" + "".join(f"  {'RR'+str(s['rr'])+'@net':>12}" for s in dev_results)
print(header)
for y in all_years:
    row = f"  {y}"
    for s in dev_results:
        v = s["yv"].get(y)
        if v:
            row += f"  {v['net2']:>+7.1f}({v['pf2']:.3f})"
        else:
            row += f"  {'---':>12}"
    print(row)

# 2026 row
row = "  2026*"
for s in oos_results:
    v = s["yv"].get(2026)
    if v:
        row += f"  {v['net2']:>+7.1f}({v['pf2']:.3f})"
    else:
        row += f"  {'---':>12}"
print(row + "  (OOS partial)")

print("\n* 2026 = OOS partial window (Apr 26 – Jun 7, seg033 only, ~81 trades max)")
print(f"\nBreakeven win rates at @2pt commission (mean ATR=20pt):")
for s in dev_results:
    print(f"  RR={s['rr']:.1f}  TP={TP_K}R  SL={s['sl_k']:.3f}R  → BE={s['be_win']:.1f}%  actual={s['win']:.1f}%  margin={s['win']-s['be_win']:+.1f}%")

print("\nDone.", flush=True)

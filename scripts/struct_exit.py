"""
Structural TP from prior bars' swing extreme.

Long  → TP = max(high[i-N .. i-1])  (nearest swing high above entry)
Short → TP = min(low[i-N  .. i-1])  (nearest swing low  below entry)

Gate: |TP - entry| must be >= min_tp_atr * ATR, else trade is rejected.
SL  = sl_atr * ATR on the opposite side.
Entry = open of entry bar. Stop-first on same-bar ambiguity.
Occupancy enforced. Reports per-year PF@1 / PF@2.
"""
import sys, pickle, numpy as np
sys.path.insert(0, "src")
from collections import defaultdict

SEG  = "artifacts/multiyear_validation_v2/segcache"
OUT  = "artifacts/rb_refinement"
MAXH = 480

# ── Load RB-K1 candidates ─────────────────────────────────────────────────────
ALL_C = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
ALL_C = [c for c in ALL_C
         if c["risk"] >= 12.0 and c["session"] == "NY_AM"
         and c["fkey"][2] == "rb" and c["context_tf"] in (1, 3, 5)]
px_ = np.array([c["_px"]            for c in ALL_C])
vw_ = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_ - vw_) / sd_) if abs(z) < 1.0]
print(f"RB-K1 stream: {len(ALL_C):,}", flush=True)

# ── Load segcache once ────────────────────────────────────────────────────────
print("Loading segcache...", flush=True)
segs_needed = sorted(set(int(c["gvid"].split("::")[0][3:6]) for c in ALL_C))
seg_data = {}
for si in segs_needed:
    bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    seg_data[si] = (
        np.array([b.open  for b in bars]),
        np.array([b.high  for b in bars]),
        np.array([b.low   for b in bars]),
        [b.ts_et for b in bars],
        {b.ts_et: i for i, b in enumerate(bars)},
    )
print(f"  {len(seg_data)} segments", flush=True)

# Pre-index candidates
cands = []
for c in ALL_C:
    si = int(c["gvid"].split("::")[0][3:6])
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    cands.append({"c": c, "si": si, "i": i, "ep": float(o_[i]),
                  "d": c["direction"], "risk": c["risk"]})
print(f"  {len(cands):,} indexed", flush=True)

# ── Simulate ──────────────────────────────────────────────────────────────────
def simulate(cands_in, lookback, min_tp_atr, sl_atr):
    trades    = []
    rejected  = 0
    for rec in cands_in:
        c = rec["c"]; si=rec["si"]; i=rec["i"]; ep=rec["ep"]
        d = rec["d"]; risk = rec["risk"]
        o_, h_, l_, ts_, _ = seg_data[si]

        # Structural TP from completed bars before entry bar
        start = max(0, i - lookback)
        if d > 0:
            tp_struct = h_[start:i].max() if i > start else ep + 2 * risk
        else:
            tp_struct = l_[start:i].min() if i > start else ep - 2 * risk

        tp_pts = abs(tp_struct - ep)
        sl_pts = sl_atr * risk

        # Gate: reject if structural target is too close
        if tp_pts < min_tp_atr * risk:
            rejected += 1
            continue

        # Ensure minimum 1.5R floor anyway
        tp_pts = max(tp_pts, min_tp_atr * risk)

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

        trades.append({"sd": c["sd"], "e": c["entry_ts"], "xts": xt[2],
                       "pts": xt[1], "risk": risk, "fk": c["fkey"],
                       "xt": xt[0], "tp_r": tp_pts / risk, "sl_r": sl_atr})
    return trades, rejected

def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], z["fk"]))
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

def report(trades, rej, label, show_years=False):
    ch = occupancy_filter(trades)
    if not ch:
        print(f"  {label:<55}  no trades (rejected={rej})"); return None
    wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    r2a = np.array([(t["pts"] - 2.0) / t["risk"] for t in ch])
    r1a = np.array([(t["pts"] - 1.0) / t["risk"] for t in ch])
    gp2 = r2a[r2a>0].sum(); lp2 = -r2a[r2a<=0].sum()
    gp1 = r1a[r1a>0].sum(); lp1 = -r1a[r1a<=0].sum()
    pf2 = gp2/lp2 if lp2>0 else float("inf")
    pf1 = gp1/lp1 if lp1>0 else float("inf")
    eq  = np.cumsum(r2a); mdd = (eq - np.maximum.accumulate(eq)).min()
    win = 100*(r2a>0).mean()
    yrs = sorted(set(t["sd"].year for t in ch))
    yv  = {}
    for y in yrs:
        sub = [t for t in ch if t["sd"].year==y]
        r2y = np.array([(t["pts"]-2)/t["risk"] for t in sub])
        gpy=r2y[r2y>0].sum(); lpy=-r2y[r2y<=0].sum()
        yv[y]=gpy/lpy if lpy>0 else float("inf")
    green = sum(1 for v in yv.values() if v>1.0)

    # avg actual TP/SL multiples used
    tp_mean = np.mean([t["tp_r"] for t in ch])
    xt_ = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1
    print(f"  {label:<55}  "
          f"n={len(ch):>5}({rej:>4}rej)  {len(ch)/wk:>4.1f}/wk  "
          f"PF@1={pf1:.4f}  PF@2={pf2:.4f}  "
          f"net@2={r2a.sum():>7.1f}  MDD@2={mdd:>7.1f}  "
          f"win={win:>5.1f}%  green={green}/{len(yrs)}  "
          f"avgTP={tp_mean:.2f}R  T={xt_['TARGET']} S={xt_['STOP']}",
          flush=True)

    if show_years:
        for y in yrs:
            sub=[t for t in ch if t["sd"].year==y]
            r2y=np.array([(t["pts"]-2)/t["risk"] for t in sub])
            r1y=np.array([(t["pts"]-1)/t["risk"] for t in sub])
            gp2y=r2y[r2y>0].sum(); lp2y=-r2y[r2y<=0].sum()
            gp1y=r1y[r1y>0].sum(); lp1y=-r1y[r1y<=0].sum()
            print(f"    {y}  n={len(sub):>4}  PF@1={(gp1y/lp1y if lp1y>0 else 0):.4f}  PF@2={(gp2y/lp2y if lp2y>0 else 0):.4f}  net@2={r2y.sum():>7.1f}")

    return pf2

# ── Baselines ─────────────────────────────────────────────────────────────────
def fixed_baseline(k_tp, k_sl):
    trades = []
    for rec in cands:
        c=rec["c"]; si=rec["si"]; i=rec["i"]; ep=rec["ep"]
        d=rec["d"]; risk=rec["risk"]
        o_,h_,l_,ts_,_=seg_data[si]
        tgt=ep+d*k_tp*risk; stp=ep-d*k_sl*risk
        end=min(len(o_)-1,i+MAXH); xt=None
        for s in range(i,end+1):
            if d>0: hs=l_[s]<=stp; ht=h_[s]>=tgt
            else:   hs=h_[s]>=stp; ht=l_[s]<=tgt
            if hs and ht: xt=("STOP",-k_sl*risk,ts_[s]); break
            if hs:        xt=("STOP",-k_sl*risk,ts_[s]); break
            if ht:        xt=("TARGET",k_tp*risk,ts_[s]); break
        if xt is None: xt=("TIME",(o_[end]-ep)*d,ts_[end])
        trades.append({"sd":c["sd"],"e":c["entry_ts"],"xts":xt[2],
                       "pts":xt[1],"risk":risk,"fk":c["fkey"],"xt":xt[0],
                       "tp_r":k_tp,"sl_r":k_sl})
    return trades

print("\n── BASELINES ────────────────────────────────────────────────────────────")
print(f"  {'label':<55}  {'n':>6}  /wk   PF@1    PF@2     net@2    MDD@2    win    green")
report(fixed_baseline(2.0, 1.0), 0, "FIXED 2.0R TP / 1.0R SL")
report(fixed_baseline(2.0, 1.5), 0, "FIXED 2.0R TP / 1.5R SL  [prev best]")

print("\n── STRUCTURAL TP: swing extreme of prior N bars ────────────────────────")
print(f"  {'label':<55}  {'n':>6}(rej)  /wk   PF@1    PF@2     net@2    MDD@2    win    green  avgTP  T S")

LOOKBACKS   = [2, 3, 5, 10, 20]
MIN_TP_ATRS = [1.5, 2.0]
SL_ATRS     = [1.0, 1.5]

best = {"pf2": 0, "label": ""}
for lb in LOOKBACKS:
    for min_tp in MIN_TP_ATRS:
        for sl in SL_ATRS:
            t, rej = simulate(cands, lb, min_tp, sl)
            lbl = f"swing-{lb}bar  minTP={min_tp}R  SL={sl}R"
            pf2 = report(t, rej, lbl)
            if pf2 and pf2 > best["pf2"]:
                best = {"pf2": pf2, "label": lbl, "t": t, "rej": rej}

print(f"\nBest: {best['label']}  PF@2={best['pf2']:.4f}")

# ── Also test: structural TP but floor at min_tp_atr and always accept (no rejection) ─
print("\n── STRUCTURAL TP: floor enforced, no trade rejection ───────────────────")
def simulate_floor(cands_in, lookback, min_tp_atr, sl_atr):
    """Same structural TP but never reject — if structure is within min_tp_atr, use min_tp_atr."""
    trades = []
    for rec in cands_in:
        c=rec["c"]; si=rec["si"]; i=rec["i"]; ep=rec["ep"]
        d=rec["d"]; risk=rec["risk"]
        o_,h_,l_,ts_,_=seg_data[si]
        start=max(0,i-lookback)
        if d>0:
            tp_struct=h_[start:i].max() if i>start else ep+2*risk
        else:
            tp_struct=l_[start:i].min() if i>start else ep-2*risk
        tp_pts=max(abs(tp_struct-ep), min_tp_atr*risk)  # floor, no reject
        sl_pts=sl_atr*risk
        tgt=ep+d*tp_pts; stp=ep-d*sl_pts
        end=min(len(o_)-1,i+MAXH); xt=None
        for s in range(i,end+1):
            if d>0: hs=l_[s]<=stp; ht=h_[s]>=tgt
            else:   hs=h_[s]>=stp; ht=l_[s]<=tgt
            if hs and ht: xt=("STOP",-sl_pts,ts_[s]); break
            if hs:        xt=("STOP",-sl_pts,ts_[s]); break
            if ht:        xt=("TARGET",tp_pts,ts_[s]); break
        if xt is None: xt=("TIME",(o_[end]-ep)*d,ts_[end])
        trades.append({"sd":c["sd"],"e":c["entry_ts"],"xts":xt[2],
                       "pts":xt[1],"risk":risk,"fk":c["fkey"],"xt":xt[0],
                       "tp_r":tp_pts/risk,"sl_r":sl_atr})
    return trades

for lb in LOOKBACKS:
    for min_tp in MIN_TP_ATRS:
        for sl in SL_ATRS:
            t=simulate_floor(cands,lb,min_tp,sl)
            lbl=f"floor-{lb}bar  minTP={min_tp}R  SL={sl}R"
            report(t,0,lbl)

# ── Year-by-year for winners ──────────────────────────────────────────────────
print("\n\n── YEAR-BY-YEAR: best structural + both baselines ───────────────────────")
for lb in [5, 10]:
    for sl in [1.0, 1.5]:
        t = simulate_floor(cands, lb, 1.5, sl)
        lbl = f"floor-{lb}bar minTP=1.5R SL={sl}R"
        print(f"\n  [{lbl}]")
        print(f"  yr        n     PF@1     PF@2    net@2")
        ch = occupancy_filter(t)
        if not ch: continue
        for y in sorted(set(x["sd"].year for x in ch)):
            sub=[x for x in ch if x["sd"].year==y]
            r2=np.array([(x["pts"]-2)/x["risk"] for x in sub])
            r1=np.array([(x["pts"]-1)/x["risk"] for x in sub])
            g2=r2[r2>0].sum(); l2=-r2[r2<=0].sum()
            g1=r1[r1>0].sum(); l1=-r1[r1<=0].sum()
            print(f"  {y}  {len(sub):>5}  {g1/l1 if l1>0 else 0:>7.4f}  {g2/l2 if l2>0 else 0:>7.4f}  {r2.sum():>7.1f}")
        r2t=np.array([(x["pts"]-2)/x["risk"] for x in ch])
        r1t=np.array([(x["pts"]-1)/x["risk"] for x in ch])
        g2t=r2t[r2t>0].sum(); l2t=-r2t[r2t<=0].sum()
        g1t=r1t[r1t>0].sum(); l1t=-r1t[r1t<=0].sum()
        eq=np.cumsum(r2t); mdd=(eq-np.maximum.accumulate(eq)).min()
        tp_mean=np.mean([x["tp_r"] for x in ch])
        print(f"  TOTAL  {len(ch):>5}  {g1t/l1t if l1t>0 else 0:>7.4f}  {g2t/l2t if l2t>0 else 0:>7.4f}  {r2t.sum():>7.1f}  MDD={mdd:.1f}  avgTP={tp_mean:.2f}R  win={100*(r2t>0).mean():.1f}%")

print("\nDone.", flush=True)

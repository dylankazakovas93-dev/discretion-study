"""
2D grid sweep: tp_k × sl_k with bar-by-bar sim from segcache.
Also tests reaction-state filters and EMA alignment filter.
TP min = 2× ATR, SL min = 1× ATR.
All exits on whole 1m bar closes (open[bar] entry, check h/l from entry bar onward).
Stop-first on same-bar ambiguity. Occupancy enforced.
"""
import sys, pickle, numpy as np, os
sys.path.insert(0, "src")
from collections import defaultdict

SEG  = "artifacts/multiyear_validation_v2/segcache"
OUT  = "artifacts/rb_refinement"
MAXH = 480

# ── Load RB-K1 candidates ────────────────────────────────────────────────────
ALL = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
ALL = [c for c in ALL
       if c["risk"] >= 12.0 and c["session"] == "NY_AM"
       and c["fkey"][2] == "rb" and c["context_tf"] in (1, 3, 5)]
px  = np.array([c["_px"]              for c in ALL])
vw  = np.array([c["vwap_CASH_0930"]   for c in ALL])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL]), 1e-9)
ALL = [c for c, z in zip(ALL, (px - vw) / sd_) if abs(z) < 1.0]
print(f"RB-K1 stream: {len(ALL):,}", flush=True)

# ── Bar-by-bar sim function ──────────────────────────────────────────────────
def simulate(candidates, k_tp, k_sl, label=""):
    bysec = defaultdict(list)
    for c in candidates:
        si = int(c["gvid"].split("::")[0][3:6])
        bysec[si].append(c)
    trades = []
    for si, grp in sorted(bysec.items()):
        bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
        o_ = np.array([b.open  for b in bars])
        h_ = np.array([b.high  for b in bars])
        l_ = np.array([b.low   for b in bars])
        ti = {b.ts_et: i for i, b in enumerate(bars)}
        for c in grp:
            i = ti.get(c["entry_ts"], -1)
            if i < 0: continue
            ep   = o_[i]; d = c["direction"]; risk = c["risk"]
            tgt  = ep + d * k_tp * risk
            stp  = ep - d * k_sl * risk
            end  = min(len(o_) - 1, i + MAXH)
            xt   = None
            for s in range(i, end + 1):
                if d > 0: hs = l_[s] <= stp; ht = h_[s] >= tgt
                else:     hs = h_[s] >= stp; ht = l_[s] <= tgt
                if hs and ht: xt = ("STOP",   -k_sl * risk, bars[s].ts_et); break
                if hs:        xt = ("STOP",   -k_sl * risk, bars[s].ts_et); break
                if ht:        xt = ("TARGET",  k_tp * risk, bars[s].ts_et); break
            if xt is None:
                xt = ("TIME", (o_[end] - ep) * d, bars[end].ts_et)
            trades.append({"sd": c["sd"], "e": c["entry_ts"], "xts": xt[2],
                           "pts": xt[1], "risk": risk, "fk": c["fkey"], "xt": xt[0]})
    return trades

# ── Reporting ────────────────────────────────────────────────────────────────
def report(trades, label, show_years=False):
    tr = sorted(trades, key=lambda z: (z["e"], z["fk"]))
    ch = []; until = None
    for t in tr:
        if until is not None and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    if not ch:
        print(f"  {label:<35}  no trades"); return None

    wk  = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    xt_ = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1

    r2a = np.array([(t["pts"] - 2.0) / t["risk"] for t in ch])
    r1a = np.array([(t["pts"] - 1.0) / t["risk"] for t in ch])
    gp2 = r2a[r2a > 0].sum(); lp2 = -r2a[r2a <= 0].sum()
    gp1 = r1a[r1a > 0].sum(); lp1 = -r1a[r1a <= 0].sum()
    pf2 = gp2 / lp2 if lp2 > 0 else float("inf")
    pf1 = gp1 / lp1 if lp1 > 0 else float("inf")
    eq  = np.cumsum(r2a)
    mdd = (eq - np.maximum.accumulate(eq)).min()
    win = 100 * (r2a > 0).mean()
    yrs = sorted(set(t["sd"].year for t in ch))
    yv  = {y: sum(1 for r in [((t["pts"]-2)/t["risk"]) for t in ch if t["sd"].year==y] if r>0)
           - sum(1 for r in [((t["pts"]-2)/t["risk"]) for t in ch if t["sd"].year==y] if r<=0)
           for y in yrs}
    green = sum(1 for v in yv.values() if v > 0)

    out = (f"  {label:<40}  n={len(ch):>5}  {len(ch)/wk:>4.1f}/wk"
           f"  PF@1={pf1:.4f}  PF@2={pf2:.4f}"
           f"  net@2={r2a.sum():>7.1f}  MDD@2={mdd:>7.1f}"
           f"  win={win:>5.1f}%  green={green}/{len(yrs)}"
           f"  T={xt_['TARGET']} S={xt_['STOP']} t={xt_['TIME']}")
    print(out, flush=True)

    if show_years:
        for y in yrs:
            sub  = [t for t in ch if t["sd"].year == y]
            r2y  = np.array([(t["pts"] - 2.0) / t["risk"] for t in sub])
            gpy  = r2y[r2y > 0].sum(); lpy = -r2y[r2y <= 0].sum()
            pfy  = gpy / lpy if lpy > 0 else float("inf")
            print(f"    {y}  n={len(sub):>4}  PF@2={pfy:.4f}  net@2={r2y.sum():>7.1f}")

    return {"label": label, "n": len(ch), "per_wk": len(ch)/wk,
            "pf1": pf1, "pf2": pf2, "net2": r2a.sum(),
            "mdd2": mdd, "win": win, "green": green, "nyrs": len(yrs)}

# ── 1. Reaction-state filter sets ───────────────────────────────────────────
# From diagnostic: TAP_ONLY (77.2%), MINIMAL_WICK_REJECTION (73.5%), STRONG_REJECTION_DEPARTURE (74.1%)
HIGH_REACT = {"TAP_ONLY", "MINIMAL_WICK_REJECTION", "STRONG_REJECTION_DEPARTURE"}
LOW_REACT  = {"DELAYED_DISPLACEMENT", "NEW_FVG", "NEW_IFVG", "IMMEDIATE_DISPLACEMENT"}

sets = {
    "ALL":        ALL,
    "HIGH_REACT": [c for c in ALL if c["reaction_state"] in HIGH_REACT],
    "LOW_REACT":  [c for c in ALL if c["reaction_state"] in LOW_REACT],
    # EMA against trade (higher median MFE)
    "EMA_VS":     [c for c in ALL if c["direction"] * c["emaslope_1"] < 0],
    # High ADX1 (≥25) — trending environment
    "ADX_HIGH":   [c for c in ALL if c["adx_1"] >= 25],
    # Low ADX1 (<20)
    "ADX_LOW":    [c for c in ALL if c["adx_1"] < 20],
    # 1m context only (purest signal)
    "CTX1M":      [c for c in ALL if c["context_tf"] == 1],
}
print("\nCandidate counts per filter set:")
for k, v in sets.items():
    print(f"  {k:<15}: {len(v):,}")

# ── 2. Grid: tp_k × sl_k ────────────────────────────────────────────────────
TP_KS = [2.0, 2.5, 3.0, 3.5, 4.0]
SL_KS = [1.0, 1.25, 1.5, 2.0]

print("\n\n── GRID SWEEP: ALL candidates ──────────────────────────────────────────")
print(f"{'label':<40}  {'n':>6}  {'wk':>4}  PF@1    PF@2     net@2    MDD@2    win    green  TP/STP/T")
grid_results = {}
for k_sl in SL_KS:
    for k_tp in TP_KS:
        lbl = f"TP={k_tp:.1f}R  SL={k_sl:.2f}R"
        t   = simulate(ALL, k_tp, k_sl)
        r   = report(t, lbl)
        grid_results[(k_tp, k_sl)] = r

# ── 3. Best combo on each filter set ─────────────────────────────────────────
print("\n\n── FILTER SETS @ best grid combos ──────────────────────────────────────")
BEST_COMBOS = [(2.0, 1.0), (2.5, 1.0), (3.0, 1.0), (2.0, 1.5), (2.5, 1.5), (3.0, 1.25)]
for fname, fcands in sets.items():
    print(f"\n  [{fname}: n={len(fcands)}]")
    for k_tp, k_sl in BEST_COMBOS:
        lbl = f"    {fname}  TP={k_tp:.1f}R  SL={k_sl:.2f}R"
        t   = simulate(fcands, k_tp, k_sl)
        report(t, lbl)

# ── 4. Year-by-year for the overall winner ───────────────────────────────────
print("\n\n── YEAR-BY-YEAR for key combos ─────────────────────────────────────────")
key_combos = [(2.0, 1.0), (2.5, 1.0), (3.0, 1.0), (2.5, 1.25), (3.0, 1.25)]
for k_tp, k_sl in key_combos:
    t = simulate(ALL, k_tp, k_sl)
    print(f"\nTP={k_tp}R  SL={k_sl}R")
    report(t, f"TP={k_tp}R SL={k_sl}R", show_years=True)

pickle.dump(grid_results, open(f"{OUT}/tpsl_grid.pkl","wb"))
print("\nDone.", flush=True)

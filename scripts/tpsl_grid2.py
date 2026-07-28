"""
2D grid sweep: tp_k × sl_k — loads segcache ONCE into memory.
Also tests reaction-state and EMA-alignment filters.
TP min=2R, SL min=1R. Stop-first. Occupancy enforced.
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
         and c["fkey"][2] == "rb" and c["context_tf"] in (1,3,5)]
px_   = np.array([c["_px"]            for c in ALL_C])
vw_   = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_   = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_-vw_)/sd_) if abs(z) < 1.0]
print(f"RB-K1 stream: {len(ALL_C):,}", flush=True)

# ── Load ALL segcache bars into memory ONCE ───────────────────────────────────
print("Loading segcache into memory...", flush=True)
segs_needed = sorted(set(int(c["gvid"].split("::")[0][3:6]) for c in ALL_C))
seg_data = {}  # si -> (o_arr, h_arr, l_arr, ts_idx_dict)
for si in segs_needed:
    bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    o_   = np.array([b.open  for b in bars])
    h_   = np.array([b.high  for b in bars])
    l_   = np.array([b.low   for b in bars])
    ts_  = [b.ts_et for b in bars]
    ti_  = {b.ts_et: i for i, b in enumerate(bars)}
    seg_data[si] = (o_, h_, l_, ts_, ti_)
print(f"  {len(seg_data)} segments loaded", flush=True)

# ── Pre-compute (entry_idx, direction, risk, sd, fkey, entry_ts) per candidate
print("Pre-computing entry indices...", flush=True)
candidates = []  # list of dicts with all needed info
for c in ALL_C:
    si  = int(c["gvid"].split("::")[0][3:6])
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i   = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    candidates.append({
        "si":    si,
        "i":     i,
        "ep":    float(o_[i]),
        "d":     c["direction"],
        "risk":  c["risk"],
        "sd":    c["sd"],
        "e":     c["entry_ts"],
        "fk":    c["fkey"],
        "react": c["reaction_state"],
        "ctx":   c["context_tf"],
        "adx1":  c["adx_1"],
        "ems1":  c["direction"] * c["emaslope_1"],  # EMA slope in trade direction
    })
print(f"  {len(candidates):,} candidates indexed", flush=True)

# ── Simulate all candidates for one (k_tp, k_sl) pair ────────────────────────
def simulate_all(cands, k_tp, k_sl):
    trades = []
    for c in cands:
        o_, h_, l_, ts_, _ = seg_data[c["si"]]
        i    = c["i"]; ep = c["ep"]; d = c["d"]; risk = c["risk"]
        tgt  = ep + d * k_tp * risk
        stp  = ep - d * k_sl * risk
        end  = min(len(o_) - 1, i + MAXH)
        xt   = None
        for s in range(i, end + 1):
            if d > 0: hs = l_[s] <= stp; ht = h_[s] >= tgt
            else:     hs = h_[s] >= stp; ht = l_[s] <= tgt
            if hs and ht: xt = ("STOP",   -k_sl * risk, ts_[s]); break
            if hs:        xt = ("STOP",   -k_sl * risk, ts_[s]); break
            if ht:        xt = ("TARGET",  k_tp * risk, ts_[s]); break
        if xt is None:
            xt = ("TIME", (o_[end] - ep) * d, ts_[end])
        trades.append({"sd": c["sd"], "e": c["e"], "xts": xt[2],
                       "pts": xt[1], "risk": risk, "fk": c["fk"], "xt": xt[0]})
    return trades

def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], z["fk"]))
    ch = []; until = None
    for t in tr:
        if until is not None and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

def pf_net(ch, cost):
    r = np.array([(t["pts"] - cost) / t["risk"] for t in ch])
    gp = r[r > 0].sum(); lp = -r[r <= 0].sum()
    return (gp / lp if lp > 0 else float("inf")), r.sum()

def report_row(ch, label):
    if not ch:
        print(f"  {label:<50}  no trades"); return
    wk   = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    pf2, net2 = pf_net(ch, 2.0)
    pf1, net1 = pf_net(ch, 1.0)
    r2   = np.array([(t["pts"] - 2.0) / t["risk"] for t in ch])
    eq   = np.cumsum(r2); mdd = (eq - np.maximum.accumulate(eq)).min()
    win  = 100 * (r2 > 0).mean()
    xt_  = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1
    # per-year PF@2
    yrs  = sorted(set(t["sd"].year for t in ch))
    yv   = {}
    for y in yrs:
        sub = [t for t in ch if t["sd"].year == y]
        r2y = np.array([(t["pts"]-2)/t["risk"] for t in sub])
        gpy = r2y[r2y>0].sum(); lpy = -r2y[r2y<=0].sum()
        yv[y] = gpy/lpy if lpy>0 else float("inf")
    green = sum(1 for v in yv.values() if v > 1.0)
    print(f"  {label:<50}  n={len(ch):>5}  {len(ch)/wk:>4.1f}/wk"
          f"  PF@1={pf1:.4f}  PF@2={pf2:.4f}"
          f"  net@2={net2:>7.1f}  MDD@2={mdd:>7.1f}"
          f"  win={win:>5.1f}%  green_yrs={green}/{len(yrs)}"
          f"  T={xt_['TARGET']} S={xt_['STOP']}", flush=True)

def report_years(ch, label):
    if not ch: return
    print(f"\n  [{label}]")
    print(f"  {'yr':<6}{'n':>5}{'PF@1':>9}{'PF@2':>9}{'net@2':>9}")
    for y in sorted(set(t["sd"].year for t in ch)):
        sub = [t for t in ch if t["sd"].year == y]
        pf2, net2 = pf_net(sub, 2.0)
        pf1, _    = pf_net(sub, 1.0)
        print(f"  {y:<6}{len(sub):>5}{pf1:>9.4f}{pf2:>9.4f}{net2:>9.1f}")
    pf2t, net2t = pf_net(ch, 2.0)
    pf1t, _     = pf_net(ch, 1.0)
    print(f"  {'TOTAL':<6}{len(ch):>5}{pf1t:>9.4f}{pf2t:>9.4f}{net2t:>9.1f}")

# ── Filter sets ───────────────────────────────────────────────────────────────
HIGH_REACT = {"TAP_ONLY", "MINIMAL_WICK_REJECTION", "STRONG_REJECTION_DEPARTURE"}
LOW_REACT  = {"DELAYED_DISPLACEMENT", "NEW_FVG", "NEW_IFVG", "IMMEDIATE_DISPLACEMENT"}

fsets = {
    "ALL":         candidates,
    "HIGH_REACT":  [c for c in candidates if c["react"] in HIGH_REACT],
    "LOW_REACT":   [c for c in candidates if c["react"] in LOW_REACT],
    "EMA_VS":      [c for c in candidates if c["ems1"] < 0],   # EMA against trade
    "EMA_WITH":    [c for c in candidates if c["ems1"] > 0],   # EMA with trade
    "ADX_HIGH":    [c for c in candidates if c["adx1"] >= 25],
    "ADX_LOW":     [c for c in candidates if c["adx1"] < 20],
    "CTX1M":       [c for c in candidates if c["ctx"] == 1],
    # Combinations
    "HIGH_REACT_EMA_VS": [c for c in candidates if c["react"] in HIGH_REACT and c["ems1"] < 0],
    "HIGH_REACT_ADX25+": [c for c in candidates if c["react"] in HIGH_REACT and c["adx1"] >= 25],
}

print("\nFilter set sizes:")
for k, v in fsets.items():
    print(f"  {k:<25}: {len(v):,}")

# ── Grid sweep on ALL ─────────────────────────────────────────────────────────
TP_KS = [2.0, 2.5, 3.0, 3.5, 4.0]
SL_KS = [1.0, 1.25, 1.5, 2.0]

print("\n\n── GRID SWEEP: ALL candidates ───────────────────────────────────────────")
print(f"  {'label':<50}  {'n':>6}  /wk   PF@1    PF@2     net@2    MDD@2    win    green  T S")
best_pf2 = 0; best_label = ""
all_results = {}
for k_sl in SL_KS:
    for k_tp in TP_KS:
        raw  = simulate_all(candidates, k_tp, k_sl)
        ch   = occupancy_filter(raw)
        lbl  = f"TP={k_tp:.1f}R  SL={k_sl:.2f}R"
        report_row(ch, lbl)
        pf2, _ = pf_net(ch, 2.0)
        all_results[(k_tp, k_sl)] = ch
        if pf2 > best_pf2: best_pf2 = pf2; best_label = lbl

print(f"\nBest PF@2 on ALL: {best_label}  ({best_pf2:.4f})")

# ── Best combos across filter sets ───────────────────────────────────────────
BEST_COMBOS = [(2.0, 1.0), (2.0, 1.25), (2.0, 1.5), (2.0, 2.0),
               (2.5, 1.0), (2.5, 1.25), (2.5, 1.5)]

print("\n\n── FILTER SETS: key combos ──────────────────────────────────────────────")
print(f"  {'label':<50}  {'n':>6}  /wk   PF@1    PF@2     net@2    MDD@2    win    green  T S")
fset_results = {}
for fname, fcands in fsets.items():
    best_pf2_f = 0; best_combo_f = None
    for k_tp, k_sl in BEST_COMBOS:
        raw = simulate_all(fcands, k_tp, k_sl)
        ch  = occupancy_filter(raw)
        lbl = f"{fname}  TP={k_tp:.1f}R  SL={k_sl:.2f}R"
        report_row(ch, lbl)
        pf2, _ = pf_net(ch, 2.0)
        fset_results[(fname, k_tp, k_sl)] = ch
        if pf2 > best_pf2_f: best_pf2_f = pf2; best_combo_f = (k_tp, k_sl)
    print(f"   → best for {fname}: TP={best_combo_f[0]}R SL={best_combo_f[1]}R  PF@2={best_pf2_f:.4f}")

# ── Year-by-year for top combos ───────────────────────────────────────────────
print("\n\n── YEAR-BY-YEAR: selected combos ────────────────────────────────────────")
for (fname, k_tp, k_sl), ch in [
    (("ALL",       2.0, 1.0),  all_results[(2.0, 1.0)]),
    (("ALL",       2.0, 1.5),  all_results[(2.0, 1.5)]),
    (("ALL",       2.0, 2.0),  all_results[(2.0, 2.0)]),
    (("HIGH_REACT",2.0, 1.5),  fset_results.get(("HIGH_REACT",2.0,1.5), [])),
    (("HIGH_REACT",2.0, 2.0),  fset_results.get(("HIGH_REACT",2.0,2.0), [])),
]:
    report_years(ch, f"{fname} TP={k_tp}R SL={k_sl}R")

print("\nDone.", flush=True)

"""
Pre-trade formula-based TP/SL optimisation.

Walk-forward: train OLS on all sessions strictly before current year's first
session, predict per-trade TP/SL multipliers for that year, simulate bar-by-bar.

Constraints
-----------
TP  >= 2 × ATR(24) 1m  (= 2 × risk)
SL  >= 1 × ATR(24) 1m  (= 1 × risk)

All exits on whole 1m bar closes only — no intrabar fills.
Stop-first on same-bar ambiguity.
One-position occupancy enforced globally.
"""
import sys, pickle, numpy as np, os
sys.path.insert(0, "src")
from collections import defaultdict

SEG  = "artifacts/multiyear_validation_v2/segcache"
OUT  = "artifacts/rb_refinement"
MAXH = 480        # max bars to hold (480 min = 8 h)
MIN_TRAIN = 200   # minimum trades to fit the formula

# ── 1. Load & filter RB-K1 candidates ────────────────────────────────────────
ALL = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
ALL = [c for c in ALL
       if c["risk"] >= 12.0
       and c["session"] == "NY_AM"
       and c["fkey"][2] == "rb"
       and c["context_tf"] in (1, 3, 5)]
px  = np.array([c["_px"]              for c in ALL])
vw  = np.array([c["vwap_CASH_0930"]   for c in ALL])
sd  = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL]), 1e-9)
ALL = [c for c, z in zip(ALL, (px - vw) / sd) if abs(z) < 1.0]
print(f"RB-K1 stream: {len(ALL):,} candidates", flush=True)

# ── 2. Pre-compute features vector per candidate ──────────────────────────────
def featurise(c):
    """Return feature array (all computed from data available before entry bar)."""
    d   = c["direction"]          # +1 long / -1 short
    r   = max(c["risk"], 12.0)
    px_ = c["_px"]

    vz   = (px_ - c["vwap_CASH_0930"]) / max(c["vwsd_CASH_0930"], 1e-9)
    vs   = c["vwslope_CASH_0930"]      # VWAP slope (points/bar) at anchor

    # EMA distance in trade-direction R units (positive = price inside EMA side)
    ema_d1  = d * (px_ - c["ema21_1"])  / r
    ema_d5  = d * (px_ - c["ema21_5"])  / r
    ema_d15 = d * (px_ - c["ema21_15"]) / r
    # EMA slope alignment with trade
    ems_1   = d * c["emaslope_1"]
    ems_5   = d * c["emaslope_5"]

    adx1  = c["adx_1"]
    adx5  = c["adx_5"]
    adx15 = c["adx_15"]
    # DI spread in trade direction (pdi - ndi if long, ndi - pdi if short)
    di_d1  = d * (c["pdi_1"]  - c["ndi_1"])
    di_d5  = d * (c["pdi_5"]  - c["ndi_5"])
    di_d15 = d * (c["pdi_15"] - c["ndi_15"])

    log_r = np.log(r)             # ATR regime proxy

    # Entry hour (ET) — time-of-day context
    h = c["entry_ts"].hour + c["entry_ts"].minute / 60.0

    return np.array([
        1.0,          # intercept
        vz,           # VWAP z-score (signed, |z|<1)
        vs * d,       # VWAP slope in trade direction
        adx1, adx5, adx15,
        di_d1, di_d5, di_d15,
        ema_d1, ema_d5, ema_d15,
        ems_1, ems_5,
        log_r,        # ATR size
        h,            # hour
        vz ** 2,      # squared z (distance from VWAP regardless of side)
    ], dtype=np.float64)

# ── 3. Measure actual MFE / MAE from segcache bars ───────────────────────────
bysec = defaultdict(list)
for c in ALL:
    si = int(c["gvid"].split("::")[0][3:6])
    bysec[si].append(c)

records = []          # {c, X, mfe_r, mae_r}
for si, grp in sorted(bysec.items()):
    bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    o = np.array([b.open  for b in bars])
    h = np.array([b.high  for b in bars])
    l = np.array([b.low   for b in bars])
    c_ = np.array([b.close for b in bars])
    ti = {b.ts_et: i for i, b in enumerate(bars)}

    for c in grp:
        i = ti.get(c["entry_ts"], -1)
        if i < 0:
            continue
        ep  = o[i]
        d   = c["direction"]
        r   = c["risk"]
        end = min(len(o) - 1, i + MAXH)

        # bar-by-bar MFE / MAE (on HIGH / LOW of each bar)
        fav = 0.0; adv = 0.0
        for s in range(i, end + 1):
            fav = max(fav, d * (h[s] - ep) / r if d > 0 else d * (l[s] - ep) / r)
            adv = min(adv, d * (l[s] - ep) / r if d > 0 else d * (h[s] - ep) / r)

        records.append({
            "c":     c,
            "X":     featurise(c),
            "mfe_r": fav,       # always >= 0
            "mae_r": adv,       # always <= 0
            "year":  c["sd"].year,
        })
    print(f"  seg{si:03d} measured", flush=True)

print(f"Total records with MFE/MAE: {len(records):,}", flush=True)

# ── 4. Walk-forward OLS formula fit ──────────────────────────────────────────
years = sorted(set(r["year"] for r in records))

def ols_fit(Xm, ym):
    """Ordinary least squares: return weight vector."""
    XtX = Xm.T @ Xm + 1e-6 * np.eye(Xm.shape[1])
    Xty = Xm.T @ ym
    return np.linalg.solve(XtX, Xty)

def predict(w, X):
    return X @ w

# We predict log(mfe_r) and log(|mae_r|) to keep predictions positive
# Clip outliers to meaningful range before log
def safe_log(v, lo, hi):
    return np.log(np.clip(v, lo, hi))

results = []   # all simulated trades from test years

for yr in years:
    train = [r for r in records if r["year"] < yr]
    test  = [r for r in records if r["year"] == yr]
    if not train or not test:
        continue

    # Fit MFE model
    Xt = np.stack([r["X"] for r in train])
    yt_mfe = safe_log([r["mfe_r"] for r in train], 0.05, 20.0)
    yt_mae = safe_log([abs(r["mae_r"]) for r in train], 0.01, 10.0)

    if len(train) < MIN_TRAIN:
        # Insufficient training data — use fixed 2R / 1R
        w_mfe = None; w_mae = None
    else:
        w_mfe = ols_fit(Xt, yt_mfe)
        w_mae = ols_fit(Xt, yt_mae)

    n_used = len(train)
    print(f"  year {yr}: train={n_used}, test={len(test)}", flush=True)
    results.append(("_train_info", yr, n_used, len(test), w_mfe, w_mae,
                    [r for r in records if r["year"] == yr]))

print("Walk-forward formulas fitted.", flush=True)

# ── 5. Bar-by-bar simulation with formula TP/SL ──────────────────────────────
#      Rebuild segcache index for simulation pass
bysec2 = defaultdict(list)   # year -> list of (c, tp_pts, sl_pts)
for item in results:
    _, yr, _, _, w_mfe, w_mae, recs = item
    for r in recs:
        c = r["c"]
        X = r["X"]
        risk = c["risk"]

        if w_mfe is None:
            tp_r = 2.0
            sl_r = 1.0
        else:
            tp_r = max(2.0, float(np.exp(predict(w_mfe, X))))
            sl_r = max(1.0, float(np.exp(predict(w_mae, X))))

        tp_pts = tp_r * risk
        sl_pts = sl_r * risk
        si = int(c["gvid"].split("::")[0][3:6])
        bysec2[si].append((c, tp_pts, sl_pts))

sim_trades = []
for si, grp in sorted(bysec2.items()):
    bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    o_ = np.array([b.open  for b in bars])
    h_ = np.array([b.high  for b in bars])
    l_ = np.array([b.low   for b in bars])
    ti2 = {b.ts_et: i for i, b in enumerate(bars)}

    for c, tp_pts, sl_pts in grp:
        i = ti2.get(c["entry_ts"], -1)
        if i < 0:
            continue
        ep  = o_[i]
        d   = c["direction"]
        tgt = ep + d * tp_pts
        stp = ep - d * sl_pts
        end = min(len(o_) - 1, i + MAXH)

        xt = None
        for s in range(i, end + 1):
            if d > 0:
                hit_s = l_[s] <= stp
                hit_t = h_[s] >= tgt
            else:
                hit_s = h_[s] >= stp
                hit_t = l_[s] <= tgt

            if hit_s and hit_t:
                # same-bar ambiguity: stop first (conservative)
                xt = ("STOP", -sl_pts, bars[s].ts_et)
                break
            if hit_s:
                xt = ("STOP", -sl_pts, bars[s].ts_et)
                break
            if hit_t:
                xt = ("TARGET", tp_pts, bars[s].ts_et)
                break

        if xt is None:
            pts = (o_[end] - ep) * d
            xt = ("TIME", pts, bars[end].ts_et)

        sim_trades.append({
            "sd":   c["sd"],
            "e":    c["entry_ts"],
            "xts":  xt[2],
            "pts":  xt[1],
            "risk": c["risk"],
            "fk":   c["fkey"],
            "xt":   xt[0],
        })

print(f"Simulated {len(sim_trades):,} trades", flush=True)

# ── 6. Occupancy filter + reporting ──────────────────────────────────────────
def report(trades, label):
    tr = sorted(trades, key=lambda z: (z["e"], z["fk"]))
    ch = []; until = None
    for t in tr:
        if until is not None and t["e"] < until:
            continue
        ch.append(t); until = t["xts"]
    if not ch:
        print(f"{label}: no trades"); return

    wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    xt_cnt = defaultdict(int)
    for t in ch: xt_cnt[t["xt"]] += 1
    stops   = xt_cnt["STOP"]
    targets = xt_cnt["TARGET"]
    times   = xt_cnt["TIME"]

    header = f"\n{'='*60}\n{label}\n{'='*60}"
    hdr2   = f"{'year':<6}{'n':>5}{'PF@1':>9}{'PF@2':>9}{'net@2':>9}{'win%':>7}"
    print(header)
    print(f"  Trades (occupancy-filtered): {len(ch)}  "
          f"({targets} target / {stops} stop / {times} time)  "
          f"{len(ch)/wk:.2f}/wk")
    print(hdr2)

    all_r2 = []
    yrs_green = 0
    for yr in sorted(set(t["sd"].year for t in ch)):
        sub = [t for t in ch if t["sd"].year == yr]
        r2  = [(t["pts"] - 2.0) / t["risk"] for t in sub]
        all_r2.extend(r2)
        gp  = sum(x for x in r2 if x > 0)
        lp  = -sum(x for x in r2 if x <= 0)
        pf  = gp / lp if lp > 0 else float("inf")
        r1  = [(t["pts"] - 1.0) / t["risk"] for t in sub]
        gp1 = sum(x for x in r1 if x > 0)
        lp1 = -sum(x for x in r1 if x <= 0)
        pf1 = gp1 / lp1 if lp1 > 0 else float("inf")
        win = 100 * sum(1 for t in sub if t["pts"] > 0) / len(sub)
        if pf > 1.0: yrs_green += 1
        print(f"  {yr:<6}{len(sub):>5}{pf1:>9.4f}{pf:>9.4f}{sum(r2):>9.1f}{win:>6.1f}%")

    r2a = np.array(all_r2)
    gpa = r2a[r2a > 0].sum(); lpa = -r2a[r2a <= 0].sum()
    pfa = gpa / lpa if lpa > 0 else float("inf")
    eq  = np.cumsum(r2a)
    mdd = (eq - np.maximum.accumulate(eq)).min()
    r1a = np.array([(t["pts"] - 1.0) / t["risk"] for t in ch])
    gp1a = r1a[r1a > 0].sum(); lp1a = -r1a[r1a <= 0].sum()
    pf1a = gp1a / lp1a if lp1a > 0 else float("inf")
    print(f"\n  TOTAL  n={len(ch)}  PF@1={pf1a:.4f}  PF@2={pfa:.4f}  "
          f"net@2={r2a.sum():.1f}  MDD@2={mdd:.1f}  "
          f"green_yrs={yrs_green}/{len(set(t['sd'].year for t in ch))}")

# Fixed 2R baseline (all trades)
def fixed_sim(k_tp, k_sl, label):
    bysec3 = defaultdict(list)
    for c in ALL:
        si = int(c["gvid"].split("::")[0][3:6])
        bysec3[si].append(c)
    trades = []
    for si, grp in sorted(bysec3.items()):
        bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
        o_ = np.array([b.open  for b in bars])
        h_ = np.array([b.high  for b in bars])
        l_ = np.array([b.low   for b in bars])
        ti_ = {b.ts_et: i for i, b in enumerate(bars)}
        for c in grp:
            i = ti_.get(c["entry_ts"], -1)
            if i < 0: continue
            ep = o_[i]; d = c["direction"]; risk = c["risk"]
            tgt = ep + d * k_tp * risk
            stp = ep - d * k_sl * risk
            end = min(len(o_) - 1, i + MAXH)
            xt = None
            for s in range(i, end + 1):
                if d > 0: hs = l_[s] <= stp; ht = h_[s] >= tgt
                else:     hs = h_[s] >= stp; ht = l_[s] <= tgt
                if hs and ht: xt = ("STOP", -k_sl * risk, bars[s].ts_et); break
                if hs:        xt = ("STOP", -k_sl * risk, bars[s].ts_et); break
                if ht:        xt = ("TARGET", k_tp * risk, bars[s].ts_et); break
            if xt is None: xt = ("TIME", (o_[end]-ep)*d, bars[end].ts_et)
            trades.append({"sd":c["sd"],"e":c["entry_ts"],"xts":xt[2],
                           "pts":xt[1],"risk":risk,"fk":c["fkey"],"xt":xt[0]})
    return trades

print("\n\nRunning fixed-baseline 2R TP / 1R SL for comparison...", flush=True)
baseline_2r = fixed_sim(2.0, 1.0, "FIXED 2R/1R")
report(baseline_2r, "BASELINE: fixed 2R target / 1R stop")

report(sim_trades, "FORMULA: walk-forward OLS TP/SL (min 2R/1R)")

pickle.dump({"formula": sim_trades, "baseline_2r": baseline_2r},
            open(f"{OUT}/formula_exit.pkl","wb"))
print("\nDone. Results saved to artifacts/rb_refinement/formula_exit.pkl", flush=True)

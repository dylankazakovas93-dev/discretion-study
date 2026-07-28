"""
Per-trade adaptive TP/SL fitted on MFE/MAE.

For every RB-K1 trade, output a specific TP and SL in points using pre-trade
features.  No trades are filtered out — every candidate gets a TP and SL.
Walk-forward causal: train on completed years strictly before the test year.

Formula
-------
  tp_r(x) = max(2.0, exp( w_tp · feats(x) ))
  sl_r(x) = max(1.0, exp( w_sl · feats(x) ))

Fitted via OLS on log(MFE_r) and log(|MAE_r|) with a walk-forward calibration
multiplier (alpha_tp, alpha_sl) that maximises PF on the previous calendar year.

Features (all computed from data available BEFORE the entry bar)
---------------------------------------------------------------
  - log(atr)             — ATR size / volatility regime
  - adx_1                — 1m ADX (trend strength)
  - di_d_1               — DI spread in trade direction (1m)
  - adx_5, di_d_5        — same on 5m
  - adx_15, di_d_15      — same on 15m
  - abs(vwap_z)          — distance from 09:30 VWAP in SD units
  - vwap_slope * dir     — VWAP slope in trade direction
  - ema_dist_1           — (px - ema21_1) * dir / atr
  - ema_slope_1 * dir    — EMA slope in trade direction
  - ema_dist_5
  - entry_hour           — hour of day (ET decimal)
  - vol_ratio            — entry bar volume / avg volume of prior 20 bars
  - body_ratio           — |open-close| / (high-low) of entry bar
  - range_vs_atr         — (high-low) of entry bar / atr (bar size vs ATR)
  - atr_vs_20d_atr       — current ATR / mean ATR of last 20 bars (vol expansion)
"""
import sys, pickle, numpy as np
sys.path.insert(0, "src")
from collections import defaultdict

SEG  = "artifacts/multiyear_validation_v2/segcache"
OUT  = "artifacts/rb_refinement"
MAXH = 480

# ── 1. Load RB-K1 candidates ─────────────────────────────────────────────────
ALL_C = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl","rb"))
ALL_C = [c for c in ALL_C
         if c["risk"] >= 12.0 and c["session"] == "NY_AM"
         and c["fkey"][2] == "rb" and c["context_tf"] in (1, 3, 5)]
px_  = np.array([c["_px"]            for c in ALL_C])
vw_  = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_  = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_ - vw_) / sd_) if abs(z) < 1.0]
print(f"RB-K1 stream: {len(ALL_C):,}", flush=True)

# ── 2. Load segcache once ─────────────────────────────────────────────────────
print("Loading segcache...", flush=True)
segs_needed = sorted(set(int(c["gvid"].split("::")[0][3:6]) for c in ALL_C))
seg_data = {}
for si in segs_needed:
    bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl","rb"))
    seg_data[si] = (
        np.array([b.open   for b in bars]),
        np.array([b.high   for b in bars]),
        np.array([b.low    for b in bars]),
        np.array([b.close  for b in bars]),
        np.array([b.volume for b in bars], dtype=float),
        [b.ts_et for b in bars],
        {b.ts_et: i for i, b in enumerate(bars)},
    )
print(f"  {len(seg_data)} segments", flush=True)

# ── 3. Featurise + measure MFE/MAE ───────────────────────────────────────────
def featurise(c, o_, h_, l_, cl_, vol_, i):
    """All values from bars[0..i-1] (completed) and bars[i] is the entry bar."""
    d    = c["direction"]
    atr  = max(c["risk"], 12.0)
    px   = o_[i]   # entry price = open of entry bar

    # Volume: entry bar vs prior 20-bar mean
    vol_window = vol_[max(0, i-20):i]
    vol_mean   = vol_window.mean() if len(vol_window) > 0 else 1.0
    vol_ratio  = vol_[i] / max(vol_mean, 1.0)

    # Entry bar OHLC geometry
    bar_range  = max(h_[i] - l_[i], 1e-6)
    body       = abs(o_[i] - cl_[i])
    body_ratio = body / bar_range           # 0=doji, 1=full body
    range_vs_atr = bar_range / atr          # bar size relative to ATR

    # ATR expansion: current ATR vs mean of last 20 bars (using bar range as ATR proxy)
    atr_hist  = np.array([h_[j] - l_[j] for j in range(max(0, i-20), i)])
    atr_mean  = atr_hist.mean() if len(atr_hist) > 0 else atr
    atr_ratio = atr / max(atr_mean, 1.0)

    vwap_z  = (px - c["vwap_CASH_0930"]) / max(c["vwsd_CASH_0930"], 1e-9)
    vs      = c["vwslope_CASH_0930"]

    # EMA distances normalised by ATR
    ema_d1  = d * (px - c["ema21_1"])  / atr
    ema_d5  = d * (px - c["ema21_5"])  / atr
    ema_s1  = d * c["emaslope_1"]
    ema_s5  = d * c["emaslope_5"]

    adx1   = c["adx_1"]
    adx5   = c["adx_5"]
    adx15  = c["adx_15"]
    di_d1  = d * (c["pdi_1"]  - c["ndi_1"])
    di_d5  = d * (c["pdi_5"]  - c["ndi_5"])
    di_d15 = d * (c["pdi_15"] - c["ndi_15"])

    hour = c["entry_ts"].hour + c["entry_ts"].minute / 60.0

    return np.array([
        1.0,              # intercept
        np.log(atr),      # volatility regime
        adx1,             # trend strength 1m
        di_d1,            # DI directional alignment 1m
        adx5,             # trend strength 5m
        di_d5,            # DI alignment 5m
        adx15,            # trend strength 15m
        di_d15,           # DI alignment 15m
        abs(vwap_z),      # distance from VWAP (scalar)
        vs * d,           # VWAP slope in trade direction
        ema_d1,           # EMA distance 1m
        ema_s1,           # EMA slope 1m
        ema_d5,           # EMA distance 5m
        ema_s5,           # EMA slope 5m
        hour,             # time of day
        vol_ratio,        # volume vs 20-bar mean
        body_ratio,       # entry bar body/range
        range_vs_atr,     # entry bar size vs ATR
        atr_ratio,        # ATR expansion vs recent history
        vwap_z ** 2,      # squared VWAP z (non-linear distance)
    ], dtype=np.float64)

records = []
print("Computing features + MFE/MAE...", flush=True)
for si, grp in [(si, [c for c in ALL_C if int(c["gvid"].split("::")[0][3:6])==si])
                for si in segs_needed]:
    o_, h_, l_, cl_, vol_, ts_, ti_ = seg_data[si]
    for c in grp:
        i = ti_.get(c["entry_ts"], -1)
        if i < 0: continue
        ep  = o_[i]; d = c["direction"]; r = c["risk"]
        end = min(len(o_) - 1, i + MAXH)

        # MFE / MAE measured on H/L of each bar
        fav = adv = 0.0
        for s in range(i, end + 1):
            fav = max(fav, (d*(h_[s]-ep) if d>0 else d*(l_[s]-ep)) / r)
            adv = min(adv, (d*(l_[s]-ep) if d>0 else d*(h_[s]-ep)) / r)

        X = featurise(c, o_, h_, l_, cl_, vol_, i)
        records.append({
            "c":      c,
            "si":     si,
            "i":      i,
            "ep":     ep,
            "X":      X,
            "mfe_r":  fav,          # >= 0
            "mae_r":  adv,          # <= 0
            "year":   c["sd"].year,
        })

print(f"Total records: {len(records):,}", flush=True)

# ── 4. Walk-forward OLS fit ───────────────────────────────────────────────────
def ols(X, y):
    XtX = X.T @ X + 1e-4 * np.eye(X.shape[1])
    return np.linalg.solve(XtX, X.T @ y)

def clip_log(v, lo, hi):
    return np.log(np.clip(v, lo, hi))

# ── 5. Calibration: find alpha multipliers that maximise PF on TRAIN data ─────
def simulate_trades_predict(recs, w_tp, w_sl, alpha_tp, alpha_sl):
    """Predict tp_r / sl_r per record, simulate bar-by-bar, return raw trade list."""
    trades = []
    for rec in recs:
        X    = rec["X"]
        risk = rec["c"]["risk"]
        c    = rec["c"]
        si   = rec["si"]; i = rec["i"]; ep = rec["ep"]; d = c["direction"]
        o_, h_, l_, cl_, vol_, ts_, _ = seg_data[si]

        tp_r = max(2.0, alpha_tp * float(np.exp(X @ w_tp)))
        sl_r = max(1.0, alpha_sl * float(np.exp(X @ w_sl)))
        tgt  = ep + d * tp_r * risk
        stp  = ep - d * sl_r * risk
        end  = min(len(o_) - 1, i + MAXH)

        xt = None
        for s in range(i, end + 1):
            if d > 0: hs = l_[s] <= stp; ht = h_[s] >= tgt
            else:     hs = h_[s] >= stp; ht = l_[s] <= tgt
            if hs and ht: xt = ("STOP",   -sl_r*risk, ts_[s]); break
            if hs:        xt = ("STOP",   -sl_r*risk, ts_[s]); break
            if ht:        xt = ("TARGET",  tp_r*risk, ts_[s]); break
        if xt is None:
            xt = ("TIME", (o_[end]-ep)*d, ts_[end])

        trades.append({"sd": c["sd"], "e": c["entry_ts"], "xts": xt[2],
                       "pts": xt[1], "risk": risk, "fk": c["fkey"], "xt": xt[0]})
    return trades

def pf2(trades):
    ch = occupancy_filter(trades)
    r  = np.array([(t["pts"]-2.0)/t["risk"] for t in ch])
    gp = r[r>0].sum(); lp = -r[r<=0].sum()
    return (gp/lp if lp>0 else 0.0)

def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], z["fk"]))
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

# Calibration grid for alpha_tp, alpha_sl
ALPHA_GRID = [0.5, 0.7, 1.0, 1.3, 1.5, 2.0]
MIN_TRAIN  = 300

print("Walk-forward fit + calibration...", flush=True)
years = sorted(set(r["year"] for r in records))
all_sim_trades = []

for yr in years:
    train = [r for r in records if r["year"] <  yr]
    test  = [r for r in records if r["year"] == yr]
    if not train or not test:
        continue

    Xt  = np.stack([r["X"] for r in train])
    yt_mfe = clip_log([r["mfe_r"]        for r in train], 0.05, 20.0)
    yt_mae = clip_log([abs(r["mae_r"])   for r in train], 0.01, 10.0)

    w_tp = ols(Xt, yt_mfe)
    w_sl = ols(Xt, yt_mae)

    # Calibrate alpha on training data to find best multiplier
    best_pf = -1; best_atp = 1.0; best_asl = 1.0
    if len(train) >= MIN_TRAIN:
        for atp in ALPHA_GRID:
            for asl in ALPHA_GRID:
                t_ = simulate_trades_predict(train, w_tp, w_sl, atp, asl)
                p  = pf2(t_)
                if p > best_pf:
                    best_pf = p; best_atp = atp; best_asl = asl
    else:
        best_atp = 1.0; best_asl = 1.0

    print(f"  {yr}: train={len(train)}, alpha_tp={best_atp}, alpha_sl={best_asl}, train_PF@2={best_pf:.4f}", flush=True)

    # Apply to test year
    test_trades = simulate_trades_predict(test, w_tp, w_sl, best_atp, best_asl)
    all_sim_trades.extend(test_trades)

print(f"Total simulated: {len(all_sim_trades):,}", flush=True)

# ── 6. Report ─────────────────────────────────────────────────────────────────
def full_report(trades, label):
    ch = occupancy_filter(trades)
    if not ch: print(f"{label}: no trades"); return
    wk   = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    xt_  = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    print(f"Trades: {len(ch)}  ({xt_['TARGET']} T / {xt_['STOP']} S / {xt_['TIME']} t)  {len(ch)/wk:.1f}/wk")
    print(f"{'yr':<6}{'n':>5}{'PF@1':>9}{'PF@2':>9}{'net@2':>9}")
    all_r2 = []
    for y in sorted(set(t["sd"].year for t in ch)):
        sub = [t for t in ch if t["sd"].year == y]
        r2  = np.array([(t["pts"]-2)/t["risk"] for t in sub])
        r1  = np.array([(t["pts"]-1)/t["risk"] for t in sub])
        gp2 = r2[r2>0].sum(); lp2 = -r2[r2<=0].sum()
        gp1 = r1[r1>0].sum(); lp1 = -r1[r1<=0].sum()
        print(f"{y:<6}{len(sub):>5}{(gp1/lp1 if lp1>0 else 0):>9.4f}{(gp2/lp2 if lp2>0 else 0):>9.4f}{r2.sum():>9.1f}")
        all_r2.extend(r2.tolist())
    r2a = np.array(all_r2)
    gpa = r2a[r2a>0].sum(); lpa = -r2a[r2a<=0].sum()
    r1a = np.array([(t["pts"]-1)/t["risk"] for t in ch])
    gp1a = r1a[r1a>0].sum(); lp1a = -r1a[r1a<=0].sum()
    eq   = np.cumsum(r2a); mdd = (eq-np.maximum.accumulate(eq)).min()
    nyrs = len(set(t["sd"].year for t in ch))
    green = sum(1 for y in set(t["sd"].year for t in ch)
                if sum((t["pts"]-2)/t["risk"] for t in ch if t["sd"].year==y)>0)
    print(f"{'TOTAL':<6}{len(ch):>5}"
          f"{(gp1a/lp1a if lp1a>0 else 0):>9.4f}"
          f"{(gpa/lpa if lpa>0 else 0):>9.4f}"
          f"{r2a.sum():>9.1f}")
    print(f"MDD@2={mdd:.1f}  win={100*(r2a>0).mean():.1f}%  green={green}/{nyrs}")

# Show formula result vs fixed 2R/1R baseline
def baseline(k_tp, k_sl):
    trades = []
    for rec in records:
        c   = rec["c"]; si=rec["si"]; i=rec["i"]; ep=rec["ep"]; d=c["direction"]
        o_,h_,l_,cl_,vol_,ts_,_ = seg_data[si]
        risk=c["risk"]; tgt=ep+d*k_tp*risk; stp=ep-d*k_sl*risk
        end=min(len(o_)-1,i+MAXH); xt=None
        for s in range(i,end+1):
            if d>0: hs=l_[s]<=stp; ht=h_[s]>=tgt
            else:   hs=h_[s]>=stp; ht=l_[s]<=tgt
            if hs and ht: xt=("STOP",-k_sl*risk,ts_[s]); break
            if hs:        xt=("STOP",-k_sl*risk,ts_[s]); break
            if ht:        xt=("TARGET",k_tp*risk,ts_[s]); break
        if xt is None: xt=("TIME",(o_[end]-ep)*d,ts_[end])
        trades.append({"sd":c["sd"],"e":c["entry_ts"],"xts":xt[2],
                       "pts":xt[1],"risk":risk,"fk":c["fkey"],"xt":xt[0]})
    return trades

print("\n\nResults:")
full_report(all_sim_trades, "ADAPTIVE FORMULA (OLS + walk-forward calibration)")
full_report(baseline(2.0, 1.0), "BASELINE: fixed 2R TP / 1R SL")
full_report(baseline(2.0, 1.5), "BASELINE: fixed 2R TP / 1.5R SL")

pickle.dump(all_sim_trades, open(f"{OUT}/adaptive_exit.pkl","wb"))
print("\nDone.", flush=True)

"""
RB origin session analysis.
Re-runs observe() on segcache bars to capture context_formation_ts,
then groups performance by which session the RB formed in.
BE30 rule applied (move to breakeven after 30 bars if in profit).
"""
import sys, pickle, dataclasses, importlib.util
import numpy as np
from collections import defaultdict

sys.path.insert(0, "src")

from discretion.setup_observer.observer import observe
from discretion.setup_observer.sessions import session_of

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


all_cands = []

for si in range(33):
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

        origin_sess = session_of(v.context_formation_ts)

        all_cands.append({
            "sd": v.session_date_et, "entry_ts": v.entry_ts, "si": si, "i": i,
            "ep": float(o_[i]), "d": v.direction, "risk": risk,
            "origin": origin_sess,
        })
        seg_n += 1

    print(f"  → {seg_n} passing candidates  total={len(all_cands)}", flush=True)

print(f"\nTotal candidates: {len(all_cands):,}", flush=True)


# ── Simulate with BE30 ────────────────────────────────────────────────────────
def simulate_be30(cands):
    seg_cache = {}
    for c in cands:
        si = c["si"]
        if si not in seg_cache:
            bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl", "rb"))
            seg_cache[si] = (
                np.array([b.open  for b in bars]),
                np.array([b.high  for b in bars]),
                np.array([b.low   for b in bars]),
                [b.ts_et for b in bars],
            )

    trades = []
    for rec in cands:
        o_, h_, l_, ts_ = seg_cache[rec["si"]]
        i = rec["i"]; ep = rec["ep"]; d = rec["d"]; risk = rec["risk"]
        n = len(o_)
        tp_pts = TP_K * risk; sl_pts = SL_K * risk
        tgt = ep + d * tp_pts; stp = ep - d * sl_pts
        be_triggered = False; end = min(n-1, i+MAXH); xt = None
        for bar in range(i, end+1):
            offset = bar - i
            if not be_triggered and offset >= 30:
                cur = h_[bar] if d > 0 else l_[bar]
                if (cur > ep) if d > 0 else (cur < ep):
                    stp = ep; be_triggered = True
            hs = (l_[bar] <= stp) if d > 0 else (h_[bar] >= stp)
            ht = (h_[bar] >= tgt) if d > 0 else (l_[bar] <= tgt)
            if hs and ht: xt = ("STOP", -abs(ep-stp), ts_[bar]); break
            if hs:        xt = ("STOP", -abs(ep-stp), ts_[bar]); break
            if ht:        xt = ("TARGET", tp_pts, ts_[bar]); break
        if xt is None:
            xt = ("TIME", (o_[end]-ep)*d, ts_[end])
        trades.append({"sd": rec["sd"], "entry_ts": rec["entry_ts"],
                       "xts": xt[2], "pts": xt[1], "risk": risk,
                       "xt": xt[0], "origin": rec["origin"]})
    return trades


def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: z["entry_ts"])
    ch = []; until = None
    for t in tr:
        if until and t["entry_ts"] < until: continue
        ch.append(t); until = t["xts"]
    return ch


print("\nSimulating...", flush=True)
trades = simulate_be30(all_cands)
ch = occupancy_filter(trades)
print(f"After occupancy: {len(ch)} trades\n", flush=True)

# ── Report by origin session ───────────────────────────────────────────────────
# Count raw (pre-occupancy) distribution
raw_by_origin = defaultdict(int)
for c in all_cands: raw_by_origin[c["origin"]] += 1

print("=" * 80)
print("RB ORIGIN SESSION  (entry: NY_AM, |z|<1.0, BE30 rule, 0.7RR)")
print("=" * 80)
print(f"\nRaw candidate distribution (pre-occupancy):")
for sess, cnt in sorted(raw_by_origin.items(), key=lambda x: -x[1]):
    print(f"  {sess:<20} {cnt:>5}  ({100*cnt/len(all_cands):.1f}%)")

print(f"\n{'Origin session':<20}  {'n':>5}  {'/wk':>4}  {'PF':>7}  {'net':>8}  {'win%':>6}  {'MDD':>7}  {'green':>6}")
print("-" * 80)

sessions_ordered = ["NY_AM", "NY_PREMARKET", "LONDON", "GLOBEX_EVENING", "ASIA", "NY_LUNCH", "NY_PM", "HALT"]

all_wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7 if ch else 1

for sess in sessions_ordered:
    sub_trades = [t for t in ch if t["origin"] == sess]
    if not sub_trades: continue
    r = np.array([t["pts"]/t["risk"] for t in sub_trades])
    gp = r[r>0].sum(); lp = -r[r<=0].sum()
    pf = gp/lp if lp > 0 else float("inf")
    win = 100*(r>0).mean()
    eq = np.cumsum(r); mdd = (eq - np.maximum.accumulate(eq)).min()
    yrs = sorted(set(t["sd"].year for t in sub_trades))
    green = 0
    for y in yrs:
        ry = np.array([t["pts"]/t["risk"] for t in sub_trades if t["sd"].year == y])
        gpy = ry[ry>0].sum(); lpy = -ry[ry<=0].sum()
        if lpy > 0 and gpy/lpy > 1.0: green += 1
    print(f"  {sess:<20}  {len(sub_trades):>5}  {len(sub_trades)/all_wk:>4.1f}  "
          f"{pf:>7.4f}  {r.sum():>+8.1f}R  {win:>5.1f}%  {mdd:>7.1f}R  {green}/{len(yrs)}")

# ── Also show overall (sanity check) ─────────────────────────────────────────
r_all = np.array([t["pts"]/t["risk"] for t in ch])
gp = r_all[r_all>0].sum(); lp = -r_all[r_all<=0].sum()
pf = gp/lp if lp > 0 else float("inf")
win = 100*(r_all>0).mean()
eq = np.cumsum(r_all); mdd = (eq - np.maximum.accumulate(eq)).min()
yrs = sorted(set(t["sd"].year for t in ch))
green = 0
for y in yrs:
    ry = np.array([t["pts"]/t["risk"] for t in ch if t["sd"].year == y])
    gpy = ry[ry>0].sum(); lpy = -ry[ry<=0].sum()
    if lpy > 0 and gpy/lpy > 1.0: green += 1
print("-" * 80)
print(f"  {'ALL (combined)':<20}  {len(ch):>5}  {len(ch)/all_wk:>4.1f}  "
      f"{pf:>7.4f}  {r_all.sum():>+8.1f}R  {win:>5.1f}%  {mdd:>7.1f}R  {green}/{len(yrs)}")

print("\nDone.", flush=True)

"""
Final OOS: 2013-2015, RB-K1, 0.7RR gross.
Full rule set: |z|<1.0 VWAP, BE30 (move to breakeven after 30 bars if in profit),
all RB origin sessions included.
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

all_trades = []

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

        d = v.direction; ep = float(o_[i])
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

        all_trades.append({
            "sd": v.session_date_et, "e": v.entry_ts,
            "xts": xt[2], "pts": xt[1], "risk": risk, "xt": xt[0],
        })
        seg_n += 1

    print(f"  seg{sid:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}"
          f"  bars={n:>7,}  cands={seg_n:>4}  total={len(all_trades):>5}", flush=True)

print(f"\nRaw trades (pre-occupancy): {len(all_trades):,}", flush=True)

def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: z["e"])
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

ch = occupancy_filter(all_trades)
print(f"After occupancy: {len(ch)}\n", flush=True)

print("=" * 65)
print(f"RB-K1  OOS 2013-2015  TP={TP_K}R  SL={SL_K:.4f}R  BE30  |z|<1  GROSS")
print("=" * 65)

yrs = sorted(set(t["sd"].year for t in ch))
wk  = (ch[-1]["sd"] - ch[0]["sd"]).days / 7 if ch else 1
all_r = []
green = 0

print(f"\n{'Year':>5}  {'n':>5}  {'PF(gross)':>10}  {'net(gross)':>11}  {'win%':>6}")
for y in yrs:
    sub = [t for t in ch if t["sd"].year == y]
    r = np.array([t["pts"]/t["risk"] for t in sub])
    all_r.extend(r)
    gp = r[r>0].sum(); lp = -r[r<=0].sum()
    pf = gp/lp if lp > 0 else float("inf")
    if pf > 1.0: green += 1
    print(f"  {y}  {len(sub):>5}  {pf:>10.4f}  {r.sum():>+11.1f}  {100*(r>0).mean():>5.1f}%")

all_r = np.array(all_r)
gp = all_r[all_r>0].sum(); lp = -all_r[all_r<=0].sum()
pf = gp/lp if lp > 0 else float("inf")
eq = np.cumsum(all_r); mdd = (eq - np.maximum.accumulate(eq)).min()
xt_ = defaultdict(int)
for t in ch: xt_[t["xt"]] += 1

print("-" * 65)
print(f"  TOTAL {len(ch):>5}  {pf:>10.4f}  {all_r.sum():>+11.1f}  {100*(all_r>0).mean():>5.1f}%")
print(f"\n  /wk={len(ch)/wk:.1f}  MDD={mdd:.1f}R  green={green}/{len(yrs)}"
      f"  T={xt_['TARGET']}  S={xt_['STOP']}  t={xt_['TIME']}")
print(f"  Breakeven win rate (0.7RR, gross): {SL_K/(TP_K+SL_K)*100:.1f}%")
print(f"\n  Baseline (no BE30): PF≈1.65  net≈+770R  win=70.2%  3/3 green")
print(f"  Dev 2018-2025 (BE30, gross):      PF≈1.40  net≈+689R  win=61.1%  8/8 green")
print("\nDone.", flush=True)

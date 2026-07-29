"""
Pull a sample trade ledger from 2013-2015 OOS data.
Processes one segment per year to get representative trades fast (~25 min).
"""
import sys, io, dataclasses, random
import numpy as np
import pandas as pd
import zstandard as zs
from collections import defaultdict
import csv as _csv

sys.path.insert(0, "src")
import importlib.util

from discretion.data.bars import Bar
from discretion.data.loader import ET
from discretion.setup_observer.observer import observe

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

SRC  = "/root/.claude/uploads/6bbfe5fa-ed66-5075-a056-4af4be88eb35/306aaf2f-glbxmdp32013010120151231.ohlcv1m.csv.zst"
TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480

# One segment per year: seg00 (2013 Q1), seg05 (2014 Q2), seg10 (2015 Q3)
TARGET_SEGS = {0, 5, 10}


def wilder_atr24(h, l, c):
    n = len(h)
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
    atr = np.empty(n)
    atr[0] = tr[0]
    k = 1.0 / 24.0
    for i in range(1, n):
        atr[i] = atr[i-1] * (1 - k) + tr[i] * k
    return atr


print("Loading 2013-2015 data...", flush=True)
rows = []
with open(SRC, "rb") as fh:
    reader = io.TextIOWrapper(zs.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
    for r in _csv.DictReader(reader):
        sym = r["symbol"]
        if not sym.startswith("NQ"): continue
        if len(sym) != 4: continue
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

bars_all = []
seq = 0; prev_sym = None; seg_id = 0
for _, r in df.iterrows():
    if prev_sym is not None and r["sym"] != prev_sym:
        seg_id += 1; seq = 0
    bars_all.append(Bar(seq=seq, ts_utc=r["ts"], ts_et=r["ts"].tz_convert(ET),
                        open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                        volume=int(r["v"]), contract=r["sym"], segment_id=seg_id))
    seq += 1; prev_sym = r["sym"]
del df

segs = defaultdict(list)
for b in bars_all: segs[b.segment_id].append(b)

all_trades = []

for sid, sbars in sorted(segs.items()):
    if sid not in TARGET_SEGS:
        continue

    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n     = len(local)
    print(f"  Processing seg{sid:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}  bars={n:,}", flush=True)

    _ev, variants, _disc = observe(local, target_window=600)

    F  = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}

    h_arr = np.array([b.high  for b in local])
    l_arr = np.array([b.low   for b in local])
    o_arr = np.array([b.open  for b in local])
    c_arr = np.array([b.close for b in local])
    ts_arr = [b.ts_et for b in local]

    atr24 = wilder_atr24(h_arr, l_arr, c_arr)

    for v in variants:
        if not v.executable: continue
        if v.session != "NY_AM": continue
        if v.context_family != "rb": continue
        if v.context_tf not in (1, 3, 5): continue

        i = ti.get(v.entry_ts, -1)
        if i < 1: continue

        px = float(F["close"][i - 1])
        vw = float(F["vwap_CASH_0930"][i - 1])
        sd = max(float(F["vwsd_CASH_0930"][i - 1]), 1e-9)
        if abs((px - vw) / sd) >= 1.0: continue

        risk = float(atr24[i - 1])
        if risk <= 0: continue

        d   = v.direction
        ep  = float(o_arr[i])
        tp_pts = TP_K * risk
        sl_pts = SL_K * risk
        tgt = ep + d * tp_pts
        stp = ep - d * sl_pts
        end = min(n - 1, i + MAXH)
        xt  = None
        for s in range(i, end + 1):
            if d > 0: hs = l_arr[s] <= stp; ht = h_arr[s] >= tgt
            else:     hs = h_arr[s] >= stp; ht = l_arr[s] <= tgt
            if hs and ht: xt = ("STOP",   -sl_pts, ts_arr[s]); break
            if hs:        xt = ("STOP",   -sl_pts, ts_arr[s]); break
            if ht:        xt = ("TARGET",  tp_pts, ts_arr[s]); break
        if xt is None:
            xt = ("TIME", (o_arr[end] - ep) * d, ts_arr[end])

        all_trades.append({
            "date":  v.entry_ts.date(),
            "time":  v.entry_ts.strftime("%H:%M"),
            "dir":   "LONG" if d > 0 else "SHORT",
            "entry": ep,
            "tp":    round(tp_pts, 2),
            "sl":    round(sl_pts, 2),
            "hit":   xt[0],
            "pnl_r": round(xt[1] / risk, 2),
            "atr":   round(risk, 2),
            "xts":   xt[2],
        })

    print(f"    → {len(all_trades)} trades so far", flush=True)

# Occupancy filter
def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["date"], z["time"]))
    ch = []; until = None
    for t in tr:
        entry_ts = t["xts"].__class__.combine(t["date"], __import__("datetime").time()) if False else None
        # simple: sort by (date, time str) and filter by xts
        if until and str(t["date"]) + t["time"] < str(until.date()) + until.strftime("%H:%M"): continue
        ch.append(t); until = t["xts"]
    return ch

ch = occupancy_filter(all_trades)
print(f"\nAfter occupancy: {len(ch)} trades from {len(TARGET_SEGS)} segments\n", flush=True)

# Sample: up to 4 from each year present
random.seed(42)
by_year = defaultdict(list)
for t in ch:
    by_year[t["date"].year].append(t)

sample = []
for yr in sorted(by_year):
    picks = random.sample(by_year[yr], min(4, len(by_year[yr])))
    sample.extend(sorted(picks, key=lambda x: x["date"]))

print("=" * 80)
print(f"{'Date':<12} {'Time':<6} {'Dir':<6} {'Entry':>8} {'TP dist':>8} {'SL dist':>8} {'Hit':<8} {'PnL R':>6} {'ATR pt':>7}")
print("-" * 80)
for t in sample:
    print(f"{str(t['date']):<12} {t['time']:<6} {t['dir']:<6} {t['entry']:>8.2f} "
          f"{t['tp']:>8.2f} {t['sl']:>8.2f} {t['hit']:<8} {t['pnl_r']:>+6.2f}R {t['atr']:>7.2f}")
print("=" * 80)
print("\nDone.", flush=True)

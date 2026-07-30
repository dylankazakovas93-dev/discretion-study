"""
Dump first 20 raw trades from OOS seg00 showing zone coords vs bar prices.
Quick sanity check that context_zone is in the right units.
"""
import sys, io, dataclasses
import numpy as np
import pandas as pd
import zstandard as zs
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

# Just seg00
bars_all = []
seq = 0
for _, r in df.iterrows():
    bars_all.append(Bar(seq=seq, ts_utc=r["ts"], ts_et=r["ts"].tz_convert(ET),
                        open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                        volume=int(r["v"]), contract=r["sym"], segment_id=0))
    seq += 1
    if r["ts"].tz_convert(ET).date() > pd.Timestamp("2013-03-07").date():
        break

local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars_all)]
n = len(local)
print(f"Loaded {n} bars ({local[0].ts_et.date()} → {local[-1].ts_et.date()})")

_ev, variants, _disc = observe(local, target_window=600)
F  = FE.segment_features(local)
ti = {b.ts_et: i for i, b in enumerate(local)}
h_ = np.array([b.high  for b in local])
l_ = np.array([b.low   for b in local])
o_ = np.array([b.open  for b in local])

def wilder_atr24(bars):
    h = np.array([b.high  for b in bars])
    l = np.array([b.low   for b in bars])
    c = np.array([b.close for b in bars])
    n = len(h); tr = np.empty(n); tr[0] = h[0]-l[0]
    for i in range(1, n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    atr = np.empty(n); atr[0] = tr[0]; k = 1/24
    for i in range(1, n):
        atr[i] = atr[i-1]*(1-k) + tr[i]*k
    return atr

atr24 = wilder_atr24(local)

print(f"\n{'ts_et':>22}  {'d':>2}  {'zone_lo':>8}  {'zone_hi':>8}  {'o[i]':>8}  {'h[i]':>8}  {'l[i]':>8}  {'ep_sim':>8}  {'ep_lim':>8}  {'diff':>7}  {'ATR':>6}  {'diff/ATR':>8}")
print("-" * 130)

count = 0
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

    d = v.direction
    zone_lo, zone_hi = v.context_zone
    ep_sim = float(o_[i])
    ep_lim = float(min(o_[i], zone_hi)) if d > 0 else float(max(o_[i], zone_lo))
    diff = abs(ep_lim - ep_sim)

    print(f"{str(v.entry_ts):>22}  {d:>2}  {zone_lo:>8.2f}  {zone_hi:>8.2f}  "
          f"{o_[i]:>8.2f}  {h_[i]:>8.2f}  {l_[i]:>8.2f}  "
          f"{ep_sim:>8.2f}  {ep_lim:>8.2f}  {diff:>7.2f}  {risk:>6.2f}  {diff/risk:>8.2f}R")
    count += 1
    if count >= 20:
        break

print(f"\n{count} trades shown.")

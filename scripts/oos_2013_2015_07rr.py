"""
Final OOS: 2013-2015, RB-K1, 0.7RR gross.

TP = 1.5 × ATR(24) 1m
SL = 1.5 / 0.7 × ATR(24) 1m  ≈ 2.143 × ATR(24) 1m

No hard ATR floor beyond what ATR itself provides.
Results shown gross (no commission deducted).
"""
import sys, io, dataclasses
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
SL_K = 1.5 / 0.7   # ≈ 2.1429
MAXH = 480


def wilder_atr24(h, l, c):
    """Wilder ATR(24) on 1m bars. Returns array same length as inputs."""
    n  = len(h)
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


# ── Load data ─────────────────────────────────────────────────────────────────
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

# ── Observe + simulate ────────────────────────────────────────────────────────
segs = defaultdict(list)
for b in bars_all: segs[b.segment_id].append(b)

all_trades = []

for sid, sbars in sorted(segs.items()):
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n     = len(local)

    _ev, variants, _disc = observe(local, target_window=600)

    F  = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}

    h_arr = np.array([b.high  for b in local])
    l_arr = np.array([b.low   for b in local])
    o_arr = np.array([b.open  for b in local])
    c_arr = np.array([b.close for b in local])
    ts_arr = [b.ts_et for b in local]

    atr24 = wilder_atr24(h_arr, l_arr, c_arr)

    seg_n = 0
    for v in variants:
        if not v.executable: continue
        if v.session != "NY_AM": continue
        if v.context_family != "rb": continue
        if v.context_tf not in (1, 3, 5): continue

        i = ti.get(v.entry_ts, -1)
        if i < 1: continue

        # VWAP z-score filter (same as dev)
        px = float(F["close"][i - 1])
        vw = float(F["vwap_CASH_0930"][i - 1])
        sd = max(float(F["vwsd_CASH_0930"][i - 1]), 1e-9)
        if abs((px - vw) / sd) >= 1.0: continue

        # ATR(24) at bar before entry — this IS the risk unit, no hard floor
        risk = float(atr24[i - 1])
        if risk <= 0: continue

        d   = v.direction
        ep  = float(o_arr[i])
        tgt = ep + d * TP_K * risk
        stp = ep - d * SL_K * risk
        end = min(n - 1, i + MAXH)
        xt  = None
        for s in range(i, end + 1):
            if d > 0: hs = l_arr[s] <= stp; ht = h_arr[s] >= tgt
            else:     hs = h_arr[s] >= stp; ht = l_arr[s] <= tgt
            if hs and ht: xt = ("STOP",   -SL_K * risk, ts_arr[s]); break
            if hs:        xt = ("STOP",   -SL_K * risk, ts_arr[s]); break
            if ht:        xt = ("TARGET",  TP_K * risk, ts_arr[s]); break
        if xt is None:
            xt = ("TIME", (o_arr[end] - ep) * d, ts_arr[end])

        all_trades.append({
            "sd":  v.session_date_et,
            "e":   v.entry_ts,
            "xts": xt[2],
            "pts": xt[1],
            "risk": risk,
            "fk":  (v.lane, v.direction, v.context_family,
                    v.session, v.entry_variant, v.reaction_state),
            "xt":  xt[0],
        })
        seg_n += 1

    print(f"  seg{sid:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}"
          f"  bars={n:>7,}  cands={seg_n:>4}  total={len(all_trades):>5}", flush=True)

print(f"\nRaw trades (pre-occupancy): {len(all_trades):,}", flush=True)

# ── Occupancy filter ──────────────────────────────────────────────────────────
def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], str(z["fk"])))
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

ch = occupancy_filter(all_trades)
print(f"After occupancy:            {len(ch)}", flush=True)

# ── Report ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print(f"RB-K1  OOS 2013-2015  TP={TP_K}R  SL={SL_K:.4f}R  (0.7RR)  GROSS")
print("=" * 65)

yrs  = sorted(set(t["sd"].year for t in ch))
wk   = (ch[-1]["sd"] - ch[0]["sd"]).days / 7 if ch else 1
all_r = []
green = 0

print(f"\n{'Year':>5}  {'n':>5}  {'PF(gross)':>10}  {'net(gross)':>11}  {'win%':>6}")
for y in yrs:
    sub = [t for t in ch if t["sd"].year == y]
    r   = np.array([t["pts"] / t["risk"] for t in sub])   # gross R per trade
    all_r.extend(r)
    gp  = r[r > 0].sum(); lp = -r[r <= 0].sum()
    pf  = gp / lp if lp > 0 else float("inf")
    if pf > 1.0: green += 1
    print(f"  {y}  {len(sub):>5}  {pf:>10.4f}  {r.sum():>+11.1f}  {100*(r>0).mean():>5.1f}%")

all_r = np.array(all_r)
gp = all_r[all_r > 0].sum(); lp = -all_r[all_r <= 0].sum()
pf  = gp / lp if lp > 0 else float("inf")
eq  = np.cumsum(all_r); mdd = (eq - np.maximum.accumulate(eq)).min()
xt_ = defaultdict(int)
for t in ch: xt_[t["xt"]] += 1

print("-" * 65)
print(f"  TOTAL {len(ch):>5}  {pf:>10.4f}  {all_r.sum():>+11.1f}  {100*(all_r>0).mean():>5.1f}%")
print(f"\n  /wk={len(ch)/wk:.1f}  MDD={mdd:.1f}R  green={green}/{len(yrs)}"
      f"  T={xt_['TARGET']}  S={xt_['STOP']}  t={xt_['TIME']}")
print(f"\n  Dev 2018-2025 (same rule, gross): PF≈1.26  net≈+285R  win=66.2%  8/8 green")
print(f"  Breakeven win rate (0.7RR, gross): {SL_K/(TP_K+SL_K)*100:.1f}%")
print("\nDone.", flush=True)

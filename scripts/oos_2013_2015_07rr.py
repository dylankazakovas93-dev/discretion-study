"""
Final OOS validation: 2013-2015 data, RB-K1 setup, 0.7RR exit rule.

Exit rule: TP = 1.5R, SL = 1.5/0.7 ≈ 2.143R
Entry = open of entry bar. Stop-first on same-bar ambiguity.
Max hold = 480 bars (8 hours).

Data: glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst (Databento GLBX.MDP3)
Setup detection: same observe() pipeline as dev/OOS 2026 runs.
"""
import sys, io, dataclasses, pickle
import numpy as np
import pandas as pd
import zstandard as zs
from collections import defaultdict

sys.path.insert(0, "src")
import importlib.util

from discretion.data.bars import Bar
from discretion.data.loader import ET
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome

fe_spec = importlib.util.spec_from_file_location("feature_engine", "scripts/feature_engine.py")
FE = importlib.util.module_from_spec(fe_spec)
fe_spec.loader.exec_module(FE)

SRC = "/root/.claude/uploads/6bbfe5fa-ed66-5075-a056-4af4be88eb35/306aaf2f-glbxmdp32013010120151231.ohlcv1m.csv.zst"
OUT_PKL = "artifacts/rb_refinement/oos_2013_2015_candidates.pkl"

TP_K = 1.5
SL_K = 1.5 / 0.7   # ≈ 2.1429R
MAXH = 480

# ── Load and build bars ────────────────────────────────────────────────────────
print("Loading 2013-2015 data...", flush=True)
rows = []
with open(SRC, "rb") as fh:
    reader = io.TextIOWrapper(zs.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
    import csv as _csv
    for r in _csv.DictReader(reader):
        sym = r["symbol"]
        if not sym.startswith("NQ"): continue
        if len(sym) != 4: continue   # NQH3, NQM3, etc. — outrights only
        rows.append((r["ts_event"], sym,
                     float(r["open"]), float(r["high"]),
                     float(r["low"]),  float(r["close"]),
                     int(float(r["volume"]))))

df = pd.DataFrame(rows, columns=["ts", "sym", "o", "h", "l", "c", "v"])
df["ts"] = pd.to_datetime(df["ts"], utc=True)
df = df.sort_values("ts").reset_index(drop=True)

# Front-month = highest daily volume contract per ET session date
df["d"] = df["ts"].dt.tz_convert(ET).dt.date
vol = df.groupby(["d", "sym"])["v"].sum().reset_index()
front = vol.sort_values("v").groupby("d").tail(1).set_index("d")["sym"].to_dict()
df = df[df.apply(lambda r: front.get(r["d"]) == r["sym"], axis=1)].reset_index(drop=True)
print(f"Front-month rows: {len(df):,}  {df['d'].min()} → {df['d'].max()}", flush=True)

# Build Bar list (same convention as oos_clean_2026.py)
bars_all = []
seq = 0; prev_sym = None; seg_id = 0
for _, r in df.iterrows():
    if prev_sym is not None and r["sym"] != prev_sym:
        seg_id += 1; seq = 0
    bars_all.append(Bar(seq=seq, ts_utc=r["ts"],
                        ts_et=r["ts"].tz_convert(ET),
                        open=r["o"], high=r["h"], low=r["l"],
                        close=r["c"], volume=int(r["v"]),
                        contract=r["sym"], segment_id=seg_id))
    seq += 1; prev_sym = r["sym"]

print(f"Total bars: {len(bars_all):,}, segments: {seg_id+1}", flush=True)
del df  # free memory

# ── Segment → observe → filter → simulate ────────────────────────────────────
segs = defaultdict(list)
for b in bars_all: segs[b.segment_id].append(b)

all_trades = []
total_cands = 0

for sid, sbars in sorted(segs.items()):
    # reset seq within segment (observe() requires 0-based)
    local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(sbars)]
    n = len(local)

    # Observe setups
    _events, variants, _disc = observe(local, target_window=600)

    # Compute features for VWAP z-score
    F = FE.segment_features(local)
    ti = {b.ts_et: i for i, b in enumerate(local)}

    # OHLC arrays for re-simulation
    o_arr = np.array([b.open  for b in local])
    h_arr = np.array([b.high  for b in local])
    l_arr = np.array([b.low   for b in local])
    ts_arr = [b.ts_et for b in local]

    seg_cands = 0
    for v in variants:
        if not v.executable: continue
        if v.session != "NY_AM": continue
        if v.context_family != "rb": continue
        if v.context_tf not in (1, 3, 5): continue

        i = ti.get(v.entry_ts, -1)
        if i < 1: continue

        risk = v.effective_stop_distance
        if risk < 12.0: continue

        # VWAP z-score at bar before entry
        px  = float(F["close"][i - 1])
        vw  = float(F["vwap_CASH_0930"][i - 1])
        sd  = max(float(F["vwsd_CASH_0930"][i - 1]), 1e-9)
        z   = (px - vw) / sd
        if abs(z) >= 1.0: continue

        # Re-simulate with 0.7RR rule
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
            "sd": v.session_date_et, "e": v.entry_ts, "xts": xt[2],
            "pts": xt[1], "risk": risk,
            "fk": (v.lane, v.direction, v.context_family,
                   v.session, v.entry_variant, v.reaction_state),
            "xt": xt[0], "z": z,
        })
        seg_cands += 1

    total_cands += seg_cands
    print(f"  seg{sid:02d}  {local[0].ts_et.date()} → {local[-1].ts_et.date()}  "
          f"bars={n:>6,}  RB-K1 cands={seg_cands:>3}  total={total_cands:>4}", flush=True)

print(f"\nTotal raw RB-K1 trades (pre-occupancy): {len(all_trades):,}", flush=True)
pickle.dump(all_trades, open(OUT_PKL, "wb"))

# ── Occupancy filter ──────────────────────────────────────────────────────────
def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: (z["e"], str(z["fk"])))
    ch = []; until = None
    for t in tr:
        if until and t["e"] < until: continue
        ch.append(t); until = t["xts"]
    return ch

ch = occupancy_filter(all_trades)
print(f"After occupancy filter: {len(ch)} trades", flush=True)

# ── Report ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"RB-K1  OOS 2013-2015  TP={TP_K}R  SL={SL_K:.4f}R  (0.7RR)")
print("=" * 70)

yrs = sorted(set(t["sd"].year for t in ch))
print(f"\n{'Year':>5}  {'n':>5}  {'PF@2':>7}  {'net@2':>8}  {'win%':>6}")
all_r2 = []
for y in yrs:
    sub = [t for t in ch if t["sd"].year == y]
    r2  = np.array([(t["pts"] - 2.0) / t["risk"] for t in sub])
    all_r2.extend(r2)
    gp  = r2[r2 > 0].sum(); lp = -r2[r2 <= 0].sum()
    pf2 = gp / lp if lp > 0 else float("inf")
    print(f"  {y}  {len(sub):>5}  {pf2:>7.4f}  {r2.sum():>+8.1f}  {100*(r2>0).mean():>5.1f}%")

all_r2 = np.array(all_r2)
gp = all_r2[all_r2 > 0].sum(); lp = -all_r2[all_r2 <= 0].sum()
pf2 = gp / lp if lp > 0 else float("inf")
eq  = np.cumsum(all_r2)
mdd = (eq - np.maximum.accumulate(eq)).min()
wk  = (ch[-1]["sd"] - ch[0]["sd"]).days / 7 if ch else 1

from collections import Counter
xt_counts = Counter(t["xt"] for t in ch)
green = sum(1 for y in yrs if sum((t["pts"]-2)/t["risk"] for t in ch if t["sd"].year==y and (t["pts"]-2)/t["risk"]>0) >
                               abs(sum((t["pts"]-2)/t["risk"] for t in ch if t["sd"].year==y and (t["pts"]-2)/t["risk"]<=0)))

print("-" * 50)
print(f"  TOTAL {len(ch):>5}  {pf2:>7.4f}  {all_r2.sum():>+8.1f}  {100*(all_r2>0).mean():>5.1f}%")
print(f"\n  /wk = {len(ch)/wk:.1f}  MDD@2 = {mdd:.1f}R  green = {green}/{len(yrs)}")
print(f"  T={xt_counts['TARGET']}  S={xt_counts['STOP']}  t={xt_counts['TIME']}")
print(f"\n  Dev 2018-2025 (same rule):  PF@2=1.2289  net@2=+270.6  win=66.2%  8/8 green")

# Pre-registered pass/fail at 2pt commission
be_win = (SL_K + 2.0/20) / (TP_K - 2.0/20 + SL_K + 2.0/20) * 100
print(f"\n  Breakeven win rate @2pt: {be_win:.1f}%  actual: {100*(all_r2>0).mean():.1f}%")
verdict = "PASS" if pf2 > 1.10 and all_r2.sum() > 0 else ("MARGINAL" if pf2 >= 1.00 else "FAIL")
print(f"  Verdict (PF@2>1.10 and net>0): {verdict}")

print("\nDone.", flush=True)

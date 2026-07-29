"""
VWAP z-score threshold sweep: test |z| < 1, 1.5, 2, 3 on dev 2018-2025 RB-K1.
Also reports BE30 true win rate (TARGET vs actual SL vs BE stop).
"""
import sys, pickle
import numpy as np
from collections import defaultdict

sys.path.insert(0, "src")

SEG  = "artifacts/multiyear_validation_v2/segcache"
TP_K = 1.5
SL_K = 1.5 / 0.7
MAXH = 480

# ── Load ──────────────────────────────────────────────────────────────────────
seg_data = {}
for si in range(33):
    try:
        bars = pickle.load(open(f"{SEG}/seg{si:03d}.pkl", "rb"))
        seg_data[si] = (
            np.array([b.open  for b in bars]),
            np.array([b.high  for b in bars]),
            np.array([b.low   for b in bars]),
            [b.ts_et for b in bars],
            {b.ts_et: i for i, b in enumerate(bars)},
        )
    except FileNotFoundError:
        pass

ALL_C = pickle.load(open("artifacts/broad_discovery/candidates_with_features.pkl", "rb"))
ALL_C = [c for c in ALL_C
         if c["session"] == "NY_AM" and c["fkey"][2] == "rb"
         and c["context_tf"] in (1, 3, 5)]

# Pre-compute z-scores
px_ = np.array([c["_px"]            for c in ALL_C])
vw_ = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
z_  = (px_ - vw_) / sd_

# Build indexed cand list with z attached
all_cands = []
for c, z in zip(ALL_C, z_):
    si = int(c["gvid"].split("::")[0][3:6])
    if si not in seg_data: continue
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    all_cands.append({"sd": c["sd"], "entry_ts": c["entry_ts"], "si": si, "i": i,
                      "ep": float(o_[i]), "d": c["direction"], "risk": c["risk"], "z": z})

print(f"Total indexed candidates (no z-filter): {len(all_cands):,}\n", flush=True)


def simulate_fixed(cands):
    trades = []
    for rec in cands:
        si = rec["si"]; i = rec["i"]; ep = rec["ep"]
        d = rec["d"]; risk = rec["risk"]
        o_, h_, l_, ts_, _ = seg_data[si]
        n = len(o_)
        tp_pts = TP_K * risk; sl_pts = SL_K * risk
        tgt = ep + d * tp_pts; stp = ep - d * sl_pts
        end = min(n - 1, i + MAXH)
        xt = None
        for bar in range(i, end + 1):
            hs = (l_[bar] <= stp) if d > 0 else (h_[bar] >= stp)
            ht = (h_[bar] >= tgt) if d > 0 else (l_[bar] <= tgt)
            if hs and ht: xt = ("STOP",   -sl_pts, ts_[bar]); break
            if hs:        xt = ("STOP",   -sl_pts, ts_[bar]); break
            if ht:        xt = ("TARGET",  tp_pts, ts_[bar]); break
        if xt is None:
            xt = ("TIME", (o_[end] - ep) * d, ts_[end])
        trades.append({"sd": rec["sd"], "entry_ts": rec["entry_ts"],
                       "xts": xt[2], "pts": xt[1], "risk": risk, "xt": xt[0]})
    return trades


def simulate_be30(cands):
    """BE after 30 bars if in profit. Tracks whether stop was BE or actual SL."""
    trades = []
    for rec in cands:
        si = rec["si"]; i = rec["i"]; ep = rec["ep"]
        d = rec["d"]; risk = rec["risk"]
        o_, h_, l_, ts_, _ = seg_data[si]
        n = len(o_)
        tp_pts = TP_K * risk; sl_pts = SL_K * risk
        tgt = ep + d * tp_pts; stp = ep - d * sl_pts
        be_triggered = False; end = min(n - 1, i + MAXH); xt = None
        for bar in range(i, end + 1):
            offset = bar - i
            if not be_triggered and offset >= 30:
                cur = h_[bar] if d > 0 else l_[bar]
                if (cur > ep) if d > 0 else (cur < ep):
                    stp = ep; be_triggered = True
            hs = (l_[bar] <= stp) if d > 0 else (h_[bar] >= stp)
            ht = (h_[bar] >= tgt) if d > 0 else (l_[bar] <= tgt)
            if hs and ht: xt = ("STOP", -abs(ep - stp), ts_[bar], be_triggered); break
            if hs:        xt = ("STOP", -abs(ep - stp), ts_[bar], be_triggered); break
            if ht:        xt = ("TARGET", tp_pts, ts_[bar], False); break
        if xt is None:
            xt = ("TIME", (o_[end] - ep) * d, ts_[end], False)
        trades.append({"sd": rec["sd"], "entry_ts": rec["entry_ts"],
                       "xts": xt[2], "pts": xt[1], "risk": risk,
                       "xt": xt[0], "was_be": xt[3]})
    return trades


def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: z["entry_ts"])
    ch = []; until = None
    for t in tr:
        if until and t["entry_ts"] < until: continue
        ch.append(t); until = t["xts"]
    return ch


def summarize(ch, label):
    if not ch: return
    wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    r = np.array([t["pts"] / t["risk"] for t in ch])
    gp = r[r > 0].sum(); lp = -r[r <= 0].sum()
    pf = gp / lp if lp > 0 else float("inf")
    win = 100 * (r > 0).mean()
    eq = np.cumsum(r); mdd = (eq - np.maximum.accumulate(eq)).min()
    yrs = sorted(set(t["sd"].year for t in ch))
    green = sum(1 for y in yrs
                for sub in [[t for t in ch if t["sd"].year == y]]
                if (lambda ry: ry[ry>0].sum() / (-ry[ry<=0].sum()) if (-ry[ry<=0].sum()) > 0 else float("inf"))(
                    np.array([t["pts"]/t["risk"] for t in sub])) > 1.0)
    print(f"  {label:<35}  n={len(ch):>5}  /wk={len(ch)/wk:>4.1f}  PF={pf:.4f}  "
          f"net={r.sum():>+7.1f}R  win={win:.1f}%  MDD={mdd:.1f}R  green={green}/{len(yrs)}")


# ── VWAP σ sweep ──────────────────────────────────────────────────────────────
print("=" * 90)
print("VWAP Z-SCORE THRESHOLD SWEEP  (fixed SL=2.14R, 0.7RR)")
print("=" * 90)
print(f"  {'Filter':<35}  {'n':>5}  {'/wk':>4}  {'PF':>7}  {'net':>8}  {'win%':>5}  {'MDD':>7}  {'green':>6}")
print("-" * 90)

for thr, label in [(0.5, "|z| < 0.5"), (1.0, "|z| < 1.0  (current)"),
                   (1.5, "|z| < 1.5"), (2.0, "|z| < 2.0"),
                   (3.0, "|z| < 3.0"), (99, "no filter")]:
    filt = [c for c in all_cands if abs(c["z"]) < thr]
    t = simulate_fixed(filt)
    ch = occupancy_filter(t)
    summarize(ch, label)

# ── BE30 true win rate breakdown ───────────────────────────────────────────────
print("\n" + "=" * 70)
print("BE30 TRUE WIN RATE  (BE after 30 bars if in profit, |z| < 1.0)")
print("=" * 70)
z1_cands = [c for c in all_cands if abs(c["z"]) < 1.0]
be30_trades = simulate_be30(z1_cands)
ch_be = occupancy_filter(be30_trades)

n_target  = sum(1 for t in ch_be if t["xt"] == "TARGET")
n_be_stop = sum(1 for t in ch_be if t["xt"] == "STOP" and t["was_be"])
n_sl_stop = sum(1 for t in ch_be if t["xt"] == "STOP" and not t["was_be"])
n_time    = sum(1 for t in ch_be if t["xt"] == "TIME")
n_total   = len(ch_be)
n_decisive = n_target + n_sl_stop   # excludes BE and TIME exits

print(f"\n  Total trades:            {n_total}")
print(f"  TARGET (win):            {n_target}  ({100*n_target/n_total:.1f}%)")
print(f"  STOP at breakeven:       {n_be_stop}  ({100*n_be_stop/n_total:.1f}%)")
print(f"  STOP at actual SL:       {n_sl_stop}  ({100*n_sl_stop/n_total:.1f}%)")
print(f"  TIME exit:               {n_time}  ({100*n_time/n_total:.1f}%)")
print(f"\n  True win rate (TARGET vs actual SL only, excl BE/TIME):")
print(f"    {n_target} / {n_decisive} = {100*n_target/n_decisive:.1f}%")
print(f"\n  Year-by-year breakdown:")
print(f"  {'Year':>5}  {'n':>5}  {'TARGET':>7}  {'BE_stop':>8}  {'SL_stop':>8}  {'true_wr':>8}")
for y in sorted(set(t["sd"].year for t in ch_be)):
    sub = [t for t in ch_be if t["sd"].year == y]
    nt = sum(1 for t in sub if t["xt"] == "TARGET")
    nb = sum(1 for t in sub if t["xt"] == "STOP" and t["was_be"])
    ns = sum(1 for t in sub if t["xt"] == "STOP" and not t["was_be"])
    nd = nt + ns
    print(f"    {y}  {len(sub):>5}  {nt:>7}  {nb:>8}  {ns:>8}  {100*nt/nd:.1f}%" if nd else f"    {y}  n/a")

print("\nDone.", flush=True)

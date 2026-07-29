"""
Breakeven stop sweep on dev 2018-2025 RB-K1 0.7RR candidates.
Tests: fixed SL vs BE-after-30min vs BE-after-50%-TP.
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
px_ = np.array([c["_px"]            for c in ALL_C])
vw_ = np.array([c["vwap_CASH_0930"] for c in ALL_C])
sd_ = np.maximum(np.array([c["vwsd_CASH_0930"] for c in ALL_C]), 1e-9)
ALL_C = [c for c, z in zip(ALL_C, (px_ - vw_) / sd_) if abs(z) < 1.0]

cands = []
for c in ALL_C:
    si = int(c["gvid"].split("::")[0][3:6])
    if si not in seg_data: continue
    o_, h_, l_, ts_, ti_ = seg_data[si]
    i = ti_.get(c["entry_ts"], -1)
    if i < 0: continue
    cands.append({"sd": c["sd"], "entry_ts": c["entry_ts"], "si": si, "i": i,
                  "ep": float(o_[i]), "d": c["direction"], "risk": c["risk"]})
print(f"Candidates: {len(cands):,}", flush=True)


def simulate(cands, mode):
    """
    mode: "fixed" | "be30" (BE after 30 bars if in profit) | "be50pct" (BE after 50% TP hit)
    """
    trades = []
    for rec in cands:
        si = rec["si"]; i = rec["i"]; ep = rec["ep"]
        d = rec["d"]; risk = rec["risk"]
        o_, h_, l_, ts_, _ = seg_data[si]
        n = len(o_)
        tp_pts = TP_K * risk
        sl_pts = SL_K * risk
        tgt = ep + d * tp_pts
        stp = ep - d * sl_pts
        be_triggered = False
        end = min(n - 1, i + MAXH)
        xt = None

        for bar in range(i, end + 1):
            offset = bar - i

            # Check BE trigger
            if not be_triggered:
                if mode == "be30" and offset >= 30:
                    # in profit = price has moved toward TP
                    cur = h_[bar] if d > 0 else l_[bar]  # best price seen this bar
                    in_profit = (cur > ep) if d > 0 else (cur < ep)
                    if in_profit:
                        stp = ep  # move to breakeven
                        be_triggered = True
                elif mode == "be50pct":
                    # has price touched 50% of TP distance?
                    half_tgt = ep + d * (tp_pts * 0.5)
                    touched = (h_[bar] >= half_tgt) if d > 0 else (l_[bar] <= half_tgt)
                    if touched:
                        stp = ep
                        be_triggered = True

            if d > 0:
                hs = l_[bar] <= stp
                ht = h_[bar] >= tgt
            else:
                hs = h_[bar] >= stp
                ht = l_[bar] <= tgt

            if hs and ht:
                xt = ("STOP", -abs(ep - stp), ts_[bar]); break
            if hs:
                xt = ("STOP", -abs(ep - stp), ts_[bar]); break
            if ht:
                xt = ("TARGET", tp_pts, ts_[bar]); break

        if xt is None:
            xt = ("TIME", (o_[end] - ep) * d, ts_[end])

        trades.append({"sd": rec["sd"], "entry_ts": rec["entry_ts"],
                       "xts": xt[2], "pts": xt[1], "risk": risk, "xt": xt[0]})
    return trades


def occupancy_filter(trades):
    tr = sorted(trades, key=lambda z: z["entry_ts"])
    ch = []; until = None
    for t in tr:
        if until and t["entry_ts"] < until: continue
        ch.append(t); until = t["xts"]
    return ch


def report(trades, label):
    ch = occupancy_filter(trades)
    if not ch: return
    wk = (ch[-1]["sd"] - ch[0]["sd"]).days / 7
    r = np.array([t["pts"] / t["risk"] for t in ch])
    gp = r[r > 0].sum(); lp = -r[r <= 0].sum()
    pf = gp / lp if lp > 0 else float("inf")
    eq = np.cumsum(r); mdd = (eq - np.maximum.accumulate(eq)).min()
    win = 100 * (r > 0).mean()
    xt_ = defaultdict(int)
    for t in ch: xt_[t["xt"]] += 1

    yrs = sorted(set(t["sd"].year for t in ch))
    green = 0
    yr_lines = []
    for y in yrs:
        sub = [t for t in ch if t["sd"].year == y]
        ry = np.array([t["pts"] / t["risk"] for t in sub])
        gpy = ry[ry > 0].sum(); lpy = -ry[ry <= 0].sum()
        pfy = gpy / lpy if lpy > 0 else float("inf")
        if pfy > 1.0: green += 1
        yr_lines.append(f"    {y}  n={len(sub):>4}  PF={pfy:.4f}  net={ry.sum():>+6.1f}R  win={100*(ry>0).mean():.1f}%")

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  n={len(ch)}  /wk={len(ch)/wk:.1f}  PF={pf:.4f}  net={r.sum():>+.1f}R  "
          f"win={win:.1f}%  MDD={mdd:.1f}R  green={green}/{len(yrs)}")
    print(f"  exits: TARGET={xt_['TARGET']}  STOP={xt_['STOP']}  TIME={xt_['TIME']}")
    for line in yr_lines:
        print(line)


print("Running simulations...", flush=True)
for mode, label in [
    ("fixed",   "FIXED SL  (0.7RR, SL=2.14R, baseline)"),
    ("be30",    "BE after 30 bars IF in profit at that moment"),
    ("be50pct", "BE after 50% of TP distance touched"),
]:
    t = simulate(cands, mode)
    report(t, label)

print("\nDone.", flush=True)

"""Earnings drop post-market. Globex reopens 18:00 ET. What does the path actually do?

No cash-open anchoring. Entry is the Globex reaction itself, at a choice of delays after
the reopen. For each entry the FULL post-entry path is walked to build MAE/MFE, which is
what a stop and a target have to be sized against.

MAE = worst drawdown against the position before the horizon.
MFE = best excursion in favour before the horizon.
A stop at the 80th percentile of MAE survives 80% of trades; a target above the median
MFE is reached less than half the time. That is the whole trade-construction problem.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os

DEV = {2020, 2022, 2024, 2026}
ROOT = os.environ["NQ_DATA_ROOT"]
DELAYS = [0, 5, 15, 30, 60]        # minutes after the Globex reopen

fr = []
for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")):
    d = zstandard.ZstdDecompressor()
    with open(p, "rb") as f:
        fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                  usecols=["ts_event","open","high","low","close","volume","symbol"]))
px = pd.concat(fr, ignore_index=True); px = px[~px.symbol.str.contains("-")]
px["ts"] = pd.to_datetime(px.ts_event, format="ISO8601", utc=True)
px["et"] = px.ts.dt.tz_convert("America/New_York")
px["sess"] = (px.et + pd.Timedelta(hours=6)).dt.date
px["tod"] = px.et.dt.hour*60 + px.et.dt.minute
px = px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
front = (px.groupby(["sess","symbol"], observed=True).volume.sum().groupby("sess").idxmax().map(lambda t: t[1]))
rth = px[(px.tod>=570)&(px.tod<960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars = {s: g.set_index("ts").sort_index() for s,g in px.groupby("symbol", observed=True)}

ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
ev = ev[(ev.family=="eps") & ev.surprise_z.notna() & ev.deadband_pass]
ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]
ev["et"] = ev.release_ts_utc.dt.tz_convert("America/New_York")
ev = ev[ev.et.dt.hour >= 16]                      # post-market releases only
opens = si.open_ts.values

rows = []
for _, e in ev.iterrows():
    t0 = e.release_ts_utc
    i = np.searchsorted(opens, np.datetime64(t0))
    if i >= len(si): continue
    s = si.iloc[i]; b = bars.get(s.front)
    if b is None: continue
    at = lambda ts: (b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0 = at(t0 - pd.Timedelta(minutes=1))
    # Globex reopen 18:00 ET on the release day; if the filing lands later, use the filing
    gx = e.et.normalize() + pd.Timedelta(hours=18)
    gx = max(gx.tz_convert("UTC"), t0)
    if not np.isfinite(p0): continue
    for dly in DELAYS:
        ets = gx + pd.Timedelta(minutes=dly)
        pe = at(ets)
        if not np.isfinite(pe): continue
        d = np.sign(pe/p0 - 1)
        if d == 0: continue
        path = b.loc[(b.index > ets) & (b.index <= s.close_ts)]
        if len(path) < 300: continue
        mfe = ((path.high.max()/pe - 1)*100) if d>0 else ((pe/path.low.min() - 1)*100)
        mae = ((pe/path.low.min() - 1)*100) if d>0 else ((path.high.max()/pe - 1)*100)
        rows.append(dict(sess=s.name, delay=dly, dirn=d, absz=abs(e.surprise_z),
            agree=float(d==np.sign(e.z_signed)),
            gap=(pe/p0-1)*100*d,                      # how far it had already moved at entry
            mfe=mfe, mae=max(mae, 0.0),
            r_close=(at(s.close_ts)/pe - 1)*100*d,
            r_open=(at(s.open_ts)/pe - 1)*100*d))
D = pd.DataFrame(rows)
D = D.groupby(["sess","delay"], as_index=False).first()
D.to_csv("data/macro/globex_path.csv", index=False)

print(f"post-market earnings sessions: {D.sess.nunique()}\n")
print("=== PATH BY ENTRY DELAY AFTER GLOBEX REOPEN (hold to next cash close) ===")
print(f"{'delay':>6}{'n':>5}{'gap@entry':>11}{'MAE p50':>9}{'p80':>7}{'p90':>7}{'MFE p50':>9}{'p80':>7}"
      f"{'MFE/MAE':>9}{'ret':>8}{'win':>6}")
for dly in DELAYS:
    k = D[D.delay==dly]
    if len(k) < 10: continue
    print(f"{dly:>6}{len(k):>5}{k.gap.median():>10.2f}%{k.mae.quantile(.5):>8.2f}%{k.mae.quantile(.8):>6.2f}%"
          f"{k.mae.quantile(.9):>6.2f}%{k.mfe.quantile(.5):>8.2f}%{k.mfe.quantile(.8):>6.2f}%"
          f"{k.mfe.median()/k.mae.median():>8.2f}{k.r_close.mean():>+7.3f}%{(k.r_close>0).mean():>5.0%}")

print("\n=== WHAT STOP SURVIVES? (entry at reopen, no target, exit at cash close) ===")
k = D[D.delay==0]
print(f"{'stop':>7}{'stopped out':>13}{'mean ret':>10}{'win':>6}")
for sp in [0.15,0.25,0.4,0.6,1.0,1.5]:
    hit = k.mae >= sp
    r = np.where(hit, -sp, k.r_close)
    print(f"{sp:>6.2f}%{hit.mean():>12.0%}{r.mean():>+9.3f}%{(r>0).mean():>6.0%}")

print("\n=== IS A TARGET EVER WORTH IT? (stop fixed at 0.6%, vary target) ===")
print(f"{'target':>8}{'mean ret':>10}{'win':>6}")
r0 = np.where(k.mae>=0.6, -0.6, k.r_close)
print(f"{'none':>8}{r0.mean():>+9.3f}%{(r0>0).mean():>6.0%}")
for tp in [0.3,0.5,0.8,1.2,2.0]:
    r = np.where(k.mae>=0.6, -0.6, np.where(k.mfe>=tp, tp, k.r_close))
    print(f"{tp:>7.2f}%{r.mean():>+9.3f}%{(r>0).mean():>6.0%}")

print("\n=== DOES WAITING HELP? MAE at each delay, same sessions only ===")
piv = D.pivot_table(index="sess", columns="delay", values="mae")
piv = piv.dropna()
print(f"  common sessions n={len(piv)}")
print("  median MAE:", "  ".join(f"{c}m={piv[c].median():.2f}%" for c in piv.columns))
print("  p80    MAE:", "  ".join(f"{c}m={piv[c].quantile(.8):.2f}%" for c in piv.columns))
pv2 = D.pivot_table(index="sess", columns="delay", values="r_close").dropna()
print("  mean ret  :", "  ".join(f"{c}m={pv2[c].mean():+.3f}%" for c in pv2.columns))

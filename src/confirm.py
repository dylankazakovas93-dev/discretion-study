"""Confirmation triggers and non-symmetric stops on the Globex earnings reaction.

Replaces the fixed time delay with Dylan's alternatives:
  - displacement confirmation: enter on first touch of +-X% from the pre-release price
  - structural stop: the opposite extreme of the window between release and entry
    (his "stop at the low"), rather than a fixed distance
  - trailing stop
and buckets by how big the EPS beat actually was, which until now was only deadbanded
at 1% of consensus with no size requirement.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os

DEV = {2020, 2022, 2024, 2026}
ROOT = os.environ["NQ_DATA_ROOT"]

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
front = (px.groupby(["sess","symbol"],observed=True).volume.sum().groupby("sess").idxmax().map(lambda t:t[1]))
rth = px[(px.tod>=570)&(px.tod<960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars = {s: g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}

ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
ev = ev[(ev.family=="eps") & ev.surprise_z.notna() & ev.deadband_pass]
ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]
ev["etloc"] = ev.release_ts_utc.dt.tz_convert("America/New_York")
ev = ev[ev.etloc.dt.hour >= 16]
opens = si.open_ts.values

def walk(path, entry, d, stop_px, trail=None):
    """Bar-by-bar exit. Stop wins any bar spanning both sides. Trail in % if given."""
    best = entry
    for _, b in path.iterrows():
        hit = (b.low <= stop_px) if d > 0 else (b.high >= stop_px)
        if hit: return (stop_px/entry - 1)*100*d, True
        if trail:
            best = max(best, b.high) if d > 0 else min(best, b.low)
            stop_px = (best*(1-trail/100)) if d > 0 else (best*(1+trail/100))
    return (path.close.iloc[-1]/entry - 1)*100*d, False

rows = []
for _, e in ev.iterrows():
    t0 = e.release_ts_utc
    i = np.searchsorted(opens, np.datetime64(t0))
    if i >= len(si): continue
    s = si.iloc[i]; b = bars.get(s.front)
    if b is None: continue
    at = lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0 = at(t0 - pd.Timedelta(minutes=1))
    gx = max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"), t0)
    if not np.isfinite(p0): continue
    scan = b.loc[(b.index >= gx) & (b.index < s.open_ts)]     # reopen -> cash open
    if len(scan) < 60: continue
    row = dict(sess=s.name, eps_pct=abs(e.surprise_abs), absz=abs(e.surprise_z))

    for tag, thr in [("t15", None), ("c02", 0.2), ("c04", 0.4), ("c06", 0.6)]:
        if thr is None:
            ets = gx + pd.Timedelta(minutes=15)
            sub = scan.loc[scan.index <= ets]
            pe = at(ets)
            if not np.isfinite(pe): continue
            d = np.sign(pe/p0 - 1)
        else:
            up = scan.high >= p0*(1+thr/100); dn = scan.low <= p0*(1-thr/100)
            iu = up.idxmax() if up.any() else None; idn = dn.idxmax() if dn.any() else None
            if iu is None and idn is None: row[f"{tag}_fire"] = 0; continue
            ets = min(x for x in [iu, idn] if x is not None)
            d = 1.0 if (iu is not None and ets == iu) else -1.0
            pe = p0*(1 + d*thr/100)
            sub = scan.loc[scan.index <= ets]
        if d == 0 or not np.isfinite(pe): continue
        path = b.loc[(b.index > ets) & (b.index <= s.close_ts)]
        if len(path) < 300: continue
        row[f"{tag}_fire"] = 1
        row[f"{tag}_plain"] = (at(s.close_ts)/pe - 1)*100*d
        # structural stop = opposite extreme of the pre-entry window
        sp = sub.low.min() if d > 0 else sub.high.max()
        row[f"{tag}_structdist"] = abs(pe/sp - 1)*100
        row[f"{tag}_struct"] = walk(path, pe, d, sp)[0]
        for tr in (0.5, 1.0):
            row[f"{tag}_trail{tr}"] = walk(path, pe, d,
                pe*(1-tr/100) if d>0 else pe*(1+tr/100), trail=tr)[0]
    rows.append(row)
D = pd.DataFrame(rows).groupby("sess", as_index=False).first()
D.to_csv("data/macro/confirm.csv", index=False)

def stat(x):
    x = x.dropna()
    if len(x) < 8: return "        n<8"
    return f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}"

print(f"sessions {len(D)}\n")
print("=== ENTRY TRIGGER x EXIT RULE (hold to next cash close unless stopped) ===")
print(f"{'trigger':<26}{'fires':>7}  {'no stop':<28}{'structural stop':<28}{'trail 0.5%':<26}{'trail 1.0%'}")
for tag, lbl in [("t15","wait 15 min (time)"),("c02","confirm +-0.2% move"),
                 ("c04","confirm +-0.4% move"),("c06","confirm +-0.6% move")]:
    f = D.get(f"{tag}_fire")
    fires = f"{f.fillna(0).mean():.0%}" if f is not None else "n/a"
    print(f"{lbl:<26}{fires:>7}  {stat(D[f'{tag}_plain']):<28}{stat(D[f'{tag}_struct']):<28}"
          f"{stat(D[f'{tag}_trail0.5']):<26}{stat(D[f'{tag}_trail1.0'])}")

print("\n=== how far away is the structural stop? (median distance from entry) ===")
for tag in ["t15","c02","c04","c06"]:
    c = D.get(f"{tag}_structdist")
    if c is not None and c.notna().sum() > 8:
        print(f"  {tag}: median {c.median():.2f}%   p80 {c.quantile(.8):.2f}%")

print("\n=== DOES THE SIZE OF THE BEAT MATTER? (wait-15 entry, no stop) ===")
k = D.dropna(subset=["t15_plain"])
for lo, hi, lbl in [(0,2,"<2%"),(2,5,"2-5%"),(5,10,"5-10%"),(10,1e9,">10%")]:
    sub = k[(k.eps_pct >= lo) & (k.eps_pct < hi)]
    if len(sub) >= 5:
        print(f"  EPS beat/miss {lbl:>7}: {stat(sub.t15_plain)}")

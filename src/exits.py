"""Dylan's three exit tests, plus the |z| threshold question on 'against the print'.

Entry is always the cash open, in the direction the market reacted to the release.
Exits tested:
  A  16:00 cash close      (the original)
  B  11:00 ET              (before the afternoon / 0DTE session)
  C  +-0.2% bracket        (TP and SL both 0.2% from entry)
  D  +-0.4% bracket

Bracket fills are conservative: if a bar's range spans both the target and the stop,
the STOP is awarded. No intrabar sequence is available at 1-minute resolution, so the
unfavourable outcome is assumed rather than the favourable one.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
from scipy import stats

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
front = (px.groupby(["sess","symbol"], observed=True).volume.sum().groupby("sess").idxmax().map(lambda t: t[1]))
rth = px[(px.tod>=570)&(px.tod<960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars = {s: g.set_index("ts").sort_index() for s,g in px.groupby("symbol", observed=True)}

ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
ev = ev[ev.surprise_z.notna() & ev.deadband_pass]
ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]
opens = si.open_ts.values

def bracket(path, entry, d, pct):
    """Conservative bracket fill: stop wins any bar that spans both levels."""
    tp = entry*(1 + d*pct/100); sl = entry*(1 - d*pct/100)
    for _, b in path.iterrows():
        hit_sl = (b.low <= sl) if d > 0 else (b.high >= sl)
        hit_tp = (b.high >= tp) if d > 0 else (b.low <= tp)
        if hit_sl: return -pct
        if hit_tp: return +pct
    return (path.close.iloc[-1]/entry - 1)*100*d      # never triggered -> exit at close

rows = []
for _, e in ev.iterrows():
    t0 = e.release_ts_utc; i = np.searchsorted(opens, np.datetime64(t0))
    if i >= len(si): continue
    s = si.iloc[i]; b = bars.get(s.front)
    if b is None: continue
    at = lambda ts: (b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0 = at(t0-pd.Timedelta(minutes=1)); popen = at(s.open_ts)
    if not all(np.isfinite([p0, popen])): continue
    d = np.sign(popen/p0-1) or 1.0
    path = b.loc[(b.index>=s.open_ts)&(b.index<=s.close_ts)]
    if len(path) < 300: continue
    p11 = path[path.index <= s.open_ts+pd.Timedelta(minutes=90)]
    rows.append(dict(sess=s.name, family=e.family, z=e.z_signed, absz=abs(e.surprise_z),
        agree=float(d==np.sign(e.z_signed)),
        A_close=(path.close.iloc[-1]/popen-1)*100*d,
        B_1100=(p11.close.iloc[-1]/popen-1)*100*d,
        C_02=bracket(path, popen, d, 0.2),
        D_04=bracket(path, popen, d, 0.4)))
D = pd.DataFrame(rows)
D = D.groupby("sess").agg({**{c:"first" for c in D.columns if c!="sess"}, "z":"mean"}).reset_index()
D.to_csv("data/macro/exits.csv", index=False)

EX = ["A_close","B_1100","C_02","D_04"]
def line(k, tag):
    if len(k) < 5: return
    o = f"  {tag:<26} n={len(k):3}"
    for x in EX:
        t = k[x].mean()/(k[x].std()/np.sqrt(len(k)))
        o += f" | {x}: {k[x].mean():+.3f}% w{(k[x]>0).mean():.0%} t{t:+.1f}"
    print(o)

print(f"sessions {len(D)}  {D.family.value_counts().to_dict()}\n")
print("=== ALL EVENT SESSIONS ===");  line(D, "all")
for f in ["inflation","eps","labour"]: line(D[D.family==f], f)
print("\n=== AGAINST THE PRINT (agree=0) ===")
line(D[D.agree==0], "against, any |z|")
for thr in [0.5, 1.0, 1.5]:
    line(D[(D.agree==0)&(D.absz>=thr)], f"against, |z|>={thr}")
print("\n=== WITH THE PRINT (agree=1), for contrast ===")
line(D[D.agree==1], "with, any |z|")
for thr in [1.0, 1.5]:
    line(D[(D.agree==1)&(D.absz>=thr)], f"with, |z|>={thr}")

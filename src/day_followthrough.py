"""Separate hypothesis: does a day's direction carry into the next Globex session?

Nothing to do with earnings. Every full RTH session in the dev years, regardless of what
happened that day. If the day closes up, does the next Globex open -> +1h/+2h/+3h and the
run into the next cash open lean the same way?

Also split by how big the day's move was, since a strong close and a drifting close are
plausibly different animals.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2018,2020,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]
fr=[]
for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")):
    d=zstandard.ZstdDecompressor()
    with open(p,"rb") as f:
        fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                  usecols=["ts_event","open","high","low","close","volume","symbol"]))
px=pd.concat(fr,ignore_index=True); px=px[~px.symbol.str.contains("-")]
px["ts"]=pd.to_datetime(px.ts_event,format="ISO8601",utc=True)
px["et"]=px.ts.dt.tz_convert("America/New_York")
px["sess"]=(px.et+pd.Timedelta(hours=6)).dt.date
px["tod"]=px.et.dt.hour*60+px.et.dt.minute
px=px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
front=(px.groupby(["sess","symbol"],observed=True).volume.sum().groupby("sess").idxmax().map(lambda t:t[1]))
px=px.merge(front.rename("f"),left_on="sess",right_index=True)
px=px[px.symbol==px.f].sort_values("ts")
rth=px[(px.tod>=570)&(px.tod<960)]
D=rth.groupby("sess").agg(o=("open","first"),c=("close","last"),n=("close","size"),
                          close_ts=("ts","last"))
D=D[D.n>=300]
D["day_ret"]=(D.c/D.o-1)*100
D=D.sort_index()
sessions=list(D.index)
bars={s:g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}
rows=[]
for i in range(len(sessions)-1):
    s0,s1=sessions[i],sessions[i+1]
    if (pd.Timestamp(s1)-pd.Timestamp(s0)).days>4: continue
    sym=front.get(s1)
    b=bars.get(sym)
    if b is None: continue
    # next session's Globex opens 18:00 ET on the calendar day before s1's RTH
    gx=(pd.Timestamp(s1).tz_localize("America/New_York")-pd.Timedelta(hours=6)).tz_convert("UTC")
    at=lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p_gx=at(gx+pd.Timedelta(minutes=1))
    if not np.isfinite(p_gx): continue
    nxt_open_ts=rth[rth.sess==s1].ts.min()
    r={"sess":s0,"day_ret":D.day_ret.loc[s0]}
    for h in (1,2,3):
        p=at(gx+pd.Timedelta(hours=h))
        if np.isfinite(p): r[f"gx{h}h"]=(p/p_gx-1)*100
    p=at(nxt_open_ts)
    if np.isfinite(p): r["to_open"]=(p/p_gx-1)*100
    rows.append(r)
F=pd.DataFrame(rows).dropna(subset=["gx1h"])
F["d"]=np.sign(F.day_ret)
for c in ("gx1h","gx2h","gx3h","to_open"):
    if c in F: F[c+"_al"]=F[c]*F.d           # aligned with the prior day's direction
F.to_csv("data/macro/day_followthrough.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    return (f"n={len(x):4} {x.mean():+.4f}% cont {(x>0).mean():.0%} "
            f"t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=20 else f"n={len(x)} --"
print(f"=== ALL SESSIONS, dev years (n={len(F)}) ===")
print("   'aligned' = next-Globex move signed by the PRIOR day's RTH direction\n")
for c,l in (("gx1h_al","Globex open -> +1h"),("gx2h_al","-> +2h"),
            ("gx3h_al","-> +3h"),("to_open_al","-> next cash open")):
    print(f"  {l:<24}{st(F.get(c))}")
print(f"\n=== BY SIZE OF THE PRIOR DAY'S MOVE ===")
b=pd.cut(F.day_ret.abs(),[0,0.5,1.0,2.0,99],labels=["<0.5%","0.5-1%","1-2%",">2%"])
for lab in ["<0.5%","0.5-1%","1-2%",">2%"]:
    k=F[b==lab]
    print(f"  |day| {lab:<7} {st(k.get('gx1h_al')):<34}{st(k.get('to_open_al'))}")
print(f"\n=== BY DIRECTION (is it symmetric?) ===")
for s,l in ((1,"up days"),(-1,"down days")):
    k=F[F.d==s]
    print(f"  {l:<10} +1h {st(k.get('gx1h_al')):<34}to open {st(k.get('to_open_al'))}")

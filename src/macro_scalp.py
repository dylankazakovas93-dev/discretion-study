"""New hypothesis: enter AFTER the first 1-minute candle on a big macro surprise, ride the
rest of the reaction, get out before it turns to noise.

Different event family from the earnings work, so this is a fresh hypothesis rather than a
re-tune. Development years only (2018/2020/2022/2024/2026); 2021/2023/2025 stay sealed.

Entry: the close of the first completed 1-minute bar at or after the release, in that bar's
direction. Exits swept from +5 minutes out to the cash open. No stop -- MAE is reported so
the stop question can be answered separately rather than assumed.
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
rth=px[(px.tod>=570)&(px.tod<960)]
si=rth.groupby("sess").agg(open_ts=("ts","first"),close_ts=("ts","last"),nb=("ts","size"))
si=si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars={s:g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}

S=pd.read_csv("data/macro/surprises.csv",parse_dates=["release_ts_utc"])
S=S[S.family.isin(["inflation","labour"])&S.surprise_z.notna()&S.deadband_pass]
S=S[pd.DatetimeIndex(S.release_ts_utc).year.isin(DEV)]
# one event per release minute: keep the largest |z| that minute
S["az"]=S.surprise_z.abs()
S=S.sort_values("az").groupby("release_ts_utc").last().reset_index()
opens=si.open_ts.values
HOR=[5,15,30,60]
rows=[]
for _,e in S.iterrows():
    t0=e.release_ts_utc
    i=np.searchsorted(opens,np.datetime64(t0))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    seg=b.loc[(b.index>=t0)&(b.index<=s.open_ts)]
    if len(seg)<45: continue
    first=seg.iloc[0]                       # the 1-minute bar containing the release
    pe=float(first.close)
    d=np.sign(first.close-first.open)
    if d==0: continue
    rec=dict(sess=s.name,yr=t0.year,series=e.series,az=e.az,
             agree=float(d==np.sign(e.z_signed)),
             impulse=abs(first.close/first.open-1)*100)
    post=seg.iloc[1:]
    for h in HOR:
        p=post.loc[post.index<=t0+pd.Timedelta(minutes=h+1)]
        if len(p)<h*0.5: continue
        rec[f"r{h}"]=(p.close.iloc[-1]/pe-1)*100*d
        rec[f"mae{h}"]=max(((pe/p.low.min()-1)*100) if d>0 else ((p.high.max()/pe-1)*100),0.0)
    rec["r_open"]=(post.close.iloc[-1]/pe-1)*100*d
    rec["mae_open"]=max(((pe/post.low.min()-1)*100) if d>0 else ((post.high.max()/pe-1)*100),0.0)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/macro_scalp.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    return (f"n={len(x):3} {x.mean():+.4f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=10 else f"n={len(x):3} --"
print(f"events {len(D)}  |  median 1-min impulse {D.impulse.median():.3f}% "
      f"({D.impulse.median()/100*20000:.0f} NQ pts at 20k)\n")
print("=== ENTER ON THE 1-MIN CLOSE, EXIT AT HORIZON (no stop) ===")
print(f"{'filter':<16}"+"".join(f"{'+'+str(h)+'m':<26}" for h in HOR)+"to cash open")
for lo,lab in ((0,"all surprises"),(1.0,"|z| >= 1.0"),(1.5,"|z| >= 1.5"),(2.0,"|z| >= 2.0")):
    k=D[D.az>=lo]
    print(f"{lab:<16}"+"".join(f"{st(k.get(f'r{h}')):<26}" for h in HOR)+st(k.get("r_open")))
print("\n=== MAE while holding (all surprises / |z|>=1.5) ===")
for lo,lab in ((0,"all"),(1.5,"|z|>=1.5")):
    k=D[D.az>=lo]
    print(f"  {lab:<10}"+"  ".join(f"+{h}m p50 {k[f'mae{h}'].median():.3f}% p90 {k[f'mae{h}'].quantile(.9):.3f}%"
          for h in HOR if f"mae{h}" in k))
print("\n=== does the 1-min candle agree with the surprise sign? ===")
for a,lab in ((1.0,"candle agrees with print"),(0.0,"candle disagrees")):
    k=D[(D.agree==a)&(D.az>=1.0)]
    print(f"  {lab:<26}"+"  ".join(f"+{h}m {st(k.get(f'r{h}'))}" for h in (5,30)))
print("\n=== by series (|z|>=1.0, exit +30m) ===")
for s in sorted(D.series.unique()):
    k=D[(D.series==s)&(D.az>=1.0)]
    if len(k)>=10: print(f"  {s:<18}{st(k.get('r30'))}")

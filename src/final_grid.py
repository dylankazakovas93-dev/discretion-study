"""Final configuration grid before freeze.

Entry: the first candle after the Globex reopen defines a boundary; enter on the first
1-minute CLOSE beyond it. Two boundary definitions (first 1-min candle, first 5-min candle).

Stops:  none | fixed 1.0% | fixed 1.6% | ATR trail at 1x, 2x, 3x (ATR-14 on 5-min bars)
Exits:  15:00 ET | 16:00 ET

Fills are conservative throughout: a bar whose range spans the stop is stopped, and the
trail only ratchets on completed bars.
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
# 15:00 ET cut
c15=rth[rth.tod<=900].groupby("sess").ts.last().rename("ts15")
si=si.join(c15)
bars={s:g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}

R=pd.read_csv("data/macro/raw/nasdaq_top10_by_year.csv")
RANK={(r.year,r.symbol):r["rank"] for _,r in R.iterrows()}
E=pd.read_csv("data/macro/earnings.csv")
E=E[E.surprise_abs.notna()&E.consensus.notna()].copy()
E["ts"]=pd.to_datetime(E.release_ts_utc,utc=True,format="ISO8601")
E["etloc"]=E.ts.dt.tz_convert("America/New_York")
E=E[(E.etloc.dt.hour>=16)&(E.etloc.dt.year.isin(DEV))]
E["sym"]=E.series.str.replace("_EPS","",regex=False)
E["rk"]=[RANK.get((t.year,s),99) for t,s in zip(E.etloc,E.sym)]
E=E.sort_values("rk").groupby(E.etloc.dt.date).first().reset_index(drop=True)
E=E[E.rk<=10]
opens=si.open_ts.values

def run(path, pe, d, mode, atr):
    """mode: ('none',),('fix',pct),('trail',k). Returns pct return, signed."""
    stop=None
    if mode[0]=="fix": stop=pe*(1-d*mode[1]/100)
    best=pe
    for _,b in path.iterrows():
        if mode[0]=="trail":
            s=best-d*mode[1]*atr
            if (b.low<=s) if d>0 else (b.high>=s): return (s/pe-1)*100*d
            best=max(best,b.high) if d>0 else min(best,b.low)
        elif stop is not None:
            if (b.low<=stop) if d>0 else (b.high>=stop): return (stop/pe-1)*100*d
    return (path.close.iloc[-1]/pe-1)*100*d

MODES=[("none",),("fix",1.0),("fix",1.6),("trail",1),("trail",2),("trail",3)]
rows=[]
for _,e in E.iterrows():
    i=np.searchsorted(opens,np.datetime64(e.ts))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None or pd.isna(s.ts15): continue
    gx=max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"),e.ts)
    w=b.loc[(b.index>=gx)&(b.index<s.open_ts)]
    if len(w)<60: continue
    m5=w.resample("5min").agg(h=("high","max"),l=("low","min"),c=("close","last")).dropna()
    if len(m5)<20: continue
    tr=pd.concat([m5.h-m5.l,(m5.h-m5.c.shift()).abs(),(m5.l-m5.c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean()
    rec={"sess":s.name,"sym":e.sym,"rk":e.rk,"yr":e.etloc.year}
    for tag,src in (("m1",w.iloc[[0]]),("m5",m5.iloc[[0]])):
        hi=float(src.h.iloc[0] if "h" in src else src.high.iloc[0])
        lo=float(src.l.iloc[0] if "l" in src else src.low.iloc[0])
        after=w.iloc[1:] if tag=="m1" else w.loc[w.index>=m5.index[1]]
        br=after[(after.close>hi)|(after.close<lo)]
        if br.empty: continue
        t0=br.index[0]; pe=float(br.close.iloc[0]); d=1.0 if pe>hi else -1.0
        a=atr.asof(t0)
        if not np.isfinite(a): a=(m5.h-m5.l).mean()
        for exitname,endts in (("15",s.ts15),("16",s.close_ts)):
            path=b.loc[(b.index>t0)&(b.index<=endts)]
            if len(path)<120: continue
            for m in MODES:
                mn=m[0] if len(m)==1 else f"{m[0]}{m[1]}"
                rec[f"{tag}_{exitname}_{mn}"]=run(path,pe,d,m,a)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/final_grid.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    return (f"{x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=8 else "--"
for lbl,sub in [("TOP 10",D),("TOP 3",D[D.rk<=3])]:
    print(f"\n================ {lbl}  (n={len(sub)}) ================")
    for tag,tl in (("m1","boundary = first 1-min candle"),("m5","boundary = first 5-min candle")):
        print(f"\n  {tl}")
        print(f"    {'stop':<12}{'exit 15:00':<26}{'exit 16:00'}")
        for m in MODES:
            mn=m[0] if len(m)==1 else f"{m[0]}{m[1]}"
            lab={"none":"no stop","fix1.0":"fixed 1.0%","fix1.6":"fixed 1.6%",
                 "trail1":"trail 1 ATR","trail2":"trail 2 ATR","trail3":"trail 3 ATR"}[mn]
            print(f"    {lab:<12}{st(sub.get(f'{tag}_15_{mn}')):<26}{st(sub.get(f'{tag}_16_{mn}'))}")

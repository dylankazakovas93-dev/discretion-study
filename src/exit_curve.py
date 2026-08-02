"""When should the trade end?

The MAE-timing split suggested holding into the NY session gives money back, but that
split is partly circular. The non-circular test is to exit at a series of clock times and
read the return curve directly.

Exits tested (ET): 04:00, 08:30, 09:30 (cash open), 11:00, 16:00 (current spec).
Also: a breakeven rule armed at the cash open, and targets at 1.6% / 2.0%.
Stops: none / 0.2% / 0.4% / 1.6%.
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
CUTS=[(4,0,"04:00"),(8,30,"08:30"),(9,30,"09:30"),(11,0,"11:00"),(16,0,"16:00")]

def walk(path,pe,d,stop_pct,tp_pct=None,be_from=None):
    stop=pe*(1-d*stop_pct/100) if stop_pct else None
    tp=pe*(1+d*tp_pct/100) if tp_pct else None
    armed=False
    for ts,b in path.iterrows():
        if be_from is not None and not armed and ts>=be_from:
            stop=pe; armed=True                       # breakeven from the cash open
        if stop is not None and ((b.low<=stop) if d>0 else (b.high>=stop)):
            return (stop/pe-1)*100*d
        if tp is not None and ((b.high>=tp) if d>0 else (b.low<=tp)):
            return (tp/pe-1)*100*d
    return (path.close.iloc[-1]/pe-1)*100*d

rows=[]
for _,e in E.iterrows():
    i=np.searchsorted(opens,np.datetime64(e.ts))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    at=lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0=at(e.ts-pd.Timedelta(minutes=1))
    gx=max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"),e.ts)
    w=b.loc[(b.index>=gx)&(b.index<s.open_ts)]
    if not np.isfinite(p0) or len(w)<60: continue
    m5=w.resample("5min").agg(c=("close","last")).dropna()
    up=(m5.c>=p0*1.001).rolling(2).sum()>=2; dn=(m5.c<=p0*0.999).rolling(2).sum()>=2
    iu=up.idxmax() if up.any() else None; idn=dn.idxmax() if dn.any() else None
    if iu is None and idn is None: continue
    t0=min(x for x in [iu,idn] if x is not None)
    d=1.0 if (iu is not None and t0==iu) else -1.0
    pe=float(m5.c.loc[t0])
    day=s.open_ts.tz_convert("America/New_York").normalize()
    rec={"sess":s.name,"rk":e.rk}
    for hh,mm,lab in CUTS:
        end=(day+pd.Timedelta(hours=hh,minutes=mm)).tz_convert("UTC")
        path=b.loc[(b.index>t0)&(b.index<=end)]
        if len(path)<30: continue
        for sp,sn in ((None,"nostop"),(0.2,"s02"),(0.4,"s04"),(1.6,"s16")):
            rec[f"{lab}_{sn}"]=walk(path,pe,d,sp)
    end16=(day+pd.Timedelta(hours=16)).tz_convert("UTC")
    path=b.loc[(b.index>t0)&(b.index<=end16)]
    if len(path)>=30:
        rec["16:00_be"]=walk(path,pe,d,1.6,be_from=s.open_ts)
        rec["16:00_tp16"]=walk(path,pe,d,1.6,tp_pct=1.6)
        rec["16:00_tp20"]=walk(path,pe,d,1.6,tp_pct=2.0)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/exit_curve.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    if len(x)<8: return "--"
    dn=x[x<0]; pf=x[x>0].sum()/abs(dn.sum()) if len(dn) else np.nan
    return f"{x.mean():+.3f}% w{(x>0).mean():.0%} PF{pf:.2f} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}"
for lbl,sub in [("TOP 10",D),("TOP 3",D[D.rk<=3])]:
    print(f"\n================ {lbl}  n={len(sub)} ================")
    print(f"  {'exit':<8}{'no stop':<28}{'stop 0.2%':<28}{'stop 0.4%':<28}{'stop 1.6%'}")
    for _,_,lab in CUTS:
        print(f"  {lab:<8}{st(sub.get(f'{lab}_nostop')):<28}{st(sub.get(f'{lab}_s02')):<28}"
              f"{st(sub.get(f'{lab}_s04')):<28}{st(sub.get(f'{lab}_s16'))}")
print(f"\n=== extras (top 10, exit 16:00, 1.6% stop) ===")
print(f"  breakeven armed at cash open : {st(D.get('16:00_be'))}")
print(f"  target 1.6%                  : {st(D.get('16:00_tp16'))}")
print(f"  target 2.0%                  : {st(D.get('16:00_tp20'))}")

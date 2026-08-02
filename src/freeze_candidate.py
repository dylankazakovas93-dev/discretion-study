"""The actual freeze candidate: best entry x the stop/exit that just proved useful.

Entry (from ANA-0017): 0.1% displacement from the pre-release price, confirmed by 2
consecutive 5-minute closes beyond it, between the Globex reopen and the cash open.
Stops (from ANA-0018): none / fixed 1.0% / fixed 1.6%.  Exits: 15:00 or 16:00 ET.
This combination has never been run -- the entry was only ever tested unstopped.
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
si=si.join(rth[rth.tod<=900].groupby("sess").ts.last().rename("ts15"))
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

def run(path,pe,d,pct):
    if pct is None: return (path.close.iloc[-1]/pe-1)*100*d
    stop=pe*(1-d*pct/100)
    for _,b in path.iterrows():
        if (b.low<=stop) if d>0 else (b.high>=stop): return -pct
    return (path.close.iloc[-1]/pe-1)*100*d

rows=[]
for _,e in E.iterrows():
    i=np.searchsorted(opens,np.datetime64(e.ts))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None or pd.isna(s.ts15): continue
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
    rec={"sess":s.name,"sym":e.sym,"rk":e.rk,"yr":e.etloc.year}
    for en,end in (("15",s.ts15),("16",s.close_ts)):
        path=b.loc[(b.index>t0)&(b.index<=end)]
        if len(path)<120: continue
        for pn,pv in (("none",None),("1.0",1.0),("1.6",1.6)):
            rec[f"{en}_{pn}"]=run(path,pe,d,pv)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/freeze_candidate.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    if len(x)<8: return "--"
    dn=x[x<0]
    return (f"{x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f} "
            f"PF{x[x>0].sum()/abs(dn.sum()):.2f}" if len(dn) else "--")
for lbl,sub in [("TOP 10",D),("TOP 3",D[D.rk<=3])]:
    print(f"\n=== {lbl}  n={len(sub)} ===")
    print(f"  {'stop':<10}{'exit 15:00':<34}{'exit 16:00'}")
    for pn,lab in (("none","no stop"),("1.0","fixed 1.0%"),("1.6","fixed 1.6%")):
        print(f"  {lab:<10}{st(sub.get(f'15_{pn}')):<34}{st(sub.get(f'16_{pn}'))}")
print("\n=== per-year, TOP 10, fixed 1.0% stop, exit 15:00 ===")
k=D.dropna(subset=["15_1.0"])
print(k.groupby("yr")["15_1.0"].agg(n="size",mean="mean",
      win=lambda x:(x>0).mean(),total="sum").round(3).to_string())

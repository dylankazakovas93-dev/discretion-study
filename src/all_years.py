"""Year-by-year for the LOCKED config across every year with rank data.

This is reporting, not searching: the config is fixed and every year is run through the
same code. Development years and holdout years are labelled so nothing is blurred.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
YEARS={2020,2021,2022,2023,2024,2025,2026}; DEV={2020,2022,2024,2026}
ROOT=os.environ["NQ_DATA_ROOT"]
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
px=px[pd.DatetimeIndex(px.sess).year.isin(YEARS)]
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
E=E[(E.etloc.dt.hour>=16)&(E.etloc.dt.year.isin(YEARS))]
E["sym"]=E.series.str.replace("_EPS","",regex=False)
E["rk"]=[RANK.get((t.year,s),99) for t,s in zip(E.etloc,E.sym)]
E=E.sort_values("rk").groupby(E.etloc.dt.date).first().reset_index(drop=True)
E=E[E.rk<=10]
opens=si.open_ts.values
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
    path=b.loc[(b.index>t0)&(b.index<=s.close_ts)]
    if len(path)<120: continue
    stop=pe*(1-d*1.6/100); r=None
    for _,x in path.iterrows():
        if (x.low<=stop) if d>0 else (x.high>=stop): r=-1.6; break
    if r is None: r=(path.close.iloc[-1]/pe-1)*100*d
    rows.append(dict(yr=e.etloc.year,r=r,entry=pe))
D=pd.DataFrame(rows)
D.to_csv("data/macro/all_years.csv",index=False)
print(f"{'year':>6}{'set':>7}{'n':>5}{'mean':>9}{'win':>7}{'PF':>7}{'$ 1 MNQ':>10}")
for y in sorted(D.yr.unique()):
    k=D[D.yr==y]; x=k.r; neg=abs(x[x<0].sum())
    print(f"{y:>6}{'DEV' if y in DEV else 'HOLD':>7}{len(k):>5}{x.mean():>+8.3f}%{(x>0).mean():>7.0%}"
          f"{(x[x>0].sum()/neg if neg else np.nan):>7.2f}{(x/100*k.entry*2).sum():>10,.0f}")
for lab,sel in (("DEV total",D.yr.isin(DEV)),("HOLD total",~D.yr.isin(DEV)),("ALL",D.yr.notna())):
    k=D[sel]; x=k.r; neg=abs(x[x<0].sum())
    print(f"{lab:>13}{len(k):>5}{x.mean():>+8.3f}%{(x>0).mean():>7.0%}"
          f"{(x[x>0].sum()/neg if neg else np.nan):>7.2f}{(x/100*k.entry*2).sum():>10,.0f}")
x=D.r
print(f"\n  pooled all 7 years: n={len(x)}  mean {x.mean():+.3f}%  win {(x>0).mean():.1%}  "
      f"t {x.mean()/(x.std()/np.sqrt(len(x))):+.2f}")
print(f"  positive years: {(D.groupby('yr').r.mean()>0).sum()} of {D.yr.nunique()}")

"""CONFIRMATORY RUN — executes SPEC_LOCKED.md verbatim on the reserved years.

Holdout: 2021, 2023, 2025. These years have never been read by any prior analysis.
Criteria fixed BEFORE this ran:  PASS = mean > 0 AND t > 1.5 AND win >= 55%
                                 FAIL = mean <= 0 OR win < 50%
Anything else is inconclusive. No parameter may change after this executes.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
HOLD={2021,2023,2025}; ROOT=os.environ["NQ_DATA_ROOT"]
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
px=px[pd.DatetimeIndex(px.sess).year.isin(HOLD)]
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
E=E[(E.etloc.dt.hour>=16)&(E.etloc.dt.year.isin(HOLD))]
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
    rows.append(dict(sess=s.name,sym=e.sym,rk=e.rk,yr=e.etloc.year,entry=pe,r=r))
D=pd.DataFrame(rows).sort_values("sess").reset_index(drop=True)
D.to_csv("data/macro/HOLDOUT_RESULT.csv",index=False)

x=D.r; n=len(x); t=x.mean()/(x.std()/np.sqrt(n)); win=(x>0).mean()
pf=x[x>0].sum()/abs(x[x<0].sum()); usd=(x/100*D.entry*2)
eq=usd.cumsum(); dd=(eq-eq.cummax()).min()
print("="*58); print("  CONFIRMATORY HOLDOUT — 2021 / 2023 / 2025"); print("="*58)
print(f"\n  trades            {n}")
print(f"  mean per trade    {x.mean():+.3f}%")
print(f"  win rate          {win:.1%}")
print(f"  profit factor     {pf:.2f}")
print(f"  t-statistic       {t:+.2f}")
print(f"  total (1 MNQ)     ${usd.sum():,.0f}   max DD ${dd:,.0f}")
print(f"\n  development was:  +0.348%  59%  PF 1.77  t +2.2  (n=93)")
print("\n  by year:")
for y in sorted(D.yr.unique()):
    k=D[D.yr==y]
    print(f"    {y}  n={len(k):3}  mean {k.r.mean():+.3f}%  win {(k.r>0).mean():.0%}  "
          f"${(k.r/100*k.entry*2).sum():>7,.0f}")
print("\n  top 3 rank subset:")
k=D[D.rk<=3]
if len(k)>=8:
    print(f"    n={len(k)}  mean {k.r.mean():+.3f}%  win {(k.r>0).mean():.0%}  "
          f"t {k.r.mean()/(k.r.std()/np.sqrt(len(k))):+.2f}")
print("\n"+"-"*58)
crit=[("mean > 0", x.mean()>0), ("t > 1.5", t>1.5), ("win >= 55%", win>=0.55)]
for c,ok in crit: print(f"   {'PASS' if ok else 'FAIL'}   {c}")
verdict = "PASS" if all(o for _,o in crit) else ("FAIL" if (x.mean()<=0 or win<0.50) else "INCONCLUSIVE")
print("-"*58); print(f"\n   VERDICT: {verdict}\n")

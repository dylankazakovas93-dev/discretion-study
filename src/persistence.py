"""Persistence-confirmed entries, and the drawdown a winning trade puts you through.

Entry grid (Dylan's): displacement threshold in {0.1, 0.2, 0.5}% from the pre-release
price, requiring price to CLOSE beyond it for {1, 2, 3} consecutive 5-minute bars before
entering. 9 combinations. Entry is the close of the last confirming bar.

Then the number that actually decides the stop: MAE conditional on the trade ENDING
PROFITABLE. A stop placed beyond the 90th percentile of winners' MAE keeps 90% of the
winners; anything tighter is cutting trades that would have paid.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2018,2020,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]
THR=[0.1,0.2,0.5]; HOLD=[1,2,3]

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

rows=[]
for _,e in E.iterrows():
    i=np.searchsorted(opens,np.datetime64(e.ts))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    at=lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0=at(e.ts-pd.Timedelta(minutes=1))
    gx=max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"),e.ts)
    scan=b.loc[(b.index>=gx)&(b.index<s.open_ts)]
    if not np.isfinite(p0) or len(scan)<60: continue
    m5=scan.resample("5min").agg(o=("open","first"),h=("high","max"),l=("low","min"),c=("close","last")).dropna()
    rec={"sess":s.name,"sym":e.sym,"rk":e.rk,"yr":e.etloc.year}
    for thr in THR:
        up=m5.c>=p0*(1+thr/100); dn=m5.c<=p0*(1-thr/100)
        for hold in HOLD:
            ru=up.rolling(hold).sum()>=hold; rd=dn.rolling(hold).sum()>=hold
            iu=ru.idxmax() if ru.any() else None; idn=rd.idxmax() if rd.any() else None
            if iu is None and idn is None: continue
            t0=min(x for x in [iu,idn] if x is not None)
            d=1.0 if (iu is not None and t0==iu) else -1.0
            pe=m5.c.loc[t0]
            path=b.loc[(b.index>t0)&(b.index<=s.close_ts)]
            if len(path)<200: continue
            r=(path.close.iloc[-1]/pe-1)*100*d
            mae=((pe/path.low.min()-1)*100) if d>0 else ((path.high.max()/pe-1)*100)
            k=f"t{thr}h{hold}"
            rec[k+"_r"]=r; rec[k+"_mae"]=max(mae,0.0)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/persistence.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    return (f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=8 else f"n={len(x):3} --"
for lbl,sub in [("TOP 10",D),("TOP 3",D[D.rk<=3])]:
    print(f"\n=== {lbl} — hold to cash close, NO STOP  (sessions {len(sub)}) ===")
    print(f"{'':<8}"+"".join(f"hold {h} bar{'s' if h>1 else ' '}          " for h in HOLD))
    for thr in THR:
        print(f"{thr:>5}%  "+"  ".join(f"{st(sub.get(f't{thr}h{h}_r')):<26}" for h in HOLD))

print("\n\n=== THE STOP QUESTION: drawdown suffered by trades that ENDED PROFITABLE ===")
print("   (a stop beyond these levels keeps that share of your winners)\n")
print(f"{'entry':<12}{'n win':>6}{'p50':>8}{'p75':>8}{'p90':>8}{'p95':>8}{'max':>8}   {'losers p50':>11}")
for thr in THR:
    for h in HOLD:
        r=D.get(f"t{thr}h{h}_r"); m=D.get(f"t{thr}h{h}_mae")
        if r is None: continue
        k=pd.DataFrame({"r":r,"m":m}).dropna()
        w=k[k.r>0]; l=k[k.r<=0]
        if len(w)<8: continue
        print(f"{thr}% x{h}bar {len(w):>6}{w.m.quantile(.5):>7.2f}%{w.m.quantile(.75):>7.2f}%"
              f"{w.m.quantile(.9):>7.2f}%{w.m.quantile(.95):>7.2f}%{w.m.max():>7.2f}%   {l.m.quantile(.5):>10.2f}%")

"""Does point-in-time Nasdaq index rank predict the trade? (Dylan's top-10 table)

Absolute market cap is entangled with the calendar -- almost nothing was worth $1T before
2022, so ">$1T" and "recent" are nearly the same variable in this sample. Index RANK is
not: being Nasdaq #1 in 2018 and Nasdaq #1 in 2026 are the same position in the index
whatever the dollar figure. That separates the size hypothesis from a regime effect.

Rank comes from Dylan's supplied year-by-year top-10 table. It covers 2020-2026; 2018
events are kept for the base-rule sample but carry no rank and are excluded from rank tests.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV = {2018, 2020, 2022, 2024, 2026}          # 2018 now in play for earnings
ROOT = os.environ["NQ_DATA_ROOT"]
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
E["rank"]=[RANK.get((t.year,s), np.nan) for t,s in zip(E.etloc,E.sym)]
opens=si.open_ts.values

def walk(path,entry,d,sp):
    for _,b in path.iterrows():
        if (b.low<=sp) if d>0 else (b.high>=sp): return (sp/entry-1)*100*d
    return (path.close.iloc[-1]/entry-1)*100*d

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
    up=scan.high>=p0*1.002; dn=scan.low<=p0*0.998
    iu=up.idxmax() if up.any() else None; idn=dn.idxmax() if dn.any() else None
    if iu is None and idn is None: continue
    ets=min(x for x in [iu,idn] if x is not None)
    d=1.0 if (iu is not None and ets==iu) else -1.0
    pe=p0*(1+d*0.002); sub=scan.loc[scan.index<=ets]
    path=b.loc[(b.index>ets)&(b.index<=s.close_ts)]
    if len(path)<300: continue
    sp=sub.low.min() if d>0 else sub.high.max()
    rows.append(dict(sess=s.name,sym=e.sym,yr=e.etloc.year,rank=e["rank"],
        plain=(at(s.close_ts)/pe-1)*100*d, stop=walk(path,pe,d,sp)))
D=pd.DataFrame(rows)
# one row per session: the highest-ranked (lowest number) company reporting that evening
D["rk"]=D["rank"].fillna(99)
S=D.sort_values("rk").groupby("sess").first().reset_index()
S.to_csv("data/macro/rank_events.csv",index=False)

def stat(x):
    x=pd.Series(x).dropna()
    return (f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=8 else f"n={len(x):3} too few"
print(f"sessions {len(S)}  | with a ranked company {int((S.rk<99).sum())}\n")
print("=== BY BEST INDEX RANK REPORTING THAT EVENING ===")
print(f"{'band':<22}{'no stop':<30}{'structural stop'}")
for lo,hi,l in [(1,3,"top 3"),(4,6,"rank 4-6"),(7,10,"rank 7-10"),(99,99,"outside top 10")]:
    k=S[(S.rk>=lo)&(S.rk<=hi)]
    print(f"{l:<22}{stat(k.plain):<30}{stat(k.stop)}")
print("\n=== CUMULATIVE ===")
for thr in [1,3,5,10]:
    k=S[S.rk<=thr]
    print(f"  top {thr:<3} {stat(k.plain):<30}{stat(k.stop)}")
print("\n=== THE REGIME TEST: top-10 events, split by era ===")
for lo,hi,l in [(2018,2020,"2018+2020"),(2022,2022,"2022"),(2024,2026,"2024+2026")]:
    k=S[(S.rk<=10)&(S.yr>=lo)&(S.yr<=hi)]
    print(f"  {l:<12}{stat(k.plain):<30}{stat(k.stop)}")
print("\n  events/yr in top-10 bucket:", S[S.rk<=10].groupby("yr").size().to_dict())

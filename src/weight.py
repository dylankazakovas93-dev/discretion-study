"""Does the reporting company's index relevance matter? (Dylan's hypothesis)

Adding PEP/COST/SBUX/GILD/AMGN/BKNG/ISRG/LRCX diluted the edge. Those are staples,
pharma, travel and medtech -- Nasdaq-100 members, but not names that drag the index.
The tech/semi cohort is where index weight and sector beta both concentrate.

Cohort membership is assigned by SECTOR, decided before looking at per-cohort results,
not by ranking outcomes. Still: this split was prompted by seeing the dilution, so it is
a hypothesis to test on held-out data, not a result.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV = {2020, 2022, 2024, 2026}; ROOT = os.environ["NQ_DATA_ROOT"]
CORE = {"AAPL","AMZN","GOOGL","META","NVDA","TSLA","MSFT","AVGO","AMD","INTC","MU",
        "QCOM","TXN","AMAT","LRCX","ADBE","NFLX","CSCO","MRVL","KLAC","NXPI","ADI",
        "ON","CDNS","SNPS","PANW","CRWD","INTU","SMCI"}            # tech / semis
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

E=pd.read_csv("data/macro/earnings.csv")
E=E[E.surprise_abs.notna()&E.consensus.notna()].copy()
E["ts"]=pd.to_datetime(E.release_ts_utc,utc=True,format="ISO8601")
E["etloc"]=E.ts.dt.tz_convert("America/New_York")
E=E[(E.etloc.dt.hour>=16)&(E.etloc.dt.year.isin(DEV))]
E["sym"]=E.series.str.replace("_EPS","",regex=False)
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
    rows.append(dict(sess=s.name,sym=e.sym,core=e.sym in CORE,hour=e.etloc.hour,
        plain=(at(s.close_ts)/pe-1)*100*d, stop=walk(path,pe,d,sp)))
D=pd.DataFrame(rows)
# a session is "core" if any core-cohort company reported that evening
S=D.groupby("sess").agg(core=("core","max"),hour=("hour","min"),
                        nrep=("sym","size"),plain=("plain","first"),stop=("stop","first")).reset_index()
def stat(x):
    x=x.dropna()
    return f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}" if len(x)>=8 else f"n={len(x)} too few"
print(f"sessions {len(S)}   (confirm +-0.2% entry)\n")
print("=== TECH/SEMI COHORT vs THE REST ===")
print(f"  core cohort reporting : no stop {stat(S[S.core].plain):<30} struct stop {stat(S[S.core].stop)}")
print(f"  non-core only         : no stop {stat(S[~S.core].plain):<30} struct stop {stat(S[~S.core].stop)}")
print("\n=== RELEASE HOUR (ET) ===")
for h in sorted(S.hour.unique()):
    k=S[S.hour==h]
    if len(k)>=8: print(f"  {h:02d}:00  {stat(k.plain):<30} struct {stat(k.stop)}")
print("\n=== HOW MANY COMPANIES REPORTED THAT EVENING ===")
for lo,hi,l in [(1,1,"1"),(2,2,"2"),(3,99,"3+")]:
    k=S[(S.nrep>=lo)&(S.nrep<=hi)]
    if len(k)>=8: print(f"  {l:>3} reporters  {stat(k.plain):<30} struct {stat(k.stop)}")
D.to_csv("data/macro/weight.csv",index=False)

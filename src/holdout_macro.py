"""CONFIRMATORY RUN — executes SPEC_LOCKED_MACRO.md verbatim on 2023 and 2025.
Criteria fixed before this ran: PASS = mean>0 AND t>1.5 AND win>=55%.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
HOLD={2023,2025}; ROOT=os.environ["NQ_DATA_ROOT"]
DAY={"US_CPI_MOM":"CPI","US_CORE_CPI_MOM":"CPI","US_PPI_MOM":"PPI","US_CORE_PPI_MOM":"PPI",
     "US_NFP":"NFP","US_UNEMP_RATE":"NFP","US_CORE_PCE_MOM":"PCE"}
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
si=rth.groupby("sess").agg(open_ts=("ts","first"),nb=("ts","size"))
si=si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars={s:g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}
S=pd.read_csv("data/macro/surprises.csv",parse_dates=["release_ts_utc"])
S=S[S.family.isin(["inflation","labour"])&S.surprise_z.notna()&S.deadband_pass]
S=S[pd.DatetimeIndex(S.release_ts_utc).year.isin(HOLD)]
S["az"]=S.surprise_z.abs()
S=S.sort_values("az").groupby("release_ts_utc").last().reset_index()
S["day"]=S.series.map(DAY)
S=S[S.day.isin(["CPI","NFP","PPI"])&(S.az>=0.75)]
opens=si.open_ts.values
def atr30(b,t0,n=14):
    h=b.loc[b.index<t0].tail(n*30+60)
    if len(h)<n*30: return np.nan
    m=h.resample("30min").agg(h=("high","max"),l=("low","min"),c=("close","last")).dropna()
    if len(m)<n+1: return np.nan
    tr=pd.concat([m.h-m.l,(m.h-m.c.shift()).abs(),(m.l-m.c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]
rows=[]
for _,e in S.iterrows():
    t0=e.release_ts_utc; i=np.searchsorted(opens,np.datetime64(t0))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    seg=b.loc[(b.index>=t0)&(b.index<=s.open_ts)]
    if len(seg)<45: continue
    first=seg.iloc[0]; pe=float(first.close); d=np.sign(first.close-first.open)
    if d==0: continue
    a=atr30(b,t0)
    if not np.isfinite(a): continue
    p30=seg.iloc[1:].loc[seg.index[1:]<=t0+pd.Timedelta(minutes=31)]
    if len(p30)<15: continue
    stop=pe-d*1.5*a; r=None
    for _,x in p30.iterrows():
        if (x.low<=stop) if d>0 else (x.high>=stop): r=(stop/pe-1)*100*d; break
    if r is None: r=(p30.close.iloc[-1]/pe-1)*100*d
    rows.append(dict(sess=s.name,yr=t0.year,day=e.day,az=e.az,entry=pe,atr=a,r=r))
D=pd.DataFrame(rows); D.to_csv("data/macro/HOLDOUT_MACRO.csv",index=False)
x=D.r; n=len(x); t=x.mean()/(x.std()/np.sqrt(n)); win=(x>0).mean()
neg=x[x<0]; pf=x[x>0].sum()/abs(neg.sum()); rr=x[x>0].mean()/abs(neg.mean())
print("="*60); print("  CONFIRMATORY HOLDOUT — MACRO RULE — 2023 / 2025"); print("="*60)
print(f"\n  trades          {n}   ({n/2:.1f}/yr)")
print(f"  mean per trade  {x.mean():+.4f}%")
print(f"  win rate        {win:.1%}   (W {(x>0).sum()} / L {(x<=0).sum()}, ratio {(x>0).sum()/(x<=0).sum():.2f})")
print(f"  profit factor   {pf:.2f}")
print(f"  RR              {rr:.2f}")
print(f"  t-statistic     {t:+.2f}")
print(f"\n  development was: +0.1253%  59%  PF 2.57  RR 1.80  t +2.91  (n=80)")
print("\n  by year:")
for y in sorted(D.yr.unique()):
    k=D[D.yr==y]; g=k.r; ng=g[g<0]
    print(f"    {y}  n={len(k):3}  mean {g.mean():+.4f}%  win {(g>0).mean():4.0%}  "
          f"PF {(g[g>0].sum()/abs(ng.sum()) if len(ng) else np.nan):5.2f}")
print("\n  by day type:")
for dy in ["CPI","NFP","PPI"]:
    k=D[D.day==dy]
    if len(k)>=5:
        g=k.r; ng=g[g<0]
        print(f"    {dy}  n={len(k):3}  mean {g.mean():+.4f}%  win {(g>0).mean():4.0%}  "
              f"PF {(g[g>0].sum()/abs(ng.sum()) if len(ng) else np.nan):5.2f}")
print("\n"+"-"*60)
crit=[("mean > 0",x.mean()>0),("t > 1.5",t>1.5),("win >= 55%",win>=0.55)]
for c,ok in crit: print(f"   {'PASS' if ok else 'FAIL'}   {c}")
v="PASS" if all(o for _,o in crit) else ("FAIL" if (x.mean()<=0 or win<0.50) else "INCONCLUSIVE")
print("-"*60); print(f"\n   VERDICT: {v}\n")

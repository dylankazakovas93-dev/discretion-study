"""Macro scalp v2: 2021 promoted to development (Dylan's call, declared before running).
Holdout is now 2023 + 2025 only.

Adds: threshold sweep 0.75/1.0/1.2, no-stop vs 0.5% stop, ATR-based sizing, and R:R.
Sizing (Dylan): 30-min ATR at entry <50 pts -> 6 MNQ, 50-100 -> 4, >100 -> 3.
Hard time exit at +30 minutes whether the trade is up or down.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2021,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]
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
px=px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
front=(px.groupby(["sess","symbol"],observed=True).volume.sum().groupby("sess").idxmax().map(lambda t:t[1]))
rth=px[(px.tod>=570)&(px.tod<960)]
si=rth.groupby("sess").agg(open_ts=("ts","first"),nb=("ts","size"))
si=si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars={s:g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}
S=pd.read_csv("data/macro/surprises.csv",parse_dates=["release_ts_utc"])
S=S[S.family.isin(["inflation","labour"])&S.surprise_z.notna()&S.deadband_pass]
S=S[pd.DatetimeIndex(S.release_ts_utc).year.isin(DEV)]
S["az"]=S.surprise_z.abs()
S=S.sort_values("az").groupby("release_ts_utc").last().reset_index()
S["day"]=S.series.map(DAY); S=S[S.day.isin(["CPI","NFP","PPI"])]
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
    p30=seg.iloc[1:].loc[seg.index[1:]<=t0+pd.Timedelta(minutes=31)]
    if len(p30)<15: continue
    a=atr30(b,t0)
    r_ns=(p30.close.iloc[-1]/pe-1)*100*d
    stop=pe*(1-d*0.5/100); r_s5=None
    for _,x in p30.iterrows():
        if (x.low<=stop) if d>0 else (x.high>=stop): r_s5=-0.5; break
    if r_s5 is None: r_s5=r_ns
    mae=max(((pe/p30.low.min()-1)*100) if d>0 else ((p30.high.max()/pe-1)*100),0.0)
    rows.append(dict(sess=s.name,yr=t0.year,day=e.day,az=e.az,entry=pe,atr=a,
                     r_ns=r_ns,r_s5=r_s5,mae=mae))
D=pd.DataFrame(rows).dropna(subset=["atr"])
D["size"]=np.where(D.atr<50,6,np.where(D.atr<=100,4,3))
D.to_csv("data/macro/macro_v2.csv",index=False)

def blk(k,col):
    x=k[col]; neg=x[x<0]
    pf=x[x>0].sum()/abs(neg.sum()) if len(neg) else np.nan
    rr=x[x>0].mean()/abs(neg.mean()) if len(neg) else np.nan
    usd=(x/100*k.entry*2*k["size"]).sum()
    return (f"n={len(x):3} mean {x.mean():+.4f}% win {(x>0).mean():5.1%} PF {pf:5.2f} "
            f"RR {rr:4.2f} t {x.mean()/(x.std()/np.sqrt(len(x))):+5.2f} ${usd:>7,.0f}")
print(f"DEV = 2021/2022/2024/2026 (4 yrs).  Holdout now 2023 + 2025.\n")
print(f"30-min ATR at entry: median {D.atr.median():.0f} pts | "
      f"size mix {D['size'].value_counts().sort_index().to_dict()} (MNQ)\n")
for thr in (0.75,1.0,1.2):
    k=D[D.az>=thr]
    print(f"|z|>={thr}  ({len(k)/4:.1f} trades/yr)")
    print(f"   no stop      {blk(k,'r_ns')}")
    print(f"   0.5% stop    {blk(k,'r_s5')}")
print("\n=== YEAR BY YEAR, no stop, +30m hard exit ===")
for thr in (0.75,1.0,1.2):
    print(f"\n  |z| >= {thr}")
    for y in sorted(D.yr.unique()):
        k=D[(D.yr==y)&(D.az>=thr)]
        if len(k)>=4: print(f"    {y}  {blk(k,'r_ns')}")
print("\n=== worst single trades, no stop (unbounded risk check) ===")
for thr in (0.75,1.0):
    k=D[D.az>=thr]
    print(f"  |z|>={thr}: worst {k.r_ns.min():+.2f}%  p5 {k.r_ns.quantile(.05):+.2f}%  "
          f"max MAE {k.mae.max():.2f}%  MAE p90 {k.mae.quantile(.9):.2f}%")

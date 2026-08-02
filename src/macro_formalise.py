"""Formalise the macro scalp: apply the stop, report PF and win rate, test a 0.5% target,
and check how much rests on the biggest few winners.

Basket: CPI / NFP / PPI release days, |z| >= 0.75. Entry is the close of the first
1-minute bar at or after 08:30 ET, in that bar's direction. Conservative fills: a bar
whose range covers both stop and target is awarded the stop.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2018,2020,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]
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
S["day"]=S.series.map(DAY)
S=S[S.day.isin(["CPI","NFP","PPI"])&(S.az>=0.75)]
opens=si.open_ts.values

def run(path,pe,d,stop_pct,tp_pct=None):
    stop=pe*(1-d*stop_pct/100) if stop_pct else None
    tp=pe*(1+d*tp_pct/100) if tp_pct else None
    for _,b in path.iterrows():
        if stop is not None and ((b.low<=stop) if d>0 else (b.high>=stop)): return -stop_pct
        if tp is not None and ((b.high>=tp) if d>0 else (b.low<=tp)): return tp_pct
    return (path.close.iloc[-1]/pe-1)*100*d

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
    popen=seg.iloc[1:]
    if len(p30)<15: continue
    rec=dict(sess=s.name,yr=t0.year,day=e.day,az=e.az,entry=pe)
    rec["A_30_nostop"]=run(p30,pe,d,None)
    rec["B_30_s05"]  =run(p30,pe,d,0.5)
    rec["C_30_s05tp05"]=run(p30,pe,d,0.5,0.5)
    rec["D_open_s05"]=run(popen,pe,d,0.5)
    rec["E_30_s03"]  =run(p30,pe,d,0.3)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/macro_formal.csv",index=False)

def line(x,lab):
    x=pd.Series(x).dropna(); neg=x[x<0]
    pf=x[x>0].sum()/abs(neg.sum()) if len(neg) else np.nan
    usd=(x/100*D.entry.reindex(x.index)*2)
    print(f"  {lab:<26}n={len(x):3}  mean {x.mean():+.4f}%  win {(x>0).mean():5.1%}  "
          f"PF {pf:5.2f}  t {x.mean()/(x.std()/np.sqrt(len(x))):+5.2f}  ${usd.sum():>6,.0f}")
print(f"BASKET: CPI/NFP/PPI days, |z|>=0.75, dev years — {len(D)} trades ({len(D)/3.5:.1f}/yr)\n")
print("=== VARIANTS ===")
line(D.A_30_nostop,"+30m, no stop")
line(D.B_30_s05,   "+30m, 0.5% stop")
line(D.E_30_s03,   "+30m, 0.3% stop")
line(D.C_30_s05tp05,"+30m, 0.5% stop + 0.5% TP")
line(D.D_open_s05, "to cash open, 0.5% stop")

print("\n=== CONCENTRATION (0.5% stop, +30m) ===")
x=D.B_30_s05; tot=x.sum(); top=x.nlargest(5)
for k in (1,3,5):
    print(f"  top {k} trades = {x.nlargest(k).sum()/tot:5.0%} of total "
          f"({x.nlargest(k).sum():+.2f}% of {tot:+.2f}%)")
for k in (3,5):
    r=x.drop(top.index[:k]); neg=r[r<0]
    print(f"  minus top {k}: n={len(r)} mean {r.mean():+.4f}%  win {(r>0).mean():.0%}  "
          f"PF {r[r>0].sum()/abs(neg.sum()):.2f}  t {r.mean()/(r.std()/np.sqrt(len(r))):+.2f}")
print(f"\n  best 5: {sorted(x.nlargest(5).round(3).tolist(),reverse=True)}")
print(f"  worst 5: {sorted(x.nsmallest(5).round(3).tolist())}")
print("\n=== by year (0.5% stop, +30m) ===")
for y in sorted(D.yr.unique()):
    k=D[D.yr==y].B_30_s05; neg=k[k<0]
    print(f"  {y}  n={len(k):3}  mean {k.mean():+.4f}%  win {(k>0).mean():5.0%}  "
          f"PF {(k[k>0].sum()/abs(neg.sum()) if len(neg) else np.nan):5.2f}")
print("\n=== by day type (0.5% stop, +30m) ===")
for dy in ["CPI","NFP","PPI"]:
    k=D[D.day==dy].B_30_s05; neg=k[k<0]
    print(f"  {dy}  n={len(k):3}  mean {k.mean():+.4f}%  win {(k>0).mean():5.0%}  "
          f"PF {(k[k>0].sum()/abs(neg.sum()) if len(neg) else np.nan):5.2f}")

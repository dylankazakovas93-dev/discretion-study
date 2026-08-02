"""Wide targets, concentration, and what the equity actually looks like in dollars.

Three questions:
  1. Do 2.5% / 3.0% targets help, where 1.6% and 2.0% did not?
  2. Is the result carried by a handful of outliers?
  3. Breakeven-at-cash-open showed PF 2.78 with a 17% win rate. Compare the two variants
     as equity curves in dollars on one MNQ, not as summary ratios.

Dollars use the actual entry price of each trade: MNQ is $2 per index point.
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

def walk(path,pe,d,stop_pct,tp_pct=None,be_from=None):
    stop=pe*(1-d*stop_pct/100); tp=pe*(1+d*tp_pct/100) if tp_pct else None
    armed=False
    for ts,b in path.iterrows():
        if be_from is not None and not armed and ts>=be_from: stop=pe; armed=True
        if (b.low<=stop) if d>0 else (b.high>=stop): return (stop/pe-1)*100*d
        if tp is not None and ((b.high>=tp) if d>0 else (b.low<=tp)): return (tp/pe-1)*100*d
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
    path=b.loc[(b.index>t0)&(b.index<=s.close_ts)]
    if len(path)<120: continue
    rec=dict(sess=s.name,sym=e.sym,rk=e.rk,yr=e.etloc.year,entry=pe)
    rec["plain"]=walk(path,pe,d,1.6)
    rec["be"]=walk(path,pe,d,1.6,be_from=s.open_ts)
    for tp in (2.0,2.5,3.0): rec[f"tp{tp}"]=walk(path,pe,d,1.6,tp_pct=tp)
    rows.append(rec)
D=pd.DataFrame(rows).sort_values("sess").reset_index(drop=True)
D.to_csv("data/macro/economics.csv",index=False)

def summ(col):
    x=D[col]; dn=x[x<0]
    usd=(x/100*D.entry*2)                      # MNQ = $2/point
    eq=usd.cumsum(); dd=(eq-eq.cummax()).min()
    return dict(mean=x.mean(), win=(x>0).mean(),
                pf=x[x>0].sum()/abs(dn.sum()) if len(dn) else np.nan,
                usd=usd.sum(), per=usd.mean(), maxdd=dd)
print(f"n={len(D)} trades, one MNQ, dev years 2020/2022/2024/2026\n")
print(f"{'variant':<22}{'mean':>8}{'win':>6}{'PF':>6}{'total $':>10}{'$/trade':>9}{'max DD $':>10}")
for c,l in [("plain","1.6% stop, no TP"),("be","+ breakeven at open"),
            ("tp2.0","+ 2.0% target"),("tp2.5","+ 2.5% target"),("tp3.0","+ 3.0% target")]:
    s=summ(c)
    print(f"{l:<22}{s['mean']:>+7.3f}%{s['win']:>6.0%}{s['pf']:>6.2f}{s['usd']:>10,.0f}{s['per']:>9,.0f}{s['maxdd']:>10,.0f}")

print("\n=== CONCENTRATION (1.6% stop, no TP) ===")
x=D.plain.sort_values(ascending=False)
tot=x.sum()
for k in (1,3,5,10):
    print(f"  top {k:2} trades contribute {x.head(k).sum()/tot:5.0%} of total return "
          f"(sum {x.head(k).sum():+.2f}% of {tot:+.2f}%)")
for k in (3,5):
    r=D.plain.drop(x.head(k).index)
    print(f"  with top {k} removed: mean {r.mean():+.3f}%  win {(r>0).mean():.0%}  "
          f"t {r.mean()/(r.std()/np.sqrt(len(r))):+.1f}")
print(f"\n  biggest 5 wins: {sorted(D.plain.nlargest(5).round(2).tolist(), reverse=True)}")
print(f"  worst 5 losses: {sorted(D.plain.nsmallest(5).round(2).tolist())}")
print("\n=== per year, $ on one MNQ ===")
for c in ("plain","be"):
    u=(D[c]/100*D.entry*2)
    print(f"  {c:<6}", {int(y): int(v) for y,v in u.groupby(D.yr).sum().items()})

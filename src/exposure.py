"""How often does the trade actually reach a target, and what does exposure buy?

Dylan's questions: how many trades touch 2 / 2.5 / 3%; the true win rate and CAGR on the
breakeven variant; and return measured against time in market rather than total dollars.

MFE here is the favourable excursion reached BEFORE the 1.6% stop would have fired, so
"touched 3%" means a 3% target would genuinely have filled.
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
    stop=pe*(1-d*1.6/100)
    mfe=0.0; exit_ts=path.index[-1]; r=None
    for ts,x in path.iterrows():
        f=((x.high/pe-1)*100) if d>0 else ((pe/x.low-1)*100)
        mfe=max(mfe,f)
        if (x.low<=stop) if d>0 else (x.high>=stop):
            r=-1.6; exit_ts=ts; break
    if r is None: r=(path.close.iloc[-1]/pe-1)*100*d
    # breakeven variant
    be_r=None; be_exit=path.index[-1]; st2=stop; armed=False
    for ts,x in path.iterrows():
        if not armed and ts>=s.open_ts: st2=pe; armed=True
        if (x.low<=st2) if d>0 else (x.high>=st2):
            be_r=(st2/pe-1)*100*d; be_exit=ts; break
    if be_r is None: be_r=(path.close.iloc[-1]/pe-1)*100*d
    rows.append(dict(sess=s.name,yr=e.etloc.year,entry=pe,r=r,be_r=be_r,mfe=mfe,
        hrs=(exit_ts-t0).total_seconds()/3600, be_hrs=(be_exit-t0).total_seconds()/3600))
D=pd.DataFrame(rows); D.to_csv("data/macro/exposure.csv",index=False)
YRS=len(D.yr.unique())+0.0; span=3.5

print(f"n={len(D)} trades over ~{span} dev years ({len(D)/span:.0f}/yr)\n")
print("=== HOW OFTEN DOES IT REACH A TARGET (before the 1.6% stop) ===")
print(f"{'level':>7}{'trades':>8}{'% of all':>10}{'per year':>10}")
for lv in (1.0,1.6,2.0,2.5,3.0,3.5):
    k=(D.mfe>=lv).sum()
    print(f"{lv:>6.1f}%{k:>8}{k/len(D):>9.0%}{k/span:>10.1f}")
print("\n  per-year count reaching each level:")
for lv in (2.0,2.5,3.0):
    print(f"   {lv}%: ", D[D.mfe>=lv].groupby("yr").size().reindex([2020,2022,2024,2026]).fillna(0).astype(int).to_dict())

print("\n=== BREAKEVEN VARIANT: outcome breakdown ===")
sc=(D.be_r.abs()<0.02).sum(); wn=(D.be_r>=0.02).sum(); ls=(D.be_r<=-0.02).sum()
print(f"  scratched at breakeven : {sc:3} ({sc/len(D):.0%})")
print(f"  winners                : {wn:3} ({wn/len(D):.0%})")
print(f"  full stop -1.6%        : {ls:3} ({ls/len(D):.0%})")
print(f"  TRUE win rate (excluding scratches) = {wn/(wn+ls):.0%}")
print(f"  plain variant true win rate         = {(D.r>0).sum()/len(D):.0%}  (no scratches exist)")

print("\n=== EXPOSURE ===")
for c,h,l in (("r","hrs","plain"),("be_r","be_hrs","breakeven")):
    usd=(D[c]/100*D.entry*2); H=D[h]
    print(f"  {l:<10} median hold {H.median():5.1f}h | total exposure {H.sum():6.0f}h "
          f"({H.sum()/span:5.0f}h/yr) | ${usd.sum()/H.sum():5.2f} per hour exposed")

print("\n=== RETURN ON RISK CAPITAL ===")
print("  CAGR is not well defined for fixed-size futures, so this states the assumption:")
print("  capital = 2x historical max drawdown (so one bad run does not end it).")
for c,h,l in (("r","hrs","plain"),("be_r","be_hrs","breakeven")):
    usd=(D[c]/100*D.entry*2); eq=usd.cumsum(); dd=abs((eq-eq.cummax()).min())
    cap=2*dd; ann=usd.sum()/span
    print(f"  {l:<10} maxDD ${dd:6,.0f} | capital ${cap:6,.0f} | ${ann:6,.0f}/yr | "
          f"{ann/cap:5.0%} per year | return/DD {usd.sum()/dd:.2f}")

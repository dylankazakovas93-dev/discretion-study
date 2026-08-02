"""Anchored-VWAP band entries and exits on top-10 earnings evenings.

VWAP is anchored at the Globex reopen and accumulated from 1-minute bars. Three band
constructions, as Dylan asked:
  sd   : VWAP +- k * volume-weighted sigma, k in {1.618, 2.618, 3.618, 4.618}
  pct  : VWAP * (1 +- m/100),               m in {0.2, 0.4, 0.6, 0.8}
  mix  : the average of the two band levels

Entry: the first 5-minute bar to CLOSE beyond a band, between the reopen and the cash open.
Direction is whichever side it closed beyond. Three exits are tested per entry:
  close   hold to the next cash close
  band    target at the next band out, stop back at VWAP
  struct  stop at the pre-entry extreme, no target

All fills are conservative: a bar spanning both stop and target is awarded to the stop.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2018,2020,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]
K_SD=[1.618,2.618,3.618,4.618]; K_PCT=[0.2,0.4,0.6,0.8]

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

def exit_walk(path,entry,d,stop,target=None):
    for _,b in path.iterrows():
        hs=(b.low<=stop) if d>0 else (b.high>=stop)
        if hs: return (stop/entry-1)*100*d
        if target is not None:
            ht=(b.high>=target) if d>0 else (b.low<=target)
            if ht: return (target/entry-1)*100*d
    return (path.close.iloc[-1]/entry-1)*100*d

rows=[]
for _,e in E.iterrows():
    i=np.searchsorted(opens,np.datetime64(e.ts))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    gx=max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"),e.ts)
    w=b.loc[(b.index>=gx)&(b.index<=s.close_ts)].copy()
    if len(w)<400: continue
    tp=(w.high+w.low+w.close)/3; v=w.volume.replace(0,np.nan)
    cv=v.cumsum(); vwap=(tp*v).cumsum()/cv
    sig=np.sqrt(((tp-vwap)**2*v).cumsum()/cv)
    scan_end=s.open_ts
    m5=w.resample("5min").agg(o=("open","first"),h=("high","max"),l=("low","min"),c=("close","last")).dropna()
    m5=m5[m5.index<scan_end]
    rec={"sess":s.name,"sym":e.sym,"rk":e.rk,"yr":e.etloc.year}
    for meth in ("sd","pct","mix"):
        for j,(ks,kp) in enumerate(zip(K_SD,K_PCT)):
            up_sd,dn_sd = vwap+ks*sig, vwap-ks*sig
            up_pc,dn_pc = vwap*(1+kp/100), vwap*(1-kp/100)
            up = up_sd if meth=="sd" else up_pc if meth=="pct" else (up_sd+up_pc)/2
            dn = dn_sd if meth=="sd" else dn_pc if meth=="pct" else (dn_sd+dn_pc)/2
            U=up.reindex(m5.index,method="ffill"); D=dn.reindex(m5.index,method="ffill")
            hit=m5[(m5.c>U)|(m5.c<D)]
            if hit.empty: continue
            t0=hit.index[0]; pe=hit.c.iloc[0]; d=1.0 if pe>U.loc[t0] else -1.0
            path=b.loc[(b.index>t0)&(b.index<=s.close_ts)]
            if len(path)<200: continue
            pre=w.loc[w.index<=t0]
            struct=pre.low.min() if d>0 else pre.high.max()
            vw_at=vwap.asof(t0)
            # next band out, for the target variant
            if j+1<len(K_SD):
                ns,npc=K_SD[j+1],K_PCT[j+1]
                nu = (vwap+ns*sig) if meth=="sd" else vwap*(1+npc/100) if meth=="pct" else ((vwap+ns*sig)+vwap*(1+npc/100))/2
                nd = (vwap-ns*sig) if meth=="sd" else vwap*(1-npc/100) if meth=="pct" else ((vwap-ns*sig)+vwap*(1-npc/100))/2
                tgt=(nu if d>0 else nd).asof(t0)
            else: tgt=None
            rec[f"{meth}{j}_close"]=(path.close.iloc[-1]/pe-1)*100*d
            rec[f"{meth}{j}_struct"]=exit_walk(path,pe,d,struct)
            if tgt is not None:
                rec[f"{meth}{j}_band"]=exit_walk(path,pe,d,vw_at,tgt)
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/vwap_bands.csv",index=False)

def st(x):
    x=pd.Series(x).dropna()
    return (f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}") if len(x)>=8 else f"n={len(x):3} --"
for label,sub in [("TOP 10",D),("TOP 3",D[D.rk<=3])]:
    print(f"\n=== {label}  (sessions {len(sub)}) ===")
    print(f"{'band':<12}{'hold to close':<30}{'struct stop':<30}{'band TP + VWAP stop'}")
    for meth in ("sd","pct","mix"):
        for j in range(4):
            lbl=f"{meth} {K_SD[j] if meth!='pct' else K_PCT[j]}"
            print(f"{lbl:<12}{st(sub.get(f'{meth}{j}_close')):<30}"
                  f"{st(sub.get(f'{meth}{j}_struct')):<30}{st(sub.get(f'{meth}{j}_band'))}")

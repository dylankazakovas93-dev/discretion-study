"""Two things Dylan's objection demands.

(1) MATCHED comparison. The earlier pullback test compared 93 immediate trades against the
    36 evenings that happened to retrace -- different samples, so entry-price effect and
    sample-selection effect were tangled. Here both entries are evaluated on the SAME
    evenings, which isolates the entry price.

(2) WHEN the drawdown happens. If MAE lands minutes after entry, entry timing is the
    problem and a better entry should fix it. If it lands hours later, no entry improvement
    can help -- the stop is absorbing a mid-trade retracement, not an entry error.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV={2018,2020,2022,2024,2026}; ROOT=os.environ["NQ_DATA_ROOT"]; STOP=1.6
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

def evaluate(b,t_entry,p_entry,d,end,open_ts):
    path=b.loc[(b.index>t_entry)&(b.index<=end)]
    if len(path)<120: return None
    stop=p_entry*(1-d*STOP/100)
    r=None
    for _,x in path.iterrows():
        if (x.low<=stop) if d>0 else (x.high>=stop): r=-STOP; break
    if r is None: r=(path.close.iloc[-1]/p_entry-1)*100*d
    ext=path.low if d>0 else path.high
    t_mae=ext.idxmin() if d>0 else ext.idxmax()
    mae=((p_entry/path.low.min()-1)*100) if d>0 else ((path.high.max()/p_entry-1)*100)
    return dict(r=r, mae=max(mae,0.0),
                mins_to_mae=(t_mae-t_entry).total_seconds()/60,
                mae_before_open=bool(t_mae<open_ts))

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
    m5=w.resample("5min").agg(h=("high","max"),l=("low","min"),c=("close","last")).dropna()
    up=(m5.c>=p0*1.001).rolling(2).sum()>=2; dn=(m5.c<=p0*0.999).rolling(2).sum()>=2
    iu=up.idxmax() if up.any() else None; idn=dn.idxmax() if dn.any() else None
    if iu is None and idn is None: continue
    t0=min(x for x in [iu,idn] if x is not None)
    d=1.0 if (iu is not None and t0==iu) else -1.0
    L=p0*(1+d*0.001)
    rec={"sess":s.name,"rk":e.rk}
    a=evaluate(b,t0,float(m5.c.loc[t0]),d,s.close_ts,s.open_ts)
    if not a: continue
    rec.update({f"imm_{k}":v for k,v in a.items()})
    post=m5.loc[m5.index>t0]; lvl=L*(1-d*0.002)
    deep=(post.l<=lvl) if d>0 else (post.h>=lvl)
    if deep.any():
        td=deep.idxmax(); back=post.loc[post.index>td]
        ok=(back.c>L) if d>0 else (back.c<L)
        if ok.any():
            te=ok.idxmax()
            pb=evaluate(b,te,float(back.c.loc[te]),d,s.close_ts,s.open_ts)
            if pb: rec.update({f"pb_{k}":v for k,v in pb.items()})
    rows.append(rec)
D=pd.DataFrame(rows)

M=D.dropna(subset=["pb_r"])
print(f"=== (1) MATCHED: the SAME {len(M)} evenings, both entries ===\n")
for tag,lab in (("imm","immediate"),("pb","pullback 0.2%")):
    r=M[f"{tag}_r"]; m=M[f"{tag}_mae"]
    print(f"  {lab:<14} mean {r.mean():+.3f}%  win {(r>0).mean():.0%}  "
          f"MAE p50 {m.quantile(.5):.2f}%  p90 {m.quantile(.9):.2f}%")
print(f"\n  MAE reduced by waiting on {(M.pb_mae<M.imm_mae).mean():.0%} of matched evenings")
print(f"  median MAE change: {(M.pb_mae-M.imm_mae).median():+.2f} pp")
print(f"  median return change: {(M.pb_r-M.imm_r).median():+.3f} pp")
print(f"\n  for contrast, the 93-evening full set immediate: mean {D.imm_r.mean():+.3f}% win {(D.imm_r>0).mean():.0%}")
print(f"  the {len(M)} evenings that retraced, immediate:  mean {M.imm_r.mean():+.3f}% win {(M.imm_r>0).mean():.0%}")
print(f"  the {len(D)-len(M)} that did NOT retrace, immediate: mean {D[D.pb_r.isna()].imm_r.mean():+.3f}% win {(D[D.pb_r.isna()].imm_r>0).mean():.0%}")

print(f"\n\n=== (2) WHEN does the worst drawdown happen? (immediate entry, n={len(D)}) ===\n")
t=D.imm_mins_to_mae
print(f"  minutes from entry to the MAE extreme: p25 {t.quantile(.25):.0f}  median {t.median():.0f}  "
      f"p75 {t.quantile(.75):.0f}  p90 {t.quantile(.9):.0f}")
print(f"  MAE occurs BEFORE the cash open on {D.imm_mae_before_open.mean():.0%} of trades")
w=D[D.imm_r>0]
print(f"\n  winners only (n={len(w)}): median {w.imm_mins_to_mae.median():.0f} min, "
      f"{w.imm_mae_before_open.mean():.0%} before the cash open")
for lo,hi,l in [(0,60,"<1h"),(60,240,"1-4h"),(240,600,"4-10h"),(600,1e9,">10h")]:
    k=D[(D.imm_mins_to_mae>=lo)&(D.imm_mins_to_mae<hi)]
    if len(k): print(f"    MAE lands {l:<6} : {len(k):3} trades ({len(k)/len(D):.0%})  mean ret {k.imm_r.mean():+.3f}%")

"""Dylan's pullback entry vs the immediate entry.

Immediate (locked spec): enter on the 2nd consecutive 5-min close beyond +-0.1% from p0.
Pullback (proposed):     the 0.1% line is only a TRIGGER. After it is set, price must
                         retrace at least R% back through it, and entry happens on the
                         first 5-min close that reclaims the line in the original direction.

The claim being tested is that a reclaim entry starts closer to the eventual low, so MAE
should fall. Cost: some evenings never retrace and never reclaim, so the trade is missed.
Both effects are measured.
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
STOP=1.6

def outcome(b,pe,d,end):
    path=b.loc[(b.index>pe[0])&(b.index<=end)]
    if len(path)<120: return None
    p=pe[1]; stop=p*(1-d*STOP/100)
    mae=((p/path.low.min()-1)*100) if d>0 else ((path.high.max()/p-1)*100)
    r=None
    for _,x in path.iterrows():
        if (x.low<=stop) if d>0 else (x.high>=stop): r=-STOP; break
    if r is None: r=(path.close.iloc[-1]/p-1)*100*d
    return r, max(mae,0.0)

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
    rec={"sess":s.name,"rk":e.rk,"yr":e.etloc.year}
    o=outcome(b,(t0,float(m5.c.loc[t0])),d,s.close_ts)
    if o: rec["imm_r"],rec["imm_mae"]=o
    post=m5.loc[m5.index>t0]
    for Rpc in (0.1,0.2,0.3):
        lvl=L*(1-d*Rpc/100)
        deep=(post.l<=lvl) if d>0 else (post.h>=lvl)
        if not deep.any(): rec[f"pb{Rpc}_fire"]=0; continue
        td=deep.idxmax()
        back=post.loc[post.index>td]
        rec_ok=(back.c>L) if d>0 else (back.c<L)
        if not rec_ok.any(): rec[f"pb{Rpc}_fire"]=0; continue
        te=rec_ok.idxmax(); rec[f"pb{Rpc}_fire"]=1
        o=outcome(b,(te,float(back.c.loc[te])),d,s.close_ts)
        if o: rec[f"pb{Rpc}_r"],rec[f"pb{Rpc}_mae"]=o
    rows.append(rec)
D=pd.DataFrame(rows); D.to_csv("data/macro/pullback.csv",index=False)

def st(r,m):
    r=pd.Series(r).dropna()
    if len(r)<8: return f"n={len(r):3} --"
    m=pd.Series(m).dropna(); dn=r[r<0]
    pf=r[r>0].sum()/abs(dn.sum()) if len(dn) else np.nan
    return (f"n={len(r):3} {r.mean():+.3f}% w{(r>0).mean():.0%} PF{pf:.2f} "
            f"t{r.mean()/(r.std()/np.sqrt(len(r))):+.1f} | MAE p50 {m.quantile(.5):.2f}% p90 {m.quantile(.9):.2f}% | never-in-DD {(m<=0.02).mean():.0%}")
print(f"=== TOP 10, 1.6% stop, exit 16:00  (evenings with a trigger: {len(D)}) ===\n")
print("immediate      ", st(D.imm_r, D.imm_mae))
for Rpc in (0.1,0.2,0.3):
    f=D.get(f"pb{Rpc}_fire")
    print(f"pullback {Rpc}%   ", st(D.get(f"pb{Rpc}_r"), D.get(f"pb{Rpc}_mae")),
          f"| fires {f.fillna(0).mean():.0%} of triggers")
print(f"\n=== TOP 3 ===\n")
T=D[D.rk<=3]
print("immediate      ", st(T.imm_r, T.imm_mae))
for Rpc in (0.1,0.2,0.3):
    print(f"pullback {Rpc}%   ", st(T.get(f"pb{Rpc}_r"), T.get(f"pb{Rpc}_mae")))

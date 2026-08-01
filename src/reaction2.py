"""Follow-ups Dylan asked for:
  1. what is actually IN the 110 sessions (macro vs earnings)
  2. streak measured as momentum INTO THE OPEN, not from the release -- for an 08:30
     print the release->open window is 1 hour, for post-market earnings it is ~17 hours,
     so a streak "from the release" is not the same object across families
  3. ADX on wider buckets rather than the terciles that produced the 20-26 spike
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
from scipy import stats

DEV = {2020, 2022, 2024, 2026}
ROOT = os.environ["NQ_DATA_ROOT"]

fr = []
for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")):
    d = zstandard.ZstdDecompressor()
    with open(p, "rb") as f:
        fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                  usecols=["ts_event","open","high","low","close","volume","symbol"]))
px = pd.concat(fr, ignore_index=True)
px = px[~px.symbol.str.contains("-")]
px["ts"] = pd.to_datetime(px.ts_event, format="ISO8601", utc=True)
px["et"] = px.ts.dt.tz_convert("America/New_York")
px["sess"] = (px.et + pd.Timedelta(hours=6)).dt.date
px["tod"] = px.et.dt.hour*60 + px.et.dt.minute
px = px[pd.DatetimeIndex(px.sess).year.isin(DEV)]

front = (px.groupby(["sess","symbol"], observed=True).volume.sum().groupby("sess").idxmax().map(lambda t: t[1]))
rth = px[(px.tod>=570)&(px.tod<960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars = {s: g.set_index("ts").sort_index() for s,g in px.groupby("symbol", observed=True)}

def adx(h,l,c,n=14):
    if len(h)<n*2: return np.nan
    up,dn=np.diff(h),-np.diff(l)
    pdm=np.where((up>dn)&(up>0),up,0.); ndm=np.where((dn>up)&(dn>0),dn,0.)
    tr=np.maximum(h[1:]-l[1:],np.maximum(abs(h[1:]-c[:-1]),abs(l[1:]-c[:-1])))
    s=lambda a: pd.Series(a).ewm(alpha=1/n,adjust=False).mean().values
    atr=s(tr); pdi=100*s(pdm)/np.where(atr==0,np.nan,atr); ndi=100*s(ndm)/np.where(atr==0,np.nan,atr)
    dx=100*abs(pdi-ndi)/np.where((pdi+ndi)==0,np.nan,pdi+ndi)
    return pd.Series(dx).ewm(alpha=1/n,adjust=False).mean().values[-1]

ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
ev = ev[ev.surprise_z.notna() & ev.deadband_pass]
ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]
opens = si.open_ts.values

rows=[]
for _,e in ev.iterrows():
    t0=e.release_ts_utc; i=np.searchsorted(opens,np.datetime64(t0))
    if i>=len(si): continue
    s=si.iloc[i]; b=bars.get(s.front)
    if b is None: continue
    at=lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0=at(t0-pd.Timedelta(minutes=1)); popen=at(s.open_ts); pclose=at(s.close_ts)
    if not all(np.isfinite([p0,popen,pclose])): continue
    win=b.loc[(b.index>=t0)&(b.index<s.open_ts)]
    if len(win)<20: continue
    react=np.sign(popen/p0-1) or 1.0
    # momentum INTO the open: consecutive 5-min bars immediately before the bell
    m5=win.resample("5min").agg(o=("open","first"),c=("close","last")).dropna()
    sg=np.sign(m5.c-m5.o).values
    st=0
    for x in sg[::-1]:
        if x==react: st+=1
        else: break
    rows.append(dict(sess=s.name, family=e.family, z=e.z_signed, react=react,
        streak_into_open=st, adx=adx(win.high.values,win.low.values,win.close.values),
        agree=float(react==np.sign(e.z_signed)), hrs=(s.open_ts-t0).total_seconds()/3600,
        y=(pclose/popen-1)*100*react))
d=pd.DataFrame(rows).dropna(subset=["y"])
d=d.groupby("sess").agg({**{c:"first" for c in d.columns if c!="sess"},"z":"mean"}).reset_index()

def ci(x):
    k=(x>0).sum(); n=len(x)
    lo,hi=stats.beta.ppf([.025,.975],k+.5,n-k+.5)
    return f"{k/n:.1%} [{lo:.0%}-{hi:.0%}]"

print(f"=== WHAT IS IN THE 110 SESSIONS ===")
print(d.family.value_counts().to_string())
print(f"\nmedian hours from release to cash open: macro "
      f"{d[d.family=='inflation'].hrs.median():.1f}h | earnings {d[d.family=='eps'].hrs.median():.1f}h\n")

print("=== BASELINE by family (follow reaction at open, exit 16:00) ===")
for f in ["inflation","eps"]:
    k=d[d.family==f]
    print(f"  {f:<10} n={len(k):3}  win {ci(k.y)}  mean {k.y.mean():+.3f}%  t={k.y.mean()/(k.y.std()/np.sqrt(len(k))):+.2f}")

print("\n=== AGREE=0 (market moved AGAINST the print), split by family ===")
for f in ["inflation","eps","ALL"]:
    k=d if f=="ALL" else d[d.family==f]
    a=k[k.agree==0]
    if len(a)>3: print(f"  {f:<10} n={len(a):3}  win {ci(a.y)}  mean {a.y.mean():+.3f}%  t={a.y.mean()/(a.y.std()/np.sqrt(len(a))):+.2f}")

print("\n=== STREAK INTO THE OPEN (consecutive 5m bars before the bell), by family ===")
for f in ["inflation","eps"]:
    k=d[d.family==f]
    b=pd.cut(k.streak_into_open,[-1,0,1,2,99],labels=["0","1","2","3+"])
    r=k.groupby(b,observed=True).agg(n=("y","size"),win=("y",lambda x:(x>0).mean()),mean=("y","mean"))
    print(f"  --- {f} ---"); print(r.round(3).to_string())

print("\n=== ADX, wider buckets (Dylan: try 10-25 as one band) ===")
for f in ["inflation","ALL"]:
    k=(d if f=="ALL" else d[d.family==f]).dropna(subset=["adx"])
    b=pd.cut(k.adx,[0,15,25,35,999],labels=["<15","15-25","25-35","35+"])
    r=k.groupby(b,observed=True).agg(n=("y","size"),win=("y",lambda x:(x>0).mean()),
        mean=("y","mean"),t=("y",lambda x:x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>2 else np.nan))
    print(f"  --- {f} ---"); print(r.round(3).to_string())
d.to_csv("data/macro/reaction2.csv",index=False)

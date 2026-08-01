"""Head-to-head: take direction from the PRINT, or from PRICE?

Everything so far took direction from how price reacted. Dylan's question is the
obvious one I never tested: if a company posts a large beat, do you just go long?

  D_print  direction = sign of the EPS surprise (beat -> long, miss -> short)
  D_price  direction = sign of price at entry vs the pre-release price
  D_both   trade only when the two agree (price has confirmed the print)

Also fixes BUG-0001: beat size is now attached inside the same loop that resolves the
response session, so there is no date join to get wrong. Multiple reporters on one
evening collapse to the single largest |EPS surprise %| of that evening.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os

DEV = {2020, 2022, 2024, 2026}
ROOT = os.environ["NQ_DATA_ROOT"]

fr = []
for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")):
    d = zstandard.ZstdDecompressor()
    with open(p, "rb") as f:
        fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                  usecols=["ts_event","open","high","low","close","volume","symbol"]))
px = pd.concat(fr, ignore_index=True); px = px[~px.symbol.str.contains("-")]
px["ts"] = pd.to_datetime(px.ts_event, format="ISO8601", utc=True)
px["et"] = px.ts.dt.tz_convert("America/New_York")
px["sess"] = (px.et + pd.Timedelta(hours=6)).dt.date
px["tod"] = px.et.dt.hour*60 + px.et.dt.minute
px = px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
front = (px.groupby(["sess","symbol"],observed=True).volume.sum().groupby("sess").idxmax().map(lambda t:t[1]))
rth = px[(px.tod>=570)&(px.tod<960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb>=300]; si["front"]=front.reindex(si.index); si=si.dropna(subset=["front"]).sort_values("open_ts")
bars = {s: g.set_index("ts").sort_index() for s,g in px.groupby("symbol",observed=True)}

# earnings with BOTH the dollar surprise and the percentage surprise
E = pd.read_csv("data/macro/earnings.csv")
E = E[E.surprise_abs.notna() & E.surprise_pct.notna()].copy()
E["ts"] = pd.to_datetime(E.release_ts_utc, utc=True, format="ISO8601")
E["etloc"] = E.ts.dt.tz_convert("America/New_York")
E = E[(E.etloc.dt.hour >= 16) & (E.etloc.dt.year.isin(DEV))]
opens = si.open_ts.values

def walk(path, entry, d, stop_px):
    for _, b in path.iterrows():
        if (b.low <= stop_px) if d > 0 else (b.high >= stop_px):
            return (stop_px/entry - 1)*100*d
    return (path.close.iloc[-1]/entry - 1)*100*d

# resolve every event to its response session, then keep the biggest beat per session
ev = []
for _, e in E.iterrows():
    i = np.searchsorted(opens, np.datetime64(e.ts))
    if i < len(si):
        ev.append(dict(sess=si.index[i], ts=e.ts, etloc=e.etloc,
                       beat=e.surprise_pct, sgn=np.sign(e.surprise_abs)))
ev = pd.DataFrame(ev)
ev["ab"] = ev.beat.abs()
ev = ev.sort_values("ab").groupby("sess", as_index=False).last()

rows = []
for _, e in ev.iterrows():
    s = si.loc[e.sess]; b = bars.get(s.front)
    if b is None: continue
    at = lambda ts:(b.close.iloc[k] if 0<=(k:=b.close.index.searchsorted(ts,side="right")-1)<len(b) else np.nan)
    p0 = at(e.ts - pd.Timedelta(minutes=1))
    gx = max((e.etloc.normalize()+pd.Timedelta(hours=18)).tz_convert("UTC"), e.ts)
    ets = gx + pd.Timedelta(minutes=15)
    pe = at(ets)
    if not all(np.isfinite([p0, pe])): continue
    scan = b.loc[(b.index >= gx) & (b.index <= ets)]
    path = b.loc[(b.index > ets) & (b.index <= s.close_ts)]
    if len(path) < 300 or len(scan) < 5: continue
    dpx, dpr = np.sign(pe/p0 - 1), e.sgn
    if dpx == 0 or dpr == 0: continue
    r = dict(sess=e.sess, beat=e.beat, ab=e.ab, agree=float(dpx == dpr),
             gap=(pe/p0 - 1)*100)
    for tag, d in [("price", dpx), ("print", dpr)]:
        sp = scan.low.min() if d > 0 else scan.high.max()
        r[f"{tag}_plain"] = (at(s.close_ts)/pe - 1)*100*d
        r[f"{tag}_stop"]  = walk(path, pe, d, sp)
    rows.append(r)
D = pd.DataFrame(rows)
D.to_csv("data/macro/print_vs_price.csv", index=False)

def stat(x):
    x = pd.Series(x).dropna()
    if len(x) < 5: return f"n={len(x)} too few"
    return f"n={len(x):3} {x.mean():+.3f}% w{(x>0).mean():.0%} t{x.mean()/(x.std()/np.sqrt(len(x))):+.1f}"

print(f"sessions {len(D)} | price and print agree on {D.agree.mean():.0%} of them\n")
print("=== DIRECTION FROM THE PRINT vs FROM PRICE (entry reopen+15m, hold to cash close) ===")
print(f"  {'PRICE direction, no stop':<32}{stat(D.price_plain)}")
print(f"  {'PRICE direction, struct stop':<32}{stat(D.price_stop)}")
print(f"  {'PRINT direction, no stop':<32}{stat(D.print_plain)}")
print(f"  {'PRINT direction, struct stop':<32}{stat(D.print_stop)}")
print(f"  {'BOTH agree, no stop':<32}{stat(D[D.agree==1].price_plain)}")
print(f"  {'BOTH agree, struct stop':<32}{stat(D[D.agree==1].price_stop)}")
print(f"  {'DISAGREE (price wins), no stop':<32}{stat(D[D.agree==0].price_plain)}")

print(f"\n=== BUG-0001 FIXED: does the SIZE of the beat matter? ===")
print(f"  beat size distribution: median {D.ab.median():.1f}%  p25 {D.ab.quantile(.25):.1f}%  p75 {D.ab.quantile(.75):.1f}%\n")
for lo, hi, l in [(0,5,"<5%"),(5,12,"5-12%"),(12,25,"12-25%"),(25,1e9,">25%")]:
    k = D[(D.ab>=lo)&(D.ab<hi)]
    print(f"  beat {l:>7}: PRINT dir {stat(k.print_plain):<30} PRICE dir {stat(k.price_plain)}")
print("\n=== does a bigger beat produce a bigger GAP? ===")
print(f"  corr(|beat %|, |gap at entry %|) = {D.ab.corr(D.gap.abs()):+.3f}")
print(f"  corr(signed beat, signed gap)    = {D.beat.corr(D.gap):+.3f}")

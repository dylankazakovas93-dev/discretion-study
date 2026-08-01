"""On event days, does the CHARACTER of the release reaction predict the rest of the move?

Different question from transmission.py. That one asked "does the surprise predict the
instant move" (yes, and it is over in 5 minutes). This one asks Dylan's question: having
watched the market react, can the shape of that reaction tell you where the session ends?

Decision point is the cash open. Everything used as a feature is observable before it.
Target is the tradeable leg: cash open -> cash close, signed by the reaction direction,
i.e. "follow the reaction into the session".
"""
import pandas as pd, numpy as np, glob, zstandard, io, os

DEV = {2020, 2022, 2024, 2026}
ROOT = os.environ.get("NQ_DATA_ROOT", "data/nq")

def load():
    fr = []
    for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")) or sorted(glob.glob(f"{ROOT}/*.zst")):
        d = zstandard.ZstdDecompressor()
        with open(p, "rb") as f:
            fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                      usecols=["ts_event","open","high","low","close","volume","symbol"]))
    df = pd.concat(fr, ignore_index=True)
    df = df[~df.symbol.str.contains("-")]
    df["ts"] = pd.to_datetime(df.ts_event, format="ISO8601", utc=True)
    df["et"] = df.ts.dt.tz_convert("America/New_York")
    df["sess"] = (df.et + pd.Timedelta(hours=6)).dt.date
    df["tod"] = df.et.dt.hour * 60 + df.et.dt.minute
    return df

def adx(h, l, c, n=14):
    if len(h) < n * 2: return np.nan
    up, dn = np.diff(h), -np.diff(l)
    pdm = np.where((up > dn) & (up > 0), up, 0.); ndm = np.where((dn > up) & (dn > 0), dn, 0.)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    s = lambda a: pd.Series(a).ewm(alpha=1/n, adjust=False).mean().values
    atr = s(tr); pdi = 100*s(pdm)/np.where(atr == 0, np.nan, atr); ndi = 100*s(ndm)/np.where(atr == 0, np.nan, atr)
    dx = 100*abs(pdi-ndi)/np.where((pdi+ndi) == 0, np.nan, pdi+ndi)
    return pd.Series(dx).ewm(alpha=1/n, adjust=False).mean().values[-1]

px = load(); px = px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
front = (px.groupby(["sess","symbol"], observed=True).volume.sum().groupby("sess").idxmax().map(lambda t: t[1]))
rth = px[(px.tod >= 570) & (px.tod < 960)]
si = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
si = si[si.nb >= 300]; si["front"] = front.reindex(si.index); si = si.dropna(subset=["front"]).sort_values("open_ts")
# trailing daily range % per session, for scaling displacement
dr = rth.groupby("sess").agg(h=("high","max"), l=("low","min"), o=("open","first"))
si["atr20"] = ((dr.h - dr.l)/dr.o*100).reindex(si.index).rolling(20, min_periods=10).mean().shift(1)

bars = {s: g.set_index("ts").sort_index() for s, g in px.groupby("symbol", observed=True)}
ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
ev = ev[ev.surprise_z.notna() & ev.deadband_pass]
ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]
opens = si.open_ts.values

rows = []
for _, e in ev.iterrows():
    t0 = e.release_ts_utc
    i = np.searchsorted(opens, np.datetime64(t0))
    if i >= len(si): continue
    s = si.iloc[i]; b = bars.get(s.front)
    if b is None or not np.isfinite(s.atr20): continue
    at = lambda ts: (b.close.iloc[k] if 0 <= (k := b.close.index.searchsorted(ts, side="right")-1) < len(b) else np.nan)
    p0 = at(t0 - pd.Timedelta(minutes=1))
    if not np.isfinite(p0): continue
    win = b.loc[(b.index >= t0) & (b.index < s.open_ts)]        # release -> cash open
    if len(win) < 20: continue
    p5   = at(t0 + pd.Timedelta(minutes=5))
    popen, pclose = at(s.open_ts), at(s.close_ts)
    if not all(np.isfinite([p5, popen, pclose])): continue

    net   = (popen/p0 - 1)*100                                   # net reaction by the open
    rng   = (win.high.max() - win.low.min())/p0*100              # path travelled
    react = np.sign(net) or 1.0
    ext5  = (p5/p0 - 1)*100                                      # the initial 5-min impulse
    # 5-min bars post-release, for streak
    m5 = win.resample("5min").agg(o=("open","first"), c=("close","last")).dropna()
    sg = np.sign(m5.c - m5.o).values
    streak = 0
    for x in sg:
        if x == react: streak += 1
        elif x != 0: streak = 0
    rows.append(dict(
        sess=s.name, series=e.series, family=e.family, z=e.z_signed, absz=abs(e.surprise_z),
        react=react,
        disp=abs(net)/s.atr20,                                   # displacement in daily-range units
        eff=abs(net)/rng if rng > 0 else np.nan,                 # clean trend vs chop
        hold=(net/ext5 if ext5 != 0 else np.nan),                # did the impulse hold or retrace
        streak=streak,
        adx=adx(win.high.values, win.low.values, win.close.values),
        agree=float(react == np.sign(e.z_signed)),
        # TARGET: follow the reaction into the session
        y=(pclose/popen - 1)*100*react))
d = pd.DataFrame(rows).dropna(subset=["y","disp","eff"])
d = d.groupby("sess").agg({**{c:"first" for c in d.columns if c != "sess"}, "z":"mean"}).reset_index()
d.to_csv("data/macro/reaction.csv", index=False)

print(f"event sessions: {len(d)}\n")
print("=== BASELINE: at the cash open, buy in the direction of the release reaction, exit 16:00 ===")
t = d.y.mean()/(d.y.std()/np.sqrt(len(d)))
print(f"  mean {d.y.mean():+.4f}%   median {d.y.median():+.4f}%   win rate {(d.y>0).mean():.1%}   t={t:+.2f}\n")

def show(col, label, q=3):
    k = d.dropna(subset=[col])
    if k[col].nunique() < q: return
    b = pd.qcut(k[col], q, duplicates="drop")
    r = k.groupby(b, observed=True).agg(n=("y","size"), win=("y", lambda x:(x>0).mean()),
        mean=("y","mean"), t=("y", lambda x: x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>2 else np.nan))
    print(f"--- {label} ---"); print(r.round(3).to_string(), "\n")

for c, l in [("disp","DISPLACEMENT: |reaction| / 20d avg daily range"),
             ("eff","EFFICIENCY: |net| / path travelled  (1=clean, 0=chop)"),
             ("hold","HOLD: net at open / initial 5-min impulse  (>1 extended, <1 retraced)"),
             ("adx","ADX(14) on the reaction window"),
             ("absz","|surprise z|")]:
    show(c, l)
print("--- STREAK: consecutive 5-min closes with the reaction into the open ---")
sb = pd.cut(d.streak, [-1,0,2,4,99], labels=["0","1-2","3-4","5+"])
print(d.groupby(sb, observed=True).agg(n=("y","size"), win=("y",lambda x:(x>0).mean()),
      mean=("y","mean"), t=("y",lambda x: x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>2 else np.nan)).round(3).to_string())
print("\n--- AGREE: did the market react in the direction the surprise implies? ---")
print(d.groupby("agree").agg(n=("y","size"), win=("y",lambda x:(x>0).mean()), mean=("y","mean"),
      t=("y",lambda x: x.mean()/(x.std()/np.sqrt(len(x))) if len(x)>2 else np.nan)).round(3).to_string())

"""Measure how NQ actually responds to standardized macro/earnings surprises.

For each event the whole response is priced off ONE contract -- the front contract of
the RESPONSE session (the next RTH session opening at or after the release). Taking every
leg from a single contract removes roll discontinuities from the measurement entirely.

Legs, all relative to p0 = last completed bar strictly BEFORE the release timestamp:
  r_5m/15m/30m/60m   immediate reaction
  r_to_open          release -> next cash open   (untradeable if you are asleep)
  r_open_close       next cash open -> cash close (the leg you can actually trade)
  r_total            release -> next cash close

The question this answers: of the total repricing, how much is gone before the bell.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os, sys

DEV = {2020, 2022, 2024, 2026}

def load_prices(root=None):
    root = root or os.environ.get("NQ_DATA_ROOT", "data/nq")
    fr = []
    paths = sorted(glob.glob(f"{root}/ext/*/*.zst")) or sorted(glob.glob(f"{root}/*.zst"))
    if not paths:
        raise SystemExit(f"no .zst price files under {root!r}; set NQ_DATA_ROOT")
    for p in paths:
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
    return df.drop(columns=["ts_event"])

def main():
    px = load_prices()
    px = px[pd.DatetimeIndex(px.sess).year.isin(DEV)]
    front = (px.groupby(["sess","symbol"], observed=True).volume.sum()
               .groupby("sess").idxmax().map(lambda t: t[1]))
    rth = px[(px.tod >= 570) & (px.tod < 960)]
    sess_info = rth.groupby("sess").agg(open_ts=("ts","first"), close_ts=("ts","last"), nb=("ts","size"))
    sess_info = sess_info[sess_info.nb >= 300]
    sess_info["front"] = front.reindex(sess_info.index)
    sess_info = sess_info.dropna(subset=["front"]).sort_values("open_ts")

    # price series per contract, for fast asof lookups
    ser = {s: g.set_index("ts").close.sort_index() for s, g in px.groupby("symbol", observed=True)}

    ev = pd.read_csv("data/macro/surprises.csv", parse_dates=["release_ts_utc"])
    ev = ev[ev.surprise_z.notna() & ev.deadband_pass]
    ev = ev[pd.DatetimeIndex(ev.release_ts_utc).year.isin(DEV)]

    opens = sess_info.open_ts.values
    rows = []
    for _, e in ev.iterrows():
        t0 = e.release_ts_utc
        i = np.searchsorted(opens, np.datetime64(t0))        # next RTH opening at/after t0
        if i >= len(sess_info): continue
        s = sess_info.iloc[i]
        p = ser.get(s.front)
        if p is None: continue
        def at(ts):
            k = p.index.searchsorted(ts, side="right") - 1   # last completed bar <= ts
            return p.iloc[k] if 0 <= k < len(p) else np.nan
        p0 = at(t0 - pd.Timedelta(minutes=1))                # strictly pre-release
        if not np.isfinite(p0): continue
        r = lambda x: (x / p0 - 1) * 100
        o, c = at(s.open_ts), at(s.close_ts)
        rows.append(dict(
            event_id=e.event_id, series=e.series, family=e.family,
            release_ts_utc=t0, resp_sess=s.name, z=e.z_signed, absz=abs(e.surprise_z),
            r_5m=r(at(t0 + pd.Timedelta(minutes=5))), r_15m=r(at(t0 + pd.Timedelta(minutes=15))),
            r_30m=r(at(t0 + pd.Timedelta(minutes=30))), r_60m=r(at(t0 + pd.Timedelta(minutes=60))),
            r_to_open=r(o), r_open_close=(c / o - 1) * 100, r_total=r(c)))
    out = pd.DataFrame(rows).dropna(subset=["r_total"])
    out.to_csv("data/macro/transmission.csv", index=False)
    return out

if __name__ == "__main__":
    d = main()
    print(f"events measured: {len(d)}  ({d.family.value_counts().to_dict()})\n")
    legs = ["r_5m","r_15m","r_30m","r_60m","r_to_open","r_open_close","r_total"]

    print("=== does the surprise predict the move? corr(signed z, return) ===")
    for fam in ["inflation","eps","ALL"]:
        s = d if fam == "ALL" else d[d.family == fam]
        cs = {l: s.z.corr(s[l]) for l in legs}
        print(f"  {fam:<10} n={len(s):3} " + "  ".join(f"{l.replace('r_',''):>10}={cs[l]:+.3f}" for l in legs))

    print("\n=== mean return (%) by signed-z tercile, ALL events ===")
    b = pd.qcut(d.z, 3, labels=["z low (bearish)","z mid","z high (bullish)"])
    print(d.groupby(b, observed=True)[legs].mean().round(4).to_string())

    print("\n=== the monetisation question: share of total move already gone ===")
    big = d[d.absz >= 1.0].copy()
    for l in ["r_5m","r_30m","r_to_open"]:
        big[l+"_share"] = big[l] / big.r_total * 100
    q = big[[l+"_share" for l in ["r_5m","r_30m","r_to_open"]]].median().round(0)
    print(f"  events with |z|>=1 : n={len(big)}")
    print(f"  median % of total repricing delivered by  +5min : {q['r_5m_share']:.0f}%")
    print(f"                                           +30min : {q['r_30m_share']:.0f}%")
    print(f"                                        cash open : {q['r_to_open_share']:.0f}%")

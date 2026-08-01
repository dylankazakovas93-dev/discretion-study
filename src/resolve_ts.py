"""Resolve the filing-timestamp ambiguity against the tape.

EDGAR's JSON `acceptanceDateTime` carries a Z suffix; the filing index page shows an
`Accepted` time. For AAPL/NVDA the two differ by exactly the ET offset (JSON is真 UTC).
For MSFT/LRCX/PEP the digits are identical, so one of the two labels must be wrong.

Ground truth: MSFT is ~8% of the Nasdaq-100. Its earnings hit NQ. So compare NQ 1-minute
volume in the 15 minutes after each candidate time against that session's own baseline.
Whichever candidate lights up is the real release time.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os, json, urllib.request
UA={"User-Agent":"discretion-study research contact dylankazakovas93@gmail.com"}
ROOT=os.environ["NQ_DATA_ROOT"]

fr=[]
for p in sorted(glob.glob(f"{ROOT}/ext/*/*.zst")):
    d=zstandard.ZstdDecompressor()
    with open(p,"rb") as f:
        fr.append(pd.read_csv(io.TextIOWrapper(d.stream_reader(f)),
                  usecols=["ts_event","close","volume","symbol"]))
px=pd.concat(fr,ignore_index=True); px=px[~px.symbol.str.contains("-")]
px["ts"]=pd.to_datetime(px.ts_event,format="ISO8601",utc=True)
px["et"]=px.ts.dt.tz_convert("America/New_York")
px["d"]=px.et.dt.date
px["tod"]=px.et.dt.hour*60+px.et.dt.minute
# front contract per calendar day
front=px.groupby(["d","symbol"],observed=True).volume.sum().groupby("d").idxmax().map(lambda t:t[1])
px=px.merge(front.rename("f"),left_on="d",right_index=True); px=px[px.symbol==px.f]

def spike(dates, hh, mm, win=15):
    """median volume ratio in the win minutes after hh:mm vs that day's 11:00-15:00 baseline"""
    out=[]
    t=hh*60+mm
    for dt in dates:
        day=px[px.d==dt]
        if len(day)<400: continue
        base=day[(day.tod>=660)&(day.tod<900)].volume
        ev=day[(day.tod>=t)&(day.tod<t+win)].volume
        if len(base)<60 or len(ev)<win*0.6 or base.median()==0: continue
        out.append(ev.median()/base.median())
    return np.median(out) if out else np.nan, len(out)

for sym,cik in [("MSFT",789019),("LRCX",707549),("AAPL",320193)]:
    d=json.load(urllib.request.urlopen(urllib.request.Request(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json",headers=UA),timeout=60))
    r=d["filings"]["recent"]
    dates=[pd.Timestamp(r["filingDate"][i]).date() for i,f in enumerate(r["form"])
           if f=="8-K" and "2.02" in (r["items"][i] or "")]
    dates=[x for x in dates if x.year in (2020,2022,2024,2026)]
    print(f"\n=== {sym}  ({len(dates)} earnings 8-K dates in dev years) ===")
    for lbl,(hh,mm) in [("12:04 ET (JSON read as UTC)",(12,0)),
                        ("16:04 ET (index page as ET)",(16,0)),
                        ("control 13:30 ET",(13,30))]:
        v,n=spike(dates,hh,mm)
        print(f"   {lbl:<30} median volume vs baseline = {v:5.2f}x   (n={n})")

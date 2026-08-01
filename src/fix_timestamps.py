"""Correct EDGAR acceptance timestamps per filer.

data.sec.gov's `acceptanceDateTime` ends in Z, but for a subset of filers the digits are
already Eastern, not UTC. Confirmed against the tape: MSFT's earnings 8-Ks show a 1.72x
NQ volume spike at 16:04 ET and nothing at 12:04 ET, and the filing index page reports
16:04 -- so for MSFT the Z is wrong.

Detection: for each filer, sample 3 earnings 8-Ks and compare the JSON value with the
index page's `Accepted` field, which is documented Eastern. If they carry the same digits
the JSON is Eastern-with-a-bad-Z; if they differ by the ET offset the JSON is true UTC.
The filer's verdict must be unanimous across samples or it is left alone and flagged.
"""
import json, csv, re, time, urllib.request
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

UA = {"User-Agent": "discretion-study research contact dylankazakovas93@gmail.com"}
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
ACCEPTED = re.compile(r">Accepted</div>\s*<div[^>]*>([\d\-]+\s[\d:]+)<")

def get(u, tries=4):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8","ignore")
        except Exception:
            time.sleep(1.5*(k+1))
    return None

E = pd.read_csv("data/macro/earnings.csv")
E["sym"] = E.series.str.replace("_EPS", "", regex=False)
E["cik"] = E.ts_source.str.extract(r"accession (\S+)")[0]
verdict = {}
for sym, g in E.groupby("sym"):
    rows = g.dropna(subset=["cik"]).head(3)
    votes = []
    for _, r in rows.iterrows():
        acc = r.cik; an = acc.replace("-", "")
        cikn = str(int(acc.split("-")[0]))
        html = get(f"https://www.sec.gov/Archives/edgar/data/{cikn}/{an}/{acc}-index.htm")
        m = ACCEPTED.search(html or "")
        if not m: continue
        page = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")           # Eastern
        js = datetime.fromisoformat(r.release_ts_utc.replace("Z", "+00:00"))
        votes.append("ET_MISLABELLED" if js.replace(tzinfo=None) == page else "UTC_OK")
        time.sleep(0.2)
    verdict[sym] = votes[0] if votes and len(set(votes)) == 1 else f"UNRESOLVED{votes}"
    print(f"  {sym:6} {verdict[sym]}")

fixed = 0
def correct(r):
    global fixed
    v = verdict.get(r.sym)
    if v != "ET_MISLABELLED": return r
    naive = datetime.fromisoformat(r.release_ts_utc.replace("Z", "+00:00")).replace(tzinfo=None)
    t_et = naive.replace(tzinfo=ET)                                          # digits were Eastern
    r.release_ts_et = t_et.isoformat()
    r.release_ts_utc = t_et.astimezone(UTC).isoformat()
    r.release_date_et = t_et.date().isoformat()
    r.notes = ("post_market" if t_et.hour >= 16 else
               "pre_market" if (t_et.hour, t_et.minute) < (9,30) else "intraday")
    r.ts_source = r.ts_source + " [corrected: JSON Z was Eastern, verified vs index page]"
    fixed += 1
    return r

E = E.apply(correct, axis=1)
E.drop(columns=["sym","cik"]).to_csv("data/macro/earnings.csv", index=False)
print(f"\ncorrected {fixed} rows")
print(E.notes.value_counts().to_string())

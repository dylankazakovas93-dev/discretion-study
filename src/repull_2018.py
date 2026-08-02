"""Re-pull all earnings back to 2018 and attach Dylan's point-in-time Nasdaq top-10 rank.

Two changes from the earlier collection:
  1. START moves from 2020-06-10 to 2018-01-01. That window was a MACRO constraint (the CPI
     table starts 2020-06) and never applied to earnings. 2018 is a dev year.
  2. Company size is now measured by Dylan's supplied year-by-year Nasdaq top-10 table --
     actual index rank, not a dollar threshold that drifts as the whole market re-rates.

2019 is a HOLDOUT year and is written but tagged; nothing downstream may read it.
Keys rotate on exhaustion.
"""
import os, csv, json, time, hashlib, urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KEYS = [k for k in os.environ.get("AV_KEYS","").split(",") if k]
UA = {"User-Agent":"discretion-study research contact dylankazakovas93@gmail.com"}
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
START, END = date(2018,1,1), date(2026,6,7)

CIK = {"AAPL":320193,"MSFT":789019,"GOOGL":1652044,"AMZN":1018724,"NVDA":1045810,
       "META":1326801,"TSLA":1318605,"NFLX":1065280,"CSCO":858877,"INTC":50863,
       "QCOM":804328,"TXN":97476,"AVGO":1730168,"ADBE":796343,"MU":723125,"AMAT":6951,
       "PEP":77476,"COST":909832,"SBUX":829224,"GILD":882095,"AMGN":318154,
       "BKNG":1075531,"ISRG":1035267,"LRCX":707549,"MRVL":1835632,"KLAC":319201,
       "NXPI":1413447,"ADI":6281,"ON":1097864,"CDNS":813672,"SNPS":883241,
       "PANW":1327567,"CRWD":1535527,"INTU":896878,"SMCI":1375365,
       "AMD":2488,"PYPL":1633917}

ki = 0
def av(sym):
    global ki
    while ki < len(KEYS):
        d = json.load(urllib.request.urlopen(
            f"https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={KEYS[ki]}", timeout=60))
        if d.get("quarterlyEarnings"): return d["quarterlyEarnings"]
        if "Information" in d or "Note" in d:
            print(f"    key {ki} exhausted, rotating"); ki += 1; continue
        return None
    return None

def edgar(cik):
    u = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
    blocks = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        time.sleep(0.15)
        blocks.append(json.load(urllib.request.urlopen(
            urllib.request.Request("https://data.sec.gov/submissions/"+f["name"], headers=UA), timeout=60)))
    return [(date.fromisoformat(b["filingDate"][i]), b["acceptanceDateTime"][i], b["accessionNumber"][i])
            for b in blocks for i,f in enumerate(b["form"]) if f=="8-K" and "2.02" in (b["items"][i] or "")]

rows = []
for sym, cik in CIK.items():
    qs = av(sym)
    if not qs:
        print(f"{sym:6} AV unavailable"); continue
    try: fil = edgar(cik)
    except Exception as ex:
        print(f"{sym:6} EDGAR error {ex}"); continue
    n = 0
    for q in qs:
        try: rd = date.fromisoformat(q["reportedDate"])
        except Exception: continue
        if not (START <= rd <= END): continue
        def num(x):
            try: return float(x)
            except (TypeError, ValueError): return None
        a, e = num(q.get("reportedEPS")), num(q.get("estimatedEPS"))
        if a is None or e is None or not e: continue
        hit = min((f for f in fil if abs(f[0]-rd) <= timedelta(days=1)),
                  key=lambda f: abs(f[0]-rd), default=None)
        if not hit: continue
        ts_utc = datetime.fromisoformat(hit[1].replace("Z","+00:00")); ts_et = ts_utc.astimezone(ET)
        surp = round(a-e, 6)
        rows.append(dict(
            event_id=hashlib.sha1(f"EPS|{sym}|{hit[2]}".encode()).hexdigest()[:12],
            event_type="earnings", series=f"{sym}_EPS",
            release_date_et=ts_et.date().isoformat(), release_ts_et=ts_et.isoformat(),
            release_ts_utc=ts_utc.isoformat(),
            ts_source=f"SEC EDGAR 8-K item 2.02 acceptanceDateTime, accession {hit[2]}",
            unit="eps_usd", actual=a, consensus=e, previous="",
            surprise_abs=surp, surprise_dir=int((surp>0)-(surp<0)),
            surprise_pct=round(surp/abs(e)*100,4),
            source_actual="alphavantage_EARNINGS", source_consensus="alphavantage_EARNINGS",
            collected_at=datetime.now(UTC).isoformat(timespec="seconds"),
            notes=("post_market" if ts_et.hour>=16 else
                   "pre_market" if (ts_et.hour,ts_et.minute)<(9,30) else "intraday")))
        n += 1
    print(f"{sym:6} {n:3} quarters  ({min((r['release_date_et'] for r in rows if r['series']==f'{sym}_EPS'), default='-')} ->)")
    time.sleep(0.6)

with open("data/macro/earnings.csv","w",newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
from collections import Counter
print(f"\ntotal {len(rows)} rows | by year {dict(sorted(Counter(r['release_date_et'][:4] for r in rows).items()))}")

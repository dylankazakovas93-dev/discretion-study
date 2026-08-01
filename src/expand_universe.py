"""Add large Nasdaq post-market reporters beyond the Mag 7.

Selection rule, fixed in advance rather than picked for results: Nasdaq-100 constituents
that were already in the index before 2020 (so membership is not being granted with
hindsight), large enough to move the index, and post-market reporters.

This does NOT eliminate survivorship -- every name here still exists and is still large
in 2026. Companies that fell out of the index since 2020 are absent and cannot be
recovered from free sources. The bias is toward winners and is documented, not fixed.
"""
import os, csv, json, time, hashlib, urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KEY = os.environ["ALPHAVANTAGE_KEY"]
UA = {"User-Agent": "discretion-study research contact dylankazakovas93@gmail.com"}
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
START, END = date(2020, 6, 10), date(2026, 6, 7)
EXTRA = {"NFLX":1065280, "CSCO":858877, "INTC":50863, "QCOM":804328, "AMD":2488,
         "TXN":97476, "AVGO":1730168, "ADBE":796343, "MU":723125, "AMAT":6951}

def edgar(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
    blocks = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        time.sleep(0.2)
        blocks.append(json.load(urllib.request.urlopen(
            urllib.request.Request("https://data.sec.gov/submissions/"+f["name"], headers=UA), timeout=60)))
    out = []
    for b in blocks:
        for i, form in enumerate(b["form"]):
            if form == "8-K" and "2.02" in (b["items"][i] or ""):
                out.append((date.fromisoformat(b["filingDate"][i]),
                            b["acceptanceDateTime"][i], b["accessionNumber"][i]))
    return out

rows = []
for sym, cik in EXTRA.items():
    try:
        av = json.load(urllib.request.urlopen(
            f"https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={KEY}", timeout=60))
        qs = av.get("quarterlyEarnings")
        if not qs:
            print(f"{sym:6} AV FAILED: {str(av)[:90]}"); time.sleep(1); continue
        filings = edgar(cik)
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
            hit = min((f for f in filings if abs(f[0]-rd) <= timedelta(days=1)),
                      key=lambda f: abs(f[0]-rd), default=None)
            if not hit: continue
            ts_utc = datetime.fromisoformat(hit[1].replace("Z","+00:00")); ts_et = ts_utc.astimezone(ET)
            sess = ("post_market" if ts_et.hour >= 16 else
                    "pre_market" if (ts_et.hour, ts_et.minute) < (9,30) else "intraday")
            surp = round(a-e, 6)
            rows.append(dict(
                event_id=hashlib.sha1(f"EPS|{sym}|{hit[2]}".encode()).hexdigest()[:12],
                event_type="earnings", series=f"{sym}_EPS",
                release_date_et=ts_et.date().isoformat(),
                release_ts_et=ts_et.isoformat(), release_ts_utc=ts_utc.isoformat(),
                ts_source=f"SEC EDGAR 8-K item 2.02 acceptanceDateTime, accession {hit[2]}",
                unit="eps_usd", actual=a, consensus=e, previous="",
                surprise_abs=surp, surprise_dir=int((surp>0)-(surp<0)),
                surprise_pct=round(surp/abs(e)*100, 4),
                source_actual="alphavantage_EARNINGS", source_consensus="alphavantage_EARNINGS",
                collected_at=datetime.now(UTC).isoformat(timespec="seconds"), notes=sess))
            n += 1
        print(f"{sym:6} {n:3} quarters matched")
        time.sleep(1)
    except Exception as ex:
        print(f"{sym:6} ERROR {type(ex).__name__}: {ex}")

old = list(csv.DictReader(open("data/macro/earnings.csv")))
allr = old + [{k: r.get(k, "") for k in old[0]} for r in rows]
with open("data/macro/earnings.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(old[0])); w.writeheader(); w.writerows(allr)
from collections import Counter
print(f"\nadded {len(rows)} | total earnings rows {len(allr)}")
print("post-market share of new rows:", Counter(r["notes"] for r in rows))

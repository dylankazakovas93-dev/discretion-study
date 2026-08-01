"""Mag 7 earnings release timestamps from SEC EDGAR.

The 8-K carrying Item 2.02 ("Results of Operations and Financial Condition") is the
filing that discloses the quarter. Its `acceptanceDateTime` is the minute EDGAR
accepted it -- the actual public-disclosure timestamp, not a calendar-page estimate.

EPS actual/consensus is NOT available here; it needs an Alpha Vantage key and is
merged in separately. This file establishes the timestamp backbone only.
"""
import json, csv, time, hashlib, urllib.request
from datetime import datetime, date
from zoneinfo import ZoneInfo

UA = {"User-Agent": "discretion-study research contact dylankazakovas93@gmail.com"}
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
MAG7 = {"AAPL": 320193, "MSFT": 789019, "GOOGL": 1652044, "AMZN": 1018724,
        "NVDA": 1045810, "META": 1326801, "TSLA": 1318605}
START, END = date(2020, 6, 10), date(2026, 6, 7)      # event window / price coverage

def filings(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
    blocks = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        time.sleep(0.2)
        blocks.append(json.load(urllib.request.urlopen(
            urllib.request.Request("https://data.sec.gov/submissions/" + f["name"], headers=UA), timeout=60)))
    for b in blocks:
        for i, form in enumerate(b["form"]):
            yield form, b["filingDate"][i], b["acceptanceDateTime"][i], (b["items"][i] or ""), b["accessionNumber"][i]

rows = []
for sym, cik in MAG7.items():
    n = 0
    for form, fdate, acc, items, accession in filings(cik):
        if form != "8-K" or "2.02" not in items:
            continue
        fd = date.fromisoformat(fdate)
        if not (START <= fd <= END):
            continue
        ts_utc = datetime.fromisoformat(acc.replace("Z", "+00:00"))
        ts_et = ts_utc.astimezone(ET)
        # RTH is 09:30-16:00 ET; anything at/after 16:00 is post-market
        session = ("post_market" if ts_et.hour >= 16 else
                   "pre_market" if (ts_et.hour, ts_et.minute) < (9, 30) else "intraday")
        rows.append(dict(
            event_id=hashlib.sha1(f"EPS|{sym}|{accession}".encode()).hexdigest()[:12],
            event_type="earnings", series=f"{sym}_EPS",
            release_date_et=ts_et.date().isoformat(),
            release_ts_et=ts_et.isoformat(), release_ts_utc=ts_utc.isoformat(),
            ts_source=f"SEC EDGAR 8-K item 2.02 acceptanceDateTime, accession {accession}",
            unit="eps_usd", actual="", consensus="", previous="",
            surprise_abs="", surprise_dir="",
            source_actual="PENDING alphavantage EARNINGS (needs API key)",
            source_consensus="PENDING alphavantage EARNINGS (needs API key)",
            collected_at=datetime.now(UTC).isoformat(timespec="seconds"),
            notes=session))
        n += 1
    print(f"{sym:6} {n:3} earnings 8-Ks in window")
    time.sleep(0.3)

rows.sort(key=lambda r: r["release_ts_utc"])
with open("data/macro/earnings_timestamps.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

from collections import Counter
print(f"\ntotal {len(rows)} | session mix {dict(Counter(r['notes'] for r in rows))}")
print(f"span {rows[0]['release_date_et']} -> {rows[-1]['release_date_et']}")
print("\nsample:")
for r in rows[:5]: print(f"  {r['series']:<11}{r['release_ts_et']}  {r['notes']}")

"""Merge Alpha Vantage EPS (actual + consensus) onto EDGAR 8-K release timestamps.

Alpha Vantage knows WHICH date a quarter was reported and what the estimate was.
EDGAR knows the exact MINUTE of disclosure. Neither alone is sufficient:
- AV `reportedDate` has no time of day.
- EDGAR Item 2.02 8-Ks include non-earnings disclosures (TSLA delivery reports).
Matching them resolves both: an 8-K with no AV counterpart is not an earnings release.

API key comes from ALPHAVANTAGE_KEY. Never hardcode it -- this file is committed.
"""
import os, csv, json, time, hashlib, urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KEY = os.environ.get("ALPHAVANTAGE_KEY")
if not KEY:
    raise SystemExit("set ALPHAVANTAGE_KEY in the environment")
ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
START, END = date(2020, 6, 10), date(2026, 6, 7)

edgar = list(csv.DictReader(open("data/macro/earnings_timestamps.csv")))
by_sym = {}
for r in edgar:
    by_sym.setdefault(r["series"].split("_")[0], []).append(r)

out, unmatched_av, report = [], [], []
for sym in MAG7:
    url = (f"https://www.alphavantage.co/query?function=EARNINGS&symbol={sym}&apikey={KEY}")
    d = json.load(urllib.request.urlopen(url, timeout=60))
    qs = d.get("quarterlyEarnings")
    if not qs:
        print(f"{sym}: NO DATA -> {list(d)[:2]} {str(d)[:120]}"); continue
    cand = list(by_sym.get(sym, []))
    matched = 0
    for q in qs:
        try: rd = date.fromisoformat(q["reportedDate"])
        except Exception: continue
        if not (START <= rd <= END): continue
        # nearest 8-K within +-1 day of AV's reported date
        hit = min((c for c in cand if abs(date.fromisoformat(c["release_date_et"]) - rd) <= timedelta(days=1)),
                  key=lambda c: abs(date.fromisoformat(c["release_date_et"]) - rd), default=None)
        def num(x):
            try: return float(x)
            except (TypeError, ValueError): return None
        a, e = num(q.get("reportedEPS")), num(q.get("estimatedEPS"))
        surp = None if (a is None or e is None) else round(a - e, 6)
        if hit:
            matched += 1; cand.remove(hit)
            ts_et, ts_utc, tsrc, sess = hit["release_ts_et"], hit["release_ts_utc"], hit["ts_source"], hit["notes"]
            rdate = hit["release_date_et"]
        else:
            unmatched_av.append((sym, rd.isoformat()))
            ts_et = ts_utc = ""; tsrc = "NO EDGAR 8-K MATCH - timestamp unknown"
            sess = q.get("reportTime", ""); rdate = rd.isoformat()
        out.append(dict(
            event_id=hashlib.sha1(f"EPS|{sym}|{rdate}".encode()).hexdigest()[:12],
            event_type="earnings", series=f"{sym}_EPS", release_date_et=rdate,
            release_ts_et=ts_et, release_ts_utc=ts_utc, ts_source=tsrc, unit="eps_usd",
            actual="" if a is None else a, consensus="" if e is None else e, previous="",
            surprise_abs="" if surp is None else surp,
            surprise_dir="" if surp is None else int((surp > 0) - (surp < 0)),
            surprise_pct="" if (surp is None or not e) else round(surp / abs(e) * 100, 4),
            source_actual="alphavantage_EARNINGS", source_consensus="alphavantage_EARNINGS",
            collected_at=datetime.now(UTC).isoformat(timespec="seconds"), notes=sess))
        report.append((sym, rdate, sess, a, e))
    print(f"{sym:6} AV quarters in window {sum(1 for q in qs if q.get('reportedDate') and START<=date.fromisoformat(q['reportedDate'])<=END):3}"
          f" | matched to 8-K {matched:3} | leftover 8-Ks (non-earnings) {len(cand):3}")
    time.sleep(1)

out.sort(key=lambda r: (r["release_date_et"], r["series"]))
with open("data/macro/earnings.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
from collections import Counter
print(f"\ntotal earnings rows {len(out)} | with consensus {sum(1 for r in out if r['consensus']!='')}"
      f" | with exact timestamp {sum(1 for r in out if r['release_ts_utc'])}")
print("session mix:", dict(Counter(r['notes'] for r in out)))
if unmatched_av: print("AV quarters with no 8-K match:", unmatched_av)

"""Normalize pasted Forex Factory calendar tables into the macro event schema.

The pastes are not clean: `previous` is often line-wrapped onto the next line,
`forecast` is sometimes absent, and shutdown catch-up releases put two reference
months on one date. So the parser is token-based (a record starts at a date, then
consumes percentages until the next date) rather than line-based.

Column order (date | actual | forecast | previous) is asserted, not assumed: FF
publishes each release's `previous` as the prior release's `actual`, so
previous[i] == actual[i+1] must hold for consecutive releases. Breaks are reported,
not silently repaired -- a break is either a mis-parse or a genuinely missing release.
"""
import re, csv, sys, hashlib
from datetime import datetime, date
from zoneinfo import ZoneInfo

ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
DATE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4})")
PCT  = re.compile(r"(-?\d+\.\d+)%")

def parse_raw(path):
    """Token-scan the paste into (date, [values...]) records."""
    text = "\n".join(l for l in open(path) if not l.lstrip().startswith("#"))
    marks = [(m.start(), m.end(), m.group(1)) for m in DATE.finditer(text)]
    recs = []
    for i, (s, e, d) in enumerate(marks):
        chunk = text[e: marks[i + 1][0] if i + 1 < len(marks) else len(text)]
        recs.append((datetime.strptime(d, "%b %d, %Y").date(),
                     [float(v) for v in PCT.findall(chunk)]))
    return recs

def build(path, series, event_type, release_time=(8, 30)):
    recs = parse_raw(path)
    rows, warn = [], []
    for d, vals in recs:
        if len(vals) == 3:   actual, cons, prev = vals
        elif len(vals) == 2: actual, cons, prev = vals[0], None, vals[1]   # forecast absent
        else:
            warn.append(f"{d}: {len(vals)} values {vals} - SKIPPED"); continue
        rows.append(dict(date=d, actual=actual, consensus=cons, previous=prev))
    rows.sort(key=lambda r: r["date"])

    # chain validation
    breaks = [(a["date"], a["actual"], b["date"], b["previous"])
              for a, b in zip(rows, rows[1:])
              if b["previous"] is not None and abs(b["previous"] - a["actual"]) > 1e-9]
    dupes = sorted({r["date"] for r in rows
                    if sum(1 for x in rows if x["date"] == r["date"]) > 1})
    gaps = [(a["date"].isoformat(), b["date"].isoformat())
            for a, b in zip(rows, rows[1:]) if (b["date"] - a["date"]).days > 45]

    out = []
    for r in rows:
        ts = datetime.combine(r["date"], datetime.min.time(), tzinfo=ET).replace(
            hour=release_time[0], minute=release_time[1])
        surp = None if r["consensus"] is None else round(r["actual"] - r["consensus"], 10)
        out.append(dict(
            event_id=hashlib.sha1(f"{series}|{r['date']}|{r['actual']}".encode()).hexdigest()[:12],
            event_type=event_type, series=series,
            release_date_et=r["date"].isoformat(),
            release_ts_et=ts.isoformat(), release_ts_utc=ts.astimezone(UTC).isoformat(),
            ts_source="BLS/BEA 08:30 ET release convention (time NOT from source table)",
            unit="pct_mom", actual=r["actual"],
            consensus="" if r["consensus"] is None else r["consensus"],
            previous="" if r["previous"] is None else r["previous"],
            surprise_abs="" if surp is None else surp,
            surprise_dir="" if surp is None else int((surp > 0) - (surp < 0)),
            source_actual="forexfactory_calendar_paste",
            source_consensus="" if r["consensus"] is None else "forexfactory_calendar_paste",
            collected_at=datetime.now(UTC).isoformat(timespec="seconds"), notes=""))
    return out, dict(breaks=breaks, dupes=dupes, gaps=gaps, warn=warn)

SERIES = [("data/macro/raw/cpi_mm_forexfactory.txt",      "US_CPI_MOM"),
          ("data/macro/raw/ppi_mm_forexfactory.txt",      "US_PPI_MOM"),
          ("data/macro/raw/core_ppi_mm_forexfactory.txt", "US_CORE_PPI_MOM"),
          ("data/macro/raw/core_pce_mm_forexfactory.txt", "US_CORE_PCE_MOM")]

if __name__ == "__main__":
    allrows = []
    for path, series in SERIES:
        rows, d = build(path, series, "macro_release")
        allrows += rows
        print(f"\n=== {series} ===")
        print(f"  rows {len(rows)}  span {rows[0]['release_date_et']} -> {rows[-1]['release_date_et']}")
        print(f"  missing consensus : {sum(1 for r in rows if r['consensus']=='')}")
        print(f"  duplicate dates   : {d['dupes'] or 'none'}")
        print(f"  gaps >45d         : {d['gaps'] or 'none'}")
        print(f"  chain breaks      : {len(d['breaks'])}")
        for b in d["breaks"]: print(f"      {b[0]} actual={b[1]}  vs  {b[2]} previous={b[3]}")
        for w in d["warn"]: print(f"      WARN {w}")
    with open("data/macro/events.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(allrows[0])); w.writeheader(); w.writerows(allrows)
    print(f"\nTOTAL rows written: {len(allrows)}")

"""Normalize a pasted Forex Factory calendar table into the macro event schema.

Column order in the raw paste is: date | actual | forecast | previous.
That mapping is asserted, not assumed: FF lists each release's `previous` as the
prior release's `actual`, so the chain previous[i] == actual[i+1] must hold for
every consecutive pair. A break means the columns are mis-ordered or a row is missing.
"""
import re, sys, csv, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

ET, UTC = ZoneInfo("America/New_York"), ZoneInfo("UTC")
ROW = re.compile(r"^\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s*$")

def parse(path, series, event_type, release_time=(8, 30)):
    rows = []
    for line in open(path):
        if line.lstrip().startswith("#") or not line.strip():
            continue
        m = ROW.match(line)
        if not m:
            raise ValueError(f"unparsed row: {line!r}")
        d, a, f, p = m.groups()
        rows.append(dict(date=datetime.strptime(d, "%b %d, %Y").date(),
                         actual=float(a), consensus=float(f), previous=float(p)))
    rows.sort(key=lambda r: r["date"])

    # --- validation: the previous/actual chain must link ---
    breaks = []
    for prev, cur in zip(rows, rows[1:]):
        if abs(cur["previous"] - prev["actual"]) > 1e-9:
            breaks.append((prev["date"], prev["actual"], cur["date"], cur["previous"]))
    gaps = [(a["date"], b["date"]) for a, b in zip(rows, rows[1:])
            if (b["date"] - a["date"]).days > 45]

    out = []
    for r in rows:
        ts_et = datetime.combine(r["date"], datetime.min.time(),
                                 tzinfo=ET).replace(hour=release_time[0], minute=release_time[1])
        surprise = round(r["actual"] - r["consensus"], 10)
        eid = hashlib.sha1(f"{series}|{r['date']}".encode()).hexdigest()[:12]
        out.append(dict(
            event_id=eid, event_type=event_type, series=series,
            release_date_et=r["date"].isoformat(),
            release_ts_et=ts_et.isoformat(),
            release_ts_utc=ts_et.astimezone(UTC).isoformat(),
            ts_source="BLS 08:30 ET release convention (time NOT from source table)",
            unit="pct_mom",
            actual=r["actual"], consensus=r["consensus"], previous=r["previous"],
            surprise_abs=surprise,
            surprise_dir=int((surprise > 0) - (surprise < 0)),
            source_actual="forexfactory_calendar_paste",
            source_consensus="forexfactory_calendar_paste",
            collected_at=datetime.now(UTC).isoformat(timespec="seconds"),
            notes=""))
    return out, breaks, gaps

if __name__ == "__main__":
    rows, breaks, gaps = parse("data/macro/raw/cpi_mm_forexfactory.txt", "US_CPI_MOM", "macro_release")
    with open("data/macro/events.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"rows written : {len(rows)}")
    print(f"date span    : {rows[0]['release_date_et']} -> {rows[-1]['release_date_et']}")
    print(f"chain breaks : {len(breaks)}")
    for b in breaks: print("   ", b)
    print(f"gaps >45d    : {gaps}")
    nz = [r for r in rows if r['surprise_abs'] != 0]
    print(f"non-zero surprises: {len(nz)}/{len(rows)}")

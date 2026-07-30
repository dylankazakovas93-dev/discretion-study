"""Streaming loader for Databento GLBX.MDP3 ohlcv-1m CSV (.zst).

Responsibilities:
  * read the compressed CSV without materialising the whole uncompressed file;
  * parse UTC timestamps and convert to America/New_York (DST-aware);
  * select the front-month contract per session and detect roll boundaries;
  * emit an ordered list of :class:`Bar`, segmented by contract roll.

Causality note: front-month roll dates are fixed market conventions, so
selecting them from full-history volume is not a look-ahead into price. What we
forbid downstream is *absolute price structures* crossing a roll boundary; the
segment_id on each bar enforces that.
"""

from __future__ import annotations

import calendar as _cal
import io
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import zstandard

from .bars import Bar

ET = "America/New_York"

# Raw data bundles shipped for this study, in chronological order.
DATA_FILES = {
    "2018-2019": "glbx-mdp3-20180101-20191230.ohlcv-1m.csv.zst",
    "2020": "glbx-mdp3-20200101-20201230.ohlcv-1m.csv.zst",
    "2021-2022": "glbx-mdp3-20210101-20221230.ohlcv-1m.csv.zst",
    "2023-2024": "glbx-mdp3-20230101-20241230.ohlcv-1m.csv.zst",
    "2025-2026": "glbx-mdp3-20250101-20260607.ohlcv-1m.csv.zst",
}


def read_raw_csv(zst_path: str, start=None, end=None) -> pd.DataFrame:
    """Decompress a .zst CSV and return the raw rows as a DataFrame.

    ``start`` / ``end`` (UTC-aware or naive-UTC timestamps) filter on ts_event
    to bound memory. All contracts present in the window are returned.
    """
    dctx = zstandard.ZstdDecompressor()
    with open(zst_path, "rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8")
            df = pd.read_csv(
                text,
                usecols=[
                    "ts_event",
                    "instrument_id",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "symbol",
                ],
            )
    df["ts_utc"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.drop(columns=["ts_event"])
    if start is not None:
        df = df[df["ts_utc"] >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df["ts_utc"] < pd.Timestamp(end, tz="UTC")]
    return df.reset_index(drop=True)


_ROLL_MONTHS = (3, 6, 9, 12)
_MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}


def _third_friday(year: int, month: int):
    """Return the date of the 3rd Friday of the given month."""
    rows = _cal.monthcalendar(year, month)
    fridays = [w[4] for w in rows if w[4] > 0]
    return pd.Timestamp(year=year, month=month, day=fridays[2]).date()


def _cme_roll_events(min_year: int, max_year: int):
    """Sorted list of (roll_date, incoming_contract) for NQ quarterly rolls.

    Roll date = Thursday 8 calendar days before the 3rd Friday of each
    quarterly expiry month.  From roll_date onwards, the NEXT quarterly
    contract is the front month (the currently-expiring contract rolls off).

    E.g., on 2018-03-08 (Thursday before Mar-2018 expiry), NQM8 (Jun-2018)
    becomes front.
    """
    # Build all quarters in chronological order for the relevant range
    quarters = sorted(
        (y, m)
        for y in range(min_year - 1, max_year + 2)
        for m in _ROLL_MONTHS
    )
    events = []
    for idx, (year, month) in enumerate(quarters[:-1]):
        tf = _third_friday(year, month)
        roll_date = tf - timedelta(days=8)    # Thursday before 3rd Friday
        # Incoming (new front) contract is the NEXT quarter
        ny, nm = quarters[idx + 1]
        mc = _MONTH_CODE[nm]
        yr1 = str(ny)[-1]
        events.append((roll_date, f"NQ{mc}{yr1}"))
    return events


def _front_month_by_day_cme(dates) -> dict:
    """Map each ET session date to its CME-calendar front-month symbol.

    A fixed pre-announced CME roll schedule: the near quarterly contract is
    front until roll_date (Thursday 8 days before 3rd-Friday expiry), after
    which the next quarterly becomes front.  This is not look-ahead into price.
    """
    if not len(dates):
        return {}
    min_year = min(d.year for d in dates)
    max_year = max(d.year for d in dates)

    # Build quarters list to derive the initial front (the contract expiring
    # at the first quarterly roll in our range).
    quarters = sorted(
        (y, m)
        for y in range(min_year - 1, max_year + 2)
        for m in _ROLL_MONTHS
    )
    events = _cme_roll_events(min_year, max_year)

    # Initial front = the contract whose expiry is the first roll in our list
    iy, im = quarters[0]
    current = f"NQ{_MONTH_CODE[im]}{str(iy)[-1]}"

    result = {}
    ei = 0
    for date in sorted(dates):
        while ei < len(events) and events[ei][0] <= date:
            current = events[ei][1]
            ei += 1
        result[date] = current
    return result


def _front_month_by_day(df: pd.DataFrame) -> pd.Series:
    """Map each ET session date to its dominant (highest-volume) contract.

    Rolls are then the days where the dominant contract changes. Using daily
    aggregate volume avoids intraday flip-flopping between adjacent contracts.
    """
    et_date = df["ts_utc"].dt.tz_convert(ET).dt.date
    vol = df.groupby([et_date, "symbol"])["volume"].sum()
    # For each date, the symbol with max total volume.
    front = vol.groupby(level=0).idxmax().map(lambda k: k[1])
    return front


def load_front_month(zst_path: str, start=None, end=None,
                     method: str = "cme_calendar") -> list[Bar]:
    """Load a front-month, roll-segmented, chronologically ordered bar list.

    A new ``segment_id`` starts whenever the front contract changes. Within a
    segment, ``seq`` is a 0-based counter. Duplicate (ts, contract) rows are
    collapsed keeping the last.

    ``method``:
      "cme_calendar"    — fixed CME quarterly roll schedule (default, causal,
                          no same-day volume look-ahead)
      "full_day_volume" — original: dominant contract by full-day ET volume
                          (documents prior behaviour; kept for reconciliation)
    """
    df = read_raw_csv(zst_path, start=start, end=end)
    if df.empty:
        return []

    et = df["ts_utc"].dt.tz_convert(ET)
    df = df.assign(_et_date=et.dt.date)
    if method == "cme_calendar":
        dates = df["_et_date"].unique()
        cme_map = _front_month_by_day_cme(dates)
        df["_front"] = df["_et_date"].map(cme_map)
    else:
        front = _front_month_by_day(df)
        df["_front"] = df["_et_date"].map(front)
    # Keep only rows belonging to the front contract for their session.
    df = df[df["symbol"] == df["_front"]].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last")
    df = df.reset_index(drop=True)

    bars: list[Bar] = []
    segment_id = -1
    seq = 0
    prev_contract = None
    for row in df.itertuples(index=False):
        contract = row.symbol
        if contract != prev_contract:
            segment_id += 1
            seq = 0
            prev_contract = contract
        ts_utc = row.ts_utc
        bars.append(
            Bar(
                seq=seq,
                ts_utc=ts_utc,
                ts_et=ts_utc.tz_convert(ET),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(row.volume),
                contract=contract,
                segment_id=segment_id,
            )
        )
        seq += 1
    return bars


@dataclass
class LoadedWindow:
    """Result of loading a development window, with provenance for reporting."""

    bars: list[Bar]
    source_file: str
    start_utc: object
    end_utc: object

    @property
    def n_bars(self) -> int:
        return len(self.bars)

    @property
    def contracts(self) -> list[str]:
        return sorted({b.contract for b in self.bars})

    @property
    def segments(self) -> list[int]:
        return sorted({b.segment_id for b in self.bars})

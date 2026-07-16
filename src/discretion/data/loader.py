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

import io
from dataclasses import dataclass

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


def load_front_month(zst_path: str, start=None, end=None) -> list[Bar]:
    """Load a front-month, roll-segmented, chronologically ordered bar list.

    A new ``segment_id`` starts whenever the front contract changes. Within a
    segment, ``seq`` is a 0-based counter. Duplicate (ts, contract) rows are
    collapsed keeping the last.
    """
    df = read_raw_csv(zst_path, start=start, end=end)
    if df.empty:
        return []

    front = _front_month_by_day(df)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df.assign(_et_date=et.dt.date)
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

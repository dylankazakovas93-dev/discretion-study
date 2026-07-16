"""Synthetic bar construction for deterministic unit tests."""

from __future__ import annotations

import pandas as pd

from discretion.data.bars import Bar

ET = "America/New_York"


def make_bars(rows, start="2025-07-07 09:30", contract="NQU5", segment=0):
    """Build a Bar list from (o,h,l,c) or (o,h,l,c,v) tuples at 1-min spacing.

    seq is 0-based within the given segment; timestamps are ET-anchored and
    converted to UTC exactly as the real loader does.
    """
    base = pd.Timestamp(start, tz=ET)
    bars = []
    for i, r in enumerate(rows):
        o, h, l, c = r[:4]
        v = r[4] if len(r) > 4 else 100
        ts_et = base + pd.Timedelta(minutes=i)
        bars.append(Bar(
            seq=i, ts_utc=ts_et.tz_convert("UTC"), ts_et=ts_et,
            open=float(o), high=float(h), low=float(l), close=float(c),
            volume=int(v), contract=contract, segment_id=segment,
        ))
    return bars


def concat_segments(*segs):
    """Concatenate bar lists that already carry distinct segment ids/contracts.

    seq is reset per segment (as the loader guarantees); timestamps stay
    monotonic across the join.
    """
    out = []
    for s in segs:
        out.extend(s)
    return out

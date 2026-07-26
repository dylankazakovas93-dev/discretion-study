"""Canonical true CME-session identity for evidence gating.

A CME session opens at 18:00:00 ET and runs through 17:59:59 ET the next
calendar day (Sunday 18:00 ET .. Monday 17:59:59 ET is one session; Monday
18:00 ET opens the next). This is the ONLY session-identity function used for
adaptive-evidence gating: candidate entry session, outcome completion session,
historical comparable admission, lookback horizon boundaries, unique-session
counts, and current-session exclusion (docs/ADAPTIVE_GRADING_REPAIR_PROTOCOL.md
Sec 1-2).

Deliberately separate from ``primitives.vwap._session_key``, which resets VWAP
at 18:00 for a different purpose (detecting the boundary between adjacent
bars, not cross-comparing arbitrary timestamps) and is not touched here.

Comparing local wall-clock (hour, minute) on an already tz-aware
``America/New_York`` timestamp is DST-transparent: the 18:00 boundary never
shifts in local time, so a DST-transition day is never split or duplicated.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd

SESSION_OPEN = (18, 0)  # true CME session open, ET


def session_date(ts_et) -> "_dt.date":
    """The session identity a timestamp belongs to, labelled by the calendar
    date on which that session's 18:00 ET open occurred. Sunday 22:00 ET,
    Monday 00:05 ET and Monday 17:59 ET all return the Sunday date (the
    session that opened Sunday 18:00 and runs through Monday 17:59:59);
    Monday 18:00 ET returns the Monday date (a new session)."""
    t = (ts_et.hour, ts_et.minute)
    d = ts_et.date()
    if t >= SESSION_OPEN:
        return d
    return d - pd.Timedelta(days=1)


def session_ordinal_map(bars) -> list[int]:
    """Per-bar 0-based chronological true-CME-session ordinal, one entry per
    bar in ``bars`` (same order/length)."""
    dates = [session_date(b.ts_et) for b in bars]
    ordinal = {d: i for i, d in enumerate(sorted(set(dates)))}
    return [ordinal[d] for d in dates]


def distinct_session_dates(bars, before_date=None) -> list:
    """Sorted distinct true CME-session dates present in ``bars``, optionally
    only those strictly before ``before_date``."""
    seen = set()
    for b in bars:
        sd = session_date(b.ts_et)
        if before_date is None or sd < before_date:
            seen.add(sd)
    return sorted(seen)

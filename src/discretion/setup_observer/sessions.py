"""Frozen ET session / time-window labeling for setup fingerprints.

Deterministic boundaries (documented, frozen for the two-week demo). ET
wall-clock; the CME maintenance halt is 17:00-17:59 (no bars). Boundaries are
inclusive of the start minute, exclusive of the next window's start.

  GLOBEX_EVENING  18:00 - 19:59
  ASIA            20:00 - 02:59
  LONDON          03:00 - 07:59
  NY_PREMARKET    08:00 - 09:29
  NY_AM           09:30 - 11:59
  NY_LUNCH        12:00 - 12:59
  NY_PM           13:00 - 16:59
"""

from __future__ import annotations

SESSION_BOUNDS = [
    ("GLOBEX_EVENING", (18, 0), (19, 59)),
    ("ASIA", (20, 0), (2, 59)),          # wraps midnight
    ("LONDON", (3, 0), (7, 59)),
    ("NY_PREMARKET", (8, 0), (9, 29)),
    ("NY_AM", (9, 30), (11, 59)),
    ("NY_LUNCH", (12, 0), (12, 59)),
    ("NY_PM", (13, 0), (16, 59)),
]


def session_of(ts_et) -> str:
    m = ts_et.hour * 60 + ts_et.minute
    def mm(hm):
        return hm[0] * 60 + hm[1]
    for name, lo, hi in SESSION_BOUNDS:
        a, b = mm(lo), mm(hi)
        if a <= b:
            if a <= m <= b:
                return name
        else:  # wraps midnight (ASIA)
            if m >= a or m <= b:
                return name
    return "HALT"  # 17:00-17:59


def time_window_fields(ts_et) -> dict:
    m = ts_et.hour * 60 + ts_et.minute
    return {
        "session": session_of(ts_et),
        "et_hour": ts_et.hour,
        "minutes_from_0930": m - (9 * 60 + 30),
        "minutes_from_1000": m - (10 * 60),
        "day_of_week": ts_et.strftime("%A"),
    }

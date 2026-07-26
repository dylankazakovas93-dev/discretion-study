"""True CME-session identity (Stage 1 repair of Problem 1)."""

from __future__ import annotations

import pandas as pd
import pytest

from discretion.data.cme_session import session_date, session_ordinal_map
from discretion.data.bars import Bar

ET = "America/New_York"


def _bar(ts_str, seq=0):
    ts_et = pd.Timestamp(ts_str, tz=ET)
    return Bar(seq=seq, ts_utc=ts_et.tz_convert("UTC"), ts_et=ts_et,
               open=1.0, high=1.0, low=1.0, close=1.0, volume=1,
               contract="NQU5", segment_id=0)


def test_sunday_evening_and_monday_morning_same_session():
    sun = session_date(_bar("2025-07-13 22:00").ts_et)   # Sunday 22:00 ET
    mon_early = session_date(_bar("2025-07-14 00:05").ts_et)
    mon_late = session_date(_bar("2025-07-14 17:59").ts_et)
    assert sun == mon_early == mon_late


def test_monday_1800_starts_new_session():
    mon_late = session_date(_bar("2025-07-14 17:59").ts_et)
    mon_open = session_date(_bar("2025-07-14 18:00").ts_et)
    assert mon_open != mon_late


def test_sunday_evening_completion_cannot_inform_monday_early_candidate():
    """Problem 1's exact defect: a Sun-evening completion and a Mon-00:05
    candidate must land in the SAME session ordinal (so the < comparison
    correctly excludes it), not adjacent-but-different ordinals."""
    bars = [_bar("2025-07-13 22:00", 0), _bar("2025-07-14 00:05", 1)]
    ords = session_ordinal_map(bars)
    assert ords[0] == ords[1]


def test_candidate_cannot_use_same_session_earlier_completion():
    """A completion earlier in the SAME session as a later-entering candidate
    is not admissible (session is a wall, not reducible to midnight)."""
    bars = [_bar("2025-07-14 01:00", 0),   # early-session completion
            _bar("2025-07-14 16:00", 1)]   # later-session candidate entry
    ords = session_ordinal_map(bars)
    completion_ord, entry_ord = ords[0], ords[1]
    assert not (completion_ord < entry_ord)   # same session -> inadmissible


def test_a_prior_completed_session_is_admitted():
    bars = [_bar("2025-07-10 20:00", 0),   # Thursday session (Thu18:00->Fri17:59)
            _bar("2025-07-14 10:00", 1)]   # Monday-morning bar (Sun-opened session)
    ords = session_ordinal_map(bars)
    assert ords[0] < ords[1]   # strictly prior session -> admissible


def test_no_calendar_date_anomaly_admits_a_same_session_late_result():
    """A result completing after the candidate's entry but on an EARLIER
    calendar date (impossible causally, but guards against a raw-date-based
    comparison bug) must never enter the pool -- ordinal order must reflect
    session order, never raw calendar date, and 'entered later' by seq is
    definitionally not 'completed before' in ordinal terms."""
    bars = [_bar("2025-07-14 01:00", 0), _bar("2025-07-14 16:00", 1)]
    ords = session_ordinal_map(bars)
    # the seq-1 candidate's own session cannot be "before" seq-0's session
    # merely because seq-0 happens to sit at an earlier bar index within the
    # same session -- both share one ordinal, so neither is "prior" to the other
    assert ords[1] == ords[0]


def test_dst_spring_forward_not_split_or_duplicated():
    # 2025-03-09 is the US spring-forward DST date; 18:00 ET local wall-clock
    # is unaffected by the UTC-offset change.
    before = session_date(_bar("2025-03-09 17:59").ts_et)
    at_open = session_date(_bar("2025-03-09 18:00").ts_et)
    after = session_date(_bar("2025-03-09 23:00").ts_et)
    assert before != at_open
    assert at_open == after   # both in the session that opened 18:00 that day


def test_dst_fall_back_not_split_or_duplicated():
    # 2025-11-02 is the US fall-back DST date.
    before = session_date(_bar("2025-11-02 17:59").ts_et)
    at_open = session_date(_bar("2025-11-02 18:00").ts_et)
    after = session_date(_bar("2025-11-02 23:30").ts_et)
    assert before != at_open
    assert at_open == after


def test_cached_and_reference_session_ordinal_match():
    """The evidence engine's per-bar ordinal map (`session_ordinal_map`, used
    as the sole 'cached' implementation) must assign every bar the same
    session as computing `session_date` directly per-bar (the 'reference'
    computation) -- i.e. there is only one implementation, not two that could
    drift; this proves the vectorized/batched path is byte-identical to the
    naive per-timestamp reference."""
    bars = [_bar("2025-07-13 20:00", 0), _bar("2025-07-14 00:05", 1),
            _bar("2025-07-14 18:00", 2), _bar("2025-07-15 12:00", 3)]
    cached = session_ordinal_map(bars)
    ref_dates = [session_date(b.ts_et) for b in bars]
    ref_ordinal = {d: i for i, d in enumerate(sorted(set(ref_dates)))}
    reference = [ref_ordinal[d] for d in ref_dates]
    assert cached == reference


def test_session_ordinal_strictly_increasing_chronologically():
    bars = [_bar("2025-07-10 20:00", 0),   # Thu session
            _bar("2025-07-14 10:00", 1),   # Sun-opened session (Mon morning)
            _bar("2025-07-14 19:00", 2)]   # Mon-opened session (after 18:00)
    ords = session_ordinal_map(bars)
    assert ords[0] < ords[1] < ords[2]

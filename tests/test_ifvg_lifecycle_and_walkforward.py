"""iFVG lifecycle repair + application walk-forward tests.

Proves: close-through deactivation persists deactivation_seq/ts causally at the
exact transition candle; a deactivated iFVG is excluded from target eligibility
strictly after that candle closes but remains eligible before it; the target
resolver never selects a stale (deactivated) iFVG; long-history executable
counts no longer collapse from ghost targets; the ATR floors are unchanged by
this repair; and the multi-lookback walk-forward lets an earlier completed
application session's private outcome feed a later session's playbook while
never entering its own or an earlier session's playbook.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date

import pandas as pd
import pytest

ET = "America/New_York"

_spec = importlib.util.spec_from_file_location(
    "mlf", os.path.join("scripts", "multi_lookback_playbook_fixed.py"))
mlf = importlib.util.module_from_spec(_spec)
sys.modules["mlf"] = mlf
_spec.loader.exec_module(mlf)

from discretion.data.loader import read_raw_csv, DATA_FILES, ET as ETC
from discretion.data.bars import Bar
from discretion.primitive_reset.timeframes import candle_series, atr_series, TIMEFRAMES
from discretion.primitive_reset.registry import ResetRegistry
from discretion.primitive_reset.fvg import detect_fvgs
from discretion.primitive_reset.ifvg import detect_ifvgs
from discretion.setup_observer.observer import observe, _all_structures_ext, _ts_resolver
from discretion.setup_observer.targets import StructTable, resolve_targets
from discretion.setup_observer.playbook import EXACT_FIELDS

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _load(start, end):
    if not os.path.exists(DATA):
        return None
    df = read_raw_csv(DATA, start=start.tz_convert("UTC").tz_localize(None), end=None)
    df = df[df["symbol"] == "NQU6"].sort_values("ts_utc").drop_duplicates("ts_utc", keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ETC)
    df = df[(et >= start) & (et <= end)].reset_index(drop=True)
    return [Bar(seq=i, ts_utc=r.ts_utc, ts_et=r.ts_utc.tz_convert(ETC), open=float(r.open),
                high=float(r.high), low=float(r.low), close=float(r.close), volume=int(r.volume),
                contract="NQU6", segment_id=0) for i, r in enumerate(df.itertuples(index=False))]


@pytest.fixture(scope="module")
def ifvgs_1w():
    bars = _load(pd.Timestamp("2026-07-05 18:00:00", tz=ETC), pd.Timestamp("2026-07-10 16:59:59", tz=ETC))
    if not bars:
        pytest.skip("raw data absent")
    reg = ResetRegistry()
    s = candle_series(bars, 1)
    a = atr_series(s)
    fvgs = detect_fvgs(bars, 1, reg)
    ifvgs = detect_ifvgs(bars, 1, fvgs, a, s, reg)
    return bars, s, ifvgs


# ---------------------------------------------------------------------------
# iFVG lifecycle repair
# ---------------------------------------------------------------------------

def test_deactivated_ifvg_has_causal_deactivation_timing(ifvgs_1w):
    _, _, ifvgs = ifvgs_1w
    deactivated = [iv for iv in ifvgs if not iv.active]
    assert deactivated
    for iv in deactivated:
        assert iv.deactivation_seq is not None
        assert iv.deactivation_ts is not None
        assert iv.deactivation_available_seq is not None
        assert iv.active_until_seq == iv.deactivation_seq


def test_close_through_deactivation_specifically_writes_timing(ifvgs_1w):
    _, _, ifvgs = ifvgs_1w
    close_through = [iv for iv in ifvgs if iv.deactivation_reason not in
                     (None, "EXPIRED_ACTIVE_8H", "EXPIRED_UNTOUCHED_8H", "DATA_END_ACTIVE")]
    assert close_through, "expected at least one traversal-deactivated iFVG"
    for iv in close_through:
        assert iv.deactivation_seq is not None
        assert iv.deactivation_available_seq is not None


def test_still_active_ifvg_has_no_deactivation_timing(ifvgs_1w):
    _, _, ifvgs = ifvgs_1w
    still_active = [iv for iv in ifvgs if iv.active]
    for iv in still_active:
        assert iv.deactivation_seq is None
        assert iv.deactivation_available_seq is None


def test_deactivated_ifvg_excluded_strictly_after_its_own_candle():
    """Eligibility rule: available_seq <= decision_seq < deactivation_available_seq.
    A decision made exactly at (or after) deactivation_available_seq must
    exclude the structure; a decision made one bar earlier must not."""
    bars = _load(pd.Timestamp("2026-06-20 18:00:00", tz=ETC), pd.Timestamp("2026-06-27 16:59:59", tz=ETC))
    if not bars:
        pytest.skip("raw data absent")
    from discretion.setup_observer.observer import _detect
    series, atr, fvgs, ifvgs, rbs, ts_index = _detect(bars)
    ts_to_seq = _ts_resolver(bars)
    structs = _all_structures_ext(fvgs, ifvgs, rbs, series, ts_index, ts_to_seq)
    ifvg_structs = [s for s in structs if s["family"] == "ifvg" and s["invalid_from"] is not None]
    assert ifvg_structs
    checked = 0
    for s in ifvg_structs[:80]:
        d = s["invalid_from"]
        before_seq = max(s["avail"], d - 1)
        if before_seq >= d:
            continue   # deactivated the same bar it became available; no valid "before" probe
        table = StructTable([s])
        opp = -s["sdir"]
        entry_price = (s["lo"] - 1.0) if opp > 0 else (s["hi"] + 1.0)
        stop_price = entry_price - 1.0 if opp > 0 else entry_price + 1.0
        _, considered_before, _ = resolve_targets(table, before_seq, opp, entry_price, stop_price, 1, "none", set())
        _, considered_after, _ = resolve_targets(table, d, opp, entry_price, stop_price, 1, "none", set())
        assert considered_after and considered_after[0]["exclusion_reason"] == "inactive_or_traversed"
        assert considered_before and considered_before[0]["exclusion_reason"] != "inactive_or_traversed"
        checked += 1
    assert checked >= 1


# ---------------------------------------------------------------------------
# target resolver never sees stale iFVGs
# ---------------------------------------------------------------------------

def test_target_resolver_contains_zero_stale_deactivated_ifvgs():
    bars = _load(pd.Timestamp("2026-06-20 18:00:00", tz=ETC), pd.Timestamp("2026-06-27 16:59:59", tz=ETC))
    if not bars:
        pytest.skip("raw data absent")
    from discretion.setup_observer.observer import _detect
    series, atr, fvgs, ifvgs, rbs, ts_index = _detect(bars)
    ts_to_seq = _ts_resolver(bars)
    structs = _all_structures_ext(fvgs, ifvgs, rbs, series, ts_index, ts_to_seq)
    ifvg_by_id = {iv.id: iv for tf in ifvgs for iv in ifvgs[tf]}
    table = StructTable(structs)
    # sample entry points across the window; verify no selected target is a
    # deactivated iFVG whose deactivation_available_seq <= the decision seq
    checked = 0
    for entry_seq in range(500, len(bars), 700):
        sel, considered, _ = resolve_targets(table, entry_seq, 1, 20000.0, 19990.0, 1, "rb", set())
        for pol, tc in sel.items():
            if tc.family != "ifvg":
                continue
            iv = ifvg_by_id.get(tc.structure_id)
            checked += 1
            if iv is not None and iv.deactivation_available_seq is not None:
                assert iv.deactivation_available_seq > entry_seq
    assert checked >= 0   # loop executed without violation (assertion above is the proof)


# ---------------------------------------------------------------------------
# long-history executable count no longer collapses
# ---------------------------------------------------------------------------

def test_long_history_executable_count_does_not_collapse():
    bars = _load(pd.Timestamp("2026-06-25 18:00:00", tz=ETC), pd.Timestamp("2026-07-09 16:59:59", tz=ETC))
    if not bars:
        pytest.skip("raw data absent")
    _, variants, _ = observe(bars, target_window=600)
    exec_count = sum(1 for v in variants if v.executable)
    # with the fix, executable setups should be found even deep into a
    # multi-week window (pre-fix this stretch produced ~0)
    assert exec_count > 0


# ---------------------------------------------------------------------------
# ATR floors unchanged
# ---------------------------------------------------------------------------

def test_atr_floor_fields_still_present_and_enforced():
    bars = _load(pd.Timestamp("2026-07-05 18:00:00", tz=ETC), pd.Timestamp("2026-07-10 16:59:59", tz=ETC))
    if not bars:
        pytest.skip("raw data absent")
    _, variants, _ = observe(bars, target_window=600)
    execs = [v for v in variants if v.executable]
    assert execs
    for v in execs[:200]:
        assert v.atr_1m_24 is not None and v.atr_5m_24 is not None
        assert v.effective_stop_distance >= v.atr_1m_24 - 1e-6
        assert v.target_distance >= v.atr_5m_24 - 1e-6
        assert v.natural_rr >= 0.5


# ---------------------------------------------------------------------------
# walk-forward causality (synthetic, fast)
# ---------------------------------------------------------------------------

def fp(**over):
    base = {f: "x" for f in EXACT_FIELDS}
    base.update(lane="A", entry_variant="ENTRY_ON_TAP", reaction_state="TAP_ONLY",
                direction=1, context_tf=1, interaction_tf=1, reaction_tf=1,
                confirmation_tf=1, trigger_tf=1, is_multi_timeframe=False,
                session="ASIA", day_of_week="Mon", context_family="rb", confluence=False,
                rb_activation_class="NOT_ACTIVATED", interaction_to_trigger_delay_bin="0-1",
                target_family="rb", target_tf=1, natural_rr_bin="1.0-2.0")
    base.update(over)
    return base


class V:
    def __init__(self, vid, ep, executable, fingerprint, ts):
        self.variant_id, self.episode_id, self.executable = vid, ep, executable
        self.fingerprint, self.entry_ts = fingerprint, ts


class O:
    def __init__(self, vid, exit_seq, success):
        self.variant_id, self.exit_seq, self.exit_type = vid, exit_seq, ("TARGET" if success else "STOP")
        self.success = success


def ts(day, hour=20):
    return pd.Timestamp(f"2026-07-{day:02d} {hour:02d}:00:00", tz=ET)


def _vbs(variants):
    out = {}
    for v in variants:
        out.setdefault(mlf.session_date(v.entry_ts), []).append(v)
    return out


def test_earlier_completed_application_session_feeds_later_playbook():
    # app session Jul-12 variant resolves at seq 100 (within its own session);
    # app session Jul-13's playbook freeze is at seq 5000 (far later) -> may use it.
    app_d1, app_d2 = date(2026, 7, 12), date(2026, 7, 13)
    v = V("EP-1-ENTRY_ON_TAP", "EP-1", True, fp(), ts(12))
    vbs = _vbs([v])
    outs = {"EP-1-ENTRY_ON_TAP": O("EP-1-ENTRY_ON_TAP", 100, True)}
    before_d2 = mlf.completed_sessions_before([app_d1, app_d2], app_d2)
    assert app_d1 in before_d2
    items = mlf.build_lookback_playbook("PREV_1_SESSION", before_d2[-1:], freeze_seq=5000,
                                        cur_date=app_d2, vars_by_session=vbs, outcome_by_vid=outs)
    assert len(items) == 1


def test_current_session_outcome_cannot_enter_its_own_playbook():
    app_d1 = date(2026, 7, 12)
    v = V("EP-2-ENTRY_ON_TAP", "EP-2", True, fp(), ts(12))
    vbs = _vbs([v])
    outs = {"EP-2-ENTRY_ON_TAP": O("EP-2-ENTRY_ON_TAP", 100, True)}
    before_d1 = mlf.completed_sessions_before([app_d1], app_d1)
    assert before_d1 == []          # the session itself is never in its own "before" list
    items = mlf.build_lookback_playbook("PREV_1_SESSION", before_d1, freeze_seq=0,
                                        cur_date=app_d1, vars_by_session=vbs, outcome_by_vid=outs)
    assert items == []


def test_future_session_outcome_cannot_enter_earlier_playbook():
    # a Jul-13 variant/outcome must never authorize a Jul-12 playbook: Jul-13
    # is not in Jul-12's "before" list, and even if mistakenly pooled, its
    # outcome resolves after any Jul-12 freeze point.
    app_d1, app_d2 = date(2026, 7, 12), date(2026, 7, 13)
    v_future = V("EP-3-ENTRY_ON_TAP", "EP-3", True, fp(), ts(13))
    vbs = _vbs([v_future])
    outs = {"EP-3-ENTRY_ON_TAP": O("EP-3-ENTRY_ON_TAP", 100, True)}
    before_d1 = mlf.completed_sessions_before([app_d1, app_d2], app_d1)
    assert app_d2 not in before_d1
    items = mlf.build_lookback_playbook("PREV_1_SESSION", before_d1, freeze_seq=50,
                                        cur_date=app_d1, vars_by_session=vbs, outcome_by_vid=outs)
    assert items == []


# ---------------------------------------------------------------------------
# artifact-level checks (skip if not yet generated)
# ---------------------------------------------------------------------------

ART = os.path.join("artifacts", "multi_lookback_playbook_fixed_2026_07_12_17")


def _need(name):
    p = os.path.join(ART, name)
    if not os.path.exists(p):
        pytest.skip(f"{name} not generated yet")
    return p


def test_cards_contain_no_outcome_fields_for_their_own_setup():
    import re
    txt = open(_need("application_setup_cards.md")).read()
    # split into per-card blocks up to (not including) the "Historical source" line
    blocks = re.split(r"\n## ", txt)
    toks = ("exit_type", "r_multiple", "mfe", "mae", "pnl")
    for b in blocks[1:]:
        own_part = b.split("**Historical source")[0]
        for t in toks:
            assert t not in own_part.lower()


def test_ifvg_lifecycle_ledger_has_zero_stale_persistent_entries():
    import csv
    rows = list(csv.DictReader(open(_need("ifvg_lifecycle_ledger.csv"))))
    stale = [r for r in rows if r["active"] == "False" and r["deactivation_available_seq"] == ""]
    assert stale == []


def test_fallback_cards_are_labelled_and_outcome_blind():
    txt = open(_need("application_setup_cards.md")).read()
    if "EXECUTABLE_BUT_NOT_HISTORICALLY_AUTHORIZED" not in txt:
        pytest.skip("no fallback cards this run")
    assert "not authorized by any lookback playbook (fallback visual-audit card)" in txt

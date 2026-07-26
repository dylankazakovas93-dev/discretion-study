"""Multi-lookback recent-validity playbook tests. Proves session-lookback
causality (current session never in its own lookback; only complete prior
sessions; exact PREV_1/3/10/20 counts; freeze at session start; a later
historical outcome cannot change an earlier session's playbook), that only
executable ATR-floor-passing variants authorize anything, that the four
lookbacks stay independent, that entry variants stay distinct, that a variant
matching several lookbacks appears once, that application-week outcomes are
never computed, and that exact/reduced/similarity modes stay separate.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date

import pandas as pd
import pytest

ET = "America/New_York"

_spec = importlib.util.spec_from_file_location(
    "mlp", os.path.join("scripts", "multi_lookback_playbook.py"))
mlp = importlib.util.module_from_spec(_spec)
sys.modules["mlp"] = mlp          # required for @dataclass processing
_spec.loader.exec_module(mlp)

from discretion.setup_observer.playbook import EXACT_FIELDS, match_modes


# ---------------------------------------------------------------------------
# synthetic helpers
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
        self.reduced_key = None


class O:
    def __init__(self, vid, exit_seq, exit_type, success):
        self.variant_id, self.exit_seq, self.exit_type, self.success = vid, exit_seq, exit_type, success


def ts(day, hour=20):
    return pd.Timestamp(f"2026-07-{day:02d} {hour:02d}:00:00", tz=ET)


# ---------------------------------------------------------------------------
# session lookback causality
# ---------------------------------------------------------------------------

DATES = [date(2026, 7, d) for d in (1, 2, 3, 6, 7, 8, 9, 10, 12, 13)]


def test_current_session_never_in_its_own_lookback():
    before = mlp.completed_sessions_before(DATES, date(2026, 7, 12))
    assert date(2026, 7, 12) not in before
    assert all(d < date(2026, 7, 12) for d in before)


def test_only_complete_prior_sessions_used():
    before = mlp.completed_sessions_before(DATES, date(2026, 7, 9))
    assert before == [date(2026, 7, d) for d in (1, 2, 3, 6, 7, 8)]


def test_prev_1_uses_exactly_one_session():
    before = mlp.completed_sessions_before(DATES, date(2026, 7, 13))
    assert len(mlp.recent_lookback(before, 1)) == 1
    assert mlp.recent_lookback(before, 1) == [date(2026, 7, 12)]


def test_prev_3_uses_exactly_three():
    before = mlp.completed_sessions_before(DATES, date(2026, 7, 13))
    assert len(mlp.recent_lookback(before, 3)) == 3


def test_prev_10_and_20_use_exactly_that_many_when_available():
    dates = [date(2026, 6, d) for d in range(1, 26)] + [date(2026, 7, 1)]
    before = mlp.completed_sessions_before(dates, date(2026, 7, 1))
    assert len(mlp.recent_lookback(before, 10)) == 10
    assert len(mlp.recent_lookback(before, 20)) == 20
    # and they are the most-recent ones
    assert mlp.recent_lookback(before, 3) == before[-3:]


# ---------------------------------------------------------------------------
# freeze at session start; later outcome cannot change earlier playbook
# ---------------------------------------------------------------------------

def _vars_by_session(variants):
    out = {}
    for v in variants:
        out.setdefault(mlp.session_date(v.entry_ts), []).append(v)
    return out


def test_playbook_freezes_at_session_start_ignoring_later_resolving_outcomes():
    # two identical successful executable variants in the same prior session; one
    # resolves BEFORE the freeze (exit 90), one AFTER (exit 200). Freeze at 100.
    d = date(2026, 7, 8)
    v_early = V("EP-1-ENTRY_ON_TAP", "EP-1", True, fp(), ts(8))
    v_late = V("EP-2-ENTRY_ON_TAP", "EP-2", True, fp(session="LONDON"), ts(8, 3))
    vbs = _vars_by_session([v_early, v_late])
    outs = {"EP-1-ENTRY_ON_TAP": O("EP-1-ENTRY_ON_TAP", 90, "TARGET", True),
            "EP-2-ENTRY_ON_TAP": O("EP-2-ENTRY_ON_TAP", 200, "TARGET", True)}
    items = mlp.build_lookback_playbook("PREV_3_SESSIONS", [d], freeze_seq=100,
                                        cur_date=date(2026, 7, 12), vars_by_session=vbs,
                                        outcome_by_vid=outs)
    authed = {i.fingerprint["session"] for i in items}
    assert "ASIA" in authed          # early one authorizes
    assert "LONDON" not in authed     # late-resolving one is excluded by the freeze


def test_later_outcome_cannot_retroactively_change_earlier_playbook():
    # same variant, outcome resolving after freeze -> no authorization at that freeze
    d = date(2026, 7, 8)
    v = V("EP-9-ENTRY_ON_TAP", "EP-9", True, fp(), ts(8))
    vbs = _vars_by_session([v])
    outs_late = {"EP-9-ENTRY_ON_TAP": O("EP-9-ENTRY_ON_TAP", 500, "TARGET", True)}
    early_freeze = mlp.build_lookback_playbook("PREV_1_SESSION", [d], 100, date(2026, 7, 12), vbs, outs_late)
    late_freeze = mlp.build_lookback_playbook("PREV_1_SESSION", [d], 600, date(2026, 7, 12), vbs, outs_late)
    assert len(early_freeze) == 0     # not yet resolved at freeze 100
    assert len(late_freeze) == 1      # resolved by freeze 600


# ---------------------------------------------------------------------------
# only executable authorizers; entry variants distinct; independence
# ---------------------------------------------------------------------------

def test_only_executable_variants_can_authorize():
    d = date(2026, 7, 8)
    v_ok = V("EP-A-ENTRY_ON_TAP", "EP-A", True, fp(), ts(8))
    v_bad = V("EP-B-ENTRY_ON_TAP", "EP-B", False, fp(session="NY_AM"), ts(8))  # not executable
    vbs = _vars_by_session([v_ok, v_bad])
    outs = {"EP-A-ENTRY_ON_TAP": O("EP-A-ENTRY_ON_TAP", 50, "TARGET", True),
            "EP-B-ENTRY_ON_TAP": O("EP-B-ENTRY_ON_TAP", 50, "TARGET", True)}
    items = mlp.build_lookback_playbook("PREV_3_SESSIONS", [d], 100, date(2026, 7, 12), vbs, outs)
    authed = {i.fingerprint["session"] for i in items}
    assert authed == {"ASIA"}         # only the executable one


def test_entry_variants_remain_distinct():
    d = date(2026, 7, 8)
    tap = V("EP-T-ENTRY_ON_TAP", "EP-T", True, fp(entry_variant="ENTRY_ON_TAP", reaction_state="TAP_ONLY"), ts(8))
    disp = V("EP-D-ENTRY_ON_IMMEDIATE_DISPLACEMENT", "EP-D", True,
             fp(entry_variant="ENTRY_ON_IMMEDIATE_DISPLACEMENT", reaction_state="IMMEDIATE_DISPLACEMENT"), ts(8))
    vbs = _vars_by_session([tap, disp])
    outs = {tap.variant_id: O(tap.variant_id, 50, "TARGET", True),
            disp.variant_id: O(disp.variant_id, 50, "TARGET", True)}
    items = mlp.build_lookback_playbook("PREV_3_SESSIONS", [d], 100, date(2026, 7, 12), vbs, outs)
    evs = {i.fingerprint["entry_variant"] for i in items}
    assert evs == {"ENTRY_ON_TAP", "ENTRY_ON_IMMEDIATE_DISPLACEMENT"}   # never merged


def test_lookbacks_are_independent():
    # a fingerprint only present in an older session authorizes the deep lookback
    # (which includes it) but not the shallow one (which does not).
    old, recent = date(2026, 7, 1), date(2026, 7, 10)
    v_old = V("EP-O-ENTRY_ON_TAP", "EP-O", True, fp(session="LONDON"), ts(1))
    v_new = V("EP-N-ENTRY_ON_TAP", "EP-N", True, fp(session="NY_PM"), ts(10))
    vbs = _vars_by_session([v_old, v_new])
    outs = {v_old.variant_id: O(v_old.variant_id, 50, "TARGET", True),
            v_new.variant_id: O(v_new.variant_id, 50, "TARGET", True)}
    prev1 = mlp.build_lookback_playbook("PREV_1_SESSION", [recent], 10_000, date(2026, 7, 12), vbs, outs)
    prev10 = mlp.build_lookback_playbook("PREV_10_SESSIONS", [old, recent], 10_000, date(2026, 7, 12), vbs, outs)
    assert {i.fingerprint["session"] for i in prev1} == {"NY_PM"}
    assert {i.fingerprint["session"] for i in prev10} == {"LONDON", "NY_PM"}


# ---------------------------------------------------------------------------
# cross-lookback classification + mode separation
# ---------------------------------------------------------------------------

def _per(**flags):
    return {ln: {"ids": (["x"] if flags.get(ln) else []), "mode": "EXACT", "support": 1, "src": []}
            for ln, _ in mlp.LOOKBACKS}


def test_cross_lookback_classification():
    assert mlp._cross_class(_per()) == "NO_ACTIONABLE_MATCH"
    assert mlp._cross_class(_per(PREV_1_SESSION=True)) == "ONE_SESSION_ONLY"
    assert mlp._cross_class(_per(PREV_3_SESSIONS=True)) == "THREE_SESSION_ONLY"
    assert mlp._cross_class(_per(PREV_10_SESSIONS=True)) == "TEN_SESSION_ONLY"
    assert mlp._cross_class(_per(PREV_20_SESSIONS=True)) == "TWENTY_SESSION_ONLY"
    assert mlp._cross_class(_per(PREV_1_SESSION=True, PREV_3_SESSIONS=True,
                                 PREV_10_SESSIONS=True, PREV_20_SESSIONS=True)) == "ALL_LOOKBACKS"
    assert mlp._cross_class(_per(PREV_3_SESSIONS=True, PREV_20_SESSIONS=True)) == "SHORT_AND_LONG_LOOKBACK_SUPPORT"


def test_exact_reduced_similarity_modes_separate():
    items = mlp.build_lookback_playbook(
        "PREV_3_SESSIONS", [date(2026, 7, 8)], 100, date(2026, 7, 12),
        _vars_by_session([V("EP-M-ENTRY_ON_TAP", "EP-M", True, fp(), ts(8))]),
        {"EP-M-ENTRY_ON_TAP": O("EP-M-ENTRY_ON_TAP", 50, "TARGET", True)})
    v_app = V("EP-APP-ENTRY_ON_TAP", "EP-APP", True, fp(), ts(13))
    m = match_modes(v_app, items)
    assert set(m) == {"EXACT", "REDUCED_FAMILY", "SIMILARITY_DIAGNOSTIC"}
    assert set(m["EXACT"]).issubset(set(m["REDUCED_FAMILY"]))
    assert m["SIMILARITY_DIAGNOSTIC"] is None or "nearest_item_id" in m["SIMILARITY_DIAGNOSTIC"]


# ---------------------------------------------------------------------------
# integration on generated artifacts (skip if the driver hasn't run)
# ---------------------------------------------------------------------------

ART = os.path.join("artifacts", "multi_lookback_playbook_2026_07_12_17")


def _need(name):
    p = os.path.join(ART, name)
    if not os.path.exists(p):
        pytest.skip(f"{name} not generated yet")
    return p


def test_application_outcomes_absent_in_artifacts():
    ci = json.load(open(_need("causal_invariants.json")))
    assert ci["application_outcomes_computed"] is False
    assert ci["violations"]["application_variant_has_outcome"] == 0
    assert ci["total_violations"] == 0


def test_twenty_session_history_supported():
    cov = json.load(open(_need("data_coverage.json")))
    assert cov["n_complete_pre_application_sessions"] >= 20
    assert cov["INSUFFICIENT_HISTORY_FOR_20_SESSION_LOOKBACK"] is False


def test_cards_have_unique_variants():
    import re
    txt = open(_need("application_setup_cards.md")).read()
    ids = re.findall(r"^## (\S+)", txt, flags=re.M)
    assert len(ids) == len(set(ids))          # a setup appears once
    assert len(ids) <= 16

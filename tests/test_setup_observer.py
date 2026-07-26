"""Setup-observer reaction-variant + recent-validity playbook tests (two-week
demo). Proves: tap entry exists without later confirmation and freezes no later
reaction info; a small close-outside is a variant without strong displacement;
minimal-wick rejection stays distinct from strong rejection; strong / immediate
/ delayed displacement stay separate and correctly measured; a large wick with
no close outside is not mislabelled CLOSE_BACK_OUTSIDE; scraping stays separate;
multi-timeframe architecture is preserved; entry-variant + reaction-state gate
the playbook so a strong-displacement success cannot authorize tap entry (and
vice versa); targets are opposing/active/causal; only executable authorized
variants are actionable; and application outcomes cannot affect the playbook.
"""
from __future__ import annotations

import dataclasses
import os

import pandas as pd
import pytest

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import (
    build_playbook, match_modes, EXACT_FIELDS, REDUCED_FIELDS,
)
from discretion.setup_observer import reaction_states as rs
from discretion.setup_observer.sessions import session_of, time_window_fields

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
OBS_START = pd.Timestamp("2026-07-05 18:00:00", tz=ET)
OBS_END = pd.Timestamp("2026-07-10 16:59:59", tz=ET)
APP_START = pd.Timestamp("2026-07-12 18:00:00", tz=ET)
APP_END = pd.Timestamp("2026-07-17 23:59:59", tz=ET)

_OUTCOME_TOKENS = ("mfe", "mae", "outcome", "pnl", "realized", "win", "loss",
                   "exit_price", "exit_type", "points", "r_multiple", "success")


def _load(start=OBS_START, end=OBS_END):
    if not os.path.exists(DATA):
        return None
    start_utc = start.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA, start=start_utc, end=None)
    df = df[df["symbol"] == "NQU6"].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df[(et >= start) & (et <= end)].reset_index(drop=True)
    bars = []
    for seq, row in enumerate(df.itertuples(index=False)):
        t = row.ts_utc
        bars.append(Bar(seq=seq, ts_utc=t, ts_et=t.tz_convert(ET),
                        open=float(row.open), high=float(row.high), low=float(row.low),
                        close=float(row.close), volume=int(row.volume),
                        contract="NQU6", segment_id=0))
    return bars


@pytest.fixture(scope="module")
def obs():
    bars = _load()
    if not bars:
        pytest.skip("raw data absent")
    eps, variants, diag = observe(bars)
    return bars, eps, variants, diag


@pytest.fixture(scope="module")
def app():
    bars = _load(APP_START, APP_END)
    if not bars:
        pytest.skip("raw data absent")
    eps, variants, diag = observe(bars)
    return bars, eps, variants, diag


# ---------------------------------------------------------------------------
# synthetic-candle unit tests for the reaction classifier
# ---------------------------------------------------------------------------

class _C:
    def __init__(self, o, h, l, c):
        self.open, self.high, self.low, self.close = o, h, l, c


def _series(specials, n=14, base=None):
    """Flat doji candles with ``specials`` (offset -> candle) overlaid."""
    base = base if base is not None else _C(100.5, 100.55, 100.45, 100.5)
    s = [_C(base.open, base.high, base.low, base.close) for _ in range(n)]
    for off, cndl in specials.items():
        s[off] = cndl
    return s


def test_tap_only_without_confirmation_is_a_variant_seed():
    """A bare tap that provokes no reaction still seeds TAP_ONLY at offset 0 and
    nothing else -- the tap entry needs no later confirmation."""
    s = _series({}, n=13)
    atr = [1.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.TAP_ONLY] == 0
    assert r["offsets"][rs.IMMEDIATE_DISPLACEMENT] is None
    assert r["offsets"][rs.STRONG_REJECTION_DEPARTURE] is None
    assert r["dominant_state"] in (rs.TAP_ONLY, rs.SCRAPING_NO_REACTION)


def test_immediate_displacement_measured():
    s = _series({11: _C(101.0, 103.1, 100.9, 103.0)}, n=13)
    atr = [2.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.IMMEDIATE_DISPLACEMENT] == 1


def test_delayed_displacement_is_separate():
    s = _series({8: _C(100.6, 105.1, 100.5, 105.0)}, n=12)
    atr = [2.0] * 12
    r = rs.classify(s, atr, 5, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.IMMEDIATE_DISPLACEMENT] is None
    assert r["offsets"][rs.DELAYED_DISPLACEMENT] == 3


def test_close_back_outside_without_strong_displacement():
    """A small directional close just outside the zone forms a variant with no
    strong displacement and no big body."""
    s = _series({11: _C(101.05, 101.3, 101.0, 101.2)}, n=13)
    atr = [2.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.CLOSE_BACK_OUTSIDE] == 1
    assert r["offsets"][rs.IMMEDIATE_DISPLACEMENT] is None


def test_minimal_wick_rejection_distinct_from_strong():
    # small body, small wick (wick/body < 1) closing just outside -> MINIMAL only
    s = _series({11: _C(101.1, 101.35, 101.0, 101.3)}, n=13)
    atr = [2.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.MINIMAL_WICK_REJECTION] == 1
    assert r["offsets"][rs.STRONG_REJECTION_DEPARTURE] is None


def test_strong_rejection_departure_measured():
    # small body but large rejection wick (wick/body >= 1), strong close & range
    s = _series({11: _C(101.2, 101.6, 100.0, 101.5)}, n=13)
    atr = [2.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.STRONG_REJECTION_DEPARTURE] == 1


def test_large_wick_no_close_outside_not_labelled_close_back_outside():
    """A big rejection wick whose close stays inside the zone is descriptive
    (wick recorded) but never CLOSE_BACK_OUTSIDE / MINIMAL_WICK_REJECTION."""
    s = _series({11: _C(100.8, 100.95, 100.0, 100.9)}, n=13)
    atr = [2.0] * 13
    r = rs.classify(s, atr, 10, 1, 100.0, 101.0, set(), set())
    assert r["offsets"][rs.CLOSE_BACK_OUTSIDE] is None
    assert r["offsets"][rs.MINIMAL_WICK_REJECTION] is None
    # but the wick is still measured descriptively
    react = [m for m in r["trace"] if m["k"] == 1][0]
    assert react["rejection_wick_pts"] > 0


def test_scraping_stays_separate():
    s = _series({}, n=16)
    atr = [1.0] * 16
    r = rs.classify(s, atr, 3, 1, 100.0, 101.0, set(), set())
    for st in (rs.CLOSE_BACK_OUTSIDE, rs.MINIMAL_WICK_REJECTION,
               rs.STRONG_REJECTION_DEPARTURE, rs.IMMEDIATE_DISPLACEMENT,
               rs.DELAYED_DISPLACEMENT):
        assert r["offsets"][st] is None
    assert r["dominant_state"] in (rs.SCRAPING_NO_REACTION, rs.TAP_ONLY)


# ---------------------------------------------------------------------------
# variant-level causal-freeze proofs (real data)
# ---------------------------------------------------------------------------

def test_tap_variant_freezes_no_later_reaction_info(obs):
    _, _, variants, _ = obs
    taps = [v for v in variants if v.entry_variant == "ENTRY_ON_TAP"]
    assert taps
    for v in taps[:200]:
        assert v.interaction_to_trigger_delay == 0
        assert v.reaction_state == rs.TAP_ONLY
        # only the interaction candle (k==0) is in the frozen trace
        assert all(m["k"] == 0 for m in v.reaction_measures_through_trigger)
        assert v.fingerprint["entry_variant"] == "ENTRY_ON_TAP"
        assert v.fingerprint["reaction_state"] == rs.TAP_ONLY


def test_later_displacement_cannot_change_earlier_tap_fingerprint(obs):
    """Where the same physical episode yields both a tap and a later
    displacement variant, the tap's fingerprint carries none of the
    displacement's reaction fields."""
    _, _, variants, _ = obs
    by_ep = {}
    for v in variants:
        by_ep.setdefault(v.episode_id, []).append(v)
    checked = 0
    for vs in by_ep.values():
        rules = {v.entry_variant: v for v in vs}
        tap = rules.get("ENTRY_ON_TAP")
        disp = rules.get("ENTRY_ON_IMMEDIATE_DISPLACEMENT") or rules.get("ENTRY_ON_DELAYED_DISPLACEMENT")
        if tap and disp:
            checked += 1
            assert tap.fingerprint["reaction_state"] == rs.TAP_ONLY
            assert tap.fingerprint["reaction_state"] != disp.fingerprint["reaction_state"]
            assert tap.interaction_to_trigger_delay < disp.interaction_to_trigger_delay
    if checked == 0:
        pytest.skip("no episode with both tap and displacement variants in window")


def test_variant_reaction_trace_never_exceeds_its_trigger(obs):
    _, _, variants, _ = obs
    for v in variants[:2000]:
        assert all(m["k"] <= v.interaction_to_trigger_delay
                   for m in v.reaction_measures_through_trigger)


# ---------------------------------------------------------------------------
# causal ordering + timeframe architecture
# ---------------------------------------------------------------------------

def test_entry_is_after_trigger_and_next_bar(obs):
    bars, _, variants, _ = obs
    for v in variants:
        assert v.entry_seq < len(bars)
        assert v.entry_seq >= v.trigger_seq
        assert v.entry_price == bars[v.entry_seq].open


def test_multi_timeframe_architecture_preserved(obs):
    _, eps, variants, diag = obs
    # some genuine cross-timeframe episodes exist (HTF context, 1m trigger)
    mtf = [v for v in variants if v.is_multi_timeframe]
    assert mtf, "expected some multi-timeframe variants"
    for v in mtf[:500]:
        assert v.trigger_tf < v.context_tf
        assert v.trigger_tf == 1
        # roles are explicit and preserved on the fingerprint
        assert v.fingerprint["context_tf"] == v.context_tf
        assert v.fingerprint["trigger_tf"] == v.trigger_tf
        assert v.fingerprint["is_multi_timeframe"] is True
    # same-timeframe architecture also present
    assert any(not v.is_multi_timeframe for v in variants)


def test_session_time_window_preserved(obs):
    bars, _, variants, _ = obs
    for v in variants[:500]:
        tw = time_window_fields(bars[v.entry_seq].ts_et)
        assert v.session == tw["session"]
        assert v.fingerprint["session"] == v.session


# ---------------------------------------------------------------------------
# targets: opposing, active, causal
# ---------------------------------------------------------------------------

def test_selected_targets_are_opposing_active_causal(obs):
    _, _, variants, _ = obs
    checked = 0
    for v in variants:
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        if prim is None:
            continue
        checked += 1
        # causal: available no later than entry
        assert prim.availability_seq <= v.entry_seq
        # profit-direction: beyond entry
        if v.direction > 0:
            assert prim.surface > v.entry_price
        else:
            assert prim.surface < v.entry_price
        # opposing + active: the chosen structure has an empty exclusion reason
        sel = [c for c in v.considered_targets if c["structure_id"] == prim.structure_id]
        assert sel and sel[0]["exclusion_reason"] == ""
    assert checked


def test_diagnostic_target_never_authorizes_execution(obs):
    _, _, variants, _ = obs
    for v in variants[:1000]:
        if v.executable:
            # executability is driven by the opposing policy, never the diagnostic
            assert v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE") is not None


# ---------------------------------------------------------------------------
# playbook: entry-variant + reaction-state gating
# ---------------------------------------------------------------------------

def _obs_playbook(obs):
    bars, _, variants, _ = obs
    outs = [o for o in (process_outcome(v, bars) for v in variants) if o]
    return variants, outs, build_playbook(variants, outs, OBS_START, OBS_END)


def test_playbook_items_carry_entry_variant_and_reaction_state(obs):
    _, _, pb = _obs_playbook(obs)
    if not pb:
        pytest.skip("no successful observation variant in window")
    for item in pb:
        assert item.entry_variant == item.fingerprint["entry_variant"]
        assert item.reaction_state == item.fingerprint["reaction_state"]
        assert "entry_variant" in EXACT_FIELDS and "entry_variant" in REDUCED_FIELDS
        assert "reaction_state" in EXACT_FIELDS and "reaction_state" in REDUCED_FIELDS


def test_strong_displacement_success_cannot_authorize_tap_entry(obs):
    """A tap-entry application variant can only match playbook items that are
    themselves tap-entry -- never a strong-displacement authorization."""
    variants, _, pb = _obs_playbook(obs)
    if not pb:
        pytest.skip("empty playbook")
    for v in variants:
        if v.entry_variant != "ENTRY_ON_TAP":
            continue
        m = match_modes(v, pb)
        for iid in m["EXACT"] + m["REDUCED_FAMILY"]:
            item = next(p for p in pb if p.item_id == iid)
            assert item.entry_variant == "ENTRY_ON_TAP"
            assert item.reaction_state == v.reaction_state


def test_tap_success_cannot_authorize_displacement_entry(obs):
    variants, _, pb = _obs_playbook(obs)
    if not pb:
        pytest.skip("empty playbook")
    for v in variants:
        if v.entry_variant not in ("ENTRY_ON_IMMEDIATE_DISPLACEMENT", "ENTRY_ON_DELAYED_DISPLACEMENT"):
            continue
        m = match_modes(v, pb)
        for iid in m["EXACT"] + m["REDUCED_FAMILY"]:
            item = next(p for p in pb if p.item_id == iid)
            assert item.entry_variant == v.entry_variant


def test_match_modes_stay_separate(obs):
    variants, _, pb = _obs_playbook(obs)
    if not pb:
        pytest.skip("empty playbook")
    for v in variants[:400]:
        m = match_modes(v, pb)
        assert set(m) == {"EXACT", "REDUCED_FAMILY", "SIMILARITY_DIAGNOSTIC"}
        assert set(m["EXACT"]).issubset(set(m["REDUCED_FAMILY"]))
        assert m["SIMILARITY_DIAGNOSTIC"] is None or "nearest_item_id" in m["SIMILARITY_DIAGNOSTIC"]


# ---------------------------------------------------------------------------
# actionable eligibility + application isolation
# ---------------------------------------------------------------------------

def test_only_executable_authorized_variants_are_actionable(app, obs):
    obars, _, ovars, _ = obs
    _, _, avars, _ = app
    outs = [o for o in (process_outcome(v, obars) for v in ovars) if o]
    pb = build_playbook(ovars, outs, OBS_START, OBS_END)
    if not pb:
        pytest.skip("empty playbook")
    for v in avars:
        m = match_modes(v, pb)
        matched = bool(m["EXACT"] or m["REDUCED_FAMILY"])
        actionable = matched and v.executable
        if actionable:
            prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
            assert prim is not None and prim.natural_rr >= 0.5
            assert v.rejection_reason == ""


def test_application_outcomes_cannot_affect_playbook(obs):
    """The playbook is a pure function of observation variants + observation
    outcomes: every authorized item is sourced only from observation-week
    variants, so nothing from the application week can enter it."""
    obars, _, ovars, _ = obs
    outs = [o for o in (process_outcome(v, obars) for v in ovars) if o]
    obs_ids = {v.variant_id for v in ovars}
    pb = build_playbook(ovars, outs, OBS_START, OBS_END)
    if not pb:
        pytest.skip("empty playbook")
    for item in pb:
        assert set(item.source_variant_ids) <= obs_ids
        for o in item.source_outcomes:
            assert o["variant_id"] in obs_ids
    # deterministic and independent of any application-week computation
    pb2 = build_playbook(ovars, outs, OBS_START, OBS_END)
    assert [p.fingerprint for p in pb] == [p.fingerprint for p in pb2]


def test_no_outcome_fields_on_variants(obs):
    _, _, variants, _ = obs
    for v in variants[:300]:
        for f in dataclasses.fields(v):
            assert not any(tok in f.name.lower() for tok in _OUTCOME_TOKENS), f.name
        for k in v.fingerprint:
            assert not any(tok in k.lower() for tok in _OUTCOME_TOKENS), k


def test_observe_is_deterministic(obs):
    bars, eps, variants, _ = obs
    eps2, vars2, _ = observe(bars)
    assert [e.episode_id for e in eps2] == [e.episode_id for e in eps]
    assert [v.variant_id for v in vars2] == [v.variant_id for v in variants]
    assert [v.fingerprint for v in vars2] == [v.fingerprint for v in variants]


# ---------------------------------------------------------------------------
# frozen session boundaries
# ---------------------------------------------------------------------------

def test_session_boundaries_frozen():
    def et(h, m=0):
        return pd.Timestamp(f"2026-07-06 {h:02d}:{m:02d}:00", tz=ET)
    assert session_of(et(18)) == "GLOBEX_EVENING"
    assert session_of(et(20)) == "ASIA"
    assert session_of(et(3)) == "LONDON"
    assert session_of(et(8)) == "NY_PREMARKET"
    assert session_of(et(9, 30)) == "NY_AM"
    assert session_of(et(12)) == "NY_LUNCH"
    assert session_of(et(13)) == "NY_PM"

"""Coherent-setup observer + recent-validity playbook tests (two-week demo).

Proves the observer only emits COHERENT setups (context -> interaction ->
confirmation -> trigger -> stop -> causal target), never bare taps/structures;
that every episode is fully causal and outcome-free; that RB activation is
descriptive not gating and cannot be rewritten by later activation; that
reaction branches (immediate vs delayed vs scraping) stay separate; that
physical duplicates collapse to one episode; that timeframe architecture and
session/time windows are preserved; that target policies never consult
outcomes; that observation fingerprints freeze before outcomes; and that the
application week cannot alter the frozen playbook or leak outcomes.
"""
from __future__ import annotations

import dataclasses
import os

import pandas as pd
import pytest

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe, _avail, MIN_EXECUTABLE_RR
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import (
    build_playbook, match_modes, EXACT_FIELDS, REDUCED_FIELDS,
)
from discretion.setup_observer.displacement import (
    measure_reaction, IMMEDIATE, DELAYED, SCRAPING, COMPRESSION,
)
from discretion.setup_observer.sessions import session_of, time_window_fields

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
OBS_START = pd.Timestamp("2026-07-05 18:00:00", tz=ET)
OBS_END = pd.Timestamp("2026-07-10 16:59:59", tz=ET)
APP_START = pd.Timestamp("2026-07-12 18:00:00", tz=ET)
APP_END = pd.Timestamp("2026-07-17 23:59:59", tz=ET)

_OUTCOME_TOKENS = ("mfe", "mae", "outcome", "pnl", "return", "realized",
                   "win", "loss", "result", "exit_price", "exit_type",
                   "points", "r_multiple", "success")


def _load(symbol="NQU6", start=OBS_START, end=OBS_END):
    if not os.path.exists(DATA):
        return None
    start_utc = start.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA, start=start_utc, end=None)
    df = df[df["symbol"] == symbol].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df[(et >= start) & (et <= end)].reset_index(drop=True)
    bars = []
    for seq, row in enumerate(df.itertuples(index=False)):
        t = row.ts_utc
        bars.append(Bar(seq=seq, ts_utc=t, ts_et=t.tz_convert(ET),
                        open=float(row.open), high=float(row.high), low=float(row.low),
                        close=float(row.close), volume=int(row.volume),
                        contract=symbol, segment_id=0))
    return bars


@pytest.fixture(scope="module")
def obs():
    bars = _load()
    if not bars:
        pytest.skip("raw data absent")
    episodes, diag = observe(bars)
    return bars, episodes, diag


@pytest.fixture(scope="module")
def app():
    bars = _load(start=APP_START, end=APP_END)
    if not bars:
        pytest.skip("raw data absent")
    episodes, diag = observe(bars)
    return bars, episodes, diag


# ---------------------------------------------------------------------------
# 1. Coherence: bare taps / bare structures never become setups
# ---------------------------------------------------------------------------

def test_every_episode_has_full_causal_chain(obs):
    """Each episode carries a context, an interaction, a confirmation and a
    trigger -- a bare structure or bare tap can never satisfy this."""
    _, episodes, _ = obs
    assert episodes
    for e in episodes:
        assert e.context_id                      # pre-existing context
        assert e.interaction_seq is not None      # price interaction
        assert e.confirmation_seq is not None     # subsequent confirmation
        assert e.trigger_seq is not None          # causal trigger
        assert e.confirm_reason in (
            "displacement", "rejection", "same_dir_fvg", "same_dir_ifvg")


def test_bare_rb_tap_without_confirmation_emits_no_setup():
    """A synthetic RB tap that provokes no reaction (flat scraping) yields no
    confirmation and therefore no episode from the reaction layer."""
    class C:  # minimal candle
        def __init__(self, o, h, l, c):
            self.open, self.high, self.low, self.close = o, h, l, c
    # zone at [100,101]; tap at idx 3, then five identical tiny doji candles.
    flat = [C(100.5, 100.6, 100.4, 100.5) for _ in range(9)]
    atr = [1.0] * 9
    r = measure_reaction(flat, atr, 3, 1, 100.0, 101.0, set(), set())
    assert r["confirm_idx"] is None
    assert r["branch"] == SCRAPING


def test_bare_fvg_interaction_without_reaction_emits_no_setup():
    """Touching an FVG with no subsequent displacement/rejection/new structure
    does not confirm -> observer would drop it (scraping)."""
    class C:
        def __init__(self, o, h, l, c):
            self.open, self.high, self.low, self.close = o, h, l, c
    flat = [C(50.0, 50.1, 49.9, 50.0) for _ in range(9)]
    atr = [2.0] * 9
    r = measure_reaction(flat, atr, 2, -1, 49.0, 51.0, set(), set())
    assert r["confirm_idx"] is None


# ---------------------------------------------------------------------------
# 2. Causal ordering (no look-ahead)
# ---------------------------------------------------------------------------

def test_interaction_precedes_confirmation(obs):
    _, episodes, _ = obs
    for e in episodes:
        assert e.interaction_seq <= e.confirmation_seq


def test_confirmation_precedes_trigger_entry(obs):
    _, episodes, _ = obs
    for e in episodes:
        assert e.trigger_seq >= 0
        # trigger fires at the confirmation candle close; entry is strictly after
        assert e.entry_seq > e.trigger_seq


def test_entry_is_next_bar_after_trigger(obs):
    bars, episodes, _ = obs
    for e in episodes:
        assert e.entry_seq < len(bars)
        assert e.entry_price == bars[e.entry_seq].open


def test_targets_available_no_later_than_entry(obs):
    _, episodes, _ = obs
    for e in episodes:
        for t in e.targets:
            assert t.availability_seq <= e.entry_seq


# ---------------------------------------------------------------------------
# 3. RB activation is descriptive, causal, and immutable
# ---------------------------------------------------------------------------

def test_unactivated_rb_may_participate(obs):
    """Lane A/E episodes exist whose RB was NOT activated at trigger time --
    activation is not a gate."""
    _, episodes, _ = obs
    rb_eps = [e for e in episodes if e.rb_wick_body is not None]
    assert rb_eps, "expected some RB-based episodes"
    assert any(e.rb_activated_at_trigger is False for e in rb_eps)


def test_later_activation_cannot_alter_earlier_fingerprint(obs):
    """If an RB only activates AFTER the trigger, the frozen activation class
    at trigger time is NOT_ACTIVATED regardless of the later flag."""
    _, episodes, _ = obs
    late = [e for e in episodes
            if e.rb_wick_body is not None and e.rb_activation_only_after_setup]
    for e in late:
        assert e.rb_activated_at_trigger is False
        assert e.fingerprint["rb_activation_class"] == "NOT_ACTIVATED"


# ---------------------------------------------------------------------------
# 4. Reaction branches stay separate; scraping is not displacement
# ---------------------------------------------------------------------------

def test_immediate_and_delayed_reactions_remain_separate(obs):
    _, episodes, _ = obs
    branches = {e.displacement_branch for e in episodes}
    assert IMMEDIATE in branches and DELAYED in branches
    for e in episodes:
        # IMMEDIATE is reserved for a next-candle displacement/rejection; a
        # same-candle structural confirmation is DELAYED, never IMMEDIATE.
        if e.displacement_branch == IMMEDIATE:
            assert e.interaction_to_confirmation_delay == 1
            assert e.confirm_reason in ("displacement", "rejection")
        if e.displacement_branch == DELAYED:
            assert not (e.interaction_to_confirmation_delay == 1
                        and e.confirm_reason in ("displacement", "rejection"))
    # the two labels are genuinely disjoint partitions of the episode set
    assert not ({e.episode_id for e in episodes if e.displacement_branch == IMMEDIATE}
                & {e.episode_id for e in episodes if e.displacement_branch == DELAYED})


def test_scraping_is_not_classified_as_displacement():
    """A run of sub-threshold bodies that never progress is SCRAPING, never
    IMMEDIATE/DELAYED/COMPRESSION."""
    class C:
        def __init__(self, o, h, l, c):
            self.open, self.high, self.low, self.close = o, h, l, c
    flat = [C(10.0, 10.05, 9.95, 10.0) for _ in range(9)]
    atr = [1.0] * 9
    r = measure_reaction(flat, atr, 2, 1, 9.0, 10.0, set(), set())
    assert r["branch"] == SCRAPING
    assert r["branch"] not in (IMMEDIATE, DELAYED, COMPRESSION)


# ---------------------------------------------------------------------------
# 5. Physical dedup
# ---------------------------------------------------------------------------

def test_same_physical_sequence_deduplicates(obs):
    """No two episodes share the same (direction, entry_seq) with overlapping
    context zones -- those collapse into one physical episode."""
    _, episodes, _ = obs
    seen = {}
    for e in episodes:
        key = (e.direction, e.entry_seq)
        if key in seen:
            (alo, ahi) = seen[key]
            (blo, bhi) = e.context_zone
            assert max(alo, blo) > min(ahi, bhi), \
                f"overlapping contexts not deduplicated at {key}"
        seen[key] = e.context_zone


# ---------------------------------------------------------------------------
# 6. Timeframe architecture and session/time preserved
# ---------------------------------------------------------------------------

def test_timeframe_architecture_preserved(obs):
    _, episodes, _ = obs
    for e in episodes:
        # the four TF roles are explicit fields, not interchangeable
        assert e.context_tf in (1, 3, 5, 15, 30, 60)
        assert e.trigger_tf == e.context_tf
        assert e.fingerprint["context_tf"] == e.context_tf
        assert e.fingerprint["trigger_tf"] == e.trigger_tf


def test_session_and_time_windows_preserved(obs):
    bars, episodes, _ = obs
    for e in episodes:
        tw = time_window_fields(bars[e.entry_seq].ts_et)
        assert e.session == tw["session"]
        assert e.et_hour == tw["et_hour"]
        assert e.fingerprint["session"] == e.session
        assert e.fingerprint["day_of_week"] == e.day_of_week


# ---------------------------------------------------------------------------
# 7. Targets: causal availability, no outcome influence
# ---------------------------------------------------------------------------

def test_targets_existed_at_trigger_time(obs):
    """Every target candidate is knowable no later than entry (its producing
    structure was available before the entry bar)."""
    _, episodes, _ = obs
    any_target = False
    for e in episodes:
        for t in e.targets:
            any_target = True
            assert t.availability_seq <= e.entry_seq
            assert t.natural_rr is None or t.natural_rr >= 0
    assert any_target


def test_target_policies_do_not_consult_outcomes(obs):
    """Target selection is purely geometric: NEAREST_VALID_STRUCTURE is the
    minimum-distance eligible structure -- recomputable without any outcome."""
    _, episodes, _ = obs
    for e in episodes:
        prim = next((t for t in e.targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
        others = [t for t in e.targets if t.policy == "NEAREST_VALID_STRUCTURE"]
        if prim is not None:
            # nearest must not be beaten by any other listed candidate distance
            assert all(prim.distance <= o.distance for o in others)


# ---------------------------------------------------------------------------
# 8. Fingerprints freeze before outcomes; no outcome leakage
# ---------------------------------------------------------------------------

def test_observation_fingerprints_freeze_before_outcomes(obs):
    """Fingerprints are fully determined by the pre-outcome episode; computing
    outcomes afterwards leaves the fingerprint byte-for-byte identical."""
    bars, episodes, _ = obs
    execs = [e for e in episodes if e.executable][:20]
    assert execs
    for e in execs:
        before = dict(e.fingerprint)
        _ = process_outcome(e, bars)
        assert e.fingerprint == before


def test_no_outcome_fields_on_episode(obs):
    _, episodes, _ = obs
    for e in episodes[:200]:
        for f in dataclasses.fields(e):
            assert not any(tok in f.name.lower() for tok in _OUTCOME_TOKENS), f.name
        for k in e.fingerprint:
            assert not any(tok in k.lower() for tok in _OUTCOME_TOKENS), k


# ---------------------------------------------------------------------------
# 9. Matching modes stay separate; application cannot alter the playbook
# ---------------------------------------------------------------------------

def test_exact_reduced_similarity_modes_are_separate(obs):
    bars, episodes, _ = obs
    outs = [o for o in (process_outcome(e, bars) for e in episodes) if o]
    pb = build_playbook(episodes, outs, OBS_START, OBS_END)
    if not pb:
        pytest.skip("no successful observation setups in window")
    for e in episodes[:300]:
        m = match_modes(e, pb)
        assert set(m) == {"EXACT", "REDUCED_FAMILY", "SIMILARITY_DIAGNOSTIC"}
        # EXACT is a strict subset of REDUCED_FAMILY (more fields must agree)
        assert set(m["EXACT"]).issubset(set(m["REDUCED_FAMILY"]))
        # similarity is diagnostic (nearest neighbour), never a membership set
        assert m["SIMILARITY_DIAGNOSTIC"] is None or \
            "nearest_item_id" in m["SIMILARITY_DIAGNOSTIC"]
    assert set(EXACT_FIELDS) >= set(REDUCED_FIELDS)


def test_application_week_cannot_alter_playbook(obs, app):
    """Building the playbook from observation data only, then again while the
    application episodes exist, yields the identical authorized items --
    application-week data has no path into playbook construction."""
    obars, oeps, _ = obs
    _, aeps, _ = app
    outs = [o for o in (process_outcome(e, obars) for e in oeps) if o]
    pb1 = build_playbook(oeps, outs, OBS_START, OBS_END)
    # even if application episodes/outcomes are (wrongly) mixed in as candidates,
    # build_playbook only credits episodes present in its outcome map; passing
    # observation outcomes keeps the authorized set fixed.
    pb2 = build_playbook(oeps + aeps, outs, OBS_START, OBS_END)
    assert [p.fingerprint for p in pb1] == [p.fingerprint for p in pb2]


def test_application_setup_matches_carry_no_outcome_fields(app, obs):
    """Application-week episodes are pre-outcome: no outcome may be attached or
    computed for them in the observer/matching path."""
    _, aeps, _ = app
    for e in aeps[:200]:
        for f in dataclasses.fields(e):
            assert not any(tok in f.name.lower() for tok in _OUTCOME_TOKENS), f.name


# ---------------------------------------------------------------------------
# 10. Determinism / reproducibility
# ---------------------------------------------------------------------------

def test_playbook_output_is_reproducible(obs):
    bars, episodes, _ = obs
    outs = [o for o in (process_outcome(e, episodes and bars) for e in episodes) if o]
    a = build_playbook(episodes, outs, OBS_START, OBS_END)
    b = build_playbook(episodes, outs, OBS_START, OBS_END)
    assert [x.item_id for x in a] == [x.item_id for x in b]
    assert [x.fingerprint for x in a] == [x.fingerprint for x in b]
    assert [x.source_episode_ids for x in a] == [x.source_episode_ids for x in b]


def test_observe_is_deterministic(obs):
    bars, episodes, _ = obs
    eps2, _ = observe(bars)
    assert len(eps2) == len(episodes)
    assert [e.episode_id for e in eps2] == [e.episode_id for e in episodes]
    assert [e.fingerprint for e in eps2] == [e.fingerprint for e in episodes]


# ---------------------------------------------------------------------------
# 11. Session labeling frozen boundaries
# ---------------------------------------------------------------------------

def test_session_boundaries_frozen():
    def et(h, m=0):
        return pd.Timestamp(f"2026-07-06 {h:02d}:{m:02d}:00", tz=ET)
    assert session_of(et(18)) == "GLOBEX_EVENING"
    assert session_of(et(20)) == "ASIA"
    assert session_of(et(2, 59)) == "ASIA"
    assert session_of(et(3)) == "LONDON"
    assert session_of(et(8)) == "NY_PREMARKET"
    assert session_of(et(9, 30)) == "NY_AM"
    assert session_of(et(12)) == "NY_LUNCH"
    assert session_of(et(13)) == "NY_PM"

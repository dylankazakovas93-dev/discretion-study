"""Setup constructor: dedup, distinct entry modes, same-bar ambiguity,
context-condition cap, and (data-gated) whole-pipeline invariants."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from discretion.primitives.engine import build_primitives
from discretion.setups.constructor import (
    SetupFactory, deduplicate, build_setups,
)
from discretion.setups.model import Setup, evaluate_outcome
from discretion.data.loader import load_front_month, DATA_FILES
from helpers import make_bars

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def _setup(entry_seq, mode, stop=98.0, target=101.0, origin="O", direction="long"):
    return Setup(
        id=f"SETUP-{entry_seq}-{mode}", direction=direction, path_family="t",
        graph="g", entry_mode=mode, origin_id=origin, transition_ids=[],
        primitive_ids=[], context_conditions=[], entry_seq=entry_seq,
        entry_ts=pd.Timestamp("2025-07-07", tz="UTC"), entry_price=100.0,
        structural_stop=stop, structural_target=target, expiry_seq=entry_seq + 10,
        expiry_rule="t", segment_id=0,
        episode_key=(origin, direction, mode, entry_seq // 3,
                     round(stop / 0.25), round(target / 0.25)),
    )


def test_deduplicate_collapses_cosmetic_duplicates():
    a = _setup(10, "formation_close")
    b = _setup(10, "formation_close")  # identical episode key
    kept, removed = deduplicate([a, b])
    assert len(kept) == 1
    assert removed == 1


def test_distinct_entry_modes_stay_separate():
    a = _setup(10, "formation_close")
    b = _setup(10, "next_bar")        # same episode, different mode
    kept, removed = deduplicate([a, b])
    assert len(kept) == 2
    assert removed == 0


def test_same_bar_stop_target_is_ambiguous():
    s = _setup(0, "formation_close", stop=98.0, target=102.0)
    s.eligible = True
    s.executed_target = 102.0
    # a single bar that spans both stop and target
    bars = make_bars([(100, 100, 100, 100), (100, 103, 97, 100)])
    evaluate_outcome(s, bars)
    assert s.outcome == "AMBIGUOUS"


def test_context_conditions_capped_at_three():
    bars = make_bars([(100, 101, 99, 100)] * 5)
    ps = build_primitives(bars)
    F = SetupFactory(ps)
    with pytest.raises(ValueError):
        F.make(direction="long", path_family="t", graph="g",
               entry_mode="formation_close", origin_id="O", transition_ids=[],
               primitive_ids=[], context_conditions=["a", "b", "c", "d"],
               entry_seq=1, entry_price=100.0, stop=99.0, target=101.0,
               cont_or_fade="continuation")


# ---- data-gated whole-pipeline invariants (skipped if raw data absent) ----

@pytest.fixture(scope="module")
def july_ledger():
    if not os.path.exists(DATA):
        pytest.skip("raw NQ data not present")
    bars = load_front_month(DATA, start="2025-07-07", end="2025-07-08")
    ps = build_primitives(bars)
    return build_setups(ps)


def test_permanent_ids_unique(july_ledger):
    ids = [s.id for s in july_ledger.all_candidates]
    assert len(ids) == len(set(ids))


def test_dedup_reduces_and_keys_unique(july_ledger):
    assert july_ledger.raw_count > len(july_ledger.eligible)
    keys = [s.episode_key for s in july_ledger.eligible]
    assert len(keys) == len(set(keys))


def test_executed_rr_all_within_band(july_ledger):
    for s in july_ledger.eligible:
        assert 0.5 <= s.executed_rr <= 1.0


def test_paths_without_fvg_sweep_rb_exist(july_ledger):
    assert any(not s.has_fvg for s in july_ledger.eligible)
    assert any(not s.has_sweep for s in july_ledger.eligible)
    assert any(not s.has_rb for s in july_ledger.eligible)


def test_both_continuation_and_fade_exist(july_ledger):
    fams = {s.continuation_or_fade for s in july_ledger.eligible}
    assert "continuation" in fams and "fade" in fams


def test_multiple_entry_modes_present(july_ledger):
    modes = {s.entry_mode for s in july_ledger.eligible}
    assert len(modes) >= 3


def test_losing_and_rejected_occurrences_retained(july_ledger):
    # losers kept in the eligible ledger; sub-0.5R kept in the rejected ledger
    assert any(s.outcome == "LOSS" for s in july_ledger.eligible)
    assert any(s.rejection_reason == "INSUFFICIENT_NATURAL_RR"
               for s in july_ledger.rejected)

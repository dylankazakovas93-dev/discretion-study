"""Frozen reward-to-risk policy: the crux rule, tested exhaustively."""

from __future__ import annotations

import copy

import pandas as pd

from discretion.setups.model import (
    Setup, apply_rr_policy, evaluate_outcome, MIN_RR, CAP_RR,
)
from helpers import make_bars


def _mk(direction, entry, stop, target, entry_seq=0):
    return Setup(
        id="SETUP-000001", direction=direction, path_family="test",
        graph="g", entry_mode="formation_close", origin_id="X",
        transition_ids=[], primitive_ids=[], context_conditions=[],
        entry_seq=entry_seq, entry_ts=pd.Timestamp("2025-07-07", tz="UTC"),
        entry_price=entry, structural_stop=stop, structural_target=target,
        expiry_seq=entry_seq + 100, expiry_rule="test", segment_id=0,
    )


def test_natural_rr_calculation():
    s = _mk("long", 100.0, 98.0, 104.0)  # risk 2, reward 4 -> rr 2.0
    apply_rr_policy(s)
    assert s.natural_rr == 2.0


def test_cap_to_exactly_1r_when_rr_ge_1_long():
    s = _mk("long", 100.0, 98.0, 110.0)  # rr 5 -> capped
    apply_rr_policy(s)
    assert s.eligible
    assert s.executed_rr == CAP_RR
    assert s.executed_target == 102.0  # entry + risk
    # natural/structural target retained separately for diagnostics
    assert s.structural_target == 110.0


def test_cap_to_exactly_1r_when_rr_ge_1_short():
    s = _mk("short", 100.0, 102.0, 90.0)  # risk 2, reward 10 -> capped
    apply_rr_policy(s)
    assert s.executed_rr == CAP_RR
    assert s.executed_target == 98.0  # entry - risk


def test_retain_natural_target_between_half_and_1r():
    s = _mk("long", 100.0, 98.0, 101.5)  # risk 2, reward 1.5 -> rr 0.75
    apply_rr_policy(s)
    assert s.eligible
    assert abs(s.executed_rr - 0.75) < 1e-9
    assert s.executed_target == 101.5  # natural target used as-is, not pushed to 1R


def test_reject_below_half_r():
    s = _mk("long", 100.0, 98.0, 100.9)  # risk 2, reward 0.9 -> rr 0.45
    apply_rr_policy(s)
    assert not s.eligible
    assert s.rejected
    assert s.rejection_reason == "INSUFFICIENT_NATURAL_RR"
    assert s.executed_target == 0.0  # never given an executable target


def test_boundary_exactly_half_r_is_eligible():
    s = _mk("long", 100.0, 100.0 - 2.0, 100.0 + 1.0)  # rr exactly 0.5
    apply_rr_policy(s)
    assert s.natural_rr == MIN_RR
    assert s.eligible
    assert s.executed_rr == 0.5


def test_target_wrong_side_rejected():
    s = _mk("long", 100.0, 98.0, 99.0)  # target below entry for a long
    apply_rr_policy(s)
    assert s.rejected
    assert s.rejection_reason == "TARGET_WRONG_SIDE"


def test_stop_cannot_be_moved_to_manufacture_eligibility():
    # A sub-0.5R setup stays rejected; the policy never adjusts the stop.
    s = _mk("long", 100.0, 90.0, 102.0)  # risk 10, reward 2 -> rr 0.2
    apply_rr_policy(s)
    assert s.rejected
    assert s.structural_stop == 90.0  # untouched


def test_target_not_moved_after_outcome():
    # Freeze, snapshot executed target, evaluate outcome, confirm no mutation.
    s = _mk("long", 100.0, 98.0, 110.0)
    apply_rr_policy(s)
    frozen_target = s.executed_target
    frozen_stop = s.structural_stop
    bars = make_bars([(100, 103, 99, 102)] * 5)  # would hit 102 target
    s.eligible = True
    evaluate_outcome(s, bars)
    assert s.executed_target == frozen_target
    assert s.structural_stop == frozen_stop


def test_all_executed_rr_within_half_to_one():
    for tgt in (101.0, 101.5, 101.9, 105.0, 110.0):
        s = _mk("long", 100.0, 98.0, tgt)
        apply_rr_policy(s)
        if s.eligible:
            assert MIN_RR <= s.executed_rr <= CAP_RR

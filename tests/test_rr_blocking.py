"""Commit 6 blocking tests for the frozen RR policy — exact boundary cases."""

from __future__ import annotations

import pandas as pd

from discretion.setups.model import Setup, apply_rr_policy, evaluate_outcome
from helpers import make_bars


def _mk(direction, entry, stop, target):
    return Setup(
        id="S-1", direction=direction, path_family="test", graph="g",
        entry_mode="formation_close", origin_id="X", transition_ids=[],
        primitive_ids=[], context_conditions=[], entry_seq=0,
        entry_ts=pd.Timestamp("2025-07-07", tz="UTC"), entry_price=entry,
        structural_stop=stop, structural_target=target, expiry_seq=100,
        expiry_rule="t", segment_id=0)


def test_exactly_half_r_accepted():
    s = _mk("long", 100.0, 98.0, 101.0)   # rr = 0.5
    apply_rr_policy(s)
    assert s.eligible and abs(s.executed_rr - 0.5) < 1e-9


def test_just_below_half_r_rejected():
    s = _mk("long", 100.0, 98.0, 100.9998)  # rr = 0.4999
    apply_rr_policy(s)
    assert s.rejected and s.rejection_reason == "INSUFFICIENT_NATURAL_RR"
    assert s.executed_target == 0.0


def test_three_quarter_r_retains_natural_target():
    s = _mk("long", 100.0, 98.0, 101.5)   # rr = 0.75
    apply_rr_policy(s)
    assert s.eligible and s.executed_target == 101.5


def test_exactly_one_r_stays_one_r():
    s = _mk("long", 100.0, 98.0, 102.0)   # rr = 1.0
    apply_rr_policy(s)
    assert s.eligible and s.executed_rr == 1.0 and s.executed_target == 102.0


def test_just_above_one_r_capped():
    s = _mk("long", 100.0, 98.0, 102.02)  # rr = 1.01
    apply_rr_policy(s)
    assert s.executed_rr == 1.0 and s.executed_target == 102.0
    assert s.structural_target == 102.02   # natural retained


def test_three_r_accepted_and_capped_not_rejected():
    s = _mk("long", 100.0, 98.0, 106.0)   # rr = 3.0
    apply_rr_policy(s)
    assert s.eligible and not s.rejected
    assert s.executed_rr == 1.0 and s.executed_target == 102.0
    assert s.structural_target == 106.0   # farther objective retained


def test_natural_target_stored_after_cap():
    s = _mk("short", 100.0, 102.0, 88.0)  # rr = 6.0 short
    apply_rr_policy(s)
    assert s.executed_target == 98.0 and s.structural_target == 88.0


def test_stop_never_moves_when_rr_low():
    s = _mk("long", 100.0, 90.0, 101.0)   # risk 10, reward 1 -> 0.1R
    apply_rr_policy(s)
    assert s.rejected and s.structural_stop == 90.0


def test_wrong_side_stop_rejected():
    s = _mk("long", 100.0, 101.0, 104.0)  # stop above entry for a long
    apply_rr_policy(s)
    assert s.rejected and s.rejection_reason == "STOP_WRONG_SIDE"


def test_wrong_side_target_rejected():
    s = _mk("short", 100.0, 102.0, 105.0)  # target above entry for a short
    apply_rr_policy(s)
    assert s.rejected and s.rejection_reason == "TARGET_WRONG_SIDE"


def test_outcome_cannot_affect_frozen_numbers():
    s = _mk("long", 100.0, 98.0, 106.0)
    apply_rr_policy(s)
    froze = (s.structural_stop, s.structural_target, s.executed_target, s.executed_rr)
    bars = make_bars([(100, 103, 97, 102)] * 6)   # would hit both target and stop
    evaluate_outcome(s, bars)
    assert (s.structural_stop, s.structural_target, s.executed_target,
            s.executed_rr) == froze

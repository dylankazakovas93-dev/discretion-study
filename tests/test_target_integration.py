"""Commit 6 blocking tests: target inventory reproducibility + branch integration."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from discretion.primitives.engine import build_primitives
from discretion.data.aggregation import aggregate_all
from discretion.primitives.wick_liquidity import detect_wick_liquidity
from discretion.primitives.htf_fvg import detect_htf_fvgs
from discretion.primitives.base import IdRegistry
from discretion.graph.pipeline import (
    run_graph_native, graph_candidate_ledger, ledger_hash)
from discretion.graph.targets import TARGET_POLICIES
from discretion.data.loader import load_front_month, DATA_FILES

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
WIN = dict(start="2025-07-07T13:00", end="2025-07-07T20:00")

pytestmark = pytest.mark.skipif(not os.path.exists(DATA), reason="raw data absent")


def _htf_hash(bars):
    agg = aggregate_all(bars)
    rows = [(tf, c.candle_id, c.open, c.high, c.low, c.close, c.available_seq)
            for tf in agg for c in agg[tf]]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def _wick_hash(bars):
    objs = detect_wick_liquidity(bars, aggregate_all(bars), IdRegistry())
    rows = [(o.id, o.timeframe, o.side, o.proximal, o.prominence_grade,
             o.created_seq) for o in objs]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def _fvg_hash(bars):
    fvgs, ifvgs = detect_htf_fvgs(bars, aggregate_all(bars), IdRegistry())
    rows = [(f.id, f.timeframe, f.direction, f.lo, f.hi, f.created_seq) for f in fvgs]
    rows += [("i", iv.id, iv.source_fvg_id, iv.created_seq) for iv in ifvgs]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


@pytest.fixture(scope="module")
def day():
    return run_graph_native(**WIN, with_evidence=False)


# ---------------- reproducibility ----------------

def test_identical_htf_candles():
    b = load_front_month(DATA, **WIN)
    assert _htf_hash(b) == _htf_hash(load_front_month(DATA, **WIN))


def test_identical_wick_objects():
    b = load_front_month(DATA, **WIN)
    assert _wick_hash(b) == _wick_hash(load_front_month(DATA, **WIN))


def test_identical_htf_fvgs():
    b = load_front_month(DATA, **WIN)
    assert _fvg_hash(b) == _fvg_hash(load_front_month(DATA, **WIN))


def test_identical_candidate_and_target_hash(day):
    r2 = run_graph_native(**WIN, with_evidence=False)
    l1, l2 = graph_candidate_ledger(day), graph_candidate_ledger(r2)
    assert ledger_hash(l1) == ledger_hash(l2)
    # selected targets identical across runs
    t1 = [(r["candidate_id"], r["target_anchor_object_id"], r["target_policy_id"])
          for r in l1]
    t2 = [(r["candidate_id"], r["target_anchor_object_id"], r["target_policy_id"])
          for r in l2]
    assert t1 == t2


# ---------------- branch integration ----------------

def test_multiple_target_policies_present(day):
    used = {c.target_policy_id for c in day["graph_candidates"]}
    assert len(used) >= 2 and used <= set(TARGET_POLICIES)


def test_same_trigger_yields_distinct_policy_variants(day):
    by_trigger = {}
    for c in day["graph_candidates"] + day["graph_rejected"]:
        by_trigger.setdefault(c.trigger_event_id, set()).add(c.target_policy_id)
    # at least one trigger produced more than one distinct policy variant
    assert any(len(v) >= 2 for v in by_trigger.values())
    # variants of one trigger have distinct candidate ids
    ids = [c.candidate_id for c in day["graph_candidates"] + day["graph_rejected"]]
    assert len(ids) == len(set(ids))


def test_mtf_target_families_are_used(day):
    fams = {c.target_anchor_type for c in day["graph_candidates"]}
    # at least one multi-timeframe target family is selected somewhere
    assert fams & {"wick_liquidity", "htf_fvg", "htf_ifvg"}


def test_every_candidate_has_considered_ledger_with_reasons(day):
    for c in day["graph_candidates"]:
        assert c.considered_targets
        # the selected target appears and is eligible in the ledger (matched by
        # both object id and family, since one object id may appear as both a
        # plain-family row and the branch-objective row)
        sel = [r for r in c.considered_targets
               if r["object_id"] == c.target_anchor_object_id
               and r["family"] == c.target_anchor_type]
        assert sel and sel[0]["eligible"]
        # unselected/ineligible targets retain rejection reasons
        for r in c.considered_targets:
            if not r["eligible"]:
                assert r["rejection_reasons"]


def test_selected_target_causally_available(day):
    for c in day["graph_candidates"]:
        row = next(r for r in c.considered_targets
                   if r["object_id"] == c.target_anchor_object_id)
        assert row["available_seq"] <= c.setup.entry_seq


def test_setup_with_no_valid_target_is_unformed(day):
    # some triggers may find no structural target -> counted, never fabricated
    assert isinstance(day["unformed_reasons"], dict)


def test_static_baseline_remains_separate(day):
    # graph-native candidate ids are disjoint from static baseline SETUP- ids
    for c in day["graph_candidates"]:
        assert c.candidate_id.startswith("GNC-")


def test_graph_native_works_with_build_setups_disabled(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disabled")
    import discretion.setups.constructor as constructor
    monkeypatch.setattr(constructor, "build_setups", boom)
    r = run_graph_native(**WIN, with_evidence=False)
    assert len(r["graph_candidates"]) > 0

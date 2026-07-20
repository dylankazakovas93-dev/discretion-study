"""Equivalence test for the staged (Stage A/B) finalization split in
scripts/finalize_stage_a.py / finalize_stage_b.py.

The split exists because a single process holding both the full branch_engine
graph and all 1.193M materialized candidates OOM-killed a ~15.5h run at the
final checkpoint-write step. This proves the split doesn't change any
candidate-facing output: scoring a candidate universe through a bars-only
engine shim (Stage A's approach -- no branches/log/registry, matching what
Stage A actually has available) produces byte-identical evidence/
qualification to scoring the same universe through the real, full result
dict, and that selection functions restricted to a window-scoped candidate
list (Stage B's approach) select the same example candidate_ids as running
them against the unrestricted full-process result.
"""
from __future__ import annotations

import os

import pytest

from discretion.primitives.engine import build_primitives
from discretion.graph.branch_engine import BranchEngine
from discretion.graph.materializer import materialize_all
from discretion.graph import review_atlas as ra
from discretion.data.loader import load_front_month, DATA_FILES
from discretion.recognizer.evidence import run_indexed_one_trigger_one_policy

DATA = os.path.join("data", "raw", DATA_FILES["2025-2026"])
# A few real sessions -- enough prior history for evidence to have a nonempty
# comparable pool, small enough to run quickly.
WIN = dict(start="2026-07-06T22:00:00", end="2026-07-10T22:00:00")


class _BarsOnlyPs:
    def __init__(self, bars):
        self.bars = bars


class _BarsOnlyEngine:
    def __init__(self, bars):
        self.ps = _BarsOnlyPs(bars)


@pytest.fixture(scope="module")
def full_result():
    if not os.path.exists(DATA):
        pytest.skip("raw data absent")
    bars = load_front_month(DATA, **WIN)
    ps = build_primitives(bars)
    br = BranchEngine(ps).run()
    result = materialize_all(br)
    result["candidates"] = result["graph_candidates"]
    return result, bars


def _last_session_window(bars, ra_mod):
    dates = sorted({ra_mod.true_session_date(b.ts_et) for b in bars})
    last = dates[-1]
    import pandas as pd
    start_et = pd.Timestamp(f"{last} 18:00:00", tz=ra_mod.ET) - pd.Timedelta(days=1)
    end_et = pd.Timestamp(f"{last} 17:59:59", tz=ra_mod.ET)
    return start_et, end_et


def test_bars_only_shim_scores_identically_to_full_result(full_result):
    result, bars = full_result
    start_et, end_et = _last_session_window(bars, ra)

    cands_in_week = [c for c in result["graph_candidates"]
                     if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), start_et, end_et)]
    assert cands_in_week, "smoke window produced no review-window candidates to compare"

    # Reference: score via the real, full result (as the original single-
    # process pipeline does).
    ref_result = dict(result)
    ref_result["candidates"] = list(result["graph_candidates"])
    ref_result, ref_scored = run_indexed_one_trigger_one_policy(
        ref_result, restrict_to=cands_in_week)
    ref_by_id = {c.candidate_id: (c.qualification, c.evidence) for c in ref_scored}

    # Stage A shim: same candidates, but "engine" only exposes bars (no ps/
    # registry/wicks/branches/log) -- exactly what finalize_stage_a.py builds.
    shim_result = {
        "graph_candidates": list(result["graph_candidates"]),
        "graph_rejected": list(result["graph_rejected"]),
        "candidates": list(result["graph_candidates"]),
        "engine": _BarsOnlyEngine(bars),
    }
    shim_cands_in_week = [c for c in shim_result["graph_candidates"]
                          if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET),
                                         start_et, end_et)]
    shim_result, shim_scored = run_indexed_one_trigger_one_policy(
        shim_result, restrict_to=shim_cands_in_week)
    shim_by_id = {c.candidate_id: (c.qualification, c.evidence) for c in shim_scored}

    assert ref_by_id.keys() == shim_by_id.keys()
    for cid in ref_by_id:
        ref_qual, ref_ev = ref_by_id[cid]
        shim_qual, shim_ev = shim_by_id[cid]
        assert ref_qual == shim_qual
        assert ref_ev == shim_ev


def test_window_scoped_selection_matches_full_process_selection(full_result):
    result, bars = full_result
    start_et, end_et = _last_session_window(bars, ra)

    cands_in_week = [c for c in result["graph_candidates"]
                     if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), start_et, end_et)]
    rej_in_week = [c for c in result["graph_rejected"]
                  if ra.in_window(c.setup.entry_ts.tz_convert(ra.ET), start_et, end_et)]
    ref_result = dict(result)
    ref_result["candidates"] = list(result["graph_candidates"])
    run_indexed_one_trigger_one_policy(ref_result, restrict_to=cands_in_week)

    # Stage B's approach: call the selection functions with graph_candidates/
    # graph_rejected already reduced to the review-week subset (as
    # finalize_stage_b.py does with the handed-off cands_in_week/rej_in_week),
    # against the same full branches/log/ps.
    windowed_result = dict(result)
    windowed_result["graph_candidates"] = cands_in_week
    windowed_result["graph_rejected"] = rej_in_week

    ref_structural = ra.select_structural_examples(result, None, start_et, end_et)
    windowed_structural = ra.select_structural_examples(windowed_result, None,
                                                         start_et, end_et)

    def _ids(d):
        out = {}
        for k, v in d.items():
            if k == "rejected_by_reason":
                out[k] = {r: (c.candidate_id if hasattr(c, "candidate_id") else c.branch_id)
                         for r, c in v.items()}
            else:
                out[k] = [c.candidate_id if hasattr(c, "candidate_id") else c.branch_id
                          for c in v]
        return out

    assert _ids(ref_structural) == _ids(windowed_structural)

    ref_qual = ra.select_qualification_examples(cands_in_week)
    windowed_qual = ra.select_qualification_examples(cands_in_week)
    assert ({k: [c.candidate_id for c in v] for k, v in ref_qual.items()}
            == {k: [c.candidate_id for c in v] for k, v in windowed_qual.items()})

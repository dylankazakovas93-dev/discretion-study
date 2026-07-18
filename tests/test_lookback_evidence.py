"""Stage 8/9/10 repair: fixed-lookback stats, one-trigger/one-policy dedup,
and the indexed session-partitioned evidence engine (synthetic-data unit
tests; real-data equivalence lives in test_review_atlas.py to avoid a second
expensive pipeline run)."""

from __future__ import annotations

from types import SimpleNamespace

from discretion.recognizer.evidence import (
    Comp, HORIZONS, _subset_stats, IndexedComparablePool, build_snapshot_indexed,
    build_snapshot, one_trigger_one_policy, MIN_SUFFICIENT_SESSIONS,
)


def _feat(**kw):
    f = {"continuation_or_fade": "continuation", "entry_mode": "first_touch",
         "origin_family": "fvg", "path_family": "fvg_fill",
         "target_policy_id": "NEAREST_VALID_STRUCTURE",
         "minutes_from_0930": 30, "dist_to_stop_atr": 0.8, "natural_rr": 0.9,
         "origin_age_bars": 3, "zone_width_atr": 0.7, "displacement_body_atr": None,
         "path_body_ratio": None, "favorable_close": None, "session": "rth",
         "target_family": "swing_high", "level_family": None,
         "nearest_vwap_band": "+1.618", "has_fvg": True, "has_ifvg": False,
         "has_rb": False, "has_sweep": False, "vwap_side": 1}
    f.update(kw)
    return f


def _comp(ord_, outcome, r, exact="G", reduced="RG", feat=None):
    return Comp(completion_ord=ord_, outcome=outcome, realized_r=r,
                executed_rr=(r if r and r > 0 else 1.0), exact=exact,
                reduced=reduced, features=feat or _feat())


# ---------------- Stage 8: extended fixed-lookback fields ----------------

def test_horizons_are_the_frozen_seven():
    assert HORIZONS == [1, 3, 5, 10, 20, 40, "ALL"]


def test_subset_stats_reports_session_bounds_and_dominance():
    subset = [_comp(0, "WIN", 1.0), _comp(0, "WIN", 1.0), _comp(5, "LOSS", -1.0)]
    stats = _subset_stats(subset, current_ord=10, horizon="ALL")
    assert stats["session_bounds"] == [0, 5]
    assert stats["top_session_share"] == round(2 / 3, 4)   # session 0 has 2/3
    assert stats["single_session_dominated"] is True        # >0.5 share


def test_subset_stats_sufficiency_flag():
    few = _subset_stats([_comp(0, "WIN", 1.0)], current_ord=10, horizon="ALL")
    assert few["sufficient_to_interpret"] is False   # 1 session < MIN_SUFFICIENT_SESSIONS
    many = _subset_stats([_comp(i, "WIN", 1.0) for i in range(MIN_SUFFICIENT_SESSIONS)],
                         current_ord=10, horizon="ALL")
    assert many["sufficient_to_interpret"] is True


def test_subset_stats_standard_error_and_avg_winner_r():
    subset = [_comp(0, "WIN", 1.0), _comp(1, "WIN", 2.0), _comp(2, "LOSS", -1.0)]
    stats = _subset_stats(subset, current_ord=10, horizon="ALL")
    assert stats["standard_error"] is not None
    assert stats["avg_executed_winner_R"] == 1.5   # mean of the two winners' executed_rr


def test_subset_stats_empty_has_null_se_and_no_dominance():
    stats = _subset_stats([], current_ord=10, horizon="ALL")
    assert stats["standard_error"] is None
    assert stats["avg_executed_winner_R"] is None
    assert stats["session_bounds"] == [None, None]
    assert stats["single_session_dominated"] is False


# ---------------- Stage 10: one-trigger/one-policy dedup ----------------

def _cand(cid, trig, policy, entry_seq=0):
    setup = SimpleNamespace(entry_seq=entry_seq, id=cid)
    return SimpleNamespace(candidate_id=cid, trigger_event_id=trig,
                           target_policy_id=policy, setup=setup)


def test_one_trigger_one_policy_keeps_min_candidate_id():
    a = _cand("GNC-000003", "EVT-1", "NEAREST_VALID_STRUCTURE")
    b = _cand("GNC-000001", "EVT-1", "NEAREST_VALID_STRUCTURE")   # dup row, same key
    c = _cand("GNC-000002", "EVT-1", "NEAREST_PROMINENT_WICK")    # distinct policy
    out = one_trigger_one_policy([a, b, c])
    ids = {x.candidate_id for x in out}
    assert ids == {"GNC-000001", "GNC-000002"}   # min-id rep for (EVT-1,NVS); NPW kept distinct


def test_distinct_target_policies_never_collapsed():
    variants = [_cand(f"GNC-{i:06d}", "EVT-1", p, entry_seq=0)
               for i, p in enumerate(("BRANCH_SEMANTIC", "NEAREST_VALID_STRUCTURE",
                                       "NEAREST_PROMINENT_WICK", "NEAREST_OPPOSING_HTF_FVG"))]
    out = one_trigger_one_policy(variants)
    assert len(out) == 4   # all four policies remain independent observations


def test_dedup_pure_does_not_mutate_input():
    a = _cand("GNC-000001", "EVT-1", "NEAREST_VALID_STRUCTURE")
    before = a.candidate_id
    one_trigger_one_policy([a, a])
    assert a.candidate_id == before


# ---------------- Stage 10: indexed vs reference equivalence ----------------

def test_indexed_snapshot_matches_reference_snapshot():
    pool_list = [_comp(0, "WIN", 1.0), _comp(1, "LOSS", -1.0), _comp(2, "WIN", 0.8),
                _comp(3, "AMBIGUOUS", None), _comp(1, "WIN", 1.2, exact="G2", reduced="RG2")]
    indexed = IndexedComparablePool()
    for c in pool_list:
        indexed.add(c)

    feats = _feat()
    ref = build_snapshot(feats, "G", "RG", pool_list, current_ord=10)
    got = build_snapshot_indexed(feats, "G", "RG", indexed, current_ord=10)
    assert ref == got


def test_indexed_partition_isolates_incompatible_features():
    compat = _comp(0, "WIN", 1.0, exact="G", reduced="RG")
    incompat = _comp(0, "WIN", 5.0, exact="OTHER",
                     reduced="RG", feat=_feat(path_family="rb_reaction"))
    indexed = IndexedComparablePool()
    indexed.add(compat)
    indexed.add(incompat)
    snap = build_snapshot_indexed(_feat(), "G", "RG", indexed, current_ord=10)
    # the incompatible-partition comp must never enter the NN/global-via-partition
    # subsets that feed this candidate's own tiers
    assert snap["levels"]["reduced"]["ALL"]["occurrences"] == 1

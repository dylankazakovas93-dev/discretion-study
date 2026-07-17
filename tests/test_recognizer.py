"""Prior-only evidence engine, hierarchical shrinkage, and qualification gate."""

from __future__ import annotations

from discretion.recognizer.evidence import (
    Comp, build_snapshot, _shrink, K_SHRINK,
)
from discretion.recognizer.similarity import hard_compatible, gower, numeric_ranges
from discretion.recognizer.gate import (
    qualify, gate_reasons, GatePolicy, QUALIFIED_PENDING_TRIGGER,
    RECORDED_NOT_ACTIVATED,
)


def _feat(cf="continuation", mode="first_touch", fam="fvg", **kw):
    f = {
        "continuation_or_fade": cf, "entry_mode": mode, "origin_family": fam,
        "minutes_from_0930": 30, "dist_to_stop_atr": 0.8, "natural_rr": 0.9,
        "origin_age_bars": 3, "zone_width_atr": 0.7, "displacement_body_atr": None,
        "path_body_ratio": None, "favorable_close": None, "session": "rth",
        "target_family": "swing_high", "level_family": None,
        "nearest_vwap_band": "+1.618", "has_fvg": True, "has_ifvg": False,
        "has_rb": False, "has_sweep": False, "vwap_side": 1,
    }
    f.update(kw)
    return f


def _comp(ord_, outcome, r, exact="G", reduced="RG", feat=None):
    return Comp(completion_ord=ord_, outcome=outcome, realized_r=r,
                executed_rr=(r if r and r > 0 else 1.0), exact=exact,
                reduced=reduced, features=feat or _feat())


# ---- shrinkage ----

def test_shrink_formula():
    est, w = _shrink(1.0, K_SHRINK, 0.0)  # n == K -> w = 0.5
    assert abs(w - 0.5) < 1e-9
    assert abs(est - 0.5) < 1e-9


def test_sparse_evidence_shrinks_toward_prior():
    est_small, w_small = _shrink(1.0, 1, 0.0)   # n=1 -> weight 1/6
    est_large, w_large = _shrink(1.0, 100, 0.0)  # n=100 -> weight ~1
    assert w_small < w_large
    assert est_small < est_large  # sparse estimate pulled toward the 0.0 prior


# ---- similarity ----

def test_hard_incompatible_continuation_vs_fade():
    assert not hard_compatible(_feat(cf="continuation"), _feat(cf="fade"))
    assert not hard_compatible(_feat(mode="formation_close"), _feat(mode="retest"))
    assert hard_compatible(_feat(), _feat())


def test_gower_prior_only_ranges():
    pool = [_feat(minutes_from_0930=0), _feat(minutes_from_0930=100)]
    ranges = numeric_ranges(pool)
    d_same = gower(_feat(minutes_from_0930=0), _feat(minutes_from_0930=0), ranges)
    d_far = gower(_feat(minutes_from_0930=0), _feat(minutes_from_0930=100), ranges)
    assert d_same < d_far


# ---- snapshot: prior-only, exclusions, hierarchy ----

def test_snapshot_uses_only_prior_completed():
    fa = _feat()
    pool = [_comp(0, "WIN", 1.0), _comp(1, "LOSS", -1.0), _comp(2, "WIN", 1.0)]
    snap = build_snapshot(fa, "G", "RG", pool, current_ord=5)
    ex = snap["levels"]["exact"]["ALL"]
    assert ex["occurrences"] == 3
    assert ex["wins"] == 2 and ex["losses"] == 1


def test_snapshot_hierarchy_weight_reported_and_bounded():
    fa = _feat()
    pool = [_comp(i, "WIN", 1.0) for i in range(4)]  # exact ess=4
    snap = build_snapshot(fa, "G", "RG", pool, current_ord=5)
    sh = snap["shrinkage"]
    assert 0 <= sh["exact"]["weight"] <= 1
    # weight = n/(n+K) = 4/9 (stored rounded to 4 dp)
    assert abs(sh["exact"]["weight"] - 4 / 9) < 1e-3
    # broad prior cannot dominate invisibly: its weight is stored
    assert "weight" in sh["nn"] and "weight" in sh["reduced"]


def test_empty_pool_yields_zero_sample():
    snap = build_snapshot(_feat(), "G", "RG", [], current_ord=5)
    assert snap["summary"]["effective_sample"] == 0
    assert qualify(snap) == RECORDED_NOT_ACTIVATED


def test_ambiguous_not_counted_as_win_or_loss():
    fa = _feat()
    pool = [_comp(0, "AMBIGUOUS", None), _comp(1, "EXPIRED", None)]
    snap = build_snapshot(fa, "G", "RG", pool, current_ord=5)
    ex = snap["levels"]["exact"]["ALL"]
    assert ex["wins"] == 0 and ex["losses"] == 0
    assert ex["effective_sample"] == 0  # no resolved W/L sessions


def test_snapshot_is_deterministic():
    fa = _feat()
    pool = [_comp(i, "WIN" if i % 2 else "LOSS", 1.0 if i % 2 else -1.0)
            for i in range(6)]
    a = build_snapshot(fa, "G", "RG", pool, 8)
    b = build_snapshot(fa, "G", "RG", pool, 8)
    assert a == b


# ---- gate ----

def _snapshot(effN=5, uniq=4, exp_r=0.2, unc=0.3, ex_est=0.2, rd_est=0.1, rec=True):
    return {"summary": {
        "effective_sample": effN, "unique_sessions": uniq,
        "shrunk_expected_R": exp_r, "uncertainty": unc,
        "exact_estimate": ex_est, "reduced_estimate": rd_est, "recency_ok": rec,
    }}


def test_gate_passes_when_all_fields_met():
    assert qualify(_snapshot()) == QUALIFIED_PENDING_TRIGGER


def test_gate_fails_on_low_sample():
    assert gate_reasons(_snapshot(effN=1)) == ["effective_sample"]
    assert qualify(_snapshot(effN=1)) == RECORDED_NOT_ACTIVATED


def test_gate_fails_on_negative_expected_r_and_disagreement():
    fails = gate_reasons(_snapshot(exp_r=-0.2, ex_est=-0.2))
    assert "shrunk_expected_R" in fails and "level_agreement" in fails


def test_gate_policy_is_frozen():
    p = GatePolicy()
    import dataclasses
    assert dataclasses.replace(p, min_effective_sample=9).min_effective_sample == 9
    # original instance unchanged (frozen)
    assert p.min_effective_sample == 4

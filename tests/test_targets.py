"""Target-candidate universe + branch-aware policy resolver (Commit 5)."""

from __future__ import annotations

from types import SimpleNamespace

from discretion.graph.targets import (
    TargetInventory, build_target_candidates, select_target, TARGET_POLICIES)
from discretion.primitives.wick_liquidity import ProminentWickLiquidity
from discretion.primitives.htf_fvg import HTFFVG
from discretion.primitives.levels import Level


def _wick(oid, tf, side, proximal, extreme, grade, seg=0, avail=1,
          overlap=None, swept=None):
    lo, hi = (proximal, extreme) if side == "upper" else (extreme, proximal)
    return ProminentWickLiquidity(
        id=oid, source_candle_id="c", timeframe=tf, side=side, segment_id=seg,
        created_seq=avail, created_ts="t", availability_ts="t",
        full_lo=min(lo, hi), full_hi=max(lo, hi), exposed={5: (min(lo, hi), max(lo, hi))},
        proximal=proximal, extreme=extreme, midpoint=(proximal + extreme) / 2,
        prominence_score=90.0 if grade == "HIGH" else 50.0, prominence_grade=grade,
        positive_overlap_seq=overlap, swept_seq=swept)


def _fvg(oid, tf, direction, lo, hi, seg=0, avail=1, fill=None, fail=None):
    f = HTFFVG(id=oid, timeframe=tf, direction=direction,
               subtype="bullish" if direction > 0 else "bearish",
               a_candle_id="a", b_candle_id="b", c_candle_id="c", segment_id=seg,
               created_seq=avail, created_ts="t", availability_ts="t", lo=lo, hi=hi,
               width_atr=1.0, first_fill_seq=fill, failed_seq=fail,
               active=(fail is None))
    return f


def _lvl(oid, price, seg=0, seq=0):
    return Level(id=oid, family="hist_level", subtype="prior_day_high", segment_id=seg,
                 created_seq=seq, created_ts=None, lo=price, hi=price, price_ref=price)


def _ps(wicks=(), fvgs=(), levels=(), swings=(), rbs=(), structures=(), vwaps=()):
    return SimpleNamespace(
        bars=[], atr=[2.0] * 1000, wicks=list(wicks), htf_fvgs=list(fvgs),
        htf_ifvgs=[], rbs=list(rbs), swings=list(swings), session_levels=list(levels),
        anchors=[], equal_levels=[], structures=list(structures), vwaps=list(vwaps))


def _build(inv, direction, entry, entry_seq, stop, branch=None):
    return build_target_candidates(inv, direction, entry, entry_seq, 0, stop,
                                   2.0, branch)


def test_behind_price_excluded_and_wrong_direction_rejected():
    inv = TargetInventory(_ps(
        wicks=[_wick("W-1", 5, "lower", 95, 90, "HIGH")],   # below -> not a target
        fvgs=[_fvg("F-1", 5, +1, 110, 112)]))               # bullish above -> wrong dir
    cands = _build(inv, +1, 100.0, 10, 98.0)
    # a structure behind price is never a target (spec: targets ahead of price)
    assert all(c.object_id != "W-1" for c in cands)
    f = next(c for c in cands if c.object_id == "F-1")
    assert "WRONG_DIRECTION" in f.rejection_reasons and not f.eligible


def test_low_prominence_and_stale_rejected():
    inv = TargetInventory(_ps(wicks=[
        _wick("W-LOW", 5, "upper", 105, 110, "LOW"),
        _wick("W-STALE", 5, "upper", 106, 111, "HIGH", overlap=8)]))  # overlapped before entry
    cands = _build(inv, +1, 100.0, 10, 98.0)
    low = next(c for c in cands if c.object_id == "W-LOW")
    stale = next(c for c in cands if c.object_id == "W-STALE")
    assert "LOW_PROMINENCE" in low.rejection_reasons and not low.eligible
    assert "STALE" in stale.rejection_reasons and not stale.eligible


def test_not_available_at_trigger_rejected():
    inv = TargetInventory(_ps(fvgs=[_fvg("F-FUT", 5, -1, 108, 112, avail=50)]))
    cands = _build(inv, +1, 100.0, 10, 98.0)
    # not yet available at seq 10 -> excluded from the trigger universe entirely
    assert all(c.object_id != "F-FUT" for c in cands)


def test_frontmost_and_occlusion():
    inv = TargetInventory(_ps(wicks=[
        _wick("W-NEAR", 5, "upper", 103, 108, "HIGH"),
        _wick("W-FAR", 15, "upper", 106, 111, "HIGH")]))
    cands = _build(inv, +1, 100.0, 10, 98.0)
    near = next(c for c in cands if c.object_id == "W-NEAR")
    far = next(c for c in cands if c.object_id == "W-FAR")
    assert near.frontmost and not far.frontmost
    assert far.occluded_by_object_id == "W-NEAR"


def test_natural_rr_recorded_under_frozen_stop():
    inv = TargetInventory(_ps(wicks=[_wick("W-1", 5, "upper", 104, 108, "HIGH")]))
    cands = _build(inv, +1, 100.0, 10, 98.0)   # risk=2, dist=4 -> rr=2.0
    w = next(c for c in cands if c.object_id == "W-1")
    assert w.natural_rr == 2.0


def test_policies_are_distinct_variants():
    inv = TargetInventory(_ps(
        wicks=[_wick("W-1", 5, "upper", 103, 108, "HIGH")],
        fvgs=[_fvg("F-1", 15, -1, 105, 107)],
        levels=[_lvl("L-1", 104.0)]))
    branch = ("L-1", "hist_level", 104.0)
    cands = _build(inv, +1, 100.0, 10, 98.0, branch)
    picks = {p: select_target(cands, p, "L-1") for p in TARGET_POLICIES}
    assert picks["NEAREST_PROMINENT_WICK"][0].object_id == "W-1"
    assert picks["NEAREST_OPPOSING_HTF_FVG"][0].object_id == "F-1"
    assert picks["BRANCH_SEMANTIC"][0].object_id == "L-1"
    # nearest valid structure = the closest eligible (wick@103) over fvg@105/level@104
    assert picks["NEAREST_VALID_STRUCTURE"][0].object_id == "W-1"


def test_policy_finds_nothing_when_family_absent():
    inv = TargetInventory(_ps(levels=[_lvl("L-1", 104.0)]))
    cands = _build(inv, +1, 100.0, 10, 98.0)
    assert select_target(cands, "NEAREST_PROMINENT_WICK") is None
    assert select_target(cands, "NEAREST_OPPOSING_HTF_FVG") is None
    assert select_target(cands, "NEAREST_VALID_STRUCTURE")[0].object_id == "L-1"


def test_resolver_never_skips_near_low_rr_for_farther():
    # nearest eligible structure is sub-0.5R; a farther one would qualify. The
    # resolver must still select the NEAR one (frozen RR decides rejection later).
    inv = TargetInventory(_ps(wicks=[
        _wick("W-NEAR", 5, "upper", 100.5, 101, "HIGH"),   # dist 0.5, risk 2 -> 0.25R
        _wick("W-FAR", 5, "upper", 103, 108, "HIGH")]))
    cands = _build(inv, +1, 100.0, 10, 98.0)
    sel, _ = select_target(cands, "NEAREST_PROMINENT_WICK")
    assert sel.object_id == "W-NEAR" and sel.natural_rr < 0.5


def test_htf_fvg_failed_before_trigger_not_fresh():
    inv = TargetInventory(_ps(fvgs=[_fvg("F-FAIL", 5, -1, 104, 108, fail=9)]))
    cands = _build(inv, +1, 100.0, 10, 98.0)
    f = next(c for c in cands if c.object_id == "F-FAIL")
    assert "STALE" in f.rejection_reasons and not f.eligible


# ---- Repair task Stage 16 #17: target eligibility never depends on stop ----

def test_target_eligibility_unaffected_by_stop_distance():
    """Only the diagnostic natural_rr field may vary with the stop; every
    other field (eligible, rejection_reasons, price, family, frontmost) must
    be identical no matter how far away the stop is placed."""
    inv = TargetInventory(_ps(wicks=[_wick("W-1", 5, "upper", 103, 108, "HIGH")]))
    near_stop = _build(inv, +1, 100.0, 10, 99.0)     # risk 1
    far_stop = _build(inv, +1, 100.0, 10, 50.0)      # risk 50 -- very different
    n = next(c for c in near_stop if c.object_id == "W-1")
    f = next(c for c in far_stop if c.object_id == "W-1")
    assert n.eligible == f.eligible
    assert n.rejection_reasons == f.rejection_reasons
    assert n.price == f.price
    assert n.family == f.family
    assert n.frontmost == f.frontmost
    assert n.natural_rr != f.natural_rr   # the ONLY field allowed to differ

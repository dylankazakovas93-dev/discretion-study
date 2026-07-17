"""Structural relationship predicate tests."""

from __future__ import annotations

import types

from discretion.graph.relationships import (
    RelCtx, evaluate, has_structural_edge, PREDICATES,
    same_object, ifvg_from_parent_fvg, touches_zone, enters_zone, fills_zone,
    closes_through_zone, sweeps_reference, directionally_supports,
    directionally_invalidates, within_supporting_atr_proximity,
    fvg_created_by_displacement,
)


class FakePrim:
    def __init__(self, id, family, lo, hi, direction=0, created_seq=0,
                 a_seq=-1, c_seq=-1, source_fvg_id=""):
        self.id, self.family = id, family
        self.lo, self.hi, self.direction = lo, hi, direction
        self.created_seq, self.a_seq, self.c_seq = created_seq, a_seq, c_seq
        self.source_fvg_id = source_fvg_id

    @property
    def price(self):
        return (self.lo + self.hi) / 2


class FakeReg:
    def __init__(self, objs):
        self._d = {o.id: o for o in objs}

    def get(self, oid):
        return self._d[oid]


def _ev(object_id="E", parent="", plo=100.0, phi=100.0, ref=100.0, direction=1,
        etype="fvg", state="FIRST_TOUCH"):
    return types.SimpleNamespace(
        object_id=object_id, parent_object_id=parent, price_low=plo, price_high=phi,
        reference_price=ref, direction=direction, event_type=etype, state_after=state)


def _ctx(atr=2.0, ev_seq=10, branch_dir=1, last=5, reg=None):
    return RelCtx(atr=atr, ev_seq=ev_seq, branch_dir=branch_dir,
                  branch_last_seq=last, reg=reg or FakeReg([]))


def test_same_object():
    obj = FakePrim("RB-1", "rejection_block", 99, 100, 1)
    assert same_object(obj, _ev(object_id="RB-1"), _ctx())
    assert not same_object(obj, _ev(object_id="X"), _ctx())


def test_ifvg_from_parent_fvg():
    fvg = FakePrim("FVG-1", "fvg", 100, 101, 1)
    ev = _ev(object_id="IFVG-1", parent="FVG-1", etype="ifvg", state="CONFIRMED")
    assert ifvg_from_parent_fvg(fvg, ev, _ctx())


def test_zone_touch_enter_fill():
    z = FakePrim("FVG-1", "fvg", 100, 101, 1)  # bullish support, far edge = 100
    assert touches_zone(z, _ev(plo=100.9, phi=101.5), _ctx())      # reaches near edge
    assert enters_zone(z, _ev(plo=100.4, phi=100.9), _ctx())       # inside
    assert fills_zone(z, _ev(plo=99.9, phi=100.6), _ctx())         # reaches far edge
    assert not fills_zone(z, _ev(plo=100.6, phi=101.0), _ctx())


def test_state_based_relationships():
    z = FakePrim("FVG-1", "fvg", 100, 101, 1)
    assert closes_through_zone(z, _ev(state="FAILURE"), _ctx())
    assert sweeps_reference(z, _ev(state="SWEEP"), _ctx())


def test_directional_support_and_invalidation():
    obj = FakePrim("O", "fvg", 100, 101, 1)
    assert directionally_supports(obj, _ev(direction=1), _ctx(branch_dir=1))
    assert not directionally_supports(obj, _ev(direction=-1), _ctx(branch_dir=1))
    assert directionally_invalidates(obj, _ev(direction=-1, state="EXPANSION"),
                                     _ctx(branch_dir=1))


def test_proximity_is_supporting_only():
    obj = FakePrim("O", "hist_level", 100, 100, 0)
    ev = _ev(ref=100.5, direction=1, state="FIRST_TOUCH", object_id="OTHER")
    assert within_supporting_atr_proximity(obj, ev, _ctx(atr=2.0))
    sat = evaluate(obj, ev, _ctx(atr=2.0, reg=FakeReg([obj])))
    # proximity + direction hold, but no structural edge -> not linkable alone
    assert not has_structural_edge(sat)


def test_structural_edge_when_same_object():
    obj = FakePrim("O", "hist_level", 100, 100, 0)
    ev = _ev(object_id="O", ref=100.0, state="SWEEP")
    sat = evaluate(obj, ev, _ctx(reg=FakeReg([obj])))
    assert "SAME_OBJECT" in sat and has_structural_edge(sat)


def test_fvg_created_by_displacement_links_to_that_displacement():
    disp = FakePrim("DISP-1", "displacement", 100, 102, 1, created_seq=5)
    fvg = FakePrim("FVG-9", "fvg", 101, 102, 1, created_seq=6, a_seq=4, c_seq=6)
    reg = FakeReg([disp, fvg])
    ev = _ev(object_id="FVG-9", etype="fvg", state="FORMED", direction=1)
    assert fvg_created_by_displacement(disp, ev, _ctx(reg=reg))
    # an FVG whose formation bars do not overlap the displacement leg does not link
    fvg2 = FakePrim("FVG-10", "fvg", 101, 102, 1, created_seq=40, a_seq=38, c_seq=40)
    reg2 = FakeReg([disp, fvg2])
    ev2 = _ev(object_id="FVG-10", etype="fvg", state="FORMED")
    assert not fvg_created_by_displacement(disp, ev2, _ctx(reg=reg2))

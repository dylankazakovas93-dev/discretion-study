"""Typed structural relationship predicates.

A causal edge between a branch's focus object and a new event requires at least
one *explicit* structural relationship — ATR proximity is only ever a supporting
condition, never an edge by itself. Each predicate is a pure function of the
event geometry/state and the focus primitive; ``evaluate`` returns the set of
satisfied relationship names, which the transition registry then matches against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import NQ_TICK

LINK_PROXIMITY_ATR = 1.5   # supporting proximity only (frozen)
LINK_MAX_GAP_BARS = 120
MIN_CONTINUATION_ATR = 1.0  # min move beyond the FVG boundary for a no-fill path


@dataclass
class RelCtx:
    atr: float
    ev_seq: int
    branch_dir: int
    branch_last_seq: int
    reg: object            # IdRegistry, for looking up event/object primitives


def _overlap(a_lo, a_hi, b_lo, b_hi) -> float:
    return min(a_hi, b_hi) - max(a_lo, b_lo)


def _is_zone(obj) -> bool:
    return obj is not None and obj.hi > obj.lo


# Each predicate: (obj, ev, ctx) -> bool. obj is the branch focus primitive.

def same_object(obj, ev, ctx):
    return obj is not None and ev.object_id == obj.id


def parent_child_object(obj, ev, ctx):
    if obj is None:
        return False
    return ev.parent_object_id == obj.id or getattr(obj, "source_fvg_id", "") == ev.object_id


def ifvg_from_parent_fvg(obj, ev, ctx):
    return ev.event_type == "ifvg" and obj is not None and ev.parent_object_id == obj.id


def touches_zone(obj, ev, ctx):
    return _is_zone(obj) and _overlap(ev.price_low, ev.price_high, obj.lo, obj.hi) >= 0


def enters_zone(obj, ev, ctx):
    return _is_zone(obj) and _overlap(ev.price_low, ev.price_high, obj.lo, obj.hi) > 0


def fills_zone(obj, ev, ctx):
    if not _is_zone(obj):
        return False
    if getattr(obj, "direction", 0) > 0:      # bullish support: far edge = lo
        return ev.price_low <= obj.lo + NQ_TICK / 2
    if getattr(obj, "direction", 0) < 0:      # bearish resistance: far edge = hi
        return ev.price_high >= obj.hi - NQ_TICK / 2
    return _overlap(ev.price_low, ev.price_high, obj.lo, obj.hi) > 0


def closes_through_zone(obj, ev, ctx):
    # a close-through of the actual focus zone (its own failure/re-inversion)
    return _acts_on_focus(obj, ev) and ev.state_after in ("FAILURE", "REINVERSION")


def _acts_on_focus(obj, ev):
    """Proof that the event acts on the branch's actual focus object/region:
    same object id, an explicit parent/child link, or source-object provenance.
    A generic state label from an unrelated object does NOT satisfy this."""
    if obj is None:
        return False
    if ev.object_id == obj.id:
        return True
    if ev.parent_object_id and ev.parent_object_id == obj.id:
        return True
    if getattr(obj, "source_fvg_id", "") == ev.object_id:
        return True
    return False


def reclaims_boundary(obj, ev, ctx):
    # a reclaim of the actual stored boundary (the focus object's own reclaim)
    return _acts_on_focus(obj, ev) and ev.state_after == "RECLAIM"


def breaks_boundary(obj, ev, ctx):
    return _acts_on_focus(obj, ev) and ev.state_after == "BREAK"


def accepts_beyond_boundary(obj, ev, ctx):
    return _acts_on_focus(obj, ev) and ev.state_after in ("ACCEPTANCE_ABOVE",
                                                          "ACCEPTANCE_BELOW")


def rejects_boundary(obj, ev, ctx):
    return _acts_on_focus(obj, ev) and ev.state_after == "REJECTION"


def sweeps_reference(obj, ev, ctx):
    return _acts_on_focus(obj, ev) and ev.state_after == "SWEEP"


def object_created_by_leg(obj, ev, ctx):
    """A zone whose formation bars coincide with the displacement leg `obj`."""
    if obj is None or obj.family != "displacement":
        return False
    prim = _lookup(ctx, ev.object_id)
    if prim is None or prim.family not in ("fvg",):
        return False
    a, c = getattr(prim, "a_seq", -1), getattr(prim, "c_seq", -2)
    return a <= obj.created_seq <= c


def fvg_created_by_displacement(obj, ev, ctx):
    return object_created_by_leg(obj, ev, ctx) and ev.event_type == "fvg"


def displacement_originates_at_object(obj, ev, ctx):
    if ev.event_type != "displacement" or ev.state_after != "FORMED":
        return False
    if obj is None:
        return False
    if _is_zone(obj):
        return _overlap(ev.price_low, ev.price_high, obj.lo, obj.hi) >= 0
    return abs(ev.reference_price - obj.price) <= LINK_PROXIMITY_ATR * (ctx.atr or 0)


def compression_forms_around_object(obj, ev, ctx):
    if ev.event_type != "structure" or ev.state_after != "COMPRESSION":
        return False
    if obj is None:
        return False
    p = obj.price if not _is_zone(obj) else (obj.lo + obj.hi) / 2
    return ev.price_low <= p <= ev.price_high


def expansion_leaves_compression(obj, ev, ctx):
    # expansion/break out of the SAME stored compression region
    return (obj is not None and obj.family == "structure"
            and _acts_on_focus(obj, ev)
            and ev.state_after in ("EXPANSION", "BREAK"))


def failed_expansion_returns_to_region(obj, ev, ctx):
    return (obj is not None and obj.family == "structure"
            and _acts_on_focus(obj, ev)
            and ev.state_after == "FAILED_CONTINUATION")


def fvg_continuation_away(obj, ev, ctx):
    """A directional displacement/expansion that moves measurably away from the
    FVG's stored boundary (a geometric relationship to that object). The branch
    separately guarantees the FVG was never touched."""
    if obj is None or not _is_zone(obj) or obj.family != "fvg":
        return False
    d = getattr(obj, "direction", 0)
    if ev.direction == 0 or ev.direction != d:
        return False
    strong = ((ev.event_type == "displacement" and ev.state_after == "FORMED")
              or (ev.event_type == "structure" and ev.state_after in ("EXPANSION", "BREAK")))
    if not strong:
        return False
    atr = ctx.atr or 0
    if atr <= 0:
        return False
    if d > 0:
        return ev.reference_price >= obj.hi + MIN_CONTINUATION_ATR * atr
    return ev.reference_price <= obj.lo - MIN_CONTINUATION_ATR * atr


def time_anchor_interaction(obj, ev, ctx):
    return (obj is not None and obj.family == "time_anchor"
            and (same_object(obj, ev, ctx)
                 or (obj.lo - (ctx.atr or 0) * 0.1 <= ev.reference_price
                     <= obj.hi + (ctx.atr or 0) * 0.1)))


def directionally_supports(obj, ev, ctx):
    return ev.direction == 0 or ctx.branch_dir == 0 or ev.direction == ctx.branch_dir


def directionally_invalidates(obj, ev, ctx):
    strong = ev.state_after in ("EXPANSION", "BREAK", "FAILURE", "ACCEPTANCE_ABOVE",
                                "ACCEPTANCE_BELOW")
    return ctx.branch_dir != 0 and ev.direction == -ctx.branch_dir and strong


def within_frozen_time_gap(obj, ev, ctx):
    return 0 < ctx.ev_seq - ctx.branch_last_seq <= LINK_MAX_GAP_BARS


def within_supporting_atr_proximity(obj, ev, ctx):
    if obj is None or not ctx.atr:
        return False
    p = obj.price if not _is_zone(obj) else (obj.lo + obj.hi) / 2
    return abs(ev.reference_price - p) <= LINK_PROXIMITY_ATR * ctx.atr


PREDICATES = {
    "SAME_OBJECT": same_object,
    "PARENT_CHILD_OBJECT": parent_child_object,
    "IFVG_CREATED_FROM_PARENT_FVG": ifvg_from_parent_fvg,
    "OBJECT_CREATED_BY_LEG": object_created_by_leg,
    "FVG_CREATED_BY_DISPLACEMENT": fvg_created_by_displacement,
    "TOUCHES_ZONE": touches_zone,
    "ENTERS_ZONE": enters_zone,
    "FILLS_ZONE": fills_zone,
    "CLOSES_THROUGH_ZONE": closes_through_zone,
    "RECLAIMS_BOUNDARY": reclaims_boundary,
    "BREAKS_BOUNDARY": breaks_boundary,
    "ACCEPTS_BEYOND_BOUNDARY": accepts_beyond_boundary,
    "REJECTS_BOUNDARY": rejects_boundary,
    "SWEEPS_REFERENCE": sweeps_reference,
    "DISPLACEMENT_ORIGINATES_AT_OBJECT": displacement_originates_at_object,
    "FVG_CONTINUATION_AWAY": fvg_continuation_away,
    "COMPRESSION_FORMS_AROUND_OBJECT": compression_forms_around_object,
    "EXPANSION_LEAVES_COMPRESSION": expansion_leaves_compression,
    "FAILED_EXPANSION_RETURNS_TO_REGION": failed_expansion_returns_to_region,
    "TIME_ANCHOR_INTERACTION": time_anchor_interaction,
    "DIRECTIONALLY_SUPPORTS": directionally_supports,
    "DIRECTIONALLY_INVALIDATES": directionally_invalidates,
    "WITHIN_FROZEN_TIME_GAP": within_frozen_time_gap,
    "WITHIN_SUPPORTING_ATR_PROXIMITY": within_supporting_atr_proximity,
}

# supporting-only names — never sufficient on their own to justify a causal edge
# (price proximity, time gap, and bare directional agreement/disagreement)
PROXIMITY_ONLY = {"WITHIN_SUPPORTING_ATR_PROXIMITY", "WITHIN_FROZEN_TIME_GAP",
                  "DIRECTIONALLY_SUPPORTS", "DIRECTIONALLY_INVALIDATES"}


def _lookup(ctx, oid):
    try:
        return ctx.reg.get(oid)
    except Exception:
        return None


def evaluate(obj, ev, ctx) -> set[str]:
    """Return the set of satisfied relationship names."""
    return {name for name, fn in PREDICATES.items() if fn(obj, ev, ctx)}


def has_structural_edge(satisfied: set[str]) -> bool:
    """True iff at least one non-proximity structural relationship holds."""
    return bool(satisfied - PROXIMITY_ONLY)


@dataclass
class TransitionEvidence:
    transition_rule_id: str
    source_branch_id: str
    source_event_id: str
    new_event_id: str
    relationships_satisfied: tuple
    conditions_satisfied: tuple
    state_before: str
    state_after: str


@dataclass
class RejectionCounter:
    counts: dict = field(default_factory=dict)

    def add(self, reason: str):
        self.counts[reason] = self.counts.get(reason, 0) + 1

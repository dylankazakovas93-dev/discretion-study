"""Typed target-candidate universe and the branch-aware target resolver.

At a graph-native trigger the resolver collects every causally available target
*ahead of price* from prominent-wick liquidity (5/15/30/60m), HTF FVGs/iFVGs,
rejection blocks, swings, historical/session/time-anchor levels, VWAP + bands,
compression boundaries, and the branch-native objective. Each becomes a typed
:class:`TargetCandidate` carrying availability, freshness, prominence, frontmost/
occlusion and its natural RR under the frozen stop.

Selection is **purely structural**: the nearest frontmost eligible target under a
policy. The frozen RR policy is applied *afterwards* to the selected target — a
near sub-0.5R target is never skipped to reach a farther qualifying one. Four
frozen policies each yield a separate research variant (never collapsed):
``BRANCH_SEMANTIC``, ``NEAREST_VALID_STRUCTURE``, ``NEAREST_PROMINENT_WICK``,
``NEAREST_OPPOSING_HTF_FVG``.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from ..data.bars import NQ_TICK

TARGET_POLICIES = ("BRANCH_SEMANTIC", "NEAREST_VALID_STRUCTURE",
                   "NEAREST_PROMINENT_WICK", "NEAREST_OPPOSING_HTF_FVG")

# rejection reasons (protocol §6)
NOT_AVAILABLE = "NOT_AVAILABLE_AT_TRIGGER"
WRONG_DIRECTION = "WRONG_DIRECTION"
WRONG_SIDE = "WRONG_SIDE_OF_ENTRY"
STALE = "STALE"
CROSS_SEGMENT = "CROSS_SEGMENT"
LOW_PROMINENCE = "LOW_PROMINENCE"

MIN_GAP = NQ_TICK


@dataclass
class TargetCandidate:
    object_id: str
    family: str
    subtype: str
    timeframe: object          # int tf, "1m", or None (branch objective)
    direction: int             # trade direction this target serves (+1/-1)
    target_surface: str        # PROXIMAL_EDGE (default)
    price: float
    availability_seq: int
    fresh: bool
    prominence_grade: str | None
    age: int
    distance_points: float
    distance_atr: float | None
    natural_rr: float | None
    eligible: bool
    rejection_reasons: list = field(default_factory=list)
    frontmost: bool = False
    occluded_by_object_id: str = ""


def _proximal(direction, lo, hi):
    """Near edge of a zone in the trade direction (price approaches it)."""
    return lo if direction > 0 else hi


class TargetInventory:
    """Immutable per-run bundle of every structure a target may come from.

    Objects are pre-bucketed by contract segment and sorted by availability so a
    trigger only scans same-segment structures already knowable at its seq — the
    genuine considered universe (never a cross-segment or future object).
    """

    def __init__(self, ps):
        self.bars = ps.bars
        self.atr = ps.atr
        wicks = [w for w in getattr(ps, "wicks", []) if w.timeframe is not None]
        htf_fvgs = getattr(ps, "htf_fvgs", [])
        htf_ifvgs = getattr(ps, "htf_ifvgs", [])
        levels = ps.session_levels + ps.anchors + ps.equal_levels
        # per segment: list of (avail_seq, tag, obj), sorted by avail_seq
        self.seg_objs: dict[int, list] = {}
        for tag, objs in (("wick", wicks), ("htf_fvg", htf_fvgs),
                          ("htf_ifvg", htf_ifvgs), ("rb", ps.rbs),
                          ("swing", ps.swings), ("level", levels),
                          ("structure", ps.structures)):
            for o in objs:
                self.seg_objs.setdefault(o.segment_id, []).append(
                    (o.available_seq if tag in ("wick", "htf_fvg", "htf_ifvg")
                     else o.created_seq, tag, o))
        for seg in self.seg_objs:
            self.seg_objs[seg].sort(key=lambda t: t[0])
        self._avail_keys = {seg: [t[0] for t in lst]
                            for seg, lst in self.seg_objs.items()}
        self.vwap_by_seq = {}
        for vs in ps.vwaps:
            for seq in vs.vwap:
                self.vwap_by_seq[seq] = vs

    def _raw(self, direction, seg, entry_seq):
        """Yield spec tuples (object_id, family, subtype, tf, proximal_price,
        segment, avail_seq, fresh, prominence, opposing_ok) for same-segment
        structures already available at ``entry_seq``."""
        raw = []
        opp = -direction
        lst = self.seg_objs.get(seg, [])
        keys = self._avail_keys[seg] if lst else []
        hi_idx = bisect_right(keys, entry_seq)
        for avail, tag, o in lst[:hi_idx]:
            if tag == "wick":
                side_ok = (o.side == "upper") if direction > 0 else (o.side == "lower")
                raw.append((o.id, "wick_liquidity", o.side, o.timeframe, o.proximal,
                            seg, avail, o.fresh_at(entry_seq) and o.active,
                            o.prominence_grade, side_ok))
            elif tag == "htf_fvg":
                raw.append((o.id, "htf_fvg", o.subtype, o.timeframe,
                            _proximal(direction, o.lo, o.hi), seg, avail,
                            o.fresh_at(entry_seq) and o.active, None, o.direction == opp))
            elif tag == "htf_ifvg":
                raw.append((o.id, "htf_ifvg", o.subtype, o.timeframe,
                            _proximal(direction, o.lo, o.hi), seg, avail,
                            o.fresh_at(entry_seq) and o.active, None, o.direction == opp))
            elif tag == "rb":
                fresh = o.invalidated_seq is None or o.invalidated_seq > entry_seq
                raw.append((o.id, "rejection_block", o.subtype, "1m",
                            _proximal(direction, o.lo, o.hi), seg, avail, fresh,
                            None, o.direction == opp))
            elif tag == "swing":
                want = "swing_high" if direction > 0 else "swing_low"
                raw.append((o.id, "swing", o.subtype, "1m", o.price_ref, seg, avail,
                            not _swept_before(o, entry_seq), None, o.subtype == want))
            elif tag == "level":
                raw.append((o.id, o.family, o.subtype, "1m", o.price_ref, seg, avail,
                            not _swept_before(o, entry_seq), None, True))
            elif tag == "structure":
                lo = getattr(o, "band_lo", o.lo)
                hi = getattr(o, "band_hi", o.hi)
                raw.append((o.id, "structure", o.subtype, "1m",
                            _proximal(direction, lo, hi), seg, avail, o.active,
                            None, True))

        vs = self.vwap_by_seq.get(entry_seq)
        if vs is not None and vs.segment_id == seg:
            val = vs.value_at(entry_seq)
            if val:
                raw.append((f"{vs.id}:vwap", "vwap", "vwap", "session",
                            val["vwap"], seg, vs.start_seq, True, None, True))
                for name, price in val["bands"].items():
                    raw.append((f"{vs.id}:{name}", "vwap_band", name, "session",
                                price, seg, vs.start_seq, True, None, True))
        return raw


def _swept_before(level, seq):
    return any(e.kind == "SWEEP" and e.seq <= seq for e in level.events)


def build_target_candidates(inv, direction, entry_price, entry_seq, seg, stop,
                            atr, branch_target=None):
    """Return every considered TargetCandidate with eligibility + RR annotated.

    ``branch_target`` = (object_id, family, price) for the BRANCH_SEMANTIC policy.
    """
    risk = abs(entry_price - stop)
    cands: list[TargetCandidate] = []

    def make(oid, fam, sub, tf, price, avail, fresh, prom, opposing_ok):
        reasons = []
        if avail > entry_seq:
            reasons.append(NOT_AVAILABLE)
        ahead = (price > entry_price + MIN_GAP if direction > 0
                 else price < entry_price - MIN_GAP)
        if not ahead:
            reasons.append(WRONG_SIDE)
        if not opposing_ok:
            reasons.append(WRONG_DIRECTION)
        if not fresh:
            reasons.append(STALE)
        if prom == "LOW":
            reasons.append(LOW_PROMINENCE)
        dist = abs(price - entry_price)
        rr = round(dist / risk, 4) if risk > 0 else None
        return TargetCandidate(
            object_id=oid, family=fam, subtype=sub, timeframe=tf,
            direction=direction, target_surface="PROXIMAL_EDGE", price=float(price),
            availability_seq=avail, fresh=fresh, prominence_grade=prom,
            age=entry_seq - avail, distance_points=round(dist, 4),
            distance_atr=round(dist / atr, 4) if atr else None, natural_rr=rr,
            eligible=not reasons, rejection_reasons=reasons)

    for (oid, fam, sub, tf, price, _csid, avail, fresh, prom, opp) in \
            inv._raw(direction, seg, entry_seq):
        cands.append(make(oid, fam, sub, tf, price, avail, fresh, prom, opp))

    # branch-native objective as its own candidate (BRANCH_SEMANTIC input)
    if branch_target is not None:
        boid, bfam, bprice = branch_target
        cands.append(make(boid, f"branch:{bfam}", bfam, None, bprice,
                          entry_seq, True, None, True))

    # frontmost / occlusion over the eligible set (nearest proximal to entry)
    eligible = [c for c in cands if c.eligible]
    eligible.sort(key=lambda c: c.distance_points)
    for rank, c in enumerate(eligible):
        if rank == 0:
            c.frontmost = True
        else:
            c.occluded_by_object_id = eligible[0].object_id
    return cands


def select_target(cands, policy, branch_object_id=None):
    """Frozen structural selection for a policy. Returns (candidate, rank) or None.

    Rank is the 0-based frontmost order within the policy's eligible subset.
    """
    if policy == "BRANCH_SEMANTIC":
        subset = [c for c in cands if c.eligible
                  and c.object_id == branch_object_id
                  and c.family.startswith("branch:")]
    elif policy == "NEAREST_VALID_STRUCTURE":
        subset = [c for c in cands if c.eligible
                  and not c.family.startswith("branch:")]
    elif policy == "NEAREST_PROMINENT_WICK":
        subset = [c for c in cands if c.eligible and c.family == "wick_liquidity"]
    elif policy == "NEAREST_OPPOSING_HTF_FVG":
        subset = [c for c in cands if c.eligible and c.family == "htf_fvg"]
    else:
        raise ValueError(f"unknown target policy {policy!r}")
    if not subset:
        return None
    subset.sort(key=lambda c: c.distance_points)
    return subset[0], 0

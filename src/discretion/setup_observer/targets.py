"""Structural target resolution (spec Part 7). A valid EXECUTION target must be
an OPPOSING structural objective that existed causally, is still active/fresh at
the trigger, lies in the profitable direction, is not one of the setup
components, and is not filled/inverted/expired/traversed/behind entry.

Three execution policies plus one diagnostic-only policy:
  NEAREST_OPPOSING_VALID_STRUCTURE   (primary execution)
  BRANCH_SEMANTIC_TARGET             (nearest opposing of the context family)
  NEAREST_OPPOSING_HIGHER_TF_STRUCTURE
  ANY_SURFACE_DIAGNOSTIC             (nearest surface, any direction -- diagnostic)

The stop is never moved and a closer valid opposing target is never skipped to
manufacture RR. RR is applied afterwards to decide executability, not to pick a
farther target.

The considered ledger records the nearest ELIGIBLE opposing candidates plus one
representative NEAREST excluded example per exclusion reason, and aggregate
exclusion counts -- the full opposing universe is summarised by those counts
rather than emitting one row per structure per variant.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from itertools import chain as _chain

POLICIES = ("NEAREST_OPPOSING_VALID_STRUCTURE", "BRANCH_SEMANTIC_TARGET",
            "NEAREST_OPPOSING_HIGHER_TF_STRUCTURE")
DIAGNOSTIC_POLICY = "ANY_SURFACE_DIAGNOSTIC"
NEAREST_ELIGIBLE_KEPT = 12


@dataclass
class TargetCandidate:
    policy: str
    structure_id: str
    family: str
    timeframe: int
    surface: float
    distance: float
    freshness_bars: int
    availability_seq: int
    natural_rr: object


class StructTable:
    """Target-eligible structures as parallel arrays sorted by availability, so
    resolution touches only structures already knowable at the entry bar. The
    indices of no-expiry 60m structures are tracked separately so a bounded
    recency window can be applied to the (8h-lifetime) intraday structures
    losslessly while still checking every long-lived 60m structure."""

    def __init__(self, structs):
        s = sorted(structs, key=lambda x: x["avail"])
        self.avail = [x["avail"] for x in s]
        self.ids = [x["id"] for x in s]
        self.fam = [x["family"] for x in s]
        self.tf = [x["tf"] for x in s]
        self.sdir = [x["sdir"] for x in s]
        self.lo = [x["lo"] for x in s]
        self.hi = [x["hi"] for x in s]
        self.invalid_from = [x["invalid_from"] for x in s]
        # Long-lived structures are always checked regardless of age: those that
        # never expire (invalid_from is None) and every 60m structure (which can
        # stay active well past the intraday 8h lifetime). Everything else is a
        # <=8h-lifetime intraday structure that can be safely windowed.
        self.always_idx = [i for i in range(len(self.avail))
                           if self.invalid_from[i] is None or self.tf[i] >= 60]
        self.always_avail = [self.avail[i] for i in self.always_idx]


def resolve_targets(table, entry_seq, direction, entry_price, stop_price,
                    context_tf, context_family, exclude_ids, window=None):
    """Returns (selected_by_policy, considered_ledger, exclusion_counts). Only
    structures with ``avail <= entry_seq`` are considered (causal).

    ``window``: if set, short-lived intraday structures (finite invalid_from,
    tf<60, <=8h = 480-bar lifetime) older than ``entry_seq - window`` bars are
    skipped -- past their lifetime, they are excluded anyway, so with ``window``
    comfortably above 480 this is lossless. Never-expiring structures and all
    60m structures are always checked regardless of age."""
    risk = abs(entry_price - stop_price)
    count = bisect.bisect_right(table.avail, entry_seq)
    eligible = []                 # (dist, i) for opposing, active, ahead, non-component
    excl_counts = {}
    excl_example = {}             # reason -> (dist, i)
    diag_i, diag_surf, diag_dist = None, None, None

    ids, sdirs, los, his, tfs, fams, avails, invs = (
        table.ids, table.sdir, table.lo, table.hi, table.tf, table.fam,
        table.avail, table.invalid_from)

    if window is None:
        idxs = range(count)
    else:
        cutoff = entry_seq - window
        lo = bisect.bisect_left(table.avail, cutoff)
        # everything in the window, plus any always-check structure older than it
        older_always = table.always_idx[:bisect.bisect_left(table.always_avail, cutoff)]
        idxs = _chain(range(lo, count), older_always)

    opp = -direction
    for i in idxs:
        lo_i, hi_i = los[i], his[i]
        if direction > 0:
            surface = lo_i
            ahead = surface > entry_price
            # nearest surface ahead (any side) for the diagnostic
            nsurf = lo_i if lo_i > entry_price else (hi_i if hi_i > entry_price else None)
            nd = (nsurf - entry_price) if nsurf is not None else None
        else:
            surface = hi_i
            ahead = surface < entry_price
            nsurf = hi_i if hi_i < entry_price else (lo_i if lo_i < entry_price else None)
            nd = (entry_price - nsurf) if nsurf is not None else None
        is_comp = ids[i] in exclude_ids
        if nd is not None and not is_comp and (diag_dist is None or nd < diag_dist):
            diag_i, diag_surf, diag_dist = i, nsurf, nd

        # eligibility for an opposing execution target
        reason = None
        if is_comp:
            reason = "component"
        elif sdirs[i] != opp:
            reason = "same_direction"
        elif invs[i] is not None and invs[i] <= entry_seq:
            reason = "inactive_or_traversed"
        elif not ahead:
            reason = "behind_entry"
        dist = abs(surface - entry_price)
        if reason is None:
            eligible.append((dist, ids[i], i))     # id tiebreak -> order-independent
        else:
            excl_counts[reason] = excl_counts.get(reason, 0) + 1
            prev = excl_example.get(reason)
            if prev is None or dist < prev[0]:
                excl_example[reason] = (dist, i)

    def rec(i, surface, dist, extra_reason=""):
        rr = (dist / risk) if risk > 0 else None
        return {"structure_id": ids[i], "family": fams[i], "tf": tfs[i],
                "surface": round(surface, 4), "distance": round(dist, 4),
                "natural_rr": (round(rr, 4) if rr is not None else None),
                "avail": avails[i], "exclusion_reason": extra_reason}

    def mk(policy, dist, i):
        surface = los[i] if direction > 0 else his[i]
        rr = (dist / risk) if risk > 0 else None
        return TargetCandidate(policy=policy, structure_id=ids[i], family=fams[i],
                               timeframe=tfs[i], surface=round(surface, 4),
                               distance=round(dist, 4), freshness_bars=entry_seq - avails[i],
                               availability_seq=avails[i],
                               natural_rr=(round(rr, 4) if rr is not None else None))

    selected = {}
    if eligible:
        eligible.sort(key=lambda t: (t[0], t[1]))   # (distance, structure_id)
        d0, _, i0 = eligible[0]
        selected["NEAREST_OPPOSING_VALID_STRUCTURE"] = mk("NEAREST_OPPOSING_VALID_STRUCTURE", d0, i0)
        fam = next(((d, i) for d, _sid, i in eligible if fams[i] == context_family), None)
        if fam:
            selected["BRANCH_SEMANTIC_TARGET"] = mk("BRANCH_SEMANTIC_TARGET", fam[0], fam[1])
        htf = next(((d, i) for d, _sid, i in eligible if tfs[i] >= context_tf), None)
        if htf:
            selected["NEAREST_OPPOSING_HIGHER_TF_STRUCTURE"] = mk(
                "NEAREST_OPPOSING_HIGHER_TF_STRUCTURE", htf[0], htf[1])
    if diag_i is not None:
        selected[DIAGNOSTIC_POLICY] = mk(DIAGNOSTIC_POLICY, diag_dist, diag_i)

    # considered ledger: nearest eligible + one nearest example per exclusion reason
    considered = []
    for d, _sid, i in eligible[:NEAREST_ELIGIBLE_KEPT]:
        surface = los[i] if direction > 0 else his[i]
        considered.append(rec(i, surface, d, ""))
    for reason, (d, i) in excl_example.items():
        surface = los[i] if direction > 0 else his[i]
        considered.append(rec(i, surface, d, reason))
    return selected, considered, excl_counts

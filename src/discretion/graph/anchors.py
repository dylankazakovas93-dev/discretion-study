"""Branch-specific stop/target anchor resolver (frozen, keyed by trigger family).

Each anchor is chosen from the branch's own structural objects (RB/FVG/iFVG
boundary, swept extreme, compression region, accepted level, VWAP/band), never a
generic universal rule and never using future outcomes. A generic nearest level
is used only as an explicitly named fallback when no branch-specific target
anchor is available. Returns typed anchors carrying object id, price and rule id.
"""

from __future__ import annotations

from ..data.bars import NQ_TICK
from ..setups.structural import nearest_level_above, nearest_level_below

STOP_BUFFER = 2 * NQ_TICK


def _band_lo_hi(z):
    return getattr(z, "band_lo", z.lo), getattr(z, "band_hi", z.hi)


def resolve_anchors(fam, direction, entry_price, seq, seg, focus, origin,
                    bar0, trig_ev, levels, vwap_value):
    """Return (stop_anchor, target_anchor) dicts with type/object_id/price/rule."""
    buf = STOP_BUFFER
    long = direction > 0
    stop = None    # (type, object_id, price)
    tgt = None

    def oid(o):
        return getattr(o, "id", "") if o is not None else ""

    # ---------------- STOP anchor (branch-specific) ----------------
    if fam in ("fvg_formation", "fvg_fill", "fvg_no_fill") and focus is not None:
        stop = ("fvg_boundary", focus.id, (focus.lo - buf) if long else (focus.hi + buf))
    elif fam in ("ifvg_activation", "ifvg_retest") and focus is not None:
        stop = ("ifvg_invalidation_boundary", focus.id,
                (focus.lo - buf) if long else (focus.hi + buf))
    elif fam in ("rb_reaction", "rb_fvg_fill") and origin is not None:
        stop = ("rb_invalidation_boundary", origin.id,
                (origin.lo - buf) if long else (origin.hi + buf))
    elif fam == "rb_failure_fade" and focus is not None:
        lo, hi = _band_lo_hi(focus)
        stop = ("failure_region_boundary", focus.id, (lo - buf) if long else (hi + buf))
    elif fam in ("sweep_fade", "sweep_reclaim_fade") and focus is not None:
        ext = (min(focus.lo, bar0.low) - buf) if long else (max(focus.hi, bar0.high) + buf)
        stop = ("swept_extreme", focus.id, ext)
    elif fam == "break_accept_cont" and focus is not None:
        stop = ("accepted_boundary", focus.id,
                (focus.price - buf) if long else (focus.price + buf))
    elif fam == "break_failed_fade" and focus is not None:
        ext = (min(focus.price, bar0.low) - buf) if long else (max(focus.price, bar0.high) + buf)
        stop = ("failed_break_boundary", focus.id, ext)
    elif fam == "anchor_reclaim" and origin is not None:
        stop = ("anchor_boundary", origin.id,
                (origin.price - buf) if long else (origin.price + buf))
    elif fam == "compression_expansion" and origin is not None:
        lo, hi = _band_lo_hi(origin)
        stop = ("compression_region", origin.id, (lo - buf) if long else (hi + buf))
    elif fam == "compression_false_expansion" and focus is not None:
        lo, hi = _band_lo_hi(focus)
        stop = ("compression_region", focus.id, (lo - buf) if long else (hi + buf))
    elif fam == "vwap_band_fade":
        # beyond the rejected band (the trigger reference price is that band)
        stop = ("vwap_band", oid(focus),
                (trig_ev.reference_price - buf) if long else (trig_ev.reference_price + buf))
    elif fam in ("vwap_bounce", "vwap_reclaim", "vwap_break_accept") and vwap_value:
        v = vwap_value["vwap"]
        stop = ("vwap", oid(focus), (v - buf) if long else (v + buf))

    if stop is None:
        # named structural fallback: focus/trigger-bar extreme
        base_lo = focus.lo if focus is not None else entry_price
        base_hi = focus.hi if focus is not None else entry_price
        stop = ("structural_extreme_fallback", oid(focus) or oid(origin),
                (min(base_lo, bar0.low) - buf) if long else (max(base_hi, bar0.high) + buf))

    # ---------------- TARGET anchor (branch-specific, then fallback) ----------------
    if fam == "vwap_band_fade" and vwap_value:
        tgt = ("vwap", oid(focus), vwap_value["vwap"])
    elif fam in ("vwap_bounce", "vwap_reclaim", "vwap_break_accept") and vwap_value:
        cand = [p for p in vwap_value["bands"].values()
                if (p > entry_price if long else p < entry_price)]
        if cand:
            tgt = ("vwap_band", oid(focus), (min(cand) if long else max(cand)))

    if tgt is None:
        lvl = (nearest_level_above(entry_price, seq, seg, levels) if long
               else nearest_level_below(entry_price, seq, seg, levels))
        if lvl is not None:
            tgt = (f"opposing_{lvl.family}", lvl.id, lvl.price_ref)

    stop_anchor = {"stop_anchor_type": stop[0], "stop_anchor_object_id": stop[1],
                   "stop_anchor_price": float(stop[2])}
    if tgt is None:
        # stop is always structural; the branch objective simply yields no
        # BRANCH_SEMANTIC target (other policies may still find one).
        return stop_anchor, None, f"{fam}|stop={stop[0]}|target=NONE"

    rule = f"{fam}|stop={stop[0]}|target={tgt[0]}"
    target_anchor = {"target_anchor_type": tgt[0], "target_anchor_object_id": tgt[1],
                     "target_anchor_price": float(tgt[2])}
    return stop_anchor, target_anchor, rule

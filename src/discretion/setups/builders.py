"""Path builders — one function per required setup-path family.

Each builder scans the primitive set for a causally coherent path and yields
frozen :class:`Setup` candidates (origin -> transition -> trigger, with a
structural stop, structural target and expiry). Builders never look past the
trigger bar to justify existence; outcome is evaluated separately later.

Coverage intent: collectively these builders exercise every required primitive
family as origin/transition/trigger, both continuation and fade, and paths with
and without FVG / iFVG / RB / liquidity sweep.
"""

from __future__ import annotations

from .structural import (
    nearest_level_above, nearest_level_below, STOP_BUFFER,
)


def _atr(F, seq):
    a = F.ps.atr[seq] if 0 <= seq < len(F.ps.atr) else None
    return a


def _disp_index(F):
    return {d.created_seq: d for d in F.ps.displacements}


# --------------------------------------------------------------------------
# FVG builders
# --------------------------------------------------------------------------

def _fvg_common(F, fvg, entry_seq, entry_price, mode, transition_ids,
                path_family, cont_or_fade, extra_ctx):
    """Assemble an FVG continuation candidate (long bull / short bear)."""
    if fvg.direction > 0:  # bullish -> long continuation
        direction = "long"
        stop = fvg.lo - STOP_BUFFER
        target = nearest_level_above(entry_price, entry_seq, fvg.segment_id, F.levels)
    else:                  # bearish -> short continuation
        direction = "short"
        stop = fvg.hi + STOP_BUFFER
        target = nearest_level_below(entry_price, entry_seq, fvg.segment_id, F.levels)
    tgt_price = target.price_ref if target else None
    graph = f"fvg:{fvg.subtype}:formed -> {mode} -> {cont_or_fade}"
    ctx = ["fvg_fresh"] + extra_ctx
    return F.make(
        direction=direction, path_family=path_family, graph=graph,
        entry_mode=mode, origin_id=fvg.id, transition_ids=transition_ids,
        primitive_ids=[fvg.id], context_conditions=ctx[:3],
        entry_seq=entry_seq, entry_price=entry_price, stop=stop, target=tgt_price,
        cont_or_fade=cont_or_fade, has_fvg=True,
    )


def build_fvg_formation(F):
    """Formation-close and next-bar continuation entries, sized gaps only."""
    disp = _disp_index(F)
    for fvg in F.ps.fvgs:
        a = _atr(F, fvg.created_seq)
        if not a or (fvg.hi - fvg.lo) < 0.5 * a:
            continue  # require a materially sized gap for a formation entry
        d = disp.get(fvg.c_seq) or disp.get(fvg.c_seq - 1)
        ctx = []
        if d is not None and d.grade == "good" and d.direction == fvg.direction:
            ctx.append("good_displacement")
        # formation-close entry at the C-bar close
        yield _fvg_common(
            F, fvg, fvg.created_seq, F.bars[fvg.created_seq].close,
            "formation_close", [fvg.id], "formation_continuation",
            "continuation", ctx,
        )
        # next-bar entry
        nb = fvg.created_seq + 1
        if nb < len(F.bars) and F.bars[nb].segment_id == fvg.segment_id:
            yield _fvg_common(
                F, fvg, nb, F.bars[nb].open, "next_bar",
                [fvg.id], "formation_continuation", "continuation", ctx,
            )


def build_fvg_fill_entries(F):
    """First-touch, midpoint and full-fill retracement continuation entries."""
    for fvg in F.ps.fvgs:
        a = _atr(F, fvg.created_seq)
        if not a or (fvg.hi - fvg.lo) < 0.5 * a:
            continue
        ft = fvg.first_event("FIRST_TOUCH")
        if ft is not None:
            yield _fvg_common(
                F, fvg, ft.seq, fvg.near_edge, "first_touch", [fvg.id],
                "retracement_continuation", "continuation", ["first_touch"],
            )
        mp = fvg.first_event("MIDPOINT")
        if mp is not None:
            yield _fvg_common(
                F, fvg, mp.seq, fvg.price, "midpoint", [fvg.id],
                "retracement_continuation", "continuation", ["consequent_encroach"],
            )
        ff = fvg.first_event("FULL_FILL")
        # full-fill continuation only if the gap did NOT close through (still coherent)
        if ff is not None and not fvg.has_event("FAILURE"):
            yield _fvg_common(
                F, fvg, ff.seq, fvg.far_edge, "full_fill", [fvg.id],
                "retracement_continuation", "continuation", ["full_fill_hold"],
            )


# --------------------------------------------------------------------------
# iFVG builders
# --------------------------------------------------------------------------

def _ifvg_candidate(F, iv, entry_seq, entry_price, mode, transition_ids, ctx):
    if iv.direction > 0:  # bullish iFVG -> long
        direction = "long"
        stop = iv.lo - STOP_BUFFER
        target = nearest_level_above(entry_price, entry_seq, iv.segment_id, F.levels)
    else:                 # bearish iFVG -> short
        direction = "short"
        stop = iv.hi + STOP_BUFFER
        target = nearest_level_below(entry_price, entry_seq, iv.segment_id, F.levels)
    tgt = target.price_ref if target else None
    graph = f"ifvg:{iv.subtype}:{mode} (from {iv.source_fvg_id})"
    return F.make(
        direction=direction, path_family="fade", graph=graph, entry_mode=mode,
        origin_id=iv.id, transition_ids=transition_ids,
        primitive_ids=[iv.id, iv.source_fvg_id], context_conditions=ctx[:3],
        entry_seq=entry_seq, entry_price=entry_price, stop=stop, target=tgt,
        cont_or_fade="fade", has_ifvg=True, has_fvg=True,
    )


def _ifvg_sized(F, iv):
    a = _atr(F, iv.created_seq)
    return bool(a) and (iv.hi - iv.lo) >= 0.5 * a


def build_ifvg_immediate(F):
    """Immediate iFVG entry at activation close and next bar (fade)."""
    for iv in F.ps.ifvgs:
        if not _ifvg_sized(F, iv):
            continue
        conf = iv.first_event("CONFIRMED")
        if conf is None:
            continue
        yield _ifvg_candidate(F, iv, conf.seq, F.bars[conf.seq].close,
                              "formation_close", [iv.id], ["ifvg_activation"])
        nb = conf.seq + 1
        if nb < len(F.bars) and F.bars[nb].segment_id == iv.segment_id:
            yield _ifvg_candidate(F, iv, nb, F.bars[nb].open, "next_bar",
                                  [iv.id], ["ifvg_activation"])


def build_ifvg_retest(F):
    """Later retest of the inverted zone (fade)."""
    for iv in F.ps.ifvgs:
        if not _ifvg_sized(F, iv):
            continue
        ft = iv.first_event("FIRST_TOUCH")
        if ft is None:
            continue
        edge = iv.lo if iv.direction < 0 else iv.hi
        yield _ifvg_candidate(F, iv, ft.seq, edge, "retest", [iv.id],
                              ["ifvg_retest"])


# --------------------------------------------------------------------------
# Rejection-block builders
# --------------------------------------------------------------------------

def _rb_candidate(F, rb, entry_seq, entry_price, mode, transition_ids, ctx):
    if rb.direction > 0:  # bullish -> long
        direction = "long"
        stop = rb.lo - STOP_BUFFER
        target = nearest_level_above(entry_price, entry_seq, rb.segment_id, F.levels)
    else:
        direction = "short"
        stop = rb.hi + STOP_BUFFER
        target = nearest_level_below(entry_price, entry_seq, rb.segment_id, F.levels)
    tgt = target.price_ref if target else None
    graph = f"rb:{rb.subtype}:{mode}"
    return F.make(
        direction=direction, path_family="formation_continuation", graph=graph,
        entry_mode=mode, origin_id=rb.id, transition_ids=transition_ids,
        primitive_ids=[rb.id], context_conditions=ctx[:3],
        entry_seq=entry_seq, entry_price=entry_price, stop=stop, target=tgt,
        cont_or_fade="continuation", has_rb=True,
    )


def build_rb_immediate(F):
    """RB confirmed-formation entry (reaction continuation, no FVG required)."""
    for rb in F.ps.rbs:
        conf = rb.first_event("CONFIRMED")
        if conf is None:
            continue
        yield _rb_candidate(F, rb, conf.seq, F.bars[conf.seq].close,
                            "formation_close", [rb.id], ["rb_confirmed"])


def build_rb_revisit(F):
    """RB first-revisit reaction entry."""
    for rb in F.ps.rbs:
        ft = rb.first_event("FIRST_TOUCH")
        if ft is None:
            continue
        edge = rb.hi if rb.direction > 0 else rb.lo
        yield _rb_candidate(F, rb, ft.seq, edge, "first_touch", [rb.id],
                            ["rb_revisit"])


# --------------------------------------------------------------------------
# Displacement retracement (no FVG / no RB required)
# --------------------------------------------------------------------------

def build_displacement_retracement(F):
    """Good displacement -> retrace into its own body -> continuation."""
    for d in F.ps.displacements:
        if d.grade != "good":
            continue
        # entry on the first later bar that retraces into the displacement range
        seg = d.segment_id
        entry_price = (d.lo + d.hi) / 2.0  # displacement midpoint (structural)
        for i in range(d.created_seq + 1, min(d.created_seq + 60, len(F.bars))):
            b = F.bars[i]
            if b.segment_id != seg:
                break
            if b.low <= entry_price <= b.high:
                if d.direction > 0:
                    direction = "long"
                    stop = d.lo - STOP_BUFFER
                    target = nearest_level_above(entry_price, i, seg, F.levels)
                else:
                    direction = "short"
                    stop = d.hi + STOP_BUFFER
                    target = nearest_level_below(entry_price, i, seg, F.levels)
                tgt = target.price_ref if target else None
                yield F.make(
                    direction=direction, path_family="retracement_continuation",
                    graph=f"displacement:good -> retrace_50 -> continuation",
                    entry_mode="midpoint", origin_id=d.id, transition_ids=[d.id],
                    primitive_ids=[d.id], context_conditions=["good_displacement"],
                    entry_seq=i, entry_price=entry_price, stop=stop, target=tgt,
                    cont_or_fade="continuation",
                )
                break


# --------------------------------------------------------------------------
# Level builders (time anchors + historical/liquidity) — continuation & fade
# --------------------------------------------------------------------------

def _level_fade(F, lv, ev):
    """Sweep/rejection of a level -> fade the other way."""
    b = F.bars[ev.seq]
    # fade direction = opposite the sweep side. note carries "above"/"below".
    if ev.note == "above":  # swept above, expect down
        direction = "short"
        entry_price = b.close
        stop = b.high + STOP_BUFFER
        target = nearest_level_below(entry_price, ev.seq, lv.segment_id, F.levels)
    else:                   # swept below, expect up
        direction = "long"
        entry_price = b.close
        stop = b.low - STOP_BUFFER
        target = nearest_level_above(entry_price, ev.seq, lv.segment_id, F.levels)
    tgt = target.price_ref if target else None
    return F.make(
        direction=direction, path_family="fade",
        graph=f"{lv.family}:{lv.subtype}:sweep -> reject -> fade",
        entry_mode="formation_close", origin_id=lv.id,
        transition_ids=[lv.id], primitive_ids=[lv.id],
        context_conditions=[f"{lv.family}_sweep"],
        entry_seq=ev.seq, entry_price=entry_price, stop=stop, target=tgt,
        cont_or_fade="fade", has_sweep=True,
    )


def _level_break_retest(F, lv):
    """Break + acceptance -> retest -> continuation."""
    brk = lv.first_event("BREAK")
    if brk is None:
        return None
    acc = lv.first_event("ACCEPTANCE_ABOVE") or lv.first_event("ACCEPTANCE_BELOW")
    if acc is None:
        return None
    up = brk.note == "up"
    # find retest of the level after acceptance
    for e in lv.events:
        if e.kind in ("REVISIT", "FIRST_TOUCH") and e.seq > acc.seq:
            entry_price = lv.price_ref
            if up:
                direction = "long"
                stop = lv.price_ref - 3 * STOP_BUFFER
                target = nearest_level_above(entry_price, e.seq, lv.segment_id, F.levels)
            else:
                direction = "short"
                stop = lv.price_ref + 3 * STOP_BUFFER
                target = nearest_level_below(entry_price, e.seq, lv.segment_id, F.levels)
            tgt = target.price_ref if target else None
            return F.make(
                direction=direction, path_family="retracement_continuation",
                graph=f"{lv.family}:{lv.subtype}:break -> accept -> retest -> continuation",
                entry_mode="retest", origin_id=lv.id, transition_ids=[lv.id],
                primitive_ids=[lv.id],
                context_conditions=[f"{lv.family}_accepted"],
                entry_seq=e.seq, entry_price=entry_price, stop=stop, target=tgt,
                cont_or_fade="continuation",
            )
    return None


def build_anchor_setups(F):
    for lv in F.ps.anchors:
        for ev in lv.events:
            if ev.kind == "SWEEP":
                yield _level_fade(F, lv, ev)
        yield _level_break_retest(F, lv)


def build_hist_level_setups(F):
    for lv in F.ps.session_levels:
        for ev in lv.events:
            if ev.kind == "SWEEP":
                yield _level_fade(F, lv, ev)
        yield _level_break_retest(F, lv)


def build_liquidity_sweep_setups(F):
    """Swing / equal-H-L liquidity sweep -> fade (classic stop run)."""
    for lv in F.ps.swings + F.ps.equal_levels:
        for ev in lv.events:
            if ev.kind == "SWEEP":
                yield _level_fade(F, lv, ev)


# --------------------------------------------------------------------------
# VWAP builders — continuation & fade
# --------------------------------------------------------------------------

def build_vwap_setups(F):
    for vs in F.ps.vwaps:
        for ev in vs.events:
            val = vs.value_at(ev.seq)
            if val is None:
                continue
            b = F.bars[ev.seq]
            seg = vs.segment_id
            if ev.kind == "REJECTION" and ev.note in ("vwap_bounce_up",):
                entry_price = b.close
                stop = min(b.low, val["vwap"]) - STOP_BUFFER
                target = nearest_level_above(entry_price, ev.seq, seg, F.levels)
                yield F.make(
                    direction="long", path_family="retracement_continuation",
                    graph="vwap:bounce -> continuation", entry_mode="first_touch",
                    origin_id=vs.id, transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["vwap_bounce"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop,
                    target=target.price_ref if target else None,
                    cont_or_fade="continuation",
                )
            elif ev.kind == "REJECTION" and ev.note in ("vwap_bounce_down",):
                entry_price = b.close
                stop = max(b.high, val["vwap"]) + STOP_BUFFER
                target = nearest_level_below(entry_price, ev.seq, seg, F.levels)
                yield F.make(
                    direction="short", path_family="retracement_continuation",
                    graph="vwap:bounce -> continuation", entry_mode="first_touch",
                    origin_id=vs.id, transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["vwap_bounce"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop,
                    target=target.price_ref if target else None,
                    cont_or_fade="continuation",
                )
            elif ev.kind == "REJECTION" and ev.note and ev.note.startswith("band_reject_+"):
                # upper-band rejection -> fade back toward vwap
                entry_price = b.close
                stop = b.high + STOP_BUFFER
                yield F.make(
                    direction="short", path_family="fade",
                    graph=f"vwap:{ev.note} -> fade_to_vwap", entry_mode="formation_close",
                    origin_id=vs.id, transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["band_rejection"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop, target=val["vwap"],
                    cont_or_fade="fade",
                )
            elif ev.kind == "REJECTION" and ev.note and ev.note.startswith("band_reject_-"):
                entry_price = b.close
                stop = b.low - STOP_BUFFER
                yield F.make(
                    direction="long", path_family="fade",
                    graph=f"vwap:{ev.note} -> fade_to_vwap", entry_mode="formation_close",
                    origin_id=vs.id, transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["band_rejection"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop, target=val["vwap"],
                    cont_or_fade="fade",
                )
            elif ev.kind == "ACCEPTANCE_ABOVE" and ev.note == "vwap":
                entry_price = b.close
                stop = val["vwap"] - STOP_BUFFER
                target = nearest_level_above(entry_price, ev.seq, seg, F.levels)
                yield F.make(
                    direction="long", path_family="formation_continuation",
                    graph="vwap:break_accept_above -> continuation",
                    entry_mode="formation_close", origin_id=vs.id,
                    transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["vwap_accept_above"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop,
                    target=target.price_ref if target else None,
                    cont_or_fade="continuation",
                )
            elif ev.kind == "ACCEPTANCE_BELOW" and ev.note == "vwap":
                entry_price = b.close
                stop = val["vwap"] + STOP_BUFFER
                target = nearest_level_below(entry_price, ev.seq, seg, F.levels)
                yield F.make(
                    direction="short", path_family="formation_continuation",
                    graph="vwap:break_accept_below -> continuation",
                    entry_mode="formation_close", origin_id=vs.id,
                    transition_ids=[vs.id], primitive_ids=[vs.id],
                    context_conditions=["vwap_accept_below"], entry_seq=ev.seq,
                    entry_price=entry_price, stop=stop,
                    target=target.price_ref if target else None,
                    cont_or_fade="continuation",
                )


# --------------------------------------------------------------------------
# Structure builders: compression/expansion, swing break/retest, failed break
# --------------------------------------------------------------------------

def build_compression_expansion(F):
    for z in F.ps.structures:
        if z.subtype != "compression":
            continue
        brk = z.first_event("BREAK")
        if brk is None:
            continue
        up = brk.note == "up"
        entry_seq = brk.seq
        b = F.bars[entry_seq]
        cont = z.first_event("CONTINUATION")
        failed = z.first_event("FAILED_CONTINUATION")
        if cont is not None and (failed is None or cont.seq <= failed.seq):
            # compression -> expansion -> continuation
            if up:
                direction, stop = "long", z.band_lo - STOP_BUFFER
                target = nearest_level_above(b.close, entry_seq, z.segment_id, F.levels)
            else:
                direction, stop = "short", z.band_hi + STOP_BUFFER
                target = nearest_level_below(b.close, entry_seq, z.segment_id, F.levels)
            yield F.make(
                direction=direction, path_family="formation_continuation",
                graph="compression -> expansion -> continuation",
                entry_mode="next_bar", origin_id=z.id, transition_ids=[z.id],
                primitive_ids=[z.id], context_conditions=["compression_break"],
                entry_seq=entry_seq, entry_price=b.close, stop=stop,
                target=target.price_ref if target else None,
                cont_or_fade="continuation",
            )
        if failed is not None:
            # compression breakout failure -> return-to-range fade
            fb = F.bars[failed.seq]
            if up:  # broke up, failed -> fade short back into range
                direction, stop = "short", fb.high + STOP_BUFFER
                target = nearest_level_below(fb.close, failed.seq, z.segment_id, F.levels)
                if target is None:
                    target_price = z.band_lo
                else:
                    target_price = target.price_ref
            else:
                direction, stop = "long", fb.low - STOP_BUFFER
                target = nearest_level_above(fb.close, failed.seq, z.segment_id, F.levels)
                target_price = target.price_ref if target else z.band_hi
            yield F.make(
                direction=direction, path_family="fade",
                graph="compression -> failed_break -> return_to_range_fade",
                entry_mode="formation_close", origin_id=z.id, transition_ids=[z.id],
                primitive_ids=[z.id], context_conditions=["failed_break"],
                entry_seq=failed.seq, entry_price=fb.close, stop=stop,
                target=target_price, cont_or_fade="fade",
            )


def build_swing_break_retest(F):
    """Swing break + acceptance -> retest -> continuation (no FVG/sweep)."""
    for lv in F.ps.swings:
        s = _level_break_retest(F, lv)
        if s is not None:
            yield s


def build_failed_swing_break(F):
    """Failed swing break (sweep then reclaim) -> reversal fade."""
    for lv in F.ps.swings:
        for ev in lv.events:
            if ev.kind == "SWEEP":
                yield _level_fade(F, lv, ev)


ALL_BUILDERS = [
    build_fvg_formation,
    build_fvg_fill_entries,
    build_ifvg_immediate,
    build_ifvg_retest,
    build_rb_immediate,
    build_rb_revisit,
    build_displacement_retracement,
    build_anchor_setups,
    build_hist_level_setups,
    build_liquidity_sweep_setups,
    build_vwap_setups,
    build_compression_expansion,
    build_swing_break_retest,
    build_failed_swing_break,
]

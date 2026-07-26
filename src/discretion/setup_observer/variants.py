"""Frozen entry-variant enumeration (spec Part 5).

One physical episode (a context structure interacted with at a specific time on
a specific trigger timeframe) spawns SEPARATE frozen research variants -- one per
causally-applicable entry rule. They are distinct setup hypotheses, never
duplicate trades. Each variant freezes independently using ONLY bars through its
own trigger: an ENTRY_ON_TAP variant cannot know whether later displacement
occurred; an ENTRY_ON_DELAYED_DISPLACEMENT variant may use bars only through
that displacement. Later path information is outcome/descriptive, never folded
back into an earlier variant's fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import (WIDTH_ATR_BINS, WICKBODY_BINS, RR_BINS, DELAY_BINS,
                     _bin, _avail, _tf_start_seq, MIN_EXECUTABLE_RR)
from . import reaction_states as rs
from .sessions import time_window_fields
from .atr_floors import (atr1m_at_trigger, atr5m_at_trigger, stop_floor, target_floor_ok,
                         TARGET_BELOW_5M_ATR, ATR_FLOOR_UNAVAILABLE)
from ..data.cme_session import session_date

# entry-rule -> (offset-key in classification, frozen reaction_state label)
RULE_SPEC = [
    ("ENTRY_ON_TAP", rs.TAP_ONLY, rs.TAP_ONLY),
    ("ENTRY_ON_FIRST_CLOSE_OUTSIDE", rs.CLOSE_BACK_OUTSIDE, rs.CLOSE_BACK_OUTSIDE),
    ("ENTRY_ON_MINIMAL_WICK_REJECTION", rs.MINIMAL_WICK_REJECTION, rs.MINIMAL_WICK_REJECTION),
    ("ENTRY_ON_STRONG_REJECTION", rs.STRONG_REJECTION_DEPARTURE, rs.STRONG_REJECTION_DEPARTURE),
    ("ENTRY_ON_IMMEDIATE_DISPLACEMENT", rs.IMMEDIATE_DISPLACEMENT, rs.IMMEDIATE_DISPLACEMENT),
    ("ENTRY_ON_DELAYED_DISPLACEMENT", rs.DELAYED_DISPLACEMENT, rs.DELAYED_DISPLACEMENT),
    ("ENTRY_ON_COMPRESSION_BREAK", rs.COMPRESSION_THEN_BREAK, rs.COMPRESSION_THEN_BREAK),
    ("ENTRY_ON_NEW_FVG", "NEW_FVG", "NEW_FVG"),
    ("ENTRY_ON_NEW_IFVG", "NEW_IFVG", "NEW_IFVG"),
]
IFVG_RETEST_RULE = ("ENTRY_ON_IFVG_RETEST", rs.TAP_ONLY, "IFVG_RETEST")


@dataclass
class Variant:
    episode_id: str
    variant_id: str
    entry_variant: str
    reaction_state: str
    lane: str
    direction: int
    # timeframe architecture (independently preserved)
    context_tf: int
    interaction_tf: int
    reaction_tf: int
    confirmation_tf: int
    trigger_tf: int
    is_multi_timeframe: bool
    # components / lineage
    context_id: str
    context_family: str
    component_ids: list
    confluence: bool
    context_zone: tuple
    context_formation_ts: object
    # causal stages (global 1m seq + ts)
    interaction_seq: int
    interaction_ts: object
    trigger_seq: int
    trigger_ts: object
    entry_seq: int
    entry_ts: object
    interaction_to_trigger_delay: int
    penetration_depth: float
    # session / time
    session: str
    et_hour: int
    minutes_from_0930: int
    minutes_from_1000: int
    day_of_week: str
    session_date_et: object
    # descriptive reaction through trigger only (causal freeze)
    reaction_measures_through_trigger: list
    # rb descriptive
    rb_wick_body: object
    rb_activated_at_trigger: object
    rb_activation_only_after_trigger: object
    # setup
    entry_price: float
    stop_price: float                 # raw structural stop (invalidation)
    stop_anchor_desc: str
    targets: dict
    considered_targets: list
    target_exclusion_counts: dict
    # ATR(24) absolute-volatility floors (causal, completed candles only)
    atr_1m_24: object
    atr_5m_24: object
    raw_stop_price: float
    raw_stop_distance: float
    effective_stop_price: float
    effective_stop_distance: float
    stop_widened_by_atr_floor: bool
    target_distance: object
    target_distance_atr5_multiple: object
    atr_floor_target_ok: bool
    natural_rr: object                # recalculated with the effective stop
    executable: bool
    rejection_reason: str
    fingerprint: dict = field(default_factory=dict)


def _rb_activation(ctx, series, trigger_global):
    rb = ctx.get("rb")
    if rb is None:
        return None, None, None
    wb = round(rb.wick_body_ratio, 4)
    if rb.activated and rb.activation_seq is not None:
        act_global = _avail(ctx["context_tf"], series[ctx["context_tf"]], rb.activation_seq)
        activated_at_trigger = act_global <= trigger_global
        only_after = act_global > trigger_global
    else:
        activated_at_trigger = False
        only_after = False
    return wb, activated_at_trigger, only_after


def _fingerprint(v: Variant):
    prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
    rb_class = ("ACTIVATED" if v.rb_activated_at_trigger else "NOT_ACTIVATED") \
        if v.rb_wick_body is not None else "NA"
    return {
        "lane": v.lane, "entry_variant": v.entry_variant, "reaction_state": v.reaction_state,
        "direction": v.direction,
        "context_tf": v.context_tf, "interaction_tf": v.interaction_tf,
        "reaction_tf": v.reaction_tf, "confirmation_tf": v.confirmation_tf,
        "trigger_tf": v.trigger_tf, "is_multi_timeframe": v.is_multi_timeframe,
        "session": v.session, "day_of_week": v.day_of_week,
        "context_family": v.context_family, "confluence": v.confluence,
        "rb_activation_class": rb_class,
        "interaction_to_trigger_delay_bin": _bin(v.interaction_to_trigger_delay, DELAY_BINS),
        "target_family": (prim.family if prim else "none"),
        "target_tf": (prim.timeframe if prim else "none"),
        # RR binned on the EFFECTIVE (ATR-floored) stop -- part of the match key
        "natural_rr_bin": _bin(v.natural_rr, RR_BINS),
        # stored for transparency (NOT matching keys -- absolute floats)
        "atr_1m_24": v.atr_1m_24, "atr_5m_24": v.atr_5m_24,
    }


def build_variants(episode_id, ctx, trigger_tf, series, atr, bars, i_idx, cls,
                   resolve_fn, confluence_ids, atrf):
    """Return the list of frozen Variant records for this physical episode.

    ``atrf`` supplies causal ATR(24) references: {"a1": atr24_1m aligned to
    ``bars``, "a5": atr24_5m aligned to the 5m series, "avail5": ascending 5m
    availability-seq array}."""
    direction = ctx["direction"]
    ctx_tf = ctx["context_tf"]
    zone_lo, zone_hi = ctx["context_zone"]
    s = series[trigger_tf]
    n = len(bars)
    is_mtf = trigger_tf != ctx_tf

    # structural stop (a price level, timeframe-independent)
    if ctx.get("rb") is not None:
        so, sh, sl, sc = ctx["rb"].source_ohlc
        stop_price = sl if direction > 0 else sh
        stop_desc = "beyond the RB source-candle wick extreme (block invalidation)"
    else:
        stop_price = zone_lo if direction > 0 else zone_hi
        stop_desc = "beyond the structure's distal boundary (structure invalidation)"

    rules = list(RULE_SPEC)
    if ctx.get("is_ifvg"):
        # for an iFVG context the tap is a retest of the inverted zone
        rules = [IFVG_RETEST_RULE] + [r for r in rules if r[0] != "ENTRY_ON_TAP"]

    out = []
    for entry_variant, off_key, state in rules:
        offset = cls["offsets"].get(off_key)
        if offset is None:
            continue
        j = i_idx + offset
        if j >= len(s):
            continue
        entry_seq = _avail(trigger_tf, s, j)
        if entry_seq >= n:
            continue
        valid_stop = (stop_price < bars[entry_seq].open) if direction > 0 \
            else (stop_price > bars[entry_seq].open)
        entry_price = bars[entry_seq].open
        trigger_global = _avail(trigger_tf, s, j)
        selected, considered, excl_counts = ({}, [], {})
        if valid_stop:
            selected, considered, excl_counts = resolve_fn(
                entry_seq, direction, entry_price, stop_price, ctx_tf,
                ctx["context_family"], set(confluence_ids))
        prim = selected.get("NEAREST_OPPOSING_VALID_STRUCTURE")

        # ---- causal ATR(24) absolute-volatility floors ----
        atr_1m = atr1m_at_trigger(atrf["a1"], entry_seq)
        atr_5m = atr5m_at_trigger(atrf["a5"], atrf["avail5"], entry_seq)
        sf = stop_floor(entry_price, direction, stop_price, atr_1m)
        eff_dist = sf["effective_stop_distance"]
        tgt_dist = round(abs(prim.surface - entry_price), 4) if prim else None
        tgt_atr5_mult = (round(tgt_dist / atr_5m, 4) if (tgt_dist is not None and atr_5m) else None)
        floor_target_ok = target_floor_ok(tgt_dist, atr_5m)
        natural_rr = (round(tgt_dist / eff_dist, 4) if (tgt_dist is not None and eff_dist > 0) else None)

        if not valid_stop:
            reason = "NO_STRUCTURAL_STOP"
        elif prim is None:
            reason = "NO_CAUSAL_OPPOSING_TARGET"
        elif atr_1m is None or atr_5m is None:
            reason = ATR_FLOOR_UNAVAILABLE
        elif not floor_target_ok:
            reason = TARGET_BELOW_5M_ATR
        elif natural_rr is None or natural_rr < MIN_EXECUTABLE_RR:
            reason = "INSUFFICIENT_NATURAL_RR"
        else:
            reason = ""
        executable = (reason == "")

        rb_wb, rb_act, rb_only_after = _rb_activation(ctx, series, trigger_global)
        # causal freeze: measures only through this variant's own trigger
        through = [m for m in cls["trace"] if m["k"] <= offset]
        interaction_global = _tf_start_seq(trigger_tf, s, i_idx)
        entry_bar = bars[entry_seq]
        tw = time_window_fields(entry_bar.ts_et)

        v = Variant(
            episode_id=episode_id, variant_id=f"{episode_id}-{entry_variant}",
            entry_variant=entry_variant, reaction_state=state, lane=ctx["lane"],
            direction=direction, context_tf=ctx_tf, interaction_tf=trigger_tf,
            reaction_tf=trigger_tf, confirmation_tf=trigger_tf, trigger_tf=trigger_tf,
            is_multi_timeframe=is_mtf, context_id=ctx["context_id"],
            context_family=ctx["context_family"], component_ids=sorted(confluence_ids),
            confluence=len(set(confluence_ids)) > 1, context_zone=(zone_lo, zone_hi),
            context_formation_ts=ctx["context_formation_ts"],
            interaction_seq=interaction_global,
            interaction_ts=s[i_idx].ts_et if trigger_tf == 1 else None,
            trigger_seq=trigger_global,
            trigger_ts=bars[min(trigger_global, n - 1)].ts_et,
            entry_seq=entry_seq, entry_ts=entry_bar.ts_et,
            interaction_to_trigger_delay=offset, penetration_depth=cls["penetration_depth"],
            session=tw["session"], et_hour=tw["et_hour"],
            minutes_from_0930=tw["minutes_from_0930"], minutes_from_1000=tw["minutes_from_1000"],
            day_of_week=tw["day_of_week"], session_date_et=session_date(entry_bar.ts_et),
            reaction_measures_through_trigger=through,
            rb_wick_body=rb_wb, rb_activated_at_trigger=rb_act,
            rb_activation_only_after_trigger=rb_only_after,
            entry_price=entry_price, stop_price=stop_price, stop_anchor_desc=stop_desc,
            targets=selected, considered_targets=considered,
            target_exclusion_counts=excl_counts,
            atr_1m_24=(round(atr_1m, 4) if atr_1m is not None else None),
            atr_5m_24=(round(atr_5m, 4) if atr_5m is not None else None),
            raw_stop_price=sf["raw_stop_price"], raw_stop_distance=sf["raw_stop_distance"],
            effective_stop_price=sf["effective_stop_price"],
            effective_stop_distance=sf["effective_stop_distance"],
            stop_widened_by_atr_floor=sf["stop_widened_by_atr_floor"],
            target_distance=tgt_dist, target_distance_atr5_multiple=tgt_atr5_mult,
            atr_floor_target_ok=floor_target_ok, natural_rr=natural_rr,
            executable=executable, rejection_reason=reason,
        )
        v.fingerprint = _fingerprint(v)
        out.append(v)
    return out

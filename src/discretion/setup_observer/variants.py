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
    stop_price: float
    stop_anchor_desc: str
    targets: dict
    considered_targets: list
    target_exclusion_counts: dict
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
        "natural_rr_bin": _bin(prim.natural_rr if prim else None, RR_BINS),
    }


def build_variants(episode_id, ctx, trigger_tf, series, atr, bars, i_idx, cls,
                   resolve_fn, confluence_ids):
    """Return the list of frozen Variant records for this physical episode."""
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
        if not valid_stop:
            reason = "NO_STRUCTURAL_STOP"
        elif prim is None:
            reason = "NO_CAUSAL_OPPOSING_TARGET"
        elif prim.natural_rr is None or prim.natural_rr < MIN_EXECUTABLE_RR:
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
            executable=executable, rejection_reason=reason,
        )
        v.fingerprint = _fingerprint(v)
        out.append(v)
    return out

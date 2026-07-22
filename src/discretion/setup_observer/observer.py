"""Coherent ICT setup observer over the FROZEN audited primitives.

A coherent setup episode requires (spec): PRE-EXISTING CONTEXT -> INTERACTION
-> SUBSEQUENT CONFIRMATION -> CAUSAL TRIGGER -> STRUCTURAL STOP -> causally
available TARGET (or explicit no-target rejection). A bare structure or bare
tap is never a setup -- those stay in the atomic diagnostic stream
(ATOMIC_RB_TAP_EVENT / ATOMIC_IFVG_ACTIVATION_EVENT), produced by
discretion.causal_replay, not here.

Only discretion.primitive_reset structures are consumed (FVG2/IFVG2/RB2 ids).
Everything is causal: interaction < confirmation < trigger; entry is the next
1-minute bar; nothing with availability after the trigger is referenced. No
outcome is computed here (outcomes live in outcomes.py, observation-week only).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..primitive_reset.timeframes import candle_series, atr_series, candle_ts_et, TIMEFRAMES
from ..primitive_reset.registry import ResetRegistry
from ..primitive_reset.fvg import detect_fvgs
from ..primitive_reset.ifvg import detect_ifvgs
from ..primitive_reset.rejection_block import detect_rejection_blocks
from ..data.cme_session import session_date
from .sessions import time_window_fields
from .displacement import measure_reaction, CONFIRM_WINDOW

MIN_EXECUTABLE_RR = 0.5   # frozen execution floor (reused, unchanged)

# frozen continuous-feature bins for EXACT matching
WIDTH_ATR_BINS = ((0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 1e9))
WICKBODY_BINS = ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 1e9))
RR_BINS = ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 1e9))


def _bin(x, bins):
    if x is None:
        return "na"
    for lo, hi in bins:
        if lo <= x < hi:
            return f"{lo}-{hi}"
    return f">{bins[-1][0]}"


def _dir(word):
    return 1 if word == "bullish" else -1


def _avail(tf, series, candle_seq):
    return candle_seq + 1 if tf == 1 else series[candle_seq].available_seq


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


@dataclass
class Episode:
    episode_id: str
    lane: str                      # A/B/C/D/E
    direction: int
    # timeframe architecture
    context_tf: int
    interaction_tf: int
    confirmation_tf: int
    trigger_tf: int
    # causal indices (global 1m)
    interaction_seq: int
    confirmation_seq: int
    trigger_seq: int               # confirmation candle (trigger fires at its close)
    entry_seq: int
    # session/time
    session: str = ""
    et_hour: int = 0
    minutes_from_0930: int = 0
    minutes_from_1000: int = 0
    day_of_week: str = ""
    session_date_et: object = None
    # components / lineage
    context_id: str = ""
    context_family: str = ""
    component_ids: list = field(default_factory=list)
    atomic_event_ids: list = field(default_factory=list)
    confluence: bool = False
    confluence_ids: list = field(default_factory=list)
    # context descriptive
    context_zone: tuple = (0.0, 0.0)
    context_formation_ts: object = None
    context_age_bars_at_interaction: int = 0
    fvg_width_atr: object = None
    ifvg_inversion_speed: object = None
    rb_wick_body: object = None
    rb_dominant_ratio: object = None
    rb_activated_at_interaction: object = None
    rb_activated_at_confirmation: object = None
    rb_activated_at_trigger: object = None
    rb_activation_age: object = None
    rb_activation_only_after_setup: object = None
    prior_tap_count: int = 0
    # reaction
    displacement_branch: str = ""
    confirm_reason: str = ""
    interaction_to_confirmation_delay: int = 0
    reaction_measures: list = field(default_factory=list)
    new_fvg_after_interaction: bool = False
    new_ifvg_after_interaction: bool = False
    # setup
    entry_price: float = 0.0
    stop_price: float = 0.0
    stop_anchor_desc: str = ""
    targets: list = field(default_factory=list)     # TargetCandidate per policy
    executable: bool = False
    rejection_reason: str = ""
    # frozen fingerprint (categorical + binned)
    fingerprint: dict = field(default_factory=dict)


def _detect(bars):
    reg = ResetRegistry()
    series, atr, fvgs, ifvgs, rbs = {}, {}, {}, {}, {}
    for tf in TIMEFRAMES:
        s = candle_series(bars, tf)
        a = atr_series(s)
        series[tf], atr[tf] = s, a
        fvgs[tf] = detect_fvgs(bars, tf, reg)
        ifvgs[tf] = detect_ifvgs(bars, tf, fvgs[tf], a, s, reg)
        rbs[tf] = detect_rejection_blocks(bars, tf, s, a, reg)
    ts_index = {tf: {candle_ts_et(c): i for i, c in enumerate(series[tf])} for tf in TIMEFRAMES}
    return series, atr, fvgs, ifvgs, rbs, ts_index


def _all_structures(fvgs, ifvgs, rbs, series, ts_index):
    """Uniform (id, family, tf, direction, lo, hi, avail_seq) for targeting."""
    out = []
    for tf in TIMEFRAMES:
        s = series[tf]
        for f in fvgs[tf]:
            out.append((f.id, "fvg", tf, _dir(f.direction), f.lo, f.hi, _avail(tf, s, f.c_seq)))
        for iv in ifvgs[tf]:
            idx = ts_index[tf].get(iv.activation_ts)
            if idx is None:
                continue
            out.append((iv.id, "ifvg", tf, _dir(iv.child_direction), iv.lo, iv.hi, _avail(tf, s, idx)))
        for rb in rbs[tf]:
            out.append((rb.id, "rb", tf, _dir(rb.direction), rb.zone_lo, rb.zone_hi,
                        _avail(tf, s, rb.source_seq)))
    return out


def _targets(all_structs, entry_seq, direction, entry_price, stop_price, context_tf, exclude_ids):
    risk = abs(entry_price - stop_price)
    elig = []
    for sid, fam, tf, sdir, lo, hi, avail in all_structs:
        if sid in exclude_ids or avail > entry_seq:
            continue
        surface = lo if direction > 0 else hi
        if (direction > 0 and surface <= entry_price) or (direction < 0 and surface >= entry_price):
            continue
        dist = abs(surface - entry_price)
        rr = (dist / risk) if risk > 0 else None
        elig.append({"sid": sid, "fam": fam, "tf": tf, "sdir": sdir, "surface": surface,
                     "dist": dist, "avail": avail, "rr": rr})
    if not elig:
        return []
    def mk(policy, e):
        return TargetCandidate(policy=policy, structure_id=e["sid"], family=e["fam"],
                               timeframe=e["tf"], surface=e["surface"], distance=e["dist"],
                               freshness_bars=entry_seq - e["avail"], availability_seq=e["avail"],
                               natural_rr=(round(e["rr"], 4) if e["rr"] is not None else None))
    out = []
    nearest = min(elig, key=lambda e: e["dist"])
    out.append(mk("NEAREST_VALID_STRUCTURE", nearest))
    opposing = [e for e in elig if e["sdir"] == -direction]
    if opposing:
        out.append(mk("BRANCH_SEMANTIC_TARGET", min(opposing, key=lambda e: e["dist"])))
    htf_opp = [e for e in elig if e["sdir"] == -direction and e["tf"] >= context_tf]
    if htf_opp:
        out.append(mk("NEAREST_OPPOSING_HIGHER_TF_STRUCTURE", min(htf_opp, key=lambda e: e["dist"])))
    return out


def _form_idx_by_dir(fvgs, ifvgs, ts_index, tf, series):
    """Sets of same-tf candle indices where an FVG formed / iFVG activated,
    keyed by direction (+1/-1)."""
    fv = {1: set(), -1: set()}
    ifv = {1: set(), -1: set()}
    for f in fvgs[tf]:
        fv[_dir(f.direction)].add(f.c_seq)
    for iv in ifvgs[tf]:
        idx = ts_index[tf].get(iv.activation_ts)
        if idx is not None:
            ifv[_dir(iv.child_direction)].add(idx)
    return fv, ifv


def observe(bars):
    """Return (episodes, diagnostics). Episodes are coherent, deduplicated,
    fully causal, pre-outcome."""
    series, atr, fvgs, ifvgs, rbs, ts_index = _detect(bars)
    all_structs = _all_structures(fvgs, ifvgs, rbs, series, ts_index)
    form_by_tf = {tf: _form_idx_by_dir(fvgs, ifvgs, ts_index, tf, series[tf]) for tf in TIMEFRAMES}
    n = len(bars)

    raw = []   # candidate episodes before dedup

    def add_candidate(lane, tf, direction, i_idx, context_id, context_family,
                      context_zone, context_form_ts, context_form_seq, extra):
        s = series[tf]
        if i_idx is None or i_idx + 1 >= len(s):
            return
        fv, ifv = form_by_tf[tf]
        fvg_form = {j for j in fv[direction] if j > i_idx}
        ifvg_form = {j for j in ifv[direction] if j > i_idx}
        inval = extra.get("invalidation_idx")
        r = measure_reaction(s, atr[tf], i_idx, direction, context_zone[0], context_zone[1],
                             fvg_form, ifvg_form, invalidation_idx=inval)
        if r["confirm_idx"] is None:
            return   # not a coherent setup (scraping / failed) -> diagnostic only
        c_idx = r["confirm_idx"]
        entry_seq = _avail(tf, s, c_idx)
        if entry_seq >= n:
            return
        raw.append({
            "lane": lane, "tf": tf, "direction": direction, "i_idx": i_idx,
            "confirm_idx": c_idx, "entry_seq": entry_seq, "context_id": context_id,
            "context_family": context_family, "context_zone": context_zone,
            "context_form_ts": context_form_ts,
            "context_age": i_idx - context_form_seq if context_form_seq is not None else 0,
            "reaction": r, "extra": extra,
            "interaction_seq_global": _avail(tf, s, i_idx),
            "trigger_seq_global": _avail(tf, s, c_idx),
        })

    # ---- Lane A: RB rejection (context RB, interaction = first tap) ----
    for tf in TIMEFRAMES:
        s = series[tf]
        for rb in rbs[tf]:
            if not rb.tap_events:
                continue
            i_idx = rb.tap_events[0]["seq"]
            direction = _dir(rb.direction)
            inval = None
            if rb.deactivation_reason in ("DEACTIVATED_CLOSE_THROUGH", "DEACTIVATED_OVERSHOOT_LIMIT") \
               and rb.deactivation_ts is not None:
                inval = ts_index[tf].get(rb.deactivation_ts)
            add_candidate("A", tf, direction, i_idx, rb.id, "rb",
                          (rb.zone_lo, rb.zone_hi), rb.source_ts, rb.source_seq,
                          {"rb": rb, "invalidation_idx": inval})

    # ---- Lane B: FVG reaction (context FVG, interaction = first touch) ----
    for tf in TIMEFRAMES:
        s = series[tf]
        for f in fvgs[tf]:
            if f.first_touch_seq is None:
                continue
            direction = _dir(f.direction)
            inval = f.inversion_seq
            add_candidate("B", tf, direction, f.first_touch_seq, f.id, "fvg",
                          (f.lo, f.hi), f.formation_ts, f.c_seq,
                          {"fvg": f, "invalidation_idx": inval})

    # ---- Lane C: iFVG direct (interaction = activation/inversion) ----
    for tf in TIMEFRAMES:
        s = series[tf]
        for iv in ifvgs[tf]:
            idx = ts_index[tf].get(iv.activation_ts)
            if idx is None:
                continue
            direction = _dir(iv.child_direction)
            add_candidate("C", tf, direction, idx, iv.id, "ifvg",
                          (iv.lo, iv.hi), iv.activation_ts, idx,
                          {"ifvg": iv, "invalidation_idx": None})

    # ---- Lane D: iFVG retest (interaction = first_touch after activation) ----
    for tf in TIMEFRAMES:
        for iv in ifvgs[tf]:
            if iv.first_touch_ts is None:
                continue
            idx = ts_index[tf].get(iv.first_touch_ts)
            act_idx = ts_index[tf].get(iv.activation_ts)
            if idx is None or act_idx is None or idx <= act_idx:
                continue
            direction = _dir(iv.child_direction)
            add_candidate("D", tf, direction, idx, iv.id, "ifvg",
                          (iv.lo, iv.hi), iv.activation_ts, act_idx,
                          {"ifvg": iv, "invalidation_idx": None})

    # ---- physical dedup: group by (direction, entry_seq); merge overlapping contexts ----
    raw.sort(key=lambda r: (r["entry_seq"], -r["tf"], r["context_id"]))
    episodes = []
    used = [False] * len(raw)
    eid = 0
    for a_i in range(len(raw)):
        if used[a_i]:
            continue
        a = raw[a_i]
        group = [a]
        used[a_i] = True
        for b_i in range(a_i + 1, len(raw)):
            if used[b_i]:
                continue
            b = raw[b_i]
            if b["entry_seq"] != a["entry_seq"] or b["direction"] != a["direction"]:
                continue
            # materially overlapping context zones -> same physical setup
            alo, ahi = a["context_zone"]; blo, bhi = b["context_zone"]
            if max(alo, blo) <= min(ahi, bhi):
                group.append(b)
                used[b_i] = True
        eid += 1
        episodes.append(_finalize(f"EP-{eid:05d}", group, bars, all_structs, series))

    diagnostics = {
        "n_episodes": len(episodes),
        "by_lane": {ln: sum(1 for e in episodes if e.lane == ln) for ln in ("A", "B", "C", "D", "E")},
        "n_executable": sum(1 for e in episodes if e.executable),
    }
    return episodes, diagnostics


def _finalize(eid, group, bars, all_structs, series):
    # primary = highest timeframe then earliest interaction
    primary = sorted(group, key=lambda r: (-r["tf"], r["i_idx"]))[0]
    tf = primary["tf"]
    direction = primary["direction"]
    entry_seq = primary["entry_seq"]
    entry_bar = bars[entry_seq]
    entry_price = entry_bar.open
    r = primary["reaction"]
    extra = primary["extra"]
    confluence_ids = sorted({g["context_id"] for g in group})
    confluence = len(confluence_ids) > 1

    # lane E refinement: RB context confirmed by a NEW same-dir FVG/iFVG
    lane = primary["lane"]
    if lane == "A" and r["confirm_reason"] in ("same_dir_fvg", "same_dir_ifvg"):
        lane = "E"

    # ---- structural stop ----
    if extra.get("rb") is not None:
        rb = extra["rb"]
        so, sh, sl, sc = rb.source_ohlc
        stop_price = sl if direction > 0 else sh
        stop_desc = "beyond the RB source-candle wick extreme (block invalidation)"
    else:
        lo, hi = primary["context_zone"]
        stop_price = lo if direction > 0 else hi
        stop_desc = "beyond the structure's distal boundary (structure invalidation)"
    valid_stop = (stop_price < entry_price) if direction > 0 else (stop_price > entry_price)

    exclude = set(confluence_ids)
    targets = _targets(all_structs, entry_seq, direction, entry_price, stop_price, tf, exclude) \
        if valid_stop else []

    # executable per NEAREST_VALID_STRUCTURE policy (primary)
    executable = False
    reason = ""
    primary_target = next((t for t in targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
    if not valid_stop:
        reason = "NO_STRUCTURAL_STOP"
    elif primary_target is None:
        reason = "NO_CAUSAL_TARGET"
    elif primary_target.natural_rr is None or primary_target.natural_rr < MIN_EXECUTABLE_RR:
        reason = "INSUFFICIENT_NATURAL_RR"
    else:
        executable = True

    # ---- RB activation states (causal) ----
    rb = extra.get("rb")
    rb_wb = rb_dom = rb_act_inter = rb_act_conf = rb_act_trig = rb_act_age = rb_act_after = None
    prior_taps = 0
    if rb is not None:
        rb_wb = round(rb.wick_body_ratio, 4)
        rb_dom = round(rb.dominant_wick_ratio, 4)
        i_idx = primary["i_idx"]; c_idx = primary["confirm_idx"]
        rb_act_inter = rb.was_activated_at(i_idx)
        rb_act_conf = rb.was_activated_at(c_idx)
        rb_act_trig = rb.was_activated_at(c_idx)   # trigger fires at confirmation close
        rb_act_age = (c_idx - rb.activation_seq) if rb.activation_seq is not None else None
        rb_act_after = bool(rb.activated and rb.activation_seq is not None and rb.activation_seq > c_idx)
        prior_taps = sum(1 for tp in rb.tap_events if tp["seq"] <= c_idx)

    fvg = extra.get("fvg"); ifvg = extra.get("ifvg")
    tw = time_window_fields(entry_bar.ts_et)

    ep = Episode(
        episode_id=eid, lane=lane, direction=direction,
        context_tf=tf, interaction_tf=tf, confirmation_tf=tf, trigger_tf=tf,
        interaction_seq=primary["interaction_seq_global"],
        confirmation_seq=primary["trigger_seq_global"],
        trigger_seq=primary["confirm_idx"], entry_seq=entry_seq,
        session=tw["session"], et_hour=tw["et_hour"],
        minutes_from_0930=tw["minutes_from_0930"], minutes_from_1000=tw["minutes_from_1000"],
        day_of_week=tw["day_of_week"], session_date_et=session_date(entry_bar.ts_et),
        context_id=primary["context_id"], context_family=primary["context_family"],
        component_ids=confluence_ids, atomic_event_ids=confluence_ids,
        confluence=confluence, confluence_ids=confluence_ids,
        context_zone=primary["context_zone"], context_formation_ts=primary["context_form_ts"],
        context_age_bars_at_interaction=primary["context_age"],
        fvg_width_atr=(round(fvg.width_atr, 4) if fvg is not None and fvg.width_atr else None),
        ifvg_inversion_speed=(ifvg.inversion_speed_bucket if ifvg is not None else None),
        rb_wick_body=rb_wb, rb_dominant_ratio=rb_dom,
        rb_activated_at_interaction=rb_act_inter, rb_activated_at_confirmation=rb_act_conf,
        rb_activated_at_trigger=rb_act_trig, rb_activation_age=rb_act_age,
        rb_activation_only_after_setup=rb_act_after, prior_tap_count=prior_taps,
        displacement_branch=r["branch"], confirm_reason=r["confirm_reason"],
        interaction_to_confirmation_delay=r["confirm_offset"],
        reaction_measures=r["per_candle"],
        new_fvg_after_interaction=(r["confirm_reason"] == "same_dir_fvg"),
        new_ifvg_after_interaction=(r["confirm_reason"] == "same_dir_ifvg"),
        entry_price=entry_price, stop_price=stop_price, stop_anchor_desc=stop_desc,
        targets=targets, executable=executable, rejection_reason=reason,
    )
    ep.fingerprint = _fingerprint(ep)
    return ep


def _fingerprint(ep: Episode) -> dict:
    prim = next((t for t in ep.targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
    rb_act_class = ("ACTIVATED" if ep.rb_activated_at_trigger else "NOT_ACTIVATED") \
        if ep.rb_wick_body is not None else "NA"
    return {
        "lane": ep.lane, "direction": ep.direction,
        "context_tf": ep.context_tf, "trigger_tf": ep.trigger_tf,
        "confirmation_tf": ep.confirmation_tf, "interaction_tf": ep.interaction_tf,
        "session": ep.session, "day_of_week": ep.day_of_week,
        "context_family": ep.context_family,
        "displacement_branch": ep.displacement_branch,
        "confirm_reason": ep.confirm_reason,
        "rb_activation_class": rb_act_class,
        "interaction_to_confirmation_delay": ep.interaction_to_confirmation_delay,
        "confluence": ep.confluence,
        "target_family": (prim.family if prim else "none"),
        "target_tf": (prim.timeframe if prim else "none"),
        # binned continuous
        "fvg_width_atr_bin": _bin(ep.fvg_width_atr, WIDTH_ATR_BINS),
        "rb_wick_body_bin": _bin(ep.rb_wick_body, WICKBODY_BINS),
        "natural_rr_bin": _bin(prim.natural_rr if prim else None, RR_BINS),
        "ifvg_inversion_speed": ep.ifvg_inversion_speed or "na",
    }

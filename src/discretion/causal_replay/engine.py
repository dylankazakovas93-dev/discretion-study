"""Bar-by-bar causal setup replay over the audited primitive-reset structures.

Terminology (kept strictly separate, spec Part 4):
  * TRIGGER_EVENT   -- a branch causally completed (a defined transition on an
                       audited structure fired at a known bar).
  * EXECUTABLE_SETUP-- a trigger with a valid structural stop, a causally
                       available structural target, natural RR >= the frozen
                       execution floor, and no occupancy/lifecycle rejection.
  * REJECTED_TRIGGER-- a completed branch that failed execution eligibility.
  * REALIZED_TRADE  -- not produced here (needs entry + subsequent path; the
                       pre-outcome stage never computes or attaches outcomes).

Causality: a structure's availability seq is the first 1-minute bar index at
which it is knowable (the bar after its producing candle closes). A trigger's
entry is the next 1-minute bar open. Stop and target are frozen at the trigger
bar from structures whose availability seq <= the entry bar; nothing with
availability after the trigger is ever referenced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..primitive_reset.timeframes import candle_series, atr_series, candle_ts_et, TIMEFRAMES
from ..primitive_reset.registry import ResetRegistry
from ..primitive_reset.fvg import detect_fvgs
from ..primitive_reset.ifvg import detect_ifvgs
from ..primitive_reset.rejection_block import detect_rejection_blocks
from ..data.cme_session import session_date

# Frozen execution policy (reused from the project's frozen RR contract):
# natural RR below this floor is rejected INSUFFICIENT_NATURAL_RR.
MIN_EXECUTABLE_RR = 0.5


def _dir(word) -> int:
    return 1 if word == "bullish" else -1


@dataclass
class AuditedStructure:
    """Uniform causal view of an audited FVG / iFVG / RB for the replay."""
    id: str
    family: str            # "fvg" / "ifvg" / "rb"
    timeframe: int
    direction: int         # +1 / -1
    zone_lo: float
    zone_hi: float
    avail_seq: int         # first 1m bar index at which knowable
    source_ts_et: object
    record: object         # the underlying frozen primitive-reset record


@dataclass
class TriggerEvent:
    trigger_id: str
    seq: int                       # trigger 1m bar (bar whose close makes it knowable)
    entry_seq: int                 # next 1m bar (entry)
    availability_ts_et: object
    direction: int
    trigger_family: str            # "IFVG_ACTIVATION" / "RB_TAP"
    trigger_timeframe: int
    branch_path: list              # explicit state-machine path
    trigger_rule: str
    trigger_structure_id: str
    component_ids: list
    # RB-specific descriptive fields
    rb_activated_at_trigger: object = None
    rb_prior_taps: list = field(default_factory=list)   # [{seq, ts, was_activated}]
    # setup fields (frozen pre-outcome)
    entry_price: float = 0.0
    stop_price: float = 0.0
    stop_anchor_id: str = ""
    stop_anchor_desc: str = ""
    target_price: object = None
    target_structure_id: str = ""
    target_policy: str = ""
    natural_rr: object = None
    executable: bool = False
    rejection_reason: str = ""
    session_date_et: object = None
    explanation: str = ""


def _avail_global_seq(tf, series, candle_seq):
    """First 1m bar index at which a completed `tf` candle is knowable."""
    if tf == 1:
        return candle_seq + 1
    return series[candle_seq].available_seq   # aggregation.HTFBar: end_seq+1


def build_structures(bars):
    """Detect the audited primitives on every governing timeframe and return
    a flat list of causal AuditedStructure views plus per-tf series maps."""
    series_by_tf = {}
    atr_by_tf = {}
    fvgs_by_tf = {}
    ifvgs_by_tf = {}
    rbs_by_tf = {}
    reg = ResetRegistry()   # one registry -> globally unique reset ids across tfs
    for tf in TIMEFRAMES:
        s = candle_series(bars, tf)
        a = atr_series(s)
        series_by_tf[tf] = s
        atr_by_tf[tf] = a
        fvgs_by_tf[tf] = detect_fvgs(bars, tf, reg)
        ifvgs_by_tf[tf] = detect_ifvgs(bars, tf, fvgs_by_tf[tf], a, s, reg)
        rbs_by_tf[tf] = detect_rejection_blocks(bars, tf, s, a, reg)

    # ts -> candle index per tf (to locate an iFVG's activation candle)
    ts_index = {tf: {candle_ts_et(c): i for i, c in enumerate(series_by_tf[tf])}
                for tf in TIMEFRAMES}

    structs = []
    for tf in TIMEFRAMES:
        s = series_by_tf[tf]
        for f in fvgs_by_tf[tf]:
            structs.append(AuditedStructure(
                id=f.id, family="fvg", timeframe=tf, direction=_dir(f.direction),
                zone_lo=f.lo, zone_hi=f.hi,
                avail_seq=_avail_global_seq(tf, s, f.c_seq),
                source_ts_et=f.formation_ts, record=f))
        for iv in ifvgs_by_tf[tf]:
            act_idx = ts_index[tf].get(iv.activation_ts)
            if act_idx is None:
                continue
            structs.append(AuditedStructure(
                id=iv.id, family="ifvg", timeframe=tf, direction=_dir(iv.child_direction),
                zone_lo=iv.lo, zone_hi=iv.hi,
                avail_seq=_avail_global_seq(tf, s, act_idx),
                source_ts_et=iv.activation_ts, record=iv))
        for rb in rbs_by_tf[tf]:
            structs.append(AuditedStructure(
                id=rb.id, family="rb", timeframe=tf, direction=_dir(rb.direction),
                zone_lo=rb.zone_lo, zone_hi=rb.zone_hi,
                avail_seq=_avail_global_seq(tf, s, rb.source_seq),
                source_ts_et=rb.source_ts, record=rb))
    return structs, series_by_tf, ifvgs_by_tf, rbs_by_tf


def _raw_triggers(bars, series_by_tf, ifvgs_by_tf, rbs_by_tf, ts_index):
    """Every branch-completion, each tied to its trigger 1m bar. Two families:
    iFVG activation (inversion) and RB first tap (price returns to the zone)."""
    raw = []   # (entry_seq, seq, family, tf, record, extra)

    # IFVG_ACTIVATION: the inversion candle completes the branch.
    for tf, ivs in ifvgs_by_tf.items():
        s = series_by_tf[tf]
        for iv in ivs:
            act_idx = ts_index[tf].get(iv.activation_ts)
            if act_idx is None:
                continue
            entry_seq = _avail_global_seq(tf, s, act_idx)
            raw.append((entry_seq, act_idx, "IFVG_ACTIVATION", tf, iv, None))

    # RB_TAP: the first tap of a live RB completes the reaction branch. Direction
    # follows the RB; activated_at_trigger is the causal flag at that tap.
    for tf, rbs in rbs_by_tf.items():
        s = series_by_tf[tf]
        for rb in rbs:
            if not rb.tap_events:
                continue
            first = rb.tap_events[0]
            entry_seq = _avail_global_seq(tf, s, first["seq"])
            raw.append((entry_seq, first["seq"], "RB_TAP", tf, rb, first))
    return raw


def _causal_target(structs, entry_seq, direction, entry_price, exclude_id):
    """Nearest audited structural surface causally available at the entry bar,
    beyond entry in the trade direction. Returns (structure, surface_price)."""
    best = None
    best_price = None
    for st in structs:
        if st.id == exclude_id:
            continue
        if st.avail_seq > entry_seq:   # not yet knowable -- never referenced
            continue
        if direction > 0:
            surface = st.zone_lo       # bullish: reach the bottom edge of a zone above
            if surface <= entry_price:
                continue
            if best_price is None or surface < best_price:
                best, best_price = st, surface
        else:
            surface = st.zone_hi       # bearish: reach the top edge of a zone below
            if surface >= entry_price:
                continue
            if best_price is None or surface > best_price:
                best, best_price = st, surface
    return best, best_price


def replay(bars):
    """Run the full causal replay; return (triggers_in_chronological_order,
    diagnostics)."""
    structs, series_by_tf, ifvgs_by_tf, rbs_by_tf = build_structures(bars)
    ts_index = {tf: {candle_ts_et(c): i for i, c in enumerate(series_by_tf[tf])}
                for tf in TIMEFRAMES}
    raw = _raw_triggers(bars, series_by_tf, ifvgs_by_tf, rbs_by_tf, ts_index)

    # Chronological order by the entry (next) bar, then trigger bar, with a
    # stable deterministic tiebreak -- outcome-independent.
    raw.sort(key=lambda r: (r[0], r[1], r[2], getattr(r[4], "id", "")))

    n_bars = len(bars)
    occupancy_until = -1   # single-position: entry bars <= this are occupied
    triggers = []
    tid = 0
    for entry_seq, seq, family, tf, rec, extra in raw:
        if entry_seq >= n_bars:
            continue   # trigger on the last bar -- no next bar to enter on
        tid += 1
        trig_id = f"TRIG-{tid:05d}"
        entry_bar = bars[entry_seq]
        entry_price = entry_bar.open

        if family == "IFVG_ACTIVATION":
            direction = _dir(rec.child_direction)
            comp = [rec.id, rec.parent_fvg_id]
            path = [f"ORIGIN_FVG:{rec.parent_fvg_id}", "PARENT_ACTIVE",
                    "CLOSE_THROUGH_DISTAL", "IFVG_ACTIVATION"]
            rule = ("a completed same-timeframe candle closed fully through the "
                    "parent FVG's distal boundary, inverting it")
            trig_struct_id = rec.id
            zone = (rec.lo, rec.hi)
            rb_act = None
            rb_taps = []
        else:  # RB_TAP
            direction = _dir(rec.direction)
            comp = [rec.id]
            path = [f"ORIGIN_RB:{rec.id}", "LIVE_FROM_SOURCE", "PRICE_RETURNED_TO_ZONE",
                    "RB_TAP_TRIGGER"]
            rule = ("price returned to and tapped a live rejection block's zone "
                    "in the block's direction")
            trig_struct_id = rec.id
            zone = (rec.zone_lo, rec.zone_hi)
            rb_act = extra["was_activated"]
            rb_taps = [{"seq": e["seq"], "ts": e["ts"], "was_activated": e["was_activated"]}
                       for e in rec.tap_events]

        # ---- frozen structural stop (from the trigger structure only) ----
        if family == "RB_TAP":
            so, sh, sl, sc = rec.source_ohlc
            if direction > 0:
                stop_price = sl
                stop_desc = "below the rejection block's source-candle low (wick extreme)"
            else:
                stop_price = sh
                stop_desc = "above the rejection block's source-candle high (wick extreme)"
            stop_anchor_id = rec.id
        else:  # iFVG
            if direction > 0:
                stop_price = zone[0]
                stop_desc = "below the iFVG's distal (lower) boundary"
            else:
                stop_price = zone[1]
                stop_desc = "above the iFVG's distal (upper) boundary"
            stop_anchor_id = rec.id

        # stop must be on the correct (losing) side of entry
        valid_stop = (stop_price < entry_price) if direction > 0 else (stop_price > entry_price)

        # ---- causal target (nearest opposing audited surface) ----
        tstruct, tprice = _causal_target(structs, entry_seq, direction, entry_price, trig_struct_id)

        # ---- natural RR + execution eligibility ----
        natural_rr = None
        executable = False
        reason = ""
        if not valid_stop:
            reason = "NO_STRUCTURAL_STOP"
        elif tstruct is None:
            reason = "NO_CAUSAL_TARGET"
        else:
            risk = abs(entry_price - stop_price)
            reward = abs(tprice - entry_price)
            natural_rr = (reward / risk) if risk > 0 else None
            if natural_rr is None:
                reason = "NO_STRUCTURAL_STOP"
            elif natural_rr < MIN_EXECUTABLE_RR:
                reason = "INSUFFICIENT_NATURAL_RR"
            elif entry_seq <= occupancy_until:
                reason = "SUPPRESSED_BY_OCCUPANCY"
            else:
                executable = True

        # ---- deterministic single-position occupancy bookkeeping ----
        # (position lifecycle only, to free the slot; NO outcome is recorded.)
        if executable:
            close_seq = _occupancy_close_seq(bars, entry_seq, direction, stop_price, tprice)
            occupancy_until = max(occupancy_until, close_seq)

        te = TriggerEvent(
            trigger_id=trig_id, seq=seq, entry_seq=entry_seq,
            availability_ts_et=bars[entry_seq].ts_et,
            direction=direction, trigger_family=family, trigger_timeframe=tf,
            branch_path=path, trigger_rule=rule, trigger_structure_id=trig_struct_id,
            component_ids=comp, rb_activated_at_trigger=rb_act, rb_prior_taps=rb_taps,
            entry_price=entry_price, stop_price=stop_price, stop_anchor_id=stop_anchor_id,
            stop_anchor_desc=stop_desc,
            target_price=tprice, target_structure_id=(tstruct.id if tstruct else ""),
            target_policy="NEAREST_CAUSAL_STRUCTURE",
            natural_rr=natural_rr, executable=executable, rejection_reason=reason,
            session_date_et=session_date(entry_bar.ts_et),
            explanation=_explain(family, direction, rec, executable, reason),
        )
        triggers.append(te)

    diagnostics = {
        "n_structures": len(structs),
        "n_triggers": len(triggers),
        "n_executable": sum(1 for t in triggers if t.executable),
        "n_rejected": sum(1 for t in triggers if not t.executable),
    }
    return triggers, diagnostics


def _occupancy_close_seq(bars, entry_seq, direction, stop_price, target_price):
    """Deterministic position-close bar for single-position occupancy only:
    the first bar after entry that touches the frozen stop or target, stop-first
    on same-bar ambiguity. Records NO outcome -- used solely to free the slot."""
    for s in range(entry_seq, len(bars)):
        b = bars[s]
        if direction > 0:
            hit_stop = b.low <= stop_price
            hit_tgt = b.high >= target_price
        else:
            hit_stop = b.high >= stop_price
            hit_tgt = b.low <= target_price
        if hit_stop or hit_tgt:
            return s
    return len(bars) - 1


def _explain(family, direction, rec, executable, reason):
    d = "long" if direction > 0 else "short"
    if family == "IFVG_ACTIVATION":
        base = (f"an FVG inverted (iFVG activated), so the engine expects a {d} "
                f"continuation away from the failed gap")
    else:
        act = "already activated" if getattr(rec, "activated", False) else "not yet activated"
        base = (f"price returned to a live rejection block ({act} at the tap) and the "
                f"engine expects a {d} reaction out of the block")
    tail = "executable" if executable else f"rejected: {reason}"
    return f"{base}; {tail}."

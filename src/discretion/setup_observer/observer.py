"""Coherent multi-timeframe ICT setup observer over the FROZEN audited
primitives.

A physical episode = a context structure that price actually interacted with, at
a specific time, on a specific trigger timeframe. Timeframe roles are preserved
independently (a lower-timeframe trigger may reference a higher-timeframe context
only when price causally reached that exact HTF zone and the LTF event happened
after). Each physical episode spawns separate frozen entry variants (variants.py)
-- reaction strength is descriptive, NOT a universal gate. No outcome is computed
here (outcomes.py, observation week only).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from ..primitive_reset.timeframes import candle_series, atr_series, candle_ts_et, TIMEFRAMES
from ..primitive_reset.registry import ResetRegistry
from ..data.atr import wilder_atr
from ..primitive_reset.fvg import detect_fvgs
from ..primitive_reset.ifvg import detect_ifvgs
from ..primitive_reset.rejection_block import detect_rejection_blocks
from .common import _dir, _avail, _tf_start_seq, MIN_EXECUTABLE_RR
from .targets import resolve_targets, StructTable
from .variants import build_variants
from . import reaction_states as rs


@dataclass
class PhysicalEpisode:
    episode_id: str
    direction: int
    lane: str
    trigger_tf: int
    context_tf: int
    is_multi_timeframe: bool
    context_family: str
    context_id: str
    component_ids: list
    confluence: bool
    interaction_seq: int
    context_zone: tuple
    dominant_state: str
    variant_ids: list = field(default_factory=list)
    n_variants: int = 0
    n_executable: int = 0


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


def _ts_resolver(bars):
    ts_list = [b.ts_et for b in bars]

    def resolve(ts):
        if ts is None:
            return None
        i = bisect.bisect_left(ts_list, ts)
        return i if i < len(ts_list) else None
    return resolve


def _all_structures_ext(fvgs, ifvgs, rbs, series, ts_index, ts_to_seq):
    """Uniform target-eligible structures with a global ``invalid_from`` seq
    (earliest 1m seq at which the structure stopped being a valid opposing
    target: inverted / filled / expired / deactivated)."""
    out = []
    for tf in TIMEFRAMES:
        s = series[tf]
        for f in fvgs[tf]:
            cand = []
            if f.inversion_seq is not None:
                cand.append(_avail(tf, s, f.inversion_seq))
            for t in (f.full_fill_ts, f.expiry_ts):
                r = ts_to_seq(t)
                if r is not None:
                    cand.append(r)
            out.append({"id": f.id, "family": "fvg", "tf": tf, "sdir": _dir(f.direction),
                        "lo": f.lo, "hi": f.hi, "avail": _avail(tf, s, f.c_seq),
                        "invalid_from": (min(cand) if cand else None)})
        for iv in ifvgs[tf]:
            idx = ts_index[tf].get(iv.activation_ts)
            if idx is None:
                continue
            # causal lifecycle field set at the exact deactivating candle
            # (close-through / traversal / expiry / data-end) -- covers every
            # deactivation path, not just lifetime expiry.
            out.append({"id": iv.id, "family": "ifvg", "tf": tf, "sdir": _dir(iv.child_direction),
                        "lo": iv.lo, "hi": iv.hi, "avail": _avail(tf, s, idx),
                        "invalid_from": iv.deactivation_available_seq})
        for rb in rbs[tf]:
            r = ts_to_seq(rb.deactivation_ts)
            out.append({"id": rb.id, "family": "rb", "tf": tf, "sdir": _dir(rb.direction),
                        "lo": rb.zone_lo, "hi": rb.zone_hi, "avail": _avail(tf, s, rb.source_seq),
                        "invalid_from": r})
    return out


def _contexts(fvgs, ifvgs, rbs, series, ts_index):
    """Setup context structures (RB / FVG / iFVG) with causal availability."""
    ctxs = []
    for tf in TIMEFRAMES:
        s = series[tf]
        for rb in rbs[tf]:
            ctxs.append({"context_id": rb.id, "context_family": "rb", "context_tf": tf,
                         "direction": _dir(rb.direction), "context_zone": (rb.zone_lo, rb.zone_hi),
                         "avail_ctx": _avail(tf, s, rb.source_seq), "context_formation_ts": rb.source_ts,
                         "rb": rb, "is_ifvg": False, "lane": "A"})
        for f in fvgs[tf]:
            ctxs.append({"context_id": f.id, "context_family": "fvg", "context_tf": tf,
                         "direction": _dir(f.direction), "context_zone": (f.lo, f.hi),
                         "avail_ctx": _avail(tf, s, f.c_seq), "context_formation_ts": f.formation_ts,
                         "rb": None, "is_ifvg": False, "lane": "B"})
        for iv in ifvgs[tf]:
            idx = ts_index[tf].get(iv.activation_ts)
            if idx is None:
                continue
            ctxs.append({"context_id": iv.id, "context_family": "ifvg", "context_tf": tf,
                         "direction": _dir(iv.child_direction), "context_zone": (iv.lo, iv.hi),
                         "avail_ctx": _avail(tf, s, idx), "context_formation_ts": iv.activation_ts,
                         "rb": None, "is_ifvg": True, "lane": "C"})
    return ctxs


def _form_by_dir(fvgs, ifvgs, ts_index, tf):
    fv = {1: set(), -1: set()}
    ifv = {1: set(), -1: set()}
    for f in fvgs[tf]:
        fv[_dir(f.direction)].add(f.c_seq)
    for iv in ifvgs[tf]:
        idx = ts_index[tf].get(iv.activation_ts)
        if idx is not None:
            ifv[_dir(iv.child_direction)].add(idx)
    return fv, ifv


def _mtf_interaction(s, tf, avail_ctx, zone, start_arr):
    """First ``tf`` candle whose bar-time is at/after the context became known
    and whose range enters the zone. ``start_arr`` is the tf's per-candle global
    start-seq array (ascending), used to skip straight to the first eligible
    candle."""
    lo, hi = zone
    i0 = bisect.bisect_left(start_arr, avail_ctx)
    for i in range(i0, len(s)):
        c = s[i]
        if c.low <= hi and c.high >= lo:
            return i
    return None


def _trigger_tf_invalidation(s, tf, i_idx, direction, zone):
    """First trigger-tf candle after interaction that closes through the zone on
    the invalidating side (support broken down / resistance broken up)."""
    lo, hi = zone
    for j in range(i_idx + 1, min(len(s), i_idx + rs.REACTION_WINDOW + 1)):
        c = s[j]
        if direction > 0 and c.close < lo:
            return j
        if direction < 0 and c.close > hi:
            return j
    return None


def observe(bars, target_window=None):
    """Return (physical_episodes, variants, diagnostics).

    ``target_window``: optional recency bound (in 1m bars) for the intraday
    target search -- lossless above 480 (the 8h intraday structure lifetime),
    used to keep resolution linear over long histories. 60m targets are always
    checked. ``None`` keeps the unbounded default."""
    series, atr, fvgs, ifvgs, rbs, ts_index = _detect(bars)
    ts_to_seq = _ts_resolver(bars)
    structs_ext = _all_structures_ext(fvgs, ifvgs, rbs, series, ts_index, ts_to_seq)
    table = StructTable(structs_ext)
    form_by_tf = {tf: _form_by_dir(fvgs, ifvgs, ts_index, tf) for tf in TIMEFRAMES}
    start_by_tf = {tf: [_tf_start_seq(tf, series[tf], i) for i in range(len(series[tf]))]
                   for tf in TIMEFRAMES}
    contexts = _contexts(fvgs, ifvgs, rbs, series, ts_index)

    # causal ATR(24) references for the absolute-volatility floors
    atrf = {"a1": wilder_atr(bars, 24),
            "a5": wilder_atr(series[5], 24),
            "avail5": [c.available_seq for c in series[5]]}

    def resolve(entry_seq, direction, entry_price, stop_price, ctf, cfam, excl):
        return resolve_targets(table, entry_seq, direction, entry_price,
                               stop_price, ctf, cfam, excl, window=target_window)

    # ---- raw physical-episode candidates across trigger timeframes ----
    # Trigger timeframes per context: same-timeframe plus a 1m refinement -- the
    # two architectures that matter most (same-tf, and HTF-context -> 1m-trigger).
    # This is the frozen, bounded MTF set for the two-week demonstration.
    raw = []
    for ctx in contexts:
        ctf = ctx["context_tf"]
        lo, hi = ctx["context_zone"]
        direction = ctx["direction"]
        for ttf in sorted({ctf, 1}):
            s = series[ttf]
            i_idx = _mtf_interaction(s, ttf, ctx["avail_ctx"], ctx["context_zone"], start_by_tf[ttf])
            if i_idx is None or i_idx + 1 >= len(s):
                continue
            fv, ifv = form_by_tf[ttf]
            fvg_form = {j for j in fv[direction] if j > i_idx}
            ifvg_form = {j for j in ifv[direction] if j > i_idx}
            inval = _trigger_tf_invalidation(s, ttf, i_idx, direction, ctx["context_zone"])
            cls = rs.classify(s, atr[ttf], i_idx, direction, lo, hi, fvg_form, ifvg_form, inval)
            raw.append({"ctx": ctx, "ttf": ttf, "i_idx": i_idx, "cls": cls,
                        "interaction_global": _tf_start_seq(ttf, s, i_idx)})

    # ---- physical dedup: bucket by (interaction_global, trigger_tf, direction),
    #      then merge overlapping context zones within each small bucket ----
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in raw:
        buckets[(r["interaction_global"], r["ttf"], r["ctx"]["direction"])].append(r)

    episodes, variants = [], []
    eid = 0
    for key in sorted(buckets):
        items = sorted(buckets[key], key=lambda r: (-r["ctx"]["context_tf"], r["i_idx"],
                                                    r["ctx"]["context_id"]))
        used = [False] * len(items)
        for i in range(len(items)):
            if used[i]:
                continue
            group = [items[i]]
            used[i] = True
            alo, ahi = items[i]["ctx"]["context_zone"]
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                blo, bhi = items[j]["ctx"]["context_zone"]
                if max(alo, blo) <= min(ahi, bhi):
                    group.append(items[j])
                    used[j] = True
                    alo, ahi = min(alo, blo), max(ahi, bhi)   # expand merged zone
            # primary context: highest context tf then earliest interaction candle
            primary = sorted(group, key=lambda r: (-r["ctx"]["context_tf"], r["i_idx"]))[0]
            confluence_ids = sorted({g["ctx"]["context_id"] for g in group})
            eid += 1
            episode_id = f"EP-{eid:05d}"
            vs = build_variants(episode_id, primary["ctx"], primary["ttf"], series, atr,
                                bars, primary["i_idx"], primary["cls"], resolve, confluence_ids, atrf)
            if not vs:
                eid -= 1
                continue
            lane = "F" if len(confluence_ids) > 1 else primary["ctx"]["lane"]
            for v in vs:
                v.lane = lane
                v.fingerprint["lane"] = lane
            variants.extend(vs)
            episodes.append(PhysicalEpisode(
                episode_id=episode_id, direction=primary["ctx"]["direction"], lane=lane,
                trigger_tf=primary["ttf"], context_tf=primary["ctx"]["context_tf"],
                is_multi_timeframe=primary["ttf"] != primary["ctx"]["context_tf"],
                context_family=primary["ctx"]["context_family"],
                context_id=primary["ctx"]["context_id"], component_ids=confluence_ids,
                confluence=len(confluence_ids) > 1,
                interaction_seq=primary["interaction_global"],
                context_zone=primary["ctx"]["context_zone"],
                dominant_state=primary["cls"]["dominant_state"],
                variant_ids=[v.variant_id for v in vs], n_variants=len(vs),
                n_executable=sum(1 for v in vs if v.executable)))

    diagnostics = {
        "n_physical_episodes": len(episodes),
        "n_variants": len(variants),
        "n_multi_timeframe_episodes": sum(1 for e in episodes if e.is_multi_timeframe),
        "variants_by_rule": _count(variants, lambda v: v.entry_variant),
        "executable_by_rule": _count([v for v in variants if v.executable], lambda v: v.entry_variant),
        "by_lane": _count(episodes, lambda e: e.lane),
    }
    return episodes, variants, diagnostics


def _count(items, key):
    out = {}
    for it in items:
        out[key(it)] = out.get(key(it), 0) + 1
    return out

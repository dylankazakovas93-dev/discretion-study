"""Emit canonical append-only events from a canonical :class:`PrimitiveSet`.

This does not detect anything itself — it re-expresses the primitives' interaction
events as typed ``CanonicalEvent`` records in strict availability order, with
deterministic ids and causal parent links. The primitive engine stays the single
source of truth (no re-implementation of FVG/iFVG/RB/VWAP/levels/ATR).
"""

from __future__ import annotations

import pandas as pd

from .schema import CanonicalEvent, EventLog, DETECTOR_VERSION

ET = "America/New_York"

# Deterministic tiebreak so a source FVG's FAILURE sorts before the iFVG
# ACTIVATION it spawns on the same bar (parent link is then resolvable).
_FAMILY_RANK = {
    "fvg": 0, "rejection_block": 1, "displacement": 2, "structure": 3,
    "time_anchor": 4, "hist_level": 5, "liquidity": 6, "vwap": 7, "ifvg": 8,
}


def _dirword(p):
    d = getattr(p, "direction", 0)
    return "BULLISH" if d > 0 else ("BEARISH" if d < 0 else "NEUTRAL")


def _event_direction(p, e):
    d = getattr(p, "direction", 0)
    if d:
        return d
    note = e.note or ""
    if "above" in note or note.endswith("_up") or note.endswith("bounce_up"):
        return 1
    if "below" in note or note.endswith("_down") or note.endswith("bounce_down"):
        return -1
    return 0


def canonical_subtype(p, e) -> str:
    fam, sub, k, note = p.family, p.subtype, e.kind, (e.note or "")
    dw = _dirword(p)
    if fam == "fvg":
        return f"{dw}_FVG_{k}"
    if fam == "ifvg":
        return f"{dw}_IFVG_ACTIVATION" if k == "CONFIRMED" else f"{dw}_IFVG_{k}"
    if fam == "rejection_block":
        return f"{dw}_RB_TAP" if k == "FIRST_TOUCH" else f"{dw}_RB_{k}"
    if fam == "displacement":
        if k == "FORMED":
            return f"{p.grade.upper()}_{dw}_DISPLACEMENT"
        return f"DISPLACEMENT_{k}"
    if fam == "time_anchor":
        return f"ANCHOR_{sub.upper()}_{k}"
    if fam in ("hist_level", "liquidity"):
        base = sub.upper()
        if k == "SWEEP":
            return f"{base}_SWEEP_{note.upper()}" if note else f"{base}_SWEEP"
        return f"{base}_{k}"
    if fam == "vwap":
        if note:
            tok = note.upper().replace("+", "P").replace("-", "M").replace(".", "_")
            return f"VWAP_{tok}"
        return f"VWAP_{k}"
    if fam == "structure":
        if sub == "compression" and k == "COMPRESSION":
            return "COMPRESSION"
        if sub == "expansion" and k == "EXPANSION":
            return f"{dw}_EXPANSION"
        return f"STRUCT_{k}"
    return f"{fam.upper()}_{k}"


def _features(p, ps, seq):
    atr = ps.atr[seq] if 0 <= seq < len(ps.atr) and ps.atr[seq] else None
    fv = {"segment": p.segment_id}
    if p.family in ("fvg", "ifvg"):
        fv["width_atr"] = round((p.hi - p.lo) / atr, 4) if atr else None
    elif p.family == "displacement":
        f = p.features
        fv.update({"grade": p.grade, "body_atr": round(f.get("body_atr", 0), 4),
                   "path_body_ratio": round(f.get("body_ratio", 0), 4)})
    elif p.family in ("hist_level", "liquidity", "time_anchor"):
        fv.update({"level_family": p.subtype, "source": getattr(p, "source", "")})
    elif p.family == "vwap":
        fv["note"] = ""
    elif p.family == "structure":
        fv.update({k: round(v, 4) for k, v in p.features.items()})
    return fv


def build_event_log(ps) -> EventLog:
    """Return an append-only EventLog derived from the primitive set."""
    bars = ps.bars
    # collect (sort_key, primitive, event, ordinal)
    items = []
    for p in ps.registry.all():
        # target-inventory objects (wick liquidity, HTF FVG/iFVG) carry permanent
        # ids but never drive canonical episode events, so they have no event log.
        for ordinal, e in enumerate(getattr(p, "events", ())):
            key = (e.seq, _FAMILY_RANK.get(p.family, 99), p.id, ordinal)
            items.append((key, p, e, ordinal))
    items.sort(key=lambda t: t[0])

    log = EventLog()
    last_event_of_object: dict[str, str] = {}
    event_id_by_object_kind: dict[tuple, str] = {}

    def et(ts):
        return str(ts.tz_convert(ET))

    for n, (key, p, e, ordinal) in enumerate(items, start=1):
        eid = f"EVT-{n:07d}"
        seq = e.seq
        ts_et = e.ts_utc.tz_convert(ET)
        avail = ts_et + pd.Timedelta(minutes=1)

        # causal parents: previous event of same object + source activation link
        parents = []
        if p.id in last_event_of_object:
            parents.append(last_event_of_object[p.id])
        parent_object = ""
        if p.family == "ifvg":
            parent_object = getattr(p, "source_fvg_id", "")
            if e.kind == "CONFIRMED" and (parent_object, "FAILURE") in event_id_by_object_kind:
                parents.append(event_id_by_object_kind[(parent_object, "FAILURE")])

        state_before = "NONE"
        if ordinal > 0:
            state_before = p.events[ordinal - 1].kind

        inval_ts = ""
        if e.kind in ("INVALIDATION", "FAILURE", "REINVERSION"):
            inval_ts = et(e.ts_utc)
        expiry_ts = et(e.ts_utc) if e.kind == "EXPIRY" else ""

        ev = CanonicalEvent(
            event_id=eid,
            event_type=p.family,
            event_subtype=canonical_subtype(p, e),
            object_id=p.id,
            parent_object_id=parent_object,
            timestamp_et=et(e.ts_utc),
            availability_timestamp_et=str(avail),
            source_timeframe="1m",
            absolute_segment_id=p.segment_id,
            normalization_segment_id=p.segment_id,
            direction=_event_direction(p, e),
            price_low=float(p.lo),
            price_high=float(p.hi),
            reference_price=float(e.price) if e.price is not None else float(p.price),
            state_before=state_before,
            state_after=e.kind,
            feature_values=_features(p, ps, seq),
            causal_parent_event_ids=tuple(parents),
            invalidation_timestamp=inval_ts,
            expiry_timestamp=expiry_ts,
            source_detector_version=DETECTOR_VERSION,
        )
        log.append(ev)
        last_event_of_object[p.id] = eid
        event_id_by_object_kind.setdefault((p.id, e.kind), eid)
    return log

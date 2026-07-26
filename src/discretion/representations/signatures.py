"""Deterministic representations for a coherent candidate.

Three views, all causal (no future-derived field):
  * exact graph signature (already on the candidate);
  * reduced graph signature — generalized but still discriminative;
  * numeric feature vector — direction-normalized where meaningful.

Direction normalization: signed magnitude features are expressed so that a
positive value means movement in the hypothesized setup direction. Features whose
session/economic meaning is genuinely asymmetric keep their raw direction and are
flagged ``symmetric=False`` in ``schemas/feature.schema.json``.
"""

from __future__ import annotations

# ---- reduced graph ----------------------------------------------------------

def _reduce_token(tok: str) -> str:
    t = tok
    if t.endswith("_TRIGGER"):
        return "ENTRY_TRIGGER"
    if "IFVG_ACTIVATION" in t:
        return "INVERSION_ACTIVATION"
    if "IFVG" in t:
        return "INVERSION_INTERACTION"
    if "FVG_FAILURE" in t:
        return "GAP_FAILURE"
    if "FVG_FORMED" in t:
        return "GAP_FORMATION"
    if "FVG_" in t:
        return "GAP_FILL"
    if "RB_" in t:
        return "STRUCTURAL_ZONE_INTERACTION"
    if "DISPLACEMENT_FAILED_CONTINUATION" in t:
        return "FAILED_REACTION"
    if "DISPLACEMENT_CONTINUATION" in t:
        return "REACTION_CONTINUATION"
    if "GOOD" in t and "DISPLACEMENT" in t:
        return "STRONG_DISPLACEMENT"
    if "BAD" in t and "DISPLACEMENT" in t:
        return "WEAK_DISPLACEMENT"
    if "DISPLACEMENT" in t:
        return "MIXED_DISPLACEMENT"
    if "COMPRESSION" in t:
        return "COMPRESSION"
    if "EXPANSION" in t:
        return "EXPANSION"
    if "BAND" in t:
        return "BAND_REJECTION"
    if t.startswith("VWAP"):
        return "VWAP_INTERACTION"
    if "SWEEP" in t:
        return "LIQUIDITY_SWEEP"
    if "RECLAIM" in t:
        return "RECLAIM"
    if "ACCEPTANCE" in t:
        return "ACCEPTANCE"
    if "BREAK" in t:
        return "LEVEL_BREAK"
    if t.startswith("ANCHOR") and "REJECTION" in t:
        return "ANCHOR_REJECTION"
    if t.startswith("ANCHOR"):
        return "ANCHOR_INTERACTION"
    if "REJECTION" in t:
        return "REJECTION"
    return "STRUCTURAL_EVENT"


def reduce_graph(exact_graph: str) -> str:
    toks = [p.strip() for p in exact_graph.split("->") if p.strip()]
    reduced = [_reduce_token(t) for t in toks]
    collapsed = []
    for r in reduced:
        if not collapsed or collapsed[-1] != r:
            collapsed.append(r)
    return " -> ".join(collapsed)


# ---- numeric features -------------------------------------------------------

# session phase from ET wall-clock
def _session(ts_et) -> str:
    hm = ts_et.hour * 60 + ts_et.minute
    if 18 * 60 <= hm or hm < 3 * 60:
        return "asia"
    if 3 * 60 <= hm < 8 * 60:
        return "london"
    if 8 * 60 <= hm < 9 * 60 + 30:
        return "ny_premarket"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "rth"
    return "post"


class FeatureContext:
    """Precomputed lookups shared across candidates for one run."""

    def __init__(self, ps):
        self.ps = ps
        self.reg = ps.registry
        self.bars = ps.bars
        self.atr = ps.atr
        # seq -> vwap session
        self.vwap_by_seq = {}
        for vs in ps.vwaps:
            for seq in vs.vwap:
                self.vwap_by_seq[seq] = vs
        self.levels = ps.all_levels

    def _target_family(self, setup):
        from ..data.bars import NQ_TICK
        for lv in self.levels:
            if lv.created_seq <= setup.entry_seq and lv.segment_id == setup.segment_id:
                if abs(lv.price_ref - setup.structural_target) < NQ_TICK:
                    return lv.subtype
        return "measured_or_other"

    def _contradictory(self, setup):
        lo, hi = sorted((setup.entry_price, setup.structural_target))
        for lv in self.levels:
            if lv.created_seq <= setup.entry_seq and lv.segment_id == setup.segment_id:
                if lo < lv.price_ref < hi:
                    return True
        return False


def build_features(candidate, ctx: FeatureContext) -> dict:
    s = candidate.setup
    bar = ctx.bars[s.entry_seq]
    atr = ctx.atr[s.entry_seq] or 0.0
    dir_sign = 1 if s.direction == "long" else -1
    origin = None
    try:
        origin = ctx.reg.get(s.origin_id)
    except Exception:
        pass
    fam = origin.family if origin else "unknown"

    f = {
        "origin_family": fam,
        "source_timeframe": "1m",
        "session": _session(bar.ts_et),
        "minutes_from_0930": bar.ts_et.hour * 60 + bar.ts_et.minute - (9 * 60 + 30),
        "direction": dir_sign,
        "entry_mode": s.entry_mode,
        "continuation_or_fade": s.continuation_or_fade,
        "path_family": s.path_family,
        "dist_to_stop_atr": round(abs(s.entry_price - s.structural_stop) / atr, 4)
        if atr else None,
        "natural_rr": round(s.natural_rr, 4),
        "executed_rr": round(s.executed_rr, 4),
        "has_fvg": s.has_fvg, "has_ifvg": s.has_ifvg, "has_rb": s.has_rb,
        "has_sweep": s.has_sweep,
        "target_family": ctx._target_family(s),
        "contradictory_structure": ctx._contradictory(s),
        "htf_alignment": "unknown_1m_only",
        # defaults, filled below when the origin family provides them
        "origin_age_bars": None, "zone_width_atr": None, "revisit_number": None,
        "displacement_grade": None, "displacement_body_atr": None,
        "path_body_ratio": None, "favorable_close": None,
        "level_family": None, "sweep_state": None,
        "vwap_side": None, "nearest_vwap_band": None,
    }

    if origin is not None:
        f["origin_age_bars"] = s.entry_seq - origin.created_seq
        if fam in ("fvg", "ifvg"):
            f["zone_width_atr"] = round((origin.hi - origin.lo) / atr, 4) if atr else None
            f["revisit_number"] = sum(1 for e in origin.events
                                      if e.kind == "REVISIT" and e.seq <= s.entry_seq)
        if fam == "displacement":
            fe = origin.features
            f["displacement_grade"] = origin.grade
            f["displacement_body_atr"] = round(fe.get("body_atr", 0), 4)
            f["path_body_ratio"] = round(fe.get("body_ratio", 0), 4)
            # favorable_close is already direction-normalized (positive=in setup dir)
            f["favorable_close"] = round(fe.get("favorable_close", 0), 4)
        if fam in ("hist_level", "liquidity", "time_anchor"):
            f["level_family"] = origin.subtype
            # causal cutoff: Primitive.has_event() checks the object's whole
            # lifetime, which can include a SWEEP recorded after this candidate's
            # own trigger (found by test_similarity_audit.py::
            # test_features_unchanged_by_bars_added_after_trigger). Match the
            # seq<=entry_seq pattern already used for revisit_number above.
            f["sweep_state"] = any(e.kind == "SWEEP" and e.seq <= s.entry_seq
                                   for e in origin.events)

    vs = ctx.vwap_by_seq.get(s.entry_seq)
    if vs is not None:
        val = vs.value_at(s.entry_seq)
        if val:
            f["vwap_side"] = int(dir_sign) if (bar.close - val["vwap"]) * dir_sign >= 0 else -int(dir_sign)
            # nearest band by absolute distance
            bands = val["bands"]
            nb = min(bands, key=lambda k: abs(bands[k] - bar.close))
            f["nearest_vwap_band"] = nb
    return f


def enrich_candidates(result) -> None:
    """Fill reduced_graph and features on every candidate (in place)."""
    ctx = FeatureContext(result["engine"].ps)
    for c in result["candidates"]:
        c.reduced_graph = reduce_graph(c.exact_graph)
        c.features = build_features(c, ctx)

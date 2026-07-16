"""Concise development review pack: 25 required categories.

Selection is deterministic and chronological (earliest qualifying occurrence),
never chosen by profit. Each setup example carries its permanent id, timestamp,
direction, exact graph, entry mode, primitive ids, frozen entry/stop/natural
target/natural RR, executed target/RR, expiry, a chart, and — shown separately —
its diagnostic outcome.
"""

from __future__ import annotations

import json
import os

from .charts import render_primitive_chart, render_setup_chart

CHART_DIR = os.path.join("artifacts", "charts")
PACK_DIR = os.path.join("artifacts", "review_pack")


def _sized_prim(ps, prims, subtype):
    """First occurrence of a subtype whose zone is materially sized (>=0.5 ATR)."""
    for p in sorted(prims, key=lambda x: x.created_seq):
        if p.subtype != subtype:
            continue
        a = ps.atr[p.created_seq] if p.created_seq < len(ps.atr) else None
        if a and (p.hi - p.lo) >= 0.5 * a:
            return p
    # fall back to first of subtype if none sized
    for p in sorted(prims, key=lambda x: x.created_seq):
        if p.subtype == subtype:
            return p
    return None


def _origin_family(ps, s):
    try:
        return ps.registry.get(s.origin_id).family
    except Exception:
        return "unknown"


def _first_setup(ledger, pred, pool=None):
    pool = ledger.eligible if pool is None else pool
    for s in sorted(pool, key=lambda x: x.entry_seq):
        if pred(s):
            return s
    return None


def build_selection(ps, ledger):
    of = lambda s: _origin_family(ps, s)
    prim = [
        ("01_bullish_fvg", "primitive", _sized_prim(ps, ps.fvgs, "bullish")),
        ("02_bearish_fvg", "primitive", _sized_prim(ps, ps.fvgs, "bearish")),
        ("03_bullish_ifvg", "primitive", _sized_prim(ps, ps.ifvgs, "bullish")),
        ("04_bearish_ifvg", "primitive", _sized_prim(ps, ps.ifvgs, "bearish")),
        ("05_bullish_rb", "primitive", _sized_prim(ps, ps.rbs, "bullish")),
        ("06_bearish_rb", "primitive", _sized_prim(ps, ps.rbs, "bearish")),
        ("07_good_displacement", "primitive",
         next((d for d in ps.displacements if d.grade == "good"), None)),
        ("08_bad_displacement", "primitive",
         next((d for d in ps.displacements if d.grade == "bad"), None)),
    ]
    stp = [
        ("09_fvg_formation_continuation", lambda s: s.has_fvg
         and s.path_family == "formation_continuation"
         and s.entry_mode in ("formation_close", "next_bar")),
        ("10_fvg_fill_continuation", lambda s: s.has_fvg
         and s.path_family == "retracement_continuation"
         and s.entry_mode in ("first_touch", "midpoint", "full_fill")),
        ("11_ifvg_immediate", lambda s: s.has_ifvg
         and s.entry_mode in ("formation_close", "next_bar")),
        ("12_ifvg_retest", lambda s: s.has_ifvg and s.entry_mode == "retest"),
        ("13_time_anchor_no_fvg", lambda s: of(s) == "time_anchor" and not s.has_fvg),
        ("14_hist_level_continuation", lambda s: of(s) == "hist_level"
         and s.continuation_or_fade == "continuation"),
        ("15_hist_level_fade", lambda s: of(s) == "hist_level"
         and s.continuation_or_fade == "fade"),
        ("16_vwap_continuation", lambda s: of(s) == "vwap"
         and s.continuation_or_fade == "continuation"),
        ("17_vwap_fade", lambda s: of(s) == "vwap"
         and s.continuation_or_fade == "fade"),
        ("18_compression_to_expansion", lambda s: of(s) == "structure"
         and s.path_family == "formation_continuation"),
        ("19_capped_1R", lambda s: abs(s.executed_rr - 1.0) < 1e-9),
        ("20_natural_half_to_1R", lambda s: 0.5 <= s.executed_rr < 1.0),
        ("22_continuation_setup", lambda s: s.continuation_or_fade == "continuation"),
        ("23_fade_setup", lambda s: s.continuation_or_fade == "fade"),
        ("24_no_fvg_no_ifvg", lambda s: not s.has_fvg and not s.has_ifvg),
        ("25_no_liquidity_sweep", lambda s: not s.has_sweep),
    ]

    selection = []
    for name, kind, p in prim:
        selection.append((name, kind, p))
    for name, pred in stp:
        selection.append((name, "setup", _first_setup(ledger, pred)))
    # 21: rejected below 0.5R, from the rejected ledger
    rej = _first_setup(
        ledger, lambda s: s.rejection_reason == "INSUFFICIENT_NATURAL_RR",
        pool=ledger.rejected)
    selection.append(("21_rejected_below_half_R", "rejected", rej))
    # keep numeric order for presentation
    selection.sort(key=lambda t: t[0])
    return selection


def _setup_detail(ps, s):
    return {
        "setup_id": s.id,
        "timestamp_et": str(s.entry_ts.tz_convert("America/New_York")),
        "direction": s.direction,
        "graph": s.graph,
        "entry_mode": s.entry_mode,
        "path_family": s.path_family,
        "continuation_or_fade": s.continuation_or_fade,
        "origin_family": _origin_family(ps, s),
        "primitive_ids": s.primitive_ids,
        "context_conditions": s.context_conditions,
        "entry": s.entry_price,
        "natural_structural_stop": s.structural_stop,
        "natural_structural_target": s.structural_target,
        "natural_rr": round(s.natural_rr, 4),
        "executed_target": s.executed_target,
        "executed_rr": round(s.executed_rr, 4),
        "expiry_rule": s.expiry_rule,
        "has_fvg": s.has_fvg, "has_ifvg": s.has_ifvg,
        "has_rb": s.has_rb, "has_sweep": s.has_sweep,
        "outcome_shown_separately": s.outcome,
    }


def generate(ps, ledger, out_md=None):
    os.makedirs(CHART_DIR, exist_ok=True)
    os.makedirs(PACK_DIR, exist_ok=True)
    out_md = out_md or os.path.join(PACK_DIR, "review_pack.md")
    bars = ps.bars
    selection = build_selection(ps, ledger)

    records = []
    lines = ["# Development Review Pack (July 2025, contaminated dev data)",
             "",
             "Deterministic chronological selection per category. Examples validate "
             "implementation only; they are NOT selected by profit and are NOT "
             "forward evidence. Outcome is shown separately from the frozen setup.",
             ""]

    for name, kind, obj in selection:
        chart_rel = os.path.join("..", "charts", f"{name}.png")
        chart_abs = os.path.join(CHART_DIR, f"{name}.png")
        lines.append(f"## {name}")
        if obj is None:
            lines.append("_No qualifying occurrence in the dev window._\n")
            records.append({"category": name, "kind": kind, "example": None})
            continue
        if kind == "primitive":
            title = f"{name}  {obj.id} {obj.subtype}  " \
                    f"{obj.created_ts.tz_convert('America/New_York')}"
            render_primitive_chart(bars, obj, chart_abs, title)
            det = {
                "primitive_id": obj.id, "family": obj.family, "subtype": obj.subtype,
                "timestamp_et": str(obj.created_ts.tz_convert("America/New_York")),
                "zone_lo": obj.lo, "zone_hi": obj.hi,
                "events": [e.kind for e in obj.events][:12],
            }
            lines.append(f"- primitive_id: `{obj.id}`  subtype: {obj.subtype}  "
                         f"zone: [{obj.lo:.2f}, {obj.hi:.2f}]")
            lines.append(f"- timestamp (ET): {det['timestamp_et']}")
        else:
            title = f"{name}  {obj.id} {obj.direction} {obj.entry_mode}"
            render_setup_chart(bars, obj, chart_abs, title)
            det = _setup_detail(ps, obj)
            lines.append(f"- setup_id: `{obj.id}`  {obj.direction}  "
                         f"mode: {obj.entry_mode}  ({obj.continuation_or_fade})")
            lines.append(f"- timestamp (ET): {det['timestamp_et']}")
            lines.append(f"- graph: `{obj.graph}`")
            lines.append(f"- primitive_ids: {obj.primitive_ids}")
            lines.append(f"- entry {obj.entry_price:.2f} | stop "
                         f"{obj.structural_stop:.2f} | natural target "
                         f"{obj.structural_target:.2f} | natural RR "
                         f"{obj.natural_rr:.3f}")
            lines.append(f"- executed target {obj.executed_target:.2f} | executed "
                         f"RR {obj.executed_rr:.3f} | expiry {obj.expiry_rule}")
            lines.append(f"- **outcome (separate/diagnostic): {obj.outcome}**")
        lines.append("")
        lines.append(f"![{name}]({chart_rel})")
        lines.append("")
        records.append({"category": name, "kind": kind, "example": det,
                        "chart": chart_rel})

    with open(out_md, "w") as fh:
        fh.write("\n".join(lines))
    with open(os.path.join(PACK_DIR, "review_pack.json"), "w") as fh:
        json.dump(records, fh, indent=2)
    return records


if __name__ == "__main__":
    from ..pipeline.run import run
    ps, ledger, _ = run()
    recs = generate(ps, ledger)
    n = sum(1 for r in recs if r["example"] is not None)
    print(f"review pack: {n}/{len(recs)} categories populated")

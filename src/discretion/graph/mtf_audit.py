"""Development audit pack for the multi-timeframe target layer (Commit 6).

Deterministic (chronological, never profit-selected) counts, ledgers, hashes and
a 25-example review pack showing the causal target inventory, the four frozen
target policies and the frozen RR behaviour. Development data only; nothing here
is a forward or edge claim.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd

from ..review.charts import _candles, _window, render_setup_chart
from .pipeline import graph_candidate_ledger, ledger_hash, counts as base_counts

OUT = os.path.join("artifacts", "mtf_targets")
CHART_DIR = os.path.join(OUT, "charts")


def _sha(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- counts

def _wick_state(w):
    if w.closed_through_seq is not None:
        return "closed_through"
    if w.swept_seq is not None:
        return "swept"
    if w.positive_overlap_seq is not None:
        return "overlapped"
    return "fresh"


def _fvg_state(f):
    if f.failed_seq is not None:
        return "failed"
    if f.first_fill_seq is not None:
        return "filled"
    return "fresh"


def mtf_counts(result):
    ps = result["engine"].ps
    cands = result["graph_candidates"]
    rej = result["graph_rejected"]

    # completed HTF candles by timeframe
    candles_by_tf = {tf: len(cs) for tf, cs in ps.htf.items()}

    # wick candidates
    wick_side_tf = Counter((w.timeframe, w.side) for w in ps.wicks)
    wick_grade = Counter(w.prominence_grade for w in ps.wicks)
    exposed_variants = {N: sum(1 for w in ps.wicks if w.exposed.get(N) is not None)
                        for N in (3, 5, 10)}
    wick_states = Counter(_wick_state(w) for w in ps.wicks)

    # HTF FVGs
    fvg_tf_dir = Counter((f.timeframe, f.subtype) for f in ps.htf_fvgs)
    fvg_states = Counter(_fvg_state(f) for f in ps.htf_fvgs)
    ifvg_parent_linked = sum(1 for iv in ps.htf_ifvgs if iv.source_fvg_id)

    # considered targets aggregated over unique triggers (variants share a ledger)
    considered_by_family = Counter()
    considered_by_tf = Counter()
    rejected_by_reason = Counter()
    seen_trig = set()
    for c in cands + rej:
        if c.trigger_event_id in seen_trig:
            continue
        seen_trig.add(c.trigger_event_id)
        for r in c.considered_targets:
            considered_by_family[r["family"]] += 1
            considered_by_tf[str(r["timeframe"])] += 1
            for reason in r["rejection_reasons"]:
                rejected_by_reason[reason] += 1

    selected_by_policy = Counter(c.target_policy_id for c in cands)
    cand_target_family = Counter(c.target_anchor_type for c in cands)
    cand_target_tf = Counter(str(c.target_anchor_timeframe) for c in cands)

    below_half = sum(1 for c in rej
                     if c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR")
    natural_half_to_1 = sum(1 for c in cands if 0.5 <= c.setup.natural_rr < 1.0)
    natural_ge_1 = sum(1 for c in cands if c.setup.natural_rr >= 1.0)

    triggers_forming = len({c.trigger_event_id for c in cands})

    return {
        "data_boundaries": result.get("_window"),
        "completed_candles_by_timeframe": candles_by_tf,
        "wick_candidates_by_tf_side": {f"{tf}m_{side}": n
                                       for (tf, side), n in sorted(wick_side_tf.items())},
        "wick_objects_by_grade": dict(wick_grade),
        "wick_exposed_variants_by_lookback": exposed_variants,
        "wick_final_states": dict(wick_states),
        "htf_fvgs_by_tf_direction": {f"{tf}m_{sub}": n
                                     for (tf, sub), n in sorted(fvg_tf_dir.items())},
        "htf_fvg_states": dict(fvg_states),
        "htf_ifvgs_parent_linked": ifvg_parent_linked,
        "htf_ifvgs_total": len(ps.htf_ifvgs),
        "target_candidates_considered_by_family": dict(considered_by_family),
        "target_candidates_considered_by_timeframe": dict(considered_by_tf),
        "target_candidates_rejected_by_reason": dict(rejected_by_reason),
        "targets_selected_by_policy": dict(selected_by_policy),
        "candidates_by_target_family": dict(cand_target_family),
        "candidates_by_target_timeframe": dict(cand_target_tf),
        "candidates_below_0p5R_rejected": below_half,
        "candidates_natural_0p5_to_1R": natural_half_to_1,
        "candidates_natural_ge_1R_capped": natural_ge_1,
        "graph_candidates_before_policy_variants": triggers_forming,
        "graph_candidates_after_policy_variants": len(cands),
        "qualification": dict(Counter(c.qualification for c in cands)),
    }


# ---------------------------------------------------------------- charts

def _zone_chart(bars, lo, hi, center, path, title, extra_lines=None):
    i0, i1 = _window(bars, center, 25, 45)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _candles(ax, bars, i0, i1)
    ax.add_patch(Rectangle((center - 0.5, lo), (i1 - 1) - center + 0.5, max(hi - lo, 0.01),
                           facecolor="#42a5f5", alpha=0.20, edgecolor="#1e88e5", zorder=0))
    ax.axvline(center, color="#616161", lw=0.8, ls=":")
    for y, c, lab in (extra_lines or []):
        ax.axhline(y, color=c, lw=0.9, ls="--", label=lab)
    if extra_lines:
        ax.legend(fontsize=6, loc="best")
    ax.set_title(title, fontsize=9)
    ax.set_ylabel("NQ points")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def _cand_chart(bars, cand, path, title):
    render_setup_chart(bars, cand.setup, path, title)


# ---------------------------------------------------------------- examples

def _first(seq, pred):
    for x in seq:
        if pred(x):
            return x
    return None


def _cand_detail(cand):
    s = cand.setup
    considered = cand.considered_targets
    return {
        "candidate_id": cand.candidate_id, "branch_id": cand.source_branch_id,
        "graph": cand.exact_graph,
        "trigger_timestamp_et": str(s.entry_ts.tz_convert("America/New_York")),
        "direction": s.direction, "trigger_family": s.path_family,
        "stop_anchor": {"type": cand.stop_anchor_type, "rule": cand.anchor_resolution_rule,
                        "price": cand.stop_anchor_price},
        "selected_target": {"object_id": cand.target_anchor_object_id,
                            "family": cand.target_anchor_type,
                            "timeframe": cand.target_anchor_timeframe,
                            "surface": cand.target_surface_policy,
                            "policy": cand.target_policy_id,
                            "rank": cand.selected_target_rank,
                            "selection_rule": cand.selection_rule_id,
                            "price": cand.target_anchor_price},
        "natural_stop": s.structural_stop, "natural_target": s.structural_target,
        "natural_rr": round(s.natural_rr, 4),
        "executed_target": s.executed_target, "executed_rr": round(s.executed_rr, 4),
        "n_considered_targets": len(considered),
        "considered_targets": considered,
        "outcome_shown_separately": s.outcome,
    }


def select_mtf_examples(result):
    """25 deterministic categories (chronological, never profit-selected)."""
    ps = result["engine"].ps
    wicks = sorted(ps.wicks, key=lambda w: (w.created_seq, w.id))
    fvgs = sorted(ps.htf_fvgs, key=lambda f: (f.created_seq, f.id))
    cands = sorted(result["graph_candidates"], key=lambda c: (c.setup.entry_seq, c.candidate_id))
    rej = sorted(result["graph_rejected"], key=lambda c: (c.setup.entry_seq, c.candidate_id))

    def wick(pred):
        return _first(wicks, pred)

    def fvg(pred):
        return _first(fvgs, pred)

    def cand(pred):
        return _first(cands, pred)

    def cand_tgt_family(fam):
        return _first(cands, lambda c: c.target_anchor_type == fam)

    S = []
    S.append(("01_high_5m_upper_wick", "wick",
              wick(lambda w: w.timeframe == 5 and w.side == "upper" and w.prominence_grade == "HIGH")))
    S.append(("02_high_5m_lower_wick", "wick",
              wick(lambda w: w.timeframe == 5 and w.side == "lower" and w.prominence_grade == "HIGH")))
    S.append(("03_15m_prominent_wick", "wick",
              wick(lambda w: w.timeframe == 15 and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("04_30m_prominent_wick", "wick",
              wick(lambda w: w.timeframe == 30 and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("05_60m_prominent_wick", "wick",
              wick(lambda w: w.timeframe == 60 and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("06_exposed_wick_no_prior_overlap", "wick",
              wick(lambda w: w.exposed.get(5) is not None and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("07_wick_invalidated_by_later_overlap", "wick",
              wick(lambda w: w.positive_overlap_seq is not None and w.swept_seq is None
                   and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("08_wick_consumed_by_sweep", "wick",
              wick(lambda w: w.swept_seq is not None and w.prominence_grade in ("HIGH", "MEDIUM"))))
    S.append(("09_fresh_5m_fvg_target", "fvg", fvg(lambda f: f.timeframe == 5 and f.active)))
    S.append(("10_fresh_15m_fvg_target", "fvg", fvg(lambda f: f.timeframe == 15 and f.active)))
    S.append(("11_fresh_30m_fvg_target", "fvg", fvg(lambda f: f.timeframe == 30 and f.active)))
    S.append(("12_fresh_60m_fvg_target", "fvg", fvg(lambda f: f.timeframe == 60 and f.active)))
    S.append(("13_failed_fvg_excluded", "fvg", fvg(lambda f: f.failed_seq is not None)))
    S.append(("14_fvg_proximal_edge_target", "cand", cand_tgt_family("htf_fvg")))
    S.append(("15_fvg_midpoint_research_variant", "note",
              "MIDPOINT/DISTAL_EDGE are frozen research surfaces exposed on every "
              "HTFFVG.surface(); executable candidates default to PROXIMAL_EDGE and "
              "no candidate switches surface from outcome."))
    S.append(("16_rb_continuation_targets_prominent_wick", "cand",
              cand(lambda c: c.setup.path_family in ("rb_reaction", "rb_fvg_fill")
                   and c.target_anchor_type == "wick_liquidity")))
    S.append(("17_fvg_continuation_targets_htf_fvg", "cand",
              cand(lambda c: c.setup.path_family in ("fvg_formation", "fvg_fill")
                   and c.target_anchor_type == "htf_fvg")))
    S.append(("18_sweep_fade_targets_opposing_mtf_liquidity", "cand",
              cand(lambda c: c.setup.path_family in ("sweep_fade", "sweep_reclaim_fade")
                   and c.target_anchor_type in ("wick_liquidity", "htf_fvg", "htf_ifvg"))))
    S.append(("19_vwap_path_retains_semantic_vwap_target", "cand",
              cand(lambda c: c.setup.path_family in ("vwap_band_fade", "vwap_bounce",
                   "vwap_reclaim", "vwap_break_accept") and "vwap" in c.target_anchor_type)
              or cand(lambda c: "vwap" in c.target_anchor_type)))
    S.append(("20_natural_0p5_to_1R_accepted", "cand",
              cand(lambda c: 0.5 <= c.setup.natural_rr < 1.0)))
    S.append(("21_natural_gt_1R_capped_to_1R", "cand",
              cand(lambda c: c.setup.natural_rr > 1.0 and c.setup.executed_rr == 1.0)))
    S.append(("22_below_0p5R_rejected_no_manipulation", "rej",
              _first(rej, lambda c: c.setup.rejection_reason == "INSUFFICIENT_NATURAL_RR")))
    S.append(("23_same_graph_two_target_policies", "policy_pair", None))
    S.append(("24_occluded_farther_target_rejected", "occlusion", None))
    S.append(("25_no_future_information_in_selection", "note",
              "Target selection reads only structures with available_seq <= "
              "entry_seq (bisect in TargetInventory._raw); freshness/fill/sweep "
              "states are stamped from completed 1-minute bars after availability; "
              "outcome is evaluated only after the candidate is stored."))
    return S


def _pick_policy_pair(result):
    by_trig = defaultdict(list)
    for c in result["graph_candidates"]:
        by_trig[c.trigger_event_id].append(c)
    for trig in sorted(by_trig):
        group = by_trig[trig]
        policies = {c.target_policy_id for c in group}
        if len(policies) >= 2:
            return sorted(group, key=lambda c: c.candidate_id)[:2]
    return None


def _pick_occlusion(result):
    for c in sorted(result["graph_candidates"], key=lambda c: c.candidate_id):
        occ = [r for r in c.considered_targets if r["occluded_by"]]
        if occ:
            return c, occ[0]
    return None


# ---------------------------------------------------------------- generate

def generate_mtf(result, window_label, out=OUT):
    chart_dir = os.path.join(out, "charts")
    os.makedirs(chart_dir, exist_ok=True)
    ps = result["engine"].ps
    bars = ps.bars
    result["_window"] = window_label
    cts = mtf_counts(result)

    # candidate ledger (with target-policy columns), gzipped (hash committed)
    cl = graph_candidate_ledger(result)
    with gzip.open(os.path.join(out, "candidates_mtf.csv.gz"), "wt") as fh:
        pd.DataFrame(cl).to_csv(fh, index=False)

    # considered-target ledger (one row per considered target per unique trigger), gz
    considered_rows = []
    seen = set()
    for c in result["graph_candidates"] + result["graph_rejected"]:
        if c.trigger_event_id in seen:
            continue
        seen.add(c.trigger_event_id)
        for r in c.considered_targets:
            row = {"trigger_event_id": c.trigger_event_id, **r}
            row["rejection_reasons"] = "|".join(r["rejection_reasons"])
            considered_rows.append(row)
    with gzip.open(os.path.join(out, "considered_targets.csv.gz"), "wt") as fh:
        pd.DataFrame(considered_rows).to_csv(fh, index=False)

    manifest = {
        "window": window_label, "counts": cts,
        "candidate_ledger_hash": ledger_hash(cl),
        "candidate_ledger_rows": len(cl),
        "considered_targets_hash": _sha(considered_rows),
        "considered_targets_rows": len(considered_rows),
        "htf_candle_hash": _sha([(tf, c.candle_id, c.open, c.high, c.low, c.close,
                                  c.available_seq) for tf in ps.htf for c in ps.htf[tf]]),
        "wick_hash": _sha([(w.id, w.timeframe, w.side, w.proximal, w.prominence_grade)
                           for w in ps.wicks]),
        "htf_fvg_hash": _sha([(f.id, f.timeframe, f.direction, f.lo, f.hi) for f in ps.htf_fvgs]),
    }

    # 25 examples
    md = ["# Multi-Timeframe Target Layer — Development Audit Pack", "",
          f"Window: {window_label}. Development (contaminated) data only — no edge "
          "or forward claim. Examples selected chronologically, never by profit. "
          "Outcome is shown separately from selection.", ""]
    examples = []
    for name, kind, obj in select_mtf_examples(result):
        md.append(f"## {name}")
        chart_rel = None
        det = None
        if kind == "note":
            det = {"note": obj}
        elif kind == "policy_pair":
            pair = _pick_policy_pair(result)
            if pair:
                det = {"note": "same trigger/graph resolved under two distinct target "
                       "policies (separate research candidates, never merged)",
                       "variants": [{"candidate_id": c.candidate_id,
                                     "target_policy_id": c.target_policy_id,
                                     "target_family": c.target_anchor_type,
                                     "target_price": c.target_anchor_price,
                                     "executed_rr": round(c.setup.executed_rr, 4)}
                                    for c in pair]}
                p = os.path.join(chart_dir, f"{name}.png")
                _cand_chart(bars, pair[0], p, f"{name} {pair[0].candidate_id}")
                chart_rel = os.path.join("charts", f"{name}.png")
        elif kind == "occlusion":
            oc = _pick_occlusion(result)
            if oc:
                c, row = oc
                det = {"candidate_id": c.candidate_id,
                       "note": "a farther active target is occluded by a nearer one "
                       "and is not selected; both retained in the ledger",
                       "occluded_target": row}
        elif obj is None:
            det = None
        elif kind == "wick":
            w = obj
            p = os.path.join(chart_dir, f"{name}.png")
            _zone_chart(bars, w.full_lo, w.full_hi, w.created_seq, p,
                        f"{name}  {w.id} {w.timeframe}m {w.side} {w.prominence_grade}",
                        [(w.proximal, "#1e88e5", f"proximal {w.proximal:.2f}")])
            chart_rel = os.path.join("charts", f"{name}.png")
            det = {"object_id": w.id, "timeframe": w.timeframe, "side": w.side,
                   "prominence_score": w.prominence_score, "grade": w.prominence_grade,
                   "full_zone": [w.full_lo, w.full_hi], "exposed_5": w.exposed.get(5),
                   "proximal": w.proximal, "extreme": w.extreme,
                   "available_seq": w.created_seq, "first_touch_seq": w.first_touch_seq,
                   "positive_overlap_seq": w.positive_overlap_seq,
                   "swept_seq": w.swept_seq, "closed_through_seq": w.closed_through_seq,
                   "final_state": _wick_state(w), "metrics": w.metrics}
        elif kind == "fvg":
            f = obj
            p = os.path.join(chart_dir, f"{name}.png")
            _zone_chart(bars, f.lo, f.hi, f.created_seq, p,
                        f"{name}  {f.id} {f.timeframe}m {f.subtype}",
                        [(f.proximal, "#1e88e5", f"proximal {f.proximal:.2f}"),
                         (f.midpoint, "#8e24aa", f"midpoint {f.midpoint:.2f}"),
                         (f.distal, "#00897b", f"distal {f.distal:.2f}")])
            chart_rel = os.path.join("charts", f"{name}.png")
            det = {"object_id": f.id, "timeframe": f.timeframe, "direction": f.subtype,
                   "abc": [f.a_candle_id, f.b_candle_id, f.c_candle_id],
                   "zone": [f.lo, f.hi], "proximal": f.proximal, "midpoint": f.midpoint,
                   "distal": f.distal, "width_atr": f.width_atr,
                   "available_seq": f.created_seq, "first_fill_seq": f.first_fill_seq,
                   "full_fill_seq": f.full_fill_seq, "failed_seq": f.failed_seq,
                   "final_state": _fvg_state(f)}
        else:  # cand / rej
            p = os.path.join(chart_dir, f"{name}.png")
            _cand_chart(bars, obj, p, f"{name} {obj.candidate_id}")
            chart_rel = os.path.join("charts", f"{name}.png")
            det = _cand_detail(obj)

        if det is None:
            md.append("_No qualifying occurrence in the dev window._\n")
            examples.append({"category": name, "example": None})
            continue
        for k, v in det.items():
            if k == "considered_targets":
                md.append(f"- {k}: {len(v)} rows (see considered_targets.csv.gz)")
            else:
                md.append(f"- {k}: {v}")
        if chart_rel:
            md.append(f"\n![{name}]({chart_rel})")
        md.append("")
        examples.append({"category": name, "chart": chart_rel, "example": det})

    manifest["n_examples_populated"] = sum(1 for e in examples if e["example"])
    with open(os.path.join(out, "audit_pack.md"), "w") as fh:
        fh.write("\n".join(md))
    with open(os.path.join(out, "audit_pack.json"), "w") as fh:
        json.dump(examples, fh, indent=2, default=str)
    with open(os.path.join(out, "counts.json"), "w") as fh:
        json.dump(cts, fh, indent=2, default=str)
    with open(os.path.join(out, "reproducibility.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return manifest, examples

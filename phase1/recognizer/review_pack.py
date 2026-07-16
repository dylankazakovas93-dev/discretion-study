"""
Front-page review pack + deliverables. Deterministic example selection (no
aesthetic choice). Structural score, learned evidence, predicted class and
realized outcome are shown as SEPARATE fields.
"""
import os
import sys
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE)); sys.path.insert(0, _HERE)
import prereg as PR

OUT = os.path.join(_HERE, "outputs")
CH = os.path.join(OUT, "charts")
os.makedirs(CH, exist_ok=True)
P1 = os.path.join(os.path.dirname(_HERE), "outputs")   # phase1 outputs
TZ = "America/New_York"


def load_tf(tf):
    d = pd.read_csv(os.path.join(P1, f"htf_candles_{tf}.csv"))
    d["bucket_open_et"] = pd.to_datetime(d["bucket_open_et"], utc=True).dt.tz_convert(TZ)
    return d.sort_values("bucket_open_et").reset_index(drop=True)


def draw_setup(o, fname):
    cd = load_tf(o["tf"])
    center = pd.Timestamp(o["trigger_ts_et"])
    ci = (cd["bucket_open_et"] - center).abs().idxmin()
    w = cd.iloc[max(0, ci - 12):min(len(cd), ci + 34)].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(13, 7))
    x = mdates.date2num(w["bucket_open_et"].dt.tz_localize(None))
    width = (x[1] - x[0]) * 0.7 if len(x) > 1 else 5e-4
    for xi, (_, r) in zip(x, w.iterrows()):
        up = r["close"] >= r["open"]; col = "#26a69a" if up else "#ef5350"
        ax.plot([xi, xi], [r["low"], r["high"]], color=col, lw=0.8, zorder=2)
        ax.add_patch(plt.Rectangle((xi - width / 2, min(r["open"], r["close"])), width,
                                   max(abs(r["close"] - r["open"]), 1e-6), color=col, zorder=3))
    col = "#c62828" if o["direction"] == "short" else "#2e7d32"
    ax.axhspan(min(o["fvg_lower"], o["fvg_upper"]) if "fvg_lower" in o else o["entry"],
               o["entry"], color=col, alpha=0.0)
    ax.axhline(o["entry"], color="#1565c0", lw=1.3, label="entry")
    ax.axhline(o["structural_stop"], color="#b71c1c", ls="--", lw=1.2, label="structural stop")
    ax.axhline(o["structural_target"], color="#1b5e20", ls="--", lw=1.2, label="structural target")
    ax.axhline(o["origin_extreme"], color="#6a1b9a", ls=":", lw=1.4, label=f"origin {o['origin_family']}")
    for key, cc, lab in [("trigger_ts_et", "#555", "trigger"), ("entry_fill_et", "#1565c0", "fill"),
                         ("resolution_et", "#000", "resolve")]:
        v = o.get(key)
        if v is not None and pd.notna(v):
            ax.axvline(mdates.date2num(pd.Timestamp(v).tz_convert(TZ).tz_localize(None)), color=cc, ls=":", lw=1.0, label=lab)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    ax.set_title(f"{o['occurrence_id']} [{o['direction']}] {o['final_predicted_class']} | outcome={o['outcome']}\n"
                 f"{o['exact_graph']}", fontsize=9)
    ax.grid(True, alpha=0.25)
    h, l = ax.get_legend_handles_labels()
    ax.legend(dict(zip(l, h)).values(), dict(zip(l, h)).keys(), fontsize=8, loc="best")
    fig.tight_layout(); fig.savefig(os.path.join(CH, fname), dpi=110); plt.close(fig)


def setup_block(o, full):
    hz = full.get("horizon_summary", {}) if full else {}
    ev = full.get("prediction", {}) if full else {}
    lines = [f"### {o['occurrence_id']}  ·  {o['final_predicted_class']}",
             f"- trigger {str(o['trigger_ts_et'])[:16]} ET · dir **{o['direction']}** · tf {o['tf']}",
             f"- graph (exact): `{o['exact_graph']}`",
             f"- graph (reduced): `{o['reduced_graph']}`",
             f"- primitives: {o['primitive_ids']}",
             f"- context (<=3): {o['context_conditions']}",
             f"- **structural score** {o['structural_score']} "
             f"(disp {o.get('sc_displacement_quality')}, trig {o.get('sc_trigger_clarity')}, "
             f"target {o.get('sc_target_room')})",
             f"- prev-session evidence (reduced family): "
             + "; ".join(f"{H}s n={hz.get(H,{}).get('n','-')} fav={hz.get(H,{}).get('fav_rate')}"
                         for H in ["1", "3", "5", "10", "20"]),
             f"- exact-graph evidence: n={o.get('exact_n')} fav={o.get('exact_fav_rate')} | "
             f"reduced n={o.get('reduced_n')} fav={o.get('reduced_fav_rate')}",
             f"- **shrunk expected R** {o.get('shrunk_expected_R')} · shrunk fav prob "
             f"{o.get('shrunk_favorable_probability')} · ESS {o.get('effective_sample_size')} · "
             f"evidence_count {o.get('evidence_count')} · uncertainty ±{o.get('uncertainty_halfwidth')}",
             f"- **predicted class (frozen before outcome): {o['final_predicted_class']}**",
             f"- entry {o['entry']} · stop {o['structural_stop']} · target {o['structural_target']} "
             f"({o['target_kind']}) · expiry E={o['expiry_E_bars']} bars",
             f"- **realized outcome (separate): {o['outcome']}** · realized R {o.get('realized_R')} · "
             f"MFE {o.get('mfe_R')}R MAE {o.get('mae_R')}R",
             f"\n![{o['occurrence_id']}](charts/{o['occurrence_id']}.png)\n"]
    return "\n".join(lines)


def main():
    j = pd.read_csv(os.path.join(OUT, "setup_occurrences_july.csv"))
    allo = pd.read_csv(os.path.join(OUT, "setup_occurrences_all.csv"))
    full_j = {o["occurrence_id"]: o for o in json.load(open(os.path.join(OUT, "july_occurrences_full.json")))}
    j = j.sort_values("trigger_ts_et").reset_index(drop=True)

    def first(df):
        return df.sort_values("trigger_ts_et").iloc[0].to_dict() if len(df) else None

    picks = {}
    picks["favorable"] = first(j[j.final_predicted_class == "FAVORABLE"])
    ins = j[j.final_predicted_class == "INSUFFICIENT_EVIDENCE"]
    adv = j[j.final_predicted_class == "ADVERSE"]
    picks["adverse_or_insufficient"] = first(adv if len(adv) else ins)
    picks["favorable_that_lost"] = first(j[(j.final_predicted_class == "FAVORABLE") & (j.outcome == "LOSS")])
    weak_won = j[(j.final_predicted_class.isin(["ADVERSE", "NEUTRAL"])) & (j.outcome == "WIN")]
    picks["weak_predicted_that_won"] = first(weak_won)
    if len(ins):
        picks["strong_but_insufficient"] = ins.sort_values("structural_score", ascending=False).iloc[0].to_dict()
    # genuinely new graph candidate: exact graph absent from ALL pre-July occurrences
    pre_exact = set(allo[~allo.occurrence_id.isin(j.occurrence_id)]["exact_graph"])
    new_cand = j[~j.exact_graph.isin(pre_exact)]
    picks["new_graph_candidate"] = first(new_cand)

    # draw charts for the picked setups
    seen = set()
    for key, o in picks.items():
        if o is None:
            continue
        if o["occurrence_id"] in seen:
            continue
        seen.add(o["occurrence_id"])
        draw_setup(o, o["occurrence_id"] + ".png")

    layers = json.load(open(os.path.join(OUT, "layer_comparison.json")))
    summ = json.load(open(os.path.join(OUT, "replay_summary.json")))

    L = ["# Phase 2 — Recognizer Review Pack (front page)\n",
         "_Observational prototype. Structural score, learned evidence, predicted class and "
         "realized outcome are separate fields. No edge claimed; one July week proves nothing._\n",
         "\n## Primitive examples (canonical Phase-1 ledgers)\n",
         "| kind | reference chart |",
         "|---|---|",
         "| valid rejection block | `../../outputs/charts/rejblock_bull_example.png` |",
         "| good displacement | `../../outputs/charts/disp_high.png` |",
         "| bad displacement | `../../outputs/charts/disp_low.png` |",
         "| valid FVG | `../../outputs/charts/fvg_5m_bull.png` |",
         "| valid iFVG | `../../outputs/charts/ifvg_bull.png` |\n",
         "\n## Predicted-setup examples (frozen before outcome)\n"]
    labels = {"favorable": "FAVORABLE", "adverse_or_insufficient": "ADVERSE / INSUFFICIENT_EVIDENCE",
              "favorable_that_lost": "FAVORABLE that LOST", "weak_predicted_that_won": "weakly-predicted (NEUTRAL) that WON",
              "strong_but_insufficient": "structurally strong but INSUFFICIENT_EVIDENCE",
              "new_graph_candidate": "genuinely new graph candidate (no prior exact-graph evidence)"}
    for key in ["favorable", "adverse_or_insufficient", "favorable_that_lost",
                "weak_predicted_that_won", "strong_but_insufficient", "new_graph_candidate"]:
        o = picks.get(key)
        L.append(f"\n## {labels[key]}\n")
        if o is None:
            L.append(f"_none present in the July window._\n")
        else:
            L.append(setup_block(o, full_j.get(o["occurrence_id"])))
    with open(os.path.join(OUT, "REVIEW_PACK.md"), "w") as f:
        f.write("\n".join(L))
    print("review pack written; picks:",
          {k: (v["occurrence_id"] if v is not None else None) for k, v in picks.items()})


if __name__ == "__main__":
    main()

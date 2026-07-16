"""
Driver: build prior setup ledger from pre-July history, replay July 6-10
chronologically, freeze each prediction from strictly-earlier sessions BEFORE
evaluating outcome, then emit ledgers, Layer 1/2/3 comparison and a review pack.

Usage: python replay.py <disc_csv> <disc_hash> <warmup_csv> <warmup_hash> <gap_csv> <gap_hash>
"""
import os
import sys
import json
import bisect
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE)); sys.path.insert(0, _HERE)
import core
import primitives as P
import prereg as PR
import engine as E
import graph as G
import evidence as EV

TZ = "America/New_York"
OUT = os.path.join(_HERE, "outputs")
os.makedirs(os.path.join(OUT, "charts"), exist_ok=True)
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60}
JULY_START = pd.Timestamp(PR.JULY_START_ET, tz=TZ)
JULY_END = pd.Timestamp(PR.JULY_END_ET, tz=TZ)


def in_july(ts):
    return JULY_START <= pd.Timestamp(ts) < JULY_END


# ---------------------------------------------------------------------------
# outcome evaluation on 1-minute bars (finest; enables same-bar ambiguity)
# ---------------------------------------------------------------------------

def seg_1m_arrays(et):
    d = {}
    for sid, g in et.groupby("segment_id"):
        g = g.sort_values("ts_open_et")
        d[int(sid)] = {
            "t": g["ts_open_et"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
            "h": g["high"].to_numpy(float), "l": g["low"].to_numpy(float),
            "c": g["close"].to_numpy(float),
        }
    return d


def evaluate_outcome(o, seg1m):
    """Frozen entry/stop/target -> outcome on 1m bars. Returns dict of outcome
    fields. Never alters the setup."""
    seg = seg1m.get(int(o["segment_id"]))
    res = {"outcome": "INCOMPLETE", "entry_fill_et": None, "resolution_et": None,
           "realized_R": np.nan, "favorable": False, "mfe_R": np.nan, "mae_R": np.nan,
           "time_to_target_min": None, "time_to_invalidation_min": None,
           "target_still_valid": True}
    if seg is None:
        return res
    t = seg["t"]; H = seg["h"]; L = seg["l"]
    entry = o["entry"]; stop = o["structural_stop"]; target = o["structural_target"]
    risk = o["risk_points"]; direction = o["direction"]
    avail = np.datetime64(pd.Timestamp(o["availability_et"]).tz_convert("UTC").tz_localize(None))
    tfm = TF_MIN.get(o["tf"], 5)
    fill_deadline = avail + np.timedelta64(PR.E_BARS * tfm, "m")
    i0 = int(np.searchsorted(t, avail))
    fill = None
    for j in range(i0, len(t)):
        if t[j] > fill_deadline:
            break
        if t[j] < avail:
            continue
        if direction == "short" and H[j] >= entry:
            fill = j; break
        if direction == "long" and L[j] <= entry:
            fill = j; break
    if fill is None:
        res["outcome"] = "EXPIRED"; return res
    res["entry_fill_et"] = pd.Timestamp(t[fill]).tz_localize("UTC").tz_convert(TZ)
    resolve_deadline = t[fill] + np.timedelta64(PR.H_BARS_1M, "m")
    mfe = mae = 0.0
    for j in range(fill, len(t)):
        if t[j] > resolve_deadline:
            res["outcome"] = "INCOMPLETE"; break
        if direction == "short":
            mfe = max(mfe, entry - L[j]); mae = max(mae, H[j] - entry)
            hit_t = L[j] <= target; hit_s = H[j] >= stop
        else:
            mfe = max(mfe, H[j] - entry); mae = max(mae, entry - L[j])
            hit_t = H[j] >= target; hit_s = L[j] <= stop
        if hit_t and hit_s:
            res["outcome"] = "AMBIGUOUS"; res["resolution_et"] = pd.Timestamp(t[j]).tz_localize("UTC").tz_convert(TZ); break
        if hit_t:
            res["outcome"] = "WIN"; res["favorable"] = True
            res["realized_R"] = abs(target - entry) / risk if risk > 0 else np.nan
            res["resolution_et"] = pd.Timestamp(t[j]).tz_localize("UTC").tz_convert(TZ)
            res["time_to_target_min"] = int((t[j] - t[fill]) / np.timedelta64(1, "m")); break
        if hit_s:
            res["outcome"] = "LOSS"; res["realized_R"] = -1.0
            res["resolution_et"] = pd.Timestamp(t[j]).tz_localize("UTC").tz_convert(TZ)
            res["time_to_invalidation_min"] = int((t[j] - t[fill]) / np.timedelta64(1, "m")); break
    res["mfe_R"] = round(mfe / risk, 3) if risk > 0 else np.nan
    res["mae_R"] = round(mae / risk, 3) if risk > 0 else np.nan
    return res


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(disc_csv, disc_hash, warm_csv, warm_hash, gap_csv, gap_hash):
    et, audit, tfl, sched, seg_led = core.build_combined(
        disc_csv, [warm_csv, gap_csv], disc_hash, [warm_hash, gap_hash])
    disc_abs = int(audit["segments"]["discovery_absolute_segment_id"])

    # BOUNDED prototype window (preregistered): keep full data for lookback but
    # only instantiate setups whose candles are at/after the window start.
    wstart = pd.Timestamp(PR.PRIOR_WINDOW_START_ET, tz=TZ)
    et = et[et["ts_open_et"] >= wstart].reset_index(drop=True)
    tfl = {k: v[v["bucket_open_et"] >= wstart].reset_index(drop=True) for k, v in tfl.items()}

    vwdf = E.compute_vwap_1m(et)
    vwdf_idx = {np.datetime64(pd.Timestamp(x).tz_convert("UTC").tz_localize(None)): k
                for k, x in enumerate(vwdf["ts_close_et"])}
    levels = E.build_levels(et)
    levels.to_csv(os.path.join(OUT, "levels.csv"), index=False)
    vjuly = vwdf[(vwdf["ts_open_et"] >= JULY_START) & (vwdf["ts_open_et"] < JULY_END)]
    vjuly.to_csv(os.path.join(OUT, "vwap_1m_july.csv"), index=False)

    # build occurrences across ALL history on setup TFs
    all_occ = []
    total_rej = 0
    prim_counts = {}
    for tf in PR.SETUP_TFS:
        cd = P.make_candles(tfl[tf], tf)
        fvgs = P.detect_fvgs(cd)
        ifvgs = P.detect_ifvg(cd, fvgs)
        prim_counts[f"fvg_{tf}"] = int(len(fvgs)); prim_counts[f"ifvg_{tf}"] = int(len(ifvgs))
        occ, rej = G.construct(tf, cd, fvgs, ifvgs, levels, vwdf, vwdf_idx, disc_abs)
        all_occ += occ; total_rej += rej
    # evaluate outcomes
    seg1m = seg_1m_arrays(et)
    for o in all_occ:
        o.update(evaluate_outcome(o, seg1m))
    all_occ.sort(key=lambda o: (pd.Timestamp(o["trigger_ts_et"]), o["occurrence_id"]))

    # chronological prediction pass (strictly-earlier sessions only).
    # store holds RUNNING aggregates; entries are folded in only AFTER a session
    # is fully predicted, so every query sees strictly-earlier sessions.
    from collections import defaultdict
    sessions = sorted({o["session_globex_day"] for o in all_occ})
    sidx = {s: i for i, s in enumerate(sessions)}
    store = {lvl: defaultdict(lambda: {"n": 0, "wins": 0, "sumR": 0.0})
             for lvl in ("exact", "reduced", "broad", "global")}
    # reduced family per-session aggregates for horizon diagnostics
    red_sess = defaultdict(list)          # key -> [(sess_idx, n, wins, sumR), ...]
    by_session = defaultdict(list)
    for o in all_occ:
        by_session[o["session_globex_day"]].append(o)

    for s in sessions:
        ci = sidx[s]
        for o in by_session[s]:
            ev = EV.evaluate(store["exact"][o["exact_graph"]],
                             store["reduced"][o["reduced_graph"]],
                             store["broad"][o["broad_family"]],
                             store["global"]["ALL"])
            o["prediction"] = ev
            o["horizon_summary"] = EV.horizon_summary(red_sess.get(o["reduced_graph"], []))
        # fold this session's completed outcomes into the running store
        sess_delta = defaultdict(lambda: {"n": 0, "wins": 0, "sumR": 0.0})
        for o in by_session[s]:
            if o["outcome"] not in ("WIN", "LOSS"):
                continue
            fav = 1 if o["outcome"] == "WIN" else 0
            R = o["realized_R"]
            for level, key in (("exact", o["exact_graph"]), ("reduced", o["reduced_graph"]),
                               ("broad", o["broad_family"]), ("global", "ALL")):
                store[level][key]["n"] += 1
                store[level][key]["wins"] += fav
                store[level][key]["sumR"] += R
            d = sess_delta[o["reduced_graph"]]
            d["n"] += 1; d["wins"] += fav; d["sumR"] += R
        for key, d in sess_delta.items():
            red_sess[key].append((ci, d["n"], d["wins"], d["sumR"]))

    # persist ledgers
    def flat(o):
        r = {k: v for k, v in o.items() if k not in ("features", "prediction", "horizon_summary")}
        for k, v in o["features"].items():
            r[f"feat_{k}"] = v
        for k, v in o["prediction"].items():
            r[k] = v
        return r

    df_all = pd.DataFrame([flat(o) for o in all_occ])
    df_all.to_csv(os.path.join(OUT, "setup_occurrences_all.csv"), index=False)
    july = [o for o in all_occ if in_july(o["trigger_ts_et"])]
    df_j = pd.DataFrame([flat(o) for o in july])
    df_j.to_csv(os.path.join(OUT, "setup_occurrences_july.csv"), index=False)
    # store full JSON (with nested prediction + horizons) for July
    with open(os.path.join(OUT, "july_occurrences_full.json"), "w") as f:
        json.dump(july, f, indent=1, default=str)

    # ---- Layer 1 / 2 / 3 comparison (descriptive) ----
    layers = layer_comparison(all_occ, july)
    with open(os.path.join(OUT, "layer_comparison.json"), "w") as f:
        json.dump(layers, f, indent=2, default=str)

    summary = {
        "setup_def_version": PR.SETUP_DEF_VERSION,
        "july_replay_boundary": [PR.JULY_START_ET, PR.JULY_END_ET],
        "total_admissible_setups": len(all_occ),
        "rejected_candidates": int(total_rej),
        "july_admissible_setups": len(july),
        "primitive_counts": prim_counts,
        "exact_graph_templates": int(df_all["exact_graph"].nunique()) if len(df_all) else 0,
        "reduced_graph_templates": sorted(df_all["reduced_graph"].unique().tolist()) if len(df_all) else [],
        "july_prediction_class_distribution": df_j["final_predicted_class"].value_counts().to_dict() if len(df_j) else {},
        "july_outcome_distribution": df_j["outcome"].value_counts().to_dict() if len(df_j) else {},
        "july_ess_distribution": df_j["effective_sample_size"].describe().to_dict() if len(df_j) else {},
    }
    with open(os.path.join(OUT, "replay_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))
    return all_occ, july, summary


def layer_comparison(all_occ, july):
    """Descriptive only. Layer1: isolated concept interactions. Layer2: coherent
    graphs (structural quality). Layer3: graphs scored by prior evidence."""
    def rate(items):
        comp = [o for o in items if o["outcome"] in ("WIN", "LOSS")]
        wins = sum(1 for o in comp if o["outcome"] == "WIN")
        return {"n": len(items), "completed": len(comp), "wins": wins,
                "losses": len(comp) - wins,
                "fav_rate": round(wins / len(comp), 3) if comp else None,
                "mean_R": round(float(np.mean([o["realized_R"] for o in comp])), 3) if comp else None}
    L1 = {fam: rate([o for o in july if o["origin_family"] == fam])
          for fam in PR.ORIGIN_FAMILIES}
    L2 = {"all_coherent_graphs": rate(july),
          "by_reduced": {rg: rate([o for o in july if o["reduced_graph"] == rg])
                         for rg in sorted({o["reduced_graph"] for o in july})}}
    L3 = {cls: rate([o for o in july if o["prediction"]["final_predicted_class"] == cls])
          for cls in ("FAVORABLE", "NEUTRAL", "ADVERSE", "INSUFFICIENT_EVIDENCE")}
    return {"layer1_isolated_concepts": L1, "layer2_coherent_graphs": L2,
            "layer3_rolling_recognizer": L3,
            "note": "Descriptive only; one July week cannot establish edge or that Layer 3 dominates."}


if __name__ == "__main__":
    main(*sys.argv[1:7])

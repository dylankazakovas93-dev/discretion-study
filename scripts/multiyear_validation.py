"""FROZEN MULTI-YEAR VALIDATION ENGINE (protocol v1.0.0).

Locked validation actually covers 2018-2019 only (2020, 2021-2022, 2023-2024
raw data files are absent from this environment -- disclosed, not fabricated).
2026 is development/mechanical-audit data and is excluded from this run.

Architecture:
  - Processed per contract-roll SEGMENT (natural causal boundary already
    enforced by the audited primitives: structures never cross a roll).
    observe() is called once per segment with locally-renumbered bars.
  - Every executable variant's outcome is computed once, immediately, within
    its own segment (self-contained: MAX_HOLD_BARS=480 is far shorter than a
    quarter, so no cross-segment bar dependency exists).
  - Session-level walk-forward playbooks (PREV_1/3/10/20) are built using a
    SESSION-DATE causal check (an outcome may authorize a playbook only when
    its exit occurred in a strictly earlier session than the playbook's own
    session) -- portable across segments, unlike raw local bar-seq.
  - Portfolio occupancy simulation uses real wall-clock timestamps (entry_ts /
    exit_ts), which are comparable across segments, unlike local seq numbers.
  - Checkpointed after every completed year.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import os
import pickle
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import date

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import load_front_month, DATA_FILES, ET
from discretion.data.cme_session import session_date
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome, MAX_HOLD_BARS
from discretion.setup_observer.playbook import EXACT_FIELDS, REDUCED_FIELDS, match_modes, pattern_key

OUT = os.path.join("artifacts", "multiyear_validation")
CKPT_DIR = os.path.join(OUT, "checkpoints")
TARGET_WINDOW = 600
LOOKBACKS = [("PREV_1_SESSION", 1), ("PREV_3_SESSIONS", 3),
             ("PREV_10_SESSIONS", 10), ("PREV_20_SESSIONS", 20)]
COSTS = {"gross": 0.0, "cost_050": 0.50, "cost_100": 1.00}

ARMS = ["L1_EXACT", "L1_EXACT_PLUS_REDUCED", "L3_EXACT", "L3_EXACT_PLUS_REDUCED",
        "L10_EXACT", "L10_EXACT_PLUS_REDUCED", "L20_EXACT", "L20_EXACT_PLUS_REDUCED",
        "ANY_EXACT", "ANY_EXACT_PLUS_REDUCED", "MULTI_LOOKBACK_EXACT", "MULTI_LOOKBACK_ANY",
        "ALL_LOOKBACKS"]


# ---------------------------------------------------------------------------
# minimal picklable variant/outcome records (avoid retaining full bar refs)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class VRec:
    gvid: str
    variant_id: str
    episode_id: str
    segment_tag: str
    entry_variant: str
    reaction_state: str
    direction: int
    lane: str
    session: str
    context_tf: int
    trigger_tf: int
    is_multi_timeframe: bool
    entry_ts: object
    session_date: object
    executable: bool
    fingerprint: dict
    natural_rr: object
    target_family: object
    target_tf: object


@dataclasses.dataclass
class ORec:
    gvid: str
    exit_type: str
    exit_ts: object
    exit_session_date: object
    points: float
    r_multiple: float
    success: bool
    mfe_points: float
    mae_points: float


def wcsv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_lookback_playbook(lookback_name, lookback_dates, cur_date, vars_by_session, outcomes):
    """Authorized items = EXACT fingerprints of successful executable variants
    in ``lookback_dates`` whose outcome's exit occurred STRICTLY before
    ``cur_date`` (session-date causal check, portable across segments)."""
    pool = [v for d in lookback_dates for v in vars_by_session.get(d, [])]
    exec_out = []
    for v in pool:
        if not v.executable:
            continue
        o = outcomes.get(v.gvid)
        if o is not None and o.exit_session_date < cur_date:
            exec_out.append((v, o))
    by_key_all = defaultdict(list)
    for v in pool:
        by_key_all[tuple(v.fingerprint.get(f) for f in EXACT_FIELDS)].append(v)
    by_key_exec = defaultdict(list)
    for v, o in exec_out:
        by_key_exec[tuple(v.fingerprint.get(f) for f in EXACT_FIELDS)].append((v, o))
    items = []
    n = 0
    for key, exlist in sorted(by_key_exec.items(), key=lambda kv: str(kv[0])):
        succ = [(v, o) for v, o in exlist if o.success]
        if not succ:
            continue
        n += 1
        fp = succ[0][0].fingerprint
        reduced_key = tuple(fp.get(k) for k in REDUCED_FIELDS)
        items.append({
            "item_id": f"{lookback_name}-{n:05d}", "fingerprint": fp, "reduced_key": reduced_key,
            "pattern_k": pattern_key(fp),
            "success_count": len(succ), "total_exec": len(exlist),
            "source_gvids": [v.gvid for v, _ in succ],
        })
    return items


def match_variant(v, playbook):
    class _Pb:
        def __init__(self, d):
            self.item_id = d["item_id"]; self.fingerprint = d["fingerprint"]
            self.reduced_key = d["reduced_key"]
    pbs = [_Pb(d) for d in playbook]
    m = match_modes(v, pbs)
    return m


def classify_arms(per_lookback):
    """per_lookback: {lname: {'EXACT':[...], 'REDUCED_FAMILY':[...]}} -> set of
    frozen arm names this variant qualifies for."""
    hit = set()
    exact_cnt = 0
    any_cnt = 0
    for lname, L in LOOKBACKS:
        m = per_lookback[lname]
        has_exact = bool(m["EXACT"])
        has_any = bool(m["EXACT"] or m["REDUCED_FAMILY"])
        if has_exact:
            exact_cnt += 1
        if has_any:
            any_cnt += 1
        tag = {1: "L1", 3: "L3", 10: "L10", 20: "L20"}[L]
        if has_exact:
            hit.add(f"{tag}_EXACT")
            hit.add(f"{tag}_EXACT_PLUS_REDUCED")
        elif has_any:
            hit.add(f"{tag}_EXACT_PLUS_REDUCED")
    if exact_cnt >= 1:
        hit.add("ANY_EXACT")
    if any_cnt >= 1:
        hit.add("ANY_EXACT_PLUS_REDUCED")
    if exact_cnt >= 2:
        hit.add("MULTI_LOOKBACK_EXACT")
    if any_cnt >= 2:
        hit.add("MULTI_LOOKBACK_ANY")
    if any_cnt == 4:
        hit.add("ALL_LOOKBACKS")
    return hit


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CKPT_DIR, exist_ok=True)

    manifest_rows = []
    roll_rows = []
    all_variants = {}     # gvid -> VRec (executable only, kept for full run)
    all_outcomes = {}     # gvid -> ORec
    vars_by_session = defaultdict(list)
    segment_meta = []

    t_start = time.time()

    path = os.path.join("data", "raw", DATA_FILES["2018-2019"])
    bars_all = load_front_month(path)
    seg_ids = sorted(set(b.segment_id for b in bars_all))
    print(f"Loaded {len(bars_all)} front-month bars, {len(seg_ids)} roll segments", flush=True)

    for seg_id in seg_ids:
        ckpt_path = os.path.join(CKPT_DIR, f"segment_{seg_id:03d}.pkl")
        seg_bars_full = [b for b in bars_all if b.segment_id == seg_id]
        contract = seg_bars_full[0].contract
        first_ts, last_ts = seg_bars_full[0].ts_et, seg_bars_full[-1].ts_et

        if os.path.exists(ckpt_path):
            with open(ckpt_path, "rb") as fh:
                ck = pickle.load(fh)
            print(f"segment {seg_id} ({contract}): loaded checkpoint, "
                  f"{ck['n_variants']} executable variants", flush=True)
        else:
            local_bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(seg_bars_full)]
            t0 = time.time()
            eps, variants, diag = observe(local_bars, target_window=TARGET_WINDOW)
            dt_observe = time.time() - t0

            seg_tag = f"seg{seg_id:03d}_{contract}"
            exec_recs, out_recs = [], []
            for v in variants:
                if not v.executable:
                    continue
                gvid = f"{seg_tag}::{v.variant_id}"
                prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
                vr = VRec(gvid=gvid, variant_id=v.variant_id, episode_id=v.episode_id,
                          segment_tag=seg_tag, entry_variant=v.entry_variant,
                          reaction_state=v.reaction_state, direction=v.direction, lane=v.lane,
                          session=v.session, context_tf=v.context_tf, trigger_tf=v.trigger_tf,
                          is_multi_timeframe=v.is_multi_timeframe, entry_ts=v.entry_ts,
                          session_date=session_date(v.entry_ts), executable=True,
                          fingerprint=dict(v.fingerprint), natural_rr=v.natural_rr,
                          target_family=(prim.family if prim else None),
                          target_tf=(prim.timeframe if prim else None))
                exec_recs.append(vr)
                o = process_outcome(v, local_bars)
                if o is not None:
                    exit_ts = local_bars[o.exit_seq].ts_et
                    out_recs.append(ORec(gvid=gvid, exit_type=o.exit_type, exit_ts=exit_ts,
                                         exit_session_date=session_date(exit_ts),
                                         points=o.points, r_multiple=o.r_multiple, success=o.success,
                                         mfe_points=o.mfe_points, mae_points=o.mae_points))
            dt_total = time.time() - t0
            ck = {"n_variants": len(exec_recs), "vrecs": exec_recs, "orecs": out_recs,
                  "n_bars": len(local_bars), "n_total_variants": len(variants),
                  "n_episodes": len(eps), "dt_observe": dt_observe, "dt_total": dt_total,
                  "contract": contract, "first_ts": str(first_ts), "last_ts": str(last_ts)}
            with open(ckpt_path, "wb") as fh:
                pickle.dump(ck, fh)
            print(f"segment {seg_id} ({contract}): {len(local_bars)} bars, "
                  f"{len(variants)} variants, {len(exec_recs)} executable, "
                  f"observe={dt_observe:.1f}s total={dt_total:.1f}s", flush=True)

        for vr in ck["vrecs"]:
            all_variants[vr.gvid] = vr
            vars_by_session[vr.session_date].append(vr)
        for orec in ck["orecs"]:
            all_outcomes[orec.gvid] = orec

        segment_meta.append({"segment_id": seg_id, "contract": ck["contract"],
                             "first_ts": ck["first_ts"], "last_ts": ck["last_ts"],
                             "n_bars": ck["n_bars"], "n_total_variants": ck["n_total_variants"],
                             "n_executable": ck["n_variants"], "n_episodes": ck.get("n_episodes")})
        roll_rows.append({"segment_id": seg_id, "contract": ck["contract"],
                          "first_ts_et": ck["first_ts"], "last_ts_et": ck["last_ts"],
                          "n_bars": ck["n_bars"]})

    with open(os.path.join(OUT, "yearly_progress.json"), "w") as fh:
        json.dump({"segments": segment_meta, "elapsed_sec": time.time() - t_start}, fh, indent=2, default=str)
    wcsv(os.path.join(OUT, "roll_manifest.csv"), roll_rows,
         ["segment_id", "contract", "first_ts_et", "last_ts_et", "n_bars"])

    session_dates = sorted(vars_by_session.keys())
    print(f"Total sessions: {len(session_dates)}; total executable variants: {len(all_variants)}", flush=True)

    # ---- data manifest (per year) ----
    by_year = defaultdict(lambda: {"sessions": set(), "bars": 0})
    for seg in segment_meta:
        y = pd.Timestamp(seg["first_ts"]).year
        by_year[y]["bars"] += seg["n_bars"]
    for d in session_dates:
        by_year[d.year]["sessions"].add(d)
    manifest_rows = [{"year": y, "n_sessions": len(v["sessions"]), "n_bars": v["bars"],
                      "first_session": str(min(v["sessions"])) if v["sessions"] else None,
                      "last_session": str(max(v["sessions"])) if v["sessions"] else None}
                     for y, v in sorted(by_year.items())]
    manifest_rows.append({"year": 2020, "n_sessions": 0, "n_bars": 0, "first_session": None,
                          "last_session": None, "note": "DATA_UNAVAILABLE"})
    manifest_rows.append({"year": "2021-2022", "n_sessions": 0, "n_bars": 0, "first_session": None,
                          "last_session": None, "note": "DATA_UNAVAILABLE"})
    manifest_rows.append({"year": "2023-2024", "n_sessions": 0, "n_bars": 0, "first_session": None,
                          "last_session": None, "note": "DATA_UNAVAILABLE"})
    wcsv(os.path.join(OUT, "data_manifest.csv"), manifest_rows,
         ["year", "n_sessions", "n_bars", "first_session", "last_session", "note"])

    # ============================================================
    # SESSION-BY-SESSION WALK-FORWARD: build playbooks, match every
    # executable variant in that session against ITS OWN session-frozen
    # playbooks (hypothesis-level; all entry variants, overlapping)
    # ============================================================
    hyp_rows = []
    causal_violation_self = 0
    causal_violation_future = 0
    stale_target_uses = 0   # tracked via existing atr_floor/target-eligibility gates already enforced upstream

    playbook_item_counts = defaultdict(dict)  # session -> lookback -> n_items

    for si, d in enumerate(session_dates):
        before = session_dates[:si]
        playbooks = {}
        for lname, L in LOOKBACKS:
            lastL = before[-L:] if before else []
            enough = len(before) >= L
            items = build_lookback_playbook(lname, lastL, d, vars_by_session, all_outcomes) if enough else []
            playbooks[lname] = items
            playbook_item_counts[str(d)][lname] = len(items)
            # causal check: no item's sources include a variant from session d or later
            for it in items:
                for gvid in it["source_gvids"]:
                    src_sd = all_variants[gvid].session_date
                    if src_sd >= d:
                        causal_violation_self += 1

        for v in vars_by_session[d]:
            per = {}
            for lname, _L in LOOKBACKS:
                m = match_variant(v, playbooks[lname])
                per[lname] = m
            arms = classify_arms(per)
            o = all_outcomes.get(v.gvid)
            hyp_rows.append({
                "gvid": v.gvid, "variant_id": v.variant_id, "episode_id": v.episode_id,
                "segment": v.segment_tag, "entry_variant": v.entry_variant,
                "reaction_state": v.reaction_state, "direction": v.direction, "lane": v.lane,
                "session": v.session, "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
                "is_multi_timeframe": v.is_multi_timeframe, "entry_ts": v.entry_ts,
                "session_date": str(d), "natural_rr": v.natural_rr,
                "target_family": v.target_family, "target_tf": v.target_tf,
                "arms": "|".join(sorted(arms)),
                "exit_type": (o.exit_type if o else None), "exit_ts": (o.exit_ts if o else None),
                "points": (o.points if o else None),
                "r_multiple": (o.r_multiple if o else None), "success": (o.success if o else None),
                "mfe_points": (o.mfe_points if o else None), "mae_points": (o.mae_points if o else None),
                "match_prev_1": ("EXACT" if per["PREV_1_SESSION"]["EXACT"] else
                                "REDUCED_FAMILY" if per["PREV_1_SESSION"]["REDUCED_FAMILY"] else ""),
                "match_prev_3": ("EXACT" if per["PREV_3_SESSIONS"]["EXACT"] else
                                "REDUCED_FAMILY" if per["PREV_3_SESSIONS"]["REDUCED_FAMILY"] else ""),
                "match_prev_10": ("EXACT" if per["PREV_10_SESSIONS"]["EXACT"] else
                                 "REDUCED_FAMILY" if per["PREV_10_SESSIONS"]["REDUCED_FAMILY"] else ""),
                "match_prev_20": ("EXACT" if per["PREV_20_SESSIONS"]["EXACT"] else
                                 "REDUCED_FAMILY" if per["PREV_20_SESSIONS"]["REDUCED_FAMILY"] else ""),
            })

    wcsv(os.path.join(OUT, "all_hypothesis_variants.csv"), hyp_rows, list(hyp_rows[0].keys()) if hyp_rows else ["gvid"])

    ci = {
        "n_sessions": len(session_dates), "n_executable_variants": len(all_variants),
        "n_hypothesis_rows": len(hyp_rows),
        "causal_violation_self_or_future_playbook_source": causal_violation_self,
        "note": "each session's own variants are excluded from its own lookback pool by "
                "construction (before = session_dates[:si]); this counter independently "
                "re-verifies every playbook item's source sessions are strictly earlier.",
    }
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(ci, fh, indent=2, default=str)

    print(json.dumps({"n_sessions": len(session_dates), "n_executable": len(all_variants),
                      "n_hypothesis_rows": len(hyp_rows), "causal_violations": causal_violation_self,
                      "elapsed_sec": round(time.time() - t_start, 1)}, indent=2))


if __name__ == "__main__":
    main()

"""FROZEN MULTI-YEAR VALIDATION ENGINE v2.0.0.

Changes vs v1 (see docs/FROZEN_MULTIYEAR_VALIDATION_PROTOCOL_V2.md):
  1. Playbook admission requires a genuinely winning record within the lookback
     (ANY_WIN control / NET_POSITIVE / PF2 -- all three pre-registered).
  2. New coarse SETUP_FAMILY match key alongside the v1 EXACT key.
  3. Costs informational only; gross is the primary basis.
Everything else -- primitives, ATR floors, stops, targets, RR floor, outcome
resolution, walk-forward causality -- is byte-identical to the frozen engine.

Validation window 2018-2025; 2026 excluded from the primary claim.
Checkpointed per contract segment so restarts are cheap.
"""
from __future__ import annotations

import csv
import dataclasses
import json
import os
import pickle
import sys
import time
from collections import defaultdict, Counter

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import load_front_month, DATA_FILES, ET
from discretion.data.cme_session import session_date
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import EXACT_FIELDS

OUT = os.path.join("artifacts", "multiyear_validation_v2")
CKPT_DIR = os.path.join(OUT, "checkpoints")
TARGET_WINDOW = 600
LOOKBACKS = [("PREV_1_SESSION", 1), ("PREV_3_SESSIONS", 3),
             ("PREV_10_SESSIONS", 10), ("PREV_20_SESSIONS", 20)]
MATCH_KEYS = ["EXACT", "FAMILY"]
ADMISSION = ["ANY_WIN", "NET_POSITIVE", "PF2"]
PF2_THRESHOLD = 2.0
VALIDATION_YEARS = (2018, 2025)      # inclusive; 2026 excluded from primary claim
DATA_ORDER = ["2018-2019", "2020", "2021-2022", "2023-2024", "2025-2026"]

HTF_BUCKET = {1: "LTF", 3: "LTF", 5: "LTF", 15: "HTF", 30: "HTF", 60: "HTF"}


def family_key(fp):
    """Frozen v2 SETUP_FAMILY key -- deliberately coarse so a NY-AM HTF RB tap
    on displacement is authorized by a prior NY-AM HTF RB tap on displacement,
    regardless of which higher timeframe or which day it was."""
    return (fp.get("lane"), fp.get("direction"), fp.get("context_family"),
            HTF_BUCKET.get(fp.get("context_tf"), "LTF"), fp.get("session"),
            fp.get("entry_variant"), fp.get("reaction_state"))


def exact_key(fp):
    return tuple(fp.get(f) for f in EXACT_FIELDS)


@dataclasses.dataclass
class VRec:
    """Memory-lean record: keys precomputed as tuples, no fingerprint dict."""
    gvid: str
    episode_id: str
    entry_variant: str
    reaction_state: str
    direction: int
    lane: str
    session: str
    context_tf: int
    trigger_tf: int
    entry_ts: object
    session_date: object
    natural_rr: object
    target_family: object
    target_tf: object
    ekey: tuple
    fkey: tuple


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


def load_all_bars():
    """Front-month bars across every data file, concatenated chronologically and
    re-segmented globally by contract change (so a contract split across two
    files is one segment, not two)."""
    allb = []
    for key in DATA_ORDER:
        p = os.path.join("data", "raw", DATA_FILES[key])
        if not os.path.exists(p):
            print(f"  MISSING {key} -> {p}", flush=True)
            continue
        b = load_front_month(p)
        print(f"  {key}: {len(b):,} front-month bars "
              f"{b[0].ts_et.date()} -> {b[-1].ts_et.date()}", flush=True)
        allb.extend(b)
    allb.sort(key=lambda x: x.ts_utc)
    # drop duplicate timestamps at file seams, keep first
    dedup, seen = [], set()
    for b in allb:
        if b.ts_utc in seen:
            continue
        seen.add(b.ts_utc)
        dedup.append(b)
    # re-segment by contract run
    segments, cur, prev = [], [], None
    for b in dedup:
        if prev is not None and b.contract != prev:
            segments.append(cur); cur = []
        cur.append(b); prev = b.contract
    if cur:
        segments.append(cur)
    return dedup, segments


def fingerprint_stats(pool, outcomes):
    """Per-key wins/losses/PF over resolved executable occurrences."""
    stats = {}
    for v, o in pool:
        for kind, k in (("EXACT", v.ekey), ("FAMILY", v.fkey)):
            s = stats.setdefault((kind, k), {"w": 0, "l": 0, "pos": 0.0, "neg": 0.0, "gvids": []})
            if o.success:
                s["w"] += 1
            else:
                s["l"] += 1
            if o.r_multiple > 0:
                s["pos"] += o.r_multiple
            else:
                s["neg"] += -o.r_multiple
            s["gvids"].append(v.gvid)
    return stats


def admitted_keys(stats, kind, rule):
    """Frozen admission rules -- all three pre-registered, none chosen post hoc."""
    out = {}
    for (k_kind, k), s in stats.items():
        if k_kind != kind:
            continue
        w, l = s["w"], s["l"]
        if w < 1:
            continue
        if rule == "ANY_WIN":
            ok = True
        elif rule == "NET_POSITIVE":
            ok = w > l
        elif rule == "PF2":
            pf = (s["pos"] / s["neg"]) if s["neg"] > 0 else float("inf")
            ok = pf >= PF2_THRESHOLD
        else:
            raise ValueError(rule)
        if ok:
            out[k] = {"wins": w, "losses": l,
                      "pf": (round(s["pos"] / s["neg"], 4) if s["neg"] > 0 else None)}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(CKPT_DIR, exist_ok=True)
    t_start = time.time()

    # Parsed-bar cache: re-parsing 2.96M bars from the .zst CSVs costs minutes on
    # every relaunch, which under frequent container restarts starved the engine
    # of time to finish a segment. Cache each segment's bars once; later launches
    # load only the one segment they need. Manifest is written last so a partial
    # cache is never treated as complete.
    SEGCACHE = os.path.join(OUT, "segcache")
    manifest_path = os.path.join(SEGCACHE, "manifest.json")
    if os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path))
        n_segments = manifest["n_segments"]
        seg_contracts = manifest["contracts"]
        print(f"segment cache HIT: {n_segments} segments, skipping CSV parse", flush=True)

        def get_seg(i):
            return pickle.load(open(os.path.join(SEGCACHE, f"seg{i:03d}.pkl"), "rb"))
    else:
        print("Loading all front-month data (first run; will cache)...", flush=True)
        all_bars, segments = load_all_bars()
        print(f"TOTAL {len(all_bars):,} bars, {len(segments)} contract segments", flush=True)
        os.makedirs(SEGCACHE, exist_ok=True)
        for i, s in enumerate(segments):
            pickle.dump(s, open(os.path.join(SEGCACHE, f"seg{i:03d}.pkl"), "wb"))
        n_segments = len(segments)
        seg_contracts = [s[0].contract for s in segments]
        json.dump({"n_segments": n_segments, "contracts": seg_contracts},
                  open(manifest_path, "w"))
        del all_bars, segments
        print(f"segment cache WRITTEN ({n_segments} segments)", flush=True)

        def get_seg(i):
            return pickle.load(open(os.path.join(SEGCACHE, f"seg{i:03d}.pkl"), "rb"))

    vars_by_session = defaultdict(list)
    outcome_by_gvid = {}
    seg_meta = []

    for si in range(n_segments):
        contract = seg_contracts[si]
        tag = f"seg{si:03d}_{contract}"
        ck_path = os.path.join(CKPT_DIR, f"{tag}.pkl")
        if os.path.exists(ck_path):
            ck = pickle.load(open(ck_path, "rb"))
            print(f"[{si+1}/{n_segments}] {tag}: checkpoint, {ck['n']} executable", flush=True)
        else:
            seg_bars = get_seg(si)
            local = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(seg_bars)]
            t0 = time.time()
            _eps, variants, _diag = observe(local, target_window=TARGET_WINDOW)
            vrecs, orecs = [], []
            for v in variants:
                if not v.executable:
                    continue
                gvid = f"{tag}::{v.variant_id}"
                prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
                fp = v.fingerprint
                vrecs.append(VRec(
                    gvid=gvid, episode_id=v.episode_id, entry_variant=v.entry_variant,
                    reaction_state=v.reaction_state, direction=v.direction, lane=v.lane,
                    session=v.session, context_tf=v.context_tf, trigger_tf=v.trigger_tf,
                    entry_ts=v.entry_ts, session_date=session_date(v.entry_ts),
                    natural_rr=v.natural_rr,
                    target_family=(prim.family if prim else None),
                    target_tf=(prim.timeframe if prim else None),
                    ekey=exact_key(fp), fkey=family_key(fp)))
                o = process_outcome(v, local)
                if o is not None:
                    xts = local[o.exit_seq].ts_et
                    orecs.append(ORec(gvid=gvid, exit_type=o.exit_type, exit_ts=xts,
                                      exit_session_date=session_date(xts), points=o.points,
                                      r_multiple=o.r_multiple, success=o.success,
                                      mfe_points=o.mfe_points, mae_points=o.mae_points))
            ck = {"n": len(vrecs), "vrecs": vrecs, "orecs": orecs, "contract": contract,
                  "n_bars": len(local), "n_variants": len(variants),
                  "first_ts": str(seg_bars[0].ts_et), "last_ts": str(seg_bars[-1].ts_et),
                  "dt": time.time() - t0}
            pickle.dump(ck, open(ck_path, "wb"))
            print(f"[{si+1}/{n_segments}] {tag}: {len(local):,} bars, "
                  f"{len(variants):,} variants, {len(vrecs)} executable, {ck['dt']:.0f}s "
                  f"| elapsed {(time.time()-t_start)/60:.0f}m", flush=True)

        for v in ck["vrecs"]:
            vars_by_session[v.session_date].append(v)
        for o in ck["orecs"]:
            outcome_by_gvid[o.gvid] = o
        seg_meta.append({"segment": si, "contract": ck["contract"], "n_bars": ck["n_bars"],
                         "n_variants": ck["n_variants"], "n_executable": ck["n"],
                         "first_ts": ck["first_ts"], "last_ts": ck["last_ts"]})

    wcsv(os.path.join(OUT, "roll_manifest.csv"), seg_meta,
         ["segment", "contract", "n_bars", "n_variants", "n_executable", "first_ts", "last_ts"])

    session_dates = sorted(vars_by_session.keys())
    val_sessions = [d for d in session_dates if VALIDATION_YEARS[0] <= d.year <= VALIDATION_YEARS[1]]
    print(f"\nSessions total {len(session_dates)}, validation (2018-2025) {len(val_sessions)}", flush=True)
    print(f"Executable variants: {len(outcome_by_gvid):,}", flush=True)

    by_year = defaultdict(lambda: {"sessions": 0, "variants": 0})
    for d in session_dates:
        by_year[d.year]["sessions"] += 1
        by_year[d.year]["variants"] += len(vars_by_session[d])
    wcsv(os.path.join(OUT, "data_manifest.csv"),
         [{"year": y, "sessions": v["sessions"], "executable_variants": v["variants"],
           "in_primary_claim": VALIDATION_YEARS[0] <= y <= VALIDATION_YEARS[1]}
          for y, v in sorted(by_year.items())],
         ["year", "sessions", "executable_variants", "in_primary_claim"])

    # ================= walk-forward =================
    hyp_rows = []
    causal_viol = 0
    pb_sizes = defaultdict(list)

    for si, d in enumerate(session_dates):
        if si % 100 == 0:
            print(f"  walk-forward {si}/{len(session_dates)} ({d}) "
                  f"| {(time.time()-t_start)/60:.0f}m", flush=True)
        before = session_dates[:si]

        # per lookback: resolved pool -> stats -> admitted key sets per rule
        admits = {}
        for lname, L in LOOKBACKS:
            lastL = before[-L:] if before else []
            if len(before) < L:
                for kind in MATCH_KEYS:
                    for rule in ADMISSION:
                        admits[(lname, kind, rule)] = {}
                continue
            pool = []
            for dd in lastL:
                for v in vars_by_session.get(dd, []):
                    o = outcome_by_gvid.get(v.gvid)
                    if o is not None and o.exit_session_date < d:
                        pool.append((v, o))
                        if v.session_date >= d:
                            causal_viol += 1
            stats = fingerprint_stats(pool, outcome_by_gvid)
            for kind in MATCH_KEYS:
                for rule in ADMISSION:
                    a = admitted_keys(stats, kind, rule)
                    admits[(lname, kind, rule)] = a
                    pb_sizes[(lname, kind, rule)].append(len(a))

        for v in vars_by_session[d]:
            o = outcome_by_gvid.get(v.gvid)
            row = {"gvid": v.gvid, "episode_id": v.episode_id, "entry_variant": v.entry_variant,
                   "reaction_state": v.reaction_state, "direction": v.direction, "lane": v.lane,
                   "session": v.session, "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
                   "entry_ts": v.entry_ts, "exit_ts": (o.exit_ts if o else None),
                   "session_date": str(d), "year": d.year, "natural_rr": v.natural_rr,
                   "target_family": v.target_family, "target_tf": v.target_tf,
                   "exit_type": (o.exit_type if o else None), "points": (o.points if o else None),
                   "r_multiple": (o.r_multiple if o else None), "success": (o.success if o else None),
                   "mfe_points": (o.mfe_points if o else None),
                   "mae_points": (o.mae_points if o else None)}
            for lname, _L in LOOKBACKS:
                for kind in MATCH_KEYS:
                    k = v.ekey if kind == "EXACT" else v.fkey
                    for rule in ADMISSION:
                        hit = admits[(lname, kind, rule)].get(k)
                        col = f"{lname}|{kind}|{rule}"
                        row[col] = (hit["wins"] if hit else 0)
            hyp_rows.append(row)

    fields = list(hyp_rows[0].keys()) if hyp_rows else ["gvid"]
    wcsv(os.path.join(OUT, "all_hypothesis_variants.csv"), hyp_rows, fields)

    pb_summary = [{"lookback": k[0], "match_key": k[1], "admission": k[2],
                   "mean_items": round(sum(v) / len(v), 1) if v else 0,
                   "max_items": max(v) if v else 0}
                  for k, v in sorted(pb_sizes.items())]
    wcsv(os.path.join(OUT, "playbook_sizes.csv"), pb_summary,
         ["lookback", "match_key", "admission", "mean_items", "max_items"])

    ci = {"n_sessions": len(session_dates), "n_validation_sessions": len(val_sessions),
          "n_executable_variants": len(outcome_by_gvid),
          "causal_violation_self_or_future_source": causal_viol,
          "validation_years": list(VALIDATION_YEARS),
          "note": "playbook pool for session d uses only sessions strictly before d, and only "
                  "outcomes whose exit session resolved strictly before d."}
    json.dump(ci, open(os.path.join(OUT, "causal_invariants.json"), "w"), indent=2, default=str)

    print(json.dumps({"sessions": len(session_dates), "executable": len(outcome_by_gvid),
                      "hyp_rows": len(hyp_rows), "causal_violations": causal_viol,
                      "elapsed_min": round((time.time() - t_start) / 60, 1)}, indent=2))


if __name__ == "__main__":
    main()

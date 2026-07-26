"""Two-week ICT setup observer + recent-validity playbook demo (NQU6).

Observation week Jul 5-10 2026: freeze coherent physical episodes and their
frozen entry VARIANTS/fingerprints FIRST, then attach observation-only outcomes,
then build a recent-validity playbook from the successful variant fingerprints.
Application week Jul 12-17 2026: replay, match every variant against the frozen
playbook (diagnostically), and surface only EXECUTABLE + AUTHORIZED variants as
actionable cards. Non-actionable matches go to a separate rejected ledger.
Application-week OUTCOMES are never computed or revealed here.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe
from discretion.setup_observer.common import MIN_EXECUTABLE_RR
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import build_playbook, match_modes, EXACT_FIELDS, pattern_key
from discretion.setup_observer.sessions import SESSION_BOUNDS
from discretion.causal_replay.engine import replay as atomic_replay

OUT = os.path.join("artifacts", "two_week_recent_validity_demo_2026_07_05_17")
DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])
OBS = (pd.Timestamp("2026-07-05 18:00:00", tz=ET), pd.Timestamp("2026-07-10 16:59:59", tz=ET))
APP = (pd.Timestamp("2026-07-12 18:00:00", tz=ET), pd.Timestamp("2026-07-17 23:59:59", tz=ET))


def load_bars(start_et, end_et):
    start_utc = start_et.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA_FILE, start=start_utc, end=None)
    df = df[df["symbol"] == "NQU6"].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    cov = {"symbol": "NQU6", "requested": [str(start_et), str(end_et)]}
    mask = (et >= start_et) & (et <= end_et)
    dfw = df[mask].reset_index(drop=True); etw = et[mask].reset_index(drop=True)
    cov["present"] = bool(len(dfw))
    if len(dfw):
        cov["first_et"] = str(etw.iloc[0]); cov["last_et"] = str(etw.iloc[-1]); cov["rows"] = int(len(dfw))
        gaps = []; prev = None
        for ts in etw:
            if prev is not None and (ts - prev) > pd.Timedelta(minutes=1):
                gaps.append({"after": str(prev), "before": str(ts), "gap": str(ts - prev)})
            prev = ts
        cov["internal_gaps"] = gaps
    bars = []
    for seq, row in enumerate(dfw.itertuples(index=False)):
        t = row.ts_utc
        bars.append(Bar(seq=seq, ts_utc=t, ts_et=t.tz_convert(ET), open=float(row.open),
                        high=float(row.high), low=float(row.low), close=float(row.close),
                        volume=int(row.volume), contract="NQU6", segment_id=0))
    return bars, cov


def wcsv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# row builders
# ---------------------------------------------------------------------------

def _ep_row(e):
    return {
        "episode_id": e.episode_id, "direction": e.direction, "lane": e.lane,
        "trigger_tf": e.trigger_tf, "context_tf": e.context_tf,
        "is_multi_timeframe": e.is_multi_timeframe, "context_family": e.context_family,
        "context_id": e.context_id, "component_ids": "|".join(e.component_ids),
        "confluence": e.confluence, "interaction_seq": e.interaction_seq,
        "context_zone_lo": e.context_zone[0], "context_zone_hi": e.context_zone[1],
        "dominant_state": e.dominant_state, "n_variants": e.n_variants,
        "n_executable": e.n_executable, "variant_ids": "|".join(e.variant_ids),
    }


EP_FIELDS = ["episode_id", "direction", "lane", "trigger_tf", "context_tf",
             "is_multi_timeframe", "context_family", "context_id", "component_ids",
             "confluence", "interaction_seq", "context_zone_lo", "context_zone_hi",
             "dominant_state", "n_variants", "n_executable", "variant_ids"]


def _var_row(v):
    prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
    return {
        "episode_id": v.episode_id, "variant_id": v.variant_id,
        "entry_variant": v.entry_variant, "reaction_state": v.reaction_state,
        "lane": v.lane, "direction": v.direction, "context_tf": v.context_tf,
        "interaction_tf": v.interaction_tf, "reaction_tf": v.reaction_tf,
        "confirmation_tf": v.confirmation_tf, "trigger_tf": v.trigger_tf,
        "is_multi_timeframe": v.is_multi_timeframe, "context_id": v.context_id,
        "context_family": v.context_family, "component_ids": "|".join(v.component_ids),
        "confluence": v.confluence, "context_zone_lo": v.context_zone[0],
        "context_zone_hi": v.context_zone[1], "context_formation_ts": v.context_formation_ts,
        "interaction_seq": v.interaction_seq, "interaction_ts": v.interaction_ts,
        "trigger_seq": v.trigger_seq, "trigger_ts": v.trigger_ts, "entry_seq": v.entry_seq,
        "entry_ts": v.entry_ts, "interaction_to_trigger_delay": v.interaction_to_trigger_delay,
        "penetration_depth": v.penetration_depth, "session": v.session, "et_hour": v.et_hour,
        "minutes_from_0930": v.minutes_from_0930, "minutes_from_1000": v.minutes_from_1000,
        "day_of_week": v.day_of_week, "session_date_et": v.session_date_et,
        "rb_wick_body": v.rb_wick_body, "rb_activated_at_trigger": v.rb_activated_at_trigger,
        "rb_activation_only_after_trigger": v.rb_activation_only_after_trigger,
        "entry_price": v.entry_price,
        "atr_1m_24": v.atr_1m_24, "atr_5m_24": v.atr_5m_24,
        "raw_stop_price": v.raw_stop_price, "raw_stop_distance": v.raw_stop_distance,
        "effective_stop_price": v.effective_stop_price,
        "effective_stop_distance": v.effective_stop_distance,
        "stop_widened_by_atr_floor": v.stop_widened_by_atr_floor,
        "stop_anchor_desc": v.stop_anchor_desc,
        "target_family": (prim.family if prim else None),
        "target_tf": (prim.timeframe if prim else None),
        "target_surface": (prim.surface if prim else None),
        "target_distance": v.target_distance,
        "target_distance_atr5_multiple": v.target_distance_atr5_multiple,
        "atr_floor_target_ok": v.atr_floor_target_ok,
        "natural_rr": v.natural_rr,
        "target_exclusion_counts": json.dumps(v.target_exclusion_counts, sort_keys=True),
        "executable": v.executable, "rejection_reason": v.rejection_reason,
    }


def _fp_row(v):
    r = {"variant_id": v.variant_id, "episode_id": v.episode_id}
    r.update(v.fingerprint)
    return r


def _target_rows(v, week):
    rows = []
    selected_by_sid = {}
    for pol, tc in v.targets.items():
        selected_by_sid.setdefault(tc.structure_id, []).append(pol)
    for c in v.considered_targets:
        rows.append({"week": week, "episode_id": v.episode_id, "variant_id": v.variant_id,
                     "structure_id": c["structure_id"], "family": c["family"], "tf": c["tf"],
                     "surface": c["surface"], "distance": c["distance"],
                     "natural_rr": c["natural_rr"], "availability_seq": c["avail"],
                     "exclusion_reason": c["exclusion_reason"],
                     "selected_as": "|".join(selected_by_sid.get(c["structure_id"], []))})
    return rows


TARGET_FIELDS = ["week", "episode_id", "variant_id", "structure_id", "family", "tf",
                 "surface", "distance", "natural_rr", "availability_seq",
                 "exclusion_reason", "selected_as"]


def _lineage_rows(e, variants_by_ep, week):
    rows = []
    for cid in e.component_ids:
        rows.append({"week": week, "episode_id": e.episode_id, "variant_id": "",
                     "role": "context/component", "structure_id": cid})
    for v in variants_by_ep.get(e.episode_id, []):
        if not v.executable:
            continue
        for pol, tc in v.targets.items():
            rows.append({"week": week, "episode_id": e.episode_id, "variant_id": v.variant_id,
                         "role": f"target:{pol}", "structure_id": tc.structure_id})
    return rows


LINEAGE_FIELDS = ["week", "episode_id", "variant_id", "role", "structure_id"]


def _causal_invariants(variants, label):
    v = {"interaction_after_trigger": 0, "entry_before_trigger": 0,
         "target_after_entry": 0, "delay_uses_future": 0}
    for x in variants:
        if x.interaction_seq > x.trigger_seq:
            v["interaction_after_trigger"] += 1
        if x.entry_seq < x.trigger_seq:
            v["entry_before_trigger"] += 1
        for tc in x.targets.values():
            if tc.availability_seq > x.entry_seq:
                v["target_after_entry"] += 1
        # a variant's frozen reaction trace must not extend past its own trigger
        if any(m["k"] > x.interaction_to_trigger_delay for m in x.reaction_measures_through_trigger):
            v["delay_uses_future"] += 1
    return {"label": label, "n_variants": len(variants), "violations": v,
            "total_violations": sum(v.values())}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUT, exist_ok=True)
    obs_bars, obs_cov = load_bars(*OBS)
    app_bars, app_cov = load_bars(*APP)
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump({"observation_week": obs_cov, "application_week": app_cov,
                   "session_bounds_et": [{"name": n, "start": s, "end": e} for n, s, e in SESSION_BOUNDS]},
                  fh, indent=2, default=str)

    var_fields = None

    # ==== OBSERVATION WEEK: freeze episodes + variants + fingerprints FIRST ====
    obs_eps, obs_vars, obs_diag = observe(obs_bars)
    obs_by_ep = {}
    for v in obs_vars:
        obs_by_ep.setdefault(v.episode_id, []).append(v)
    var_fields = list(_var_row(obs_vars[0]).keys()) if obs_vars else ["variant_id"]

    wcsv(os.path.join(OUT, "observation_week_episodes.csv"),
         [_ep_row(e) for e in obs_eps], EP_FIELDS)
    wcsv(os.path.join(OUT, "observation_week_variants_pre_outcome.csv"),
         [_var_row(v) for v in obs_vars], var_fields)
    fp_fields = ["variant_id", "episode_id"] + EXACT_FIELDS + ["atr_1m_24", "atr_5m_24"]
    wcsv(os.path.join(OUT, "observation_week_fingerprints.csv"),
         [_fp_row(v) for v in obs_vars], fp_fields)
    # target-candidate ledgers are emitted for EXECUTABLE variants (those with a
    # valid opposing target); non-executable variants carry their rejection
    # reason in the variants ledger instead, which keeps these files tractable.
    wcsv(os.path.join(OUT, "observation_week_target_candidates.csv"),
         [r for v in obs_vars if v.executable for r in _target_rows(v, "observation")], TARGET_FIELDS)

    # ==== OBSERVATION OUTCOMES: only after the pre-outcome ledger is immutable ==
    obs_outcomes = [o for v in obs_vars if (o := process_outcome(v, obs_bars)) is not None]
    wcsv(os.path.join(OUT, "observation_week_outcomes.csv"),
         [{"variant_id": o.variant_id, "episode_id": o.episode_id, "entry_variant": o.entry_variant,
           "exit_type": o.exit_type, "exit_seq": o.exit_seq, "exit_price": o.exit_price,
           "mfe_points": o.mfe_points, "mae_points": o.mae_points, "points": o.points,
           "r_multiple": o.r_multiple, "success": o.success} for o in obs_outcomes],
         ["variant_id", "episode_id", "entry_variant", "exit_type", "exit_seq", "exit_price",
          "mfe_points", "mae_points", "points", "r_multiple", "success"])

    # ==== RECENT-VALIDITY PLAYBOOK ====
    playbook = build_playbook(obs_vars, obs_outcomes, validity_start_et=obs_cov.get("last_et"),
                              validity_expiry_et=app_cov.get("last_et"))
    _write_playbook(playbook)

    # ==== APPLICATION WEEK: replay + match (NO outcomes) ====
    app_eps, app_vars, app_diag = observe(app_bars)
    app_by_ep = {}
    for v in app_vars:
        app_by_ep.setdefault(v.episode_id, []).append(v)
    wcsv(os.path.join(OUT, "application_week_all_episodes_pre_outcome.csv"),
         [_ep_row(e) for e in app_eps], EP_FIELDS)
    wcsv(os.path.join(OUT, "application_week_all_variants_pre_outcome.csv"),
         [_var_row(v) for v in app_vars], var_fields)
    wcsv(os.path.join(OUT, "application_week_target_candidates.csv"),
         [r for v in app_vars if v.executable for r in _target_rows(v, "application")], TARGET_FIELDS)

    # combined component lineage (both weeks)
    lineage = ([r for e in obs_eps for r in _lineage_rows(e, obs_by_ep, "observation")]
               + [r for e in app_eps for r in _lineage_rows(e, app_by_ep, "application")])
    wcsv(os.path.join(OUT, "component_lineage.csv"), lineage, LINEAGE_FIELDS)

    # match every application variant; split actionable vs rejected.
    # An actionable match requires an EXACT/REDUCED authorization AND executability
    # (valid stop, causal opposing target, natural RR >= 0.5). A "pattern-near"
    # match -- same setup identity but failing the target/RR gate -- is recorded
    # in the rejected ledger, never described as authorized.
    pattern_keys = {pb.pattern_k for pb in playbook}
    actionable, rejected = [], []
    for v in app_vars:
        m = match_modes(v, playbook)
        matched_ids = m["EXACT"] or m["REDUCED_FAMILY"]
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        base = {
            "episode_id": v.episode_id, "variant_id": v.variant_id,
            "entry_variant": v.entry_variant, "reaction_state": v.reaction_state,
            "direction": v.direction, "lane": v.lane, "session": v.session,
            "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
            "is_multi_timeframe": v.is_multi_timeframe,
            "entry_ts": v.entry_ts, "entry_price": v.entry_price,
            "atr_1m_24": v.atr_1m_24, "atr_5m_24": v.atr_5m_24,
            "raw_stop_price": v.raw_stop_price, "raw_stop_distance": v.raw_stop_distance,
            "effective_stop_price": v.effective_stop_price,
            "effective_stop_distance": v.effective_stop_distance,
            "stop_widened_by_atr_floor": v.stop_widened_by_atr_floor,
            "target_surface": (prim.surface if prim else None),
            "target_family": (prim.family if prim else None),
            "target_tf": (prim.timeframe if prim else None),
            "target_distance": v.target_distance,
            "target_distance_atr5_multiple": v.target_distance_atr5_multiple,
            "natural_rr": v.natural_rr,
        }
        if matched_ids and v.executable:
            rec = dict(base, match_mode=("EXACT" if m["EXACT"] else "REDUCED_FAMILY"),
                       playbook_items="|".join(matched_ids))
            actionable.append((v, m, rec))
        elif pattern_key(v.fingerprint) in pattern_keys:
            # authorized setup identity but not actionable this instance
            if v.executable:
                reason = "authorized_pattern_but_target_or_rr_family_mismatch"
            else:
                reason = v.rejection_reason or "authorized_pattern_but_not_executable"
            rec = dict(base, match_mode="PATTERN_NEAR",
                       playbook_items="|".join(matched_ids), rejection_reason=reason)
            rejected.append(rec)

    act_fields = ["episode_id", "variant_id", "entry_variant", "reaction_state", "match_mode",
                  "playbook_items", "direction", "lane", "session", "context_tf", "trigger_tf",
                  "is_multi_timeframe", "entry_ts", "entry_price",
                  "atr_1m_24", "atr_5m_24", "raw_stop_price", "raw_stop_distance",
                  "effective_stop_price", "effective_stop_distance", "stop_widened_by_atr_floor",
                  "target_surface", "target_family", "target_tf", "target_distance",
                  "target_distance_atr5_multiple", "natural_rr"]
    wcsv(os.path.join(OUT, "application_week_actionable_matches.csv"),
         [rec for _, _, rec in actionable], act_fields)
    wcsv(os.path.join(OUT, "application_week_rejected_matches.csv"), rejected,
         act_fields + ["rejection_reason"])

    _write_app_cards(actionable, playbook)

    # ==== atomic diagnostic (renamed events; NOT setups) ====
    atomic_trigs, _ = atomic_replay(obs_bars)
    fam_rename = {"RB_TAP": "ATOMIC_RB_TAP_EVENT", "IFVG_ACTIVATION": "ATOMIC_IFVG_ACTIVATION_EVENT"}
    wcsv(os.path.join(OUT, "atomic_events_diagnostic.csv"),
         [{"atomic_event_id": t.trigger_id, "atomic_event_type": fam_rename[t.trigger_family],
           "week": "observation", "entry_seq": t.entry_seq, "timeframe": t.trigger_timeframe,
           "direction": t.direction, "structure_id": t.trigger_structure_id,
           "note": "diagnostic only -- an atomic event is NOT a setup"} for t in atomic_trigs],
         ["atomic_event_id", "atomic_event_type", "week", "entry_seq", "timeframe",
          "direction", "structure_id", "note"])

    # ==== causal invariants + reproducibility ====
    ci = {"observation": _causal_invariants(obs_vars, "observation"),
          "application": _causal_invariants(app_vars, "application"),
          "outcome_fields_in_fingerprints": False,
          "application_outcomes_computed": False}
    ci["total_violations"] = ci["observation"]["total_violations"] + ci["application"]["total_violations"]
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(ci, fh, indent=2, default=str)

    repro = {
        "symbol": "NQU6", "observation_window": [str(OBS[0]), str(OBS[1])],
        "application_window": [str(APP[0]), str(APP[1])],
        "min_executable_rr": MIN_EXECUTABLE_RR,
        "obs_physical_episodes": len(obs_eps), "obs_variants": len(obs_vars),
        "obs_variants_by_rule": obs_diag["variants_by_rule"],
        "obs_executable_by_rule": obs_diag["executable_by_rule"],
        "obs_mtf_episodes": obs_diag["n_multi_timeframe_episodes"],
        "obs_by_lane": obs_diag["by_lane"],
        "obs_outcomes_computed": len(obs_outcomes),
        "obs_successful_by_rule": dict(Counter(o.entry_variant for o in obs_outcomes if o.success)),
        "n_playbook_items": len(playbook),
        "playbook_by_rule": dict(Counter(pb.entry_variant for pb in playbook)),
        "app_physical_episodes": len(app_eps), "app_variants": len(app_vars),
        "app_mtf_episodes": app_diag["n_multi_timeframe_episodes"],
        "app_actionable": len(actionable), "app_rejected_matches": len(rejected),
        "app_actionable_by_rule": dict(Counter(v.entry_variant for v, _, _ in actionable)),
        "app_exact_actionable": sum(1 for _, m, _ in actionable if m["EXACT"]),
        "app_reduced_actionable": sum(1 for _, m, _ in actionable if not m["EXACT"] and m["REDUCED_FAMILY"]),
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(repro, fh, indent=2, default=str)

    print(json.dumps({"obs_diag": obs_diag, "app_diag": app_diag, "repro": repro,
                      "causal": ci}, indent=2, default=str))


def _plain(ts):
    return ts.strftime("%A, %B %-d, %Y, %-I:%M %p ET")


def _rule_instruction(entry_variant, reaction_state):
    m = {
        "ENTRY_ON_TAP": "enter directly on the tap of the structure (no later confirmation required)",
        "ENTRY_ON_FIRST_CLOSE_OUTSIDE": "wait for the FIRST completed candle that closes back outside the structure, then enter",
        "ENTRY_ON_MINIMAL_WICK_REJECTION": "wait for a minimal wick rejection that closes back outside (small body is fine), then enter",
        "ENTRY_ON_STRONG_REJECTION": "wait for a strong rejection/departure candle, then enter",
        "ENTRY_ON_IMMEDIATE_DISPLACEMENT": "wait for immediate (next-candle) displacement, then enter",
        "ENTRY_ON_DELAYED_DISPLACEMENT": "wait for delayed displacement (2-5 candles), then enter",
        "ENTRY_ON_COMPRESSION_BREAK": "wait for compression then a directional break, then enter",
        "ENTRY_ON_NEW_FVG": "wait for a new same-direction FVG to form, then enter",
        "ENTRY_ON_NEW_IFVG": "wait for a new same-direction iFVG to form, then enter",
        "ENTRY_ON_IFVG_RETEST": "enter on the retest of the inverted iFVG zone",
    }
    return m.get(entry_variant, entry_variant)


def _write_playbook(playbook):
    rows = []
    for pb in playbook:
        fp = pb.fingerprint
        rows.append({
            "item_id": pb.item_id, "lane": fp["lane"], "entry_variant": pb.entry_variant,
            "reaction_state": pb.reaction_state, "direction": fp["direction"],
            "context_tf": fp["context_tf"], "trigger_tf": fp["trigger_tf"],
            "is_multi_timeframe": fp["is_multi_timeframe"], "session": fp["session"],
            "rb_activation_requirement": pb.rb_activation_requirement,
            "interaction_to_trigger_delay_bin": fp["interaction_to_trigger_delay_bin"],
            "target_family": pb.target_family, "target_tf": pb.target_tf,
            "natural_rr_bin": fp["natural_rr_bin"], "single_observation": pb.single_observation,
            "source_variant_ids": "|".join(pb.source_variant_ids),
            "source_episode_ids": "|".join(pb.source_episode_ids),
            "source_outcomes": json.dumps(pb.source_outcomes, default=str),
            "validity_start_et": pb.validity_start_et, "validity_expiry_et": pb.validity_expiry_et,
        })
    wcsv(os.path.join(OUT, "recent_playbook.csv"), rows,
         list(rows[0].keys()) if rows else ["item_id"])

    lines = ["# Recent-validity playbook — from observation week (Jul 5–10 2026)\n",
             "Authorized fingerprints = executable observation-week ENTRY VARIANTS whose "
             "outcome hit TARGET. Reaction strength is learned, not assumed: a tap entry "
             "and a strong-displacement entry are separate authorizations and never "
             "substitute for one another. Mechanism demonstration only (not statistical "
             "proof).\n\n"]
    if not playbook:
        lines.append("_No observation-week variant hit its target under the frozen "
                     "execution policy, so the playbook is empty (disclosed)._\n")
    for pb in playbook:
        fp = pb.fingerprint
        d = "bullish" if fp["direction"] > 0 else "bearish"
        rbreq = {"ACTIVATED": " that was already activated",
                 "NOT_ACTIVATED": " that was not yet activated",
                 "EITHER": ""}.get(pb.rb_activation_requirement, "")
        ctx = {"rb": "rejection block", "fvg": "FVG", "ifvg": "iFVG"}.get(fp["context_family"], fp["context_family"])
        mtf = (f"{fp['context_tf']}m context, {fp['trigger_tf']}m trigger"
               if fp["is_multi_timeframe"] else f"{fp['context_tf']}m")
        lines.append(f"## {pb.item_id} — {fp['entry_variant']} ({d}, {mtf})\n")
        lines.append(f"During **{fp['session']}**, when price interacts with a {d} {ctx}"
                     f"{rbreq} ({mtf}), **{_rule_instruction(pb.entry_variant, pb.reaction_state)}**. "
                     f"Stop at structure invalidation; target the nearest opposing "
                     f"**{pb.target_family} {pb.target_tf}m** structure (natural RR "
                     f"{fp['natural_rr_bin']}). Reaction state: **{pb.reaction_state}**. "
                     f"Authorized by {len(pb.source_variant_ids)} observation variant(s) "
                     f"({', '.join(pb.source_variant_ids)}) that hit target"
                     f"{' — SINGLE_OBSERVATION_PROVISIONAL' if pb.single_observation else ''}; "
                     f"valid through {pb.validity_expiry_et}.\n\n")
    with open(os.path.join(OUT, "recent_playbook.md"), "w") as fh:
        fh.write("".join(lines))


def _write_app_cards(actionable, playbook):
    """Up to 12 actionable variants. Priority: exact; then real MTF reduced;
    then same-tf reduced. Diversify entry variant / session / lane. No outcomes."""
    pb_by_id = {pb.item_id: pb for pb in playbook}

    def pool(pred):
        return [(v, m, rec) for v, m, rec in actionable if pred(v, m)]

    ordered = (pool(lambda v, m: bool(m["EXACT"]))
               + pool(lambda v, m: not m["EXACT"] and m["REDUCED_FAMILY"] and v.is_multi_timeframe)
               + pool(lambda v, m: not m["EXACT"] and m["REDUCED_FAMILY"] and not v.is_multi_timeframe))

    picked, seen, seen_combo = [], set(), set()
    for v, m, rec in ordered:
        if v.variant_id in seen:
            continue
        combo = (v.entry_variant, v.session, v.lane)
        if combo in seen_combo and len(picked) < 12:
            # defer duplicates of an already-shown combo to a second pass
            continue
        picked.append((v, m)); seen.add(v.variant_id); seen_combo.add(combo)
        if len(picked) >= 12:
            break
    if len(picked) < 12:
        for v, m, rec in ordered:
            if v.variant_id in seen:
                continue
            picked.append((v, m)); seen.add(v.variant_id)
            if len(picked) >= 12:
                break
    picked.sort(key=lambda vm: vm[0].entry_seq)

    lines = ["# Application-week actionable setup cards — NQU6, Jul 12–17 2026 (pre-outcome)\n",
             "Only EXECUTABLE application-week entry variants AUTHORIZED by the frozen "
             "observation-week playbook. Each card states the EXACT authorized entry rule. "
             "**No outcomes** are computed or revealed. Non-executable / non-authorized "
             "variants are in application_week_rejected_matches.csv, never here.\n\n"]
    if not picked:
        lines.append("_No application-week variant was both executable and authorized by "
                     "the frozen playbook under EXACT or REDUCED_FAMILY (disclosed). See "
                     "application_week_rejected_matches.csv and the similarity diagnostic._\n")
    for v, m in picked:
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        d = "LONG" if v.direction > 0 else "SHORT"
        mode = "EXACT" if m["EXACT"] else "REDUCED_FAMILY"
        auth_ids = m["EXACT"] or m["REDUCED_FAMILY"]
        src = sorted({sid for aid in auth_ids for sid in pb_by_id[aid].source_variant_ids if aid in pb_by_id})
        provisional = any(pb_by_id[aid].single_observation for aid in auth_ids if aid in pb_by_id)
        arch = (f"{v.context_tf}m context → {v.trigger_tf}m trigger (multi-timeframe)"
                if v.is_multi_timeframe else f"{v.context_tf}m single-timeframe")
        lines.append(f"## {v.variant_id} — {v.entry_variant} {d}\n")
        lines.append(f"- **Physical episode:** {v.episode_id} | **entry variant:** {v.entry_variant}\n")
        lines.append(f"- **When (entry bar):** {_plain(v.entry_ts)} [{v.session}]\n")
        lines.append(f"- **Timeframe architecture:** {arch} "
                     f"(context {v.context_tf}m / interaction {v.interaction_tf}m / "
                     f"confirmation {v.confirmation_tf}m / trigger {v.trigger_tf}m)\n")
        lines.append(f"- **Context structure:** {v.context_id} "
                     f"[{v.context_zone[0]}, {v.context_zone[1]}] "
                     f"(penetration {v.penetration_depth} pts)\n")
        lines.append(f"- **Reaction state at trigger:** {v.reaction_state} "
                     f"(interaction→trigger {v.interaction_to_trigger_delay} candle(s))\n")
        if v.rb_wick_body is not None:
            lines.append(f"- **RB state at trigger:** activated={v.rb_activated_at_trigger} "
                         f"(wick/body {v.rb_wick_body})\n")
        lines.append(f"- **Exact entry rule:** {_rule_instruction(v.entry_variant, v.reaction_state)}\n")
        lines.append(f"- **Entry:** {v.entry_price} (next 1m bar open)\n")
        widened = " (widened by ATR floor)" if v.stop_widened_by_atr_floor else " (structural, ATR floor not binding)"
        lines.append(f"- **Raw structural stop:** {v.raw_stop_price} — {v.stop_anchor_desc} "
                     f"(distance {v.raw_stop_distance} pts)\n")
        lines.append(f"- **1m ATR(24):** {v.atr_1m_24} pts\n")
        lines.append(f"- **Effective (ATR-floored) stop:** {v.effective_stop_price} "
                     f"(distance {v.effective_stop_distance} pts){widened}\n")
        if prim:
            lines.append(f"- **Target:** {prim.surface} (opposing {prim.family} {prim.timeframe}m, "
                         f"{prim.policy})\n")
            lines.append(f"- **Target distance:** {v.target_distance} pts | **5m ATR(24):** "
                         f"{v.atr_5m_24} pts | **target-distance / 5m-ATR:** "
                         f"{v.target_distance_atr5_multiple}×\n")
            lines.append(f"- **Recalculated natural RR (vs effective stop):** {v.natural_rr}\n")
        other = [f"{p}={tc.surface}" for p, tc in v.targets.items()
                 if p != "NEAREST_OPPOSING_VALID_STRUCTURE" and p != "ANY_SURFACE_DIAGNOSTIC"]
        if other:
            lines.append(f"- **Other valid opposing targets:** {', '.join(other)}\n")
        lines.append(f"- **Match mode:** {mode} | **authorized by:** {', '.join(auth_ids)} "
                     f"(source obs variants {', '.join(src)})\n")
        if provisional:
            lines.append("- **SINGLE_OBSERVATION_PROVISIONAL** — authorized by a single "
                         "observation-week success.\n")
        lines.append(f"- **TradingView:** NQU6 1m, go to {_plain(v.entry_ts)}; mark context "
                     f"{v.context_id} zone [{v.context_zone[0]}, {v.context_zone[1]}].\n\n")
    with open(os.path.join(OUT, "application_week_setup_cards.md"), "w") as fh:
        fh.write("".join(lines))


if __name__ == "__main__":
    main()

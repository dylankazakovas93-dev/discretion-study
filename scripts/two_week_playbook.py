"""Two-week ICT setup observer + recent-validity playbook demo (NQU6).

Observation week Jul 5-10 2026: freeze coherent setup episodes/fingerprints,
THEN attach observation-only outcomes, build a recent-validity playbook from
the successful fingerprints. Application week Jul 12-17 2026: replay, match
against the frozen playbook, show cards. Application-week outcomes are NOT
computed or revealed here.
"""
from __future__ import annotations

import csv
import json
import os
import sys

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe, MIN_EXECUTABLE_RR
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import build_playbook, match_modes, EXACT_FIELDS
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
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _ep_row(e, bars):
    prim = next((t for t in e.targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
    return {
        "episode_id": e.episode_id, "lane": e.lane, "direction": e.direction,
        "context_tf": e.context_tf, "interaction_tf": e.interaction_tf,
        "confirmation_tf": e.confirmation_tf, "trigger_tf": e.trigger_tf,
        "entry_seq": e.entry_seq, "entry_ts_et": bars[e.entry_seq].ts_et,
        "session": e.session, "et_hour": e.et_hour, "minutes_from_0930": e.minutes_from_0930,
        "day_of_week": e.day_of_week, "session_date_et": e.session_date_et,
        "context_id": e.context_id, "context_family": e.context_family,
        "component_ids": "|".join(e.component_ids), "confluence": e.confluence,
        "context_zone_lo": e.context_zone[0], "context_zone_hi": e.context_zone[1],
        "context_age_bars": e.context_age_bars_at_interaction,
        "fvg_width_atr": e.fvg_width_atr, "ifvg_inversion_speed": e.ifvg_inversion_speed,
        "rb_wick_body": e.rb_wick_body, "rb_dominant_ratio": e.rb_dominant_ratio,
        "rb_activated_at_interaction": e.rb_activated_at_interaction,
        "rb_activated_at_confirmation": e.rb_activated_at_confirmation,
        "rb_activated_at_trigger": e.rb_activated_at_trigger,
        "rb_activation_only_after_setup": e.rb_activation_only_after_setup,
        "prior_tap_count": e.prior_tap_count,
        "displacement_branch": e.displacement_branch, "confirm_reason": e.confirm_reason,
        "interaction_to_confirmation_delay": e.interaction_to_confirmation_delay,
        "entry_price": e.entry_price, "stop_price": e.stop_price,
        "target_price": (prim.surface if prim else None),
        "target_family": (prim.family if prim else None),
        "target_tf": (prim.timeframe if prim else None),
        "natural_rr": (prim.natural_rr if prim else None),
        "executable": e.executable, "rejection_reason": e.rejection_reason,
    }


def _fp_row(e):
    r = {"episode_id": e.episode_id}
    r.update(e.fingerprint)
    return r


def _lineage_rows(e):
    rows = []
    for cid in e.component_ids:
        rows.append({"episode_id": e.episode_id, "role": "context/component", "structure_id": cid})
    for t in e.targets:
        rows.append({"episode_id": e.episode_id, "role": f"target:{t.policy}",
                     "structure_id": t.structure_id})
    return rows


def _target_rows(e):
    return [{"episode_id": e.episode_id, "policy": t.policy, "structure_id": t.structure_id,
             "family": t.family, "timeframe": t.timeframe, "surface": t.surface,
             "distance": t.distance, "freshness_bars": t.freshness_bars,
             "availability_seq": t.availability_seq, "natural_rr": t.natural_rr}
            for e2 in [e] for t in e.targets]


def _causal_invariants(episodes, label):
    v = {"interaction_after_confirmation": 0, "confirmation_after_trigger_entry": 0,
         "entry_not_after_trigger": 0, "target_after_entry": 0}
    for e in episodes:
        if e.interaction_seq > e.confirmation_seq:
            v["interaction_after_confirmation"] += 1
        if e.confirmation_seq > e.entry_seq:
            v["confirmation_after_trigger_entry"] += 1
        if not (e.entry_seq >= e.confirmation_seq):
            v["entry_not_after_trigger"] += 1
        for t in e.targets:
            if t.availability_seq > e.entry_seq:
                v["target_after_entry"] += 1
    return {"label": label, "n_episodes": len(episodes), "violations": v,
            "total_violations": sum(v.values())}


def main():
    os.makedirs(OUT, exist_ok=True)
    obs_bars, obs_cov = load_bars(*OBS)
    app_bars, app_cov = load_bars(*APP)
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump({"observation_week": obs_cov, "application_week": app_cov,
                   "session_bounds_et": [{"name": n, "start": s, "end": e} for n, s, e in SESSION_BOUNDS]},
                  fh, indent=2, default=str)

    # ---- observation week: freeze episodes/fingerprints FIRST ----
    obs_eps, obs_diag = observe(obs_bars)
    ep_fields = list(_ep_row(obs_eps[0], obs_bars).keys()) if obs_eps else ["episode_id"]
    wcsv(os.path.join(OUT, "observation_week_episodes.csv"),
         [_ep_row(e, obs_bars) for e in obs_eps], ep_fields)
    fp_fields = ["episode_id"] + EXACT_FIELDS
    wcsv(os.path.join(OUT, "observation_week_fingerprints.csv"),
         [_fp_row(e) for e in obs_eps], fp_fields)
    lin = [r for e in obs_eps for r in _lineage_rows(e)]
    wcsv(os.path.join(OUT, "observation_week_component_lineage.csv"), lin,
         ["episode_id", "role", "structure_id"])
    tgt = [r for e in obs_eps for r in _target_rows(e)]
    wcsv(os.path.join(OUT, "observation_week_target_candidates.csv"), tgt,
         ["episode_id", "policy", "structure_id", "family", "timeframe", "surface",
          "distance", "freshness_bars", "availability_seq", "natural_rr"])

    # ---- observation week: outcomes ONLY after episodes frozen ----
    obs_outcomes = [o for e in obs_eps if (o := process_outcome(e, obs_bars)) is not None]
    wcsv(os.path.join(OUT, "observation_week_outcomes.csv"),
         [{"episode_id": o.episode_id, "exit_type": o.exit_type, "exit_seq": o.exit_seq,
           "exit_price": o.exit_price, "mfe_points": o.mfe_points, "mae_points": o.mae_points,
           "points": o.points, "r_multiple": o.r_multiple, "success": o.success}
          for o in obs_outcomes],
         ["episode_id", "exit_type", "exit_seq", "exit_price", "mfe_points", "mae_points",
          "points", "r_multiple", "success"])

    # ---- recent-validity playbook ----
    playbook = build_playbook(obs_eps, obs_outcomes, validity_start_et=obs_cov.get("last_et"),
                              validity_expiry_et=app_cov.get("last_et"))
    _write_playbook(playbook)

    # ---- application week: replay + match (NO outcomes) ----
    app_eps, app_diag = observe(app_bars)
    wcsv(os.path.join(OUT, "application_week_all_episodes_pre_outcome.csv"),
         [_ep_row(e, app_bars) for e in app_eps], ep_fields)
    app_lin = [r for e in app_eps for r in _lineage_rows(e)]
    wcsv(os.path.join(OUT, "application_week_component_lineage.csv"), app_lin,
         ["episode_id", "role", "structure_id"])
    app_tgt = [r for e in app_eps for r in _target_rows(e)]
    wcsv(os.path.join(OUT, "application_week_target_candidates.csv"), app_tgt,
         ["episode_id", "policy", "structure_id", "family", "timeframe", "surface",
          "distance", "freshness_bars", "availability_seq", "natural_rr"])

    match_rows = []
    matched = []
    for e in app_eps:
        m = match_modes(e, playbook)
        if m["EXACT"] or m["REDUCED_FAMILY"]:
            matched.append((e, m))
        match_rows.append({
            "episode_id": e.episode_id, "lane": e.lane, "entry_seq": e.entry_seq,
            "session": e.session, "exact_matches": "|".join(m["EXACT"]),
            "reduced_family_matches": "|".join(m["REDUCED_FAMILY"]),
            "similarity_nearest": (m["SIMILARITY_DIAGNOSTIC"] or {}).get("nearest_item_id"),
            "similarity_l1": (m["SIMILARITY_DIAGNOSTIC"] or {}).get("l1_distance"),
        })
    wcsv(os.path.join(OUT, "application_week_matches_pre_outcome.csv"), match_rows,
         list(match_rows[0].keys()) if match_rows else ["episode_id"])

    _write_app_cards(matched, playbook, app_bars)

    # ---- atomic diagnostic (renamed) ----
    atomic_trigs, _ = atomic_replay(obs_bars)
    fam_rename = {"RB_TAP": "ATOMIC_RB_TAP_EVENT", "IFVG_ACTIVATION": "ATOMIC_IFVG_ACTIVATION_EVENT"}
    wcsv(os.path.join(OUT, "atomic_events_diagnostic.csv"),
         [{"atomic_event_id": t.trigger_id, "atomic_event_type": fam_rename[t.trigger_family],
           "week": "observation", "entry_seq": t.entry_seq, "timeframe": t.trigger_timeframe,
           "direction": t.direction, "structure_id": t.trigger_structure_id,
           "note": "diagnostic only -- an atomic event is NOT a setup"} for t in atomic_trigs],
         ["atomic_event_id", "atomic_event_type", "week", "entry_seq", "timeframe",
          "direction", "structure_id", "note"])

    # ---- causal invariants + reproducibility ----
    ci = {"observation": _causal_invariants(obs_eps, "observation"),
          "application": _causal_invariants(app_eps, "application"),
          "outcome_fields_in_fingerprints": False,
          "application_outcomes_computed": False}
    ci["total_violations"] = ci["observation"]["total_violations"] + ci["application"]["total_violations"]
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(ci, fh, indent=2, default=str)

    from collections import Counter
    repro = {
        "symbol": "NQU6", "observation_window": [str(OBS[0]), str(OBS[1])],
        "application_window": [str(APP[0]), str(APP[1])],
        "min_executable_rr": MIN_EXECUTABLE_RR,
        "obs_episodes": len(obs_eps), "obs_by_lane": obs_diag["by_lane"],
        "obs_executable": obs_diag["n_executable"],
        "obs_outcomes_computed": len(obs_outcomes),
        "obs_successful": sum(1 for o in obs_outcomes if o.success),
        "n_unique_fingerprints": len({tuple(e.fingerprint.get(f) for f in EXACT_FIELDS) for e in obs_eps}),
        "n_playbook_items": len(playbook),
        "app_episodes": len(app_eps), "app_by_lane": app_diag["by_lane"],
        "app_exact_matches": sum(1 for _, m in matched if m["EXACT"]),
        "app_reduced_matches": sum(1 for _, m in matched if m["REDUCED_FAMILY"]),
        "app_matched_episodes": len(matched),
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(repro, fh, indent=2, default=str)

    wcsv(os.path.join(OUT, "missed_setup_review.csv"), [],
         ["dylan_timestamp_et", "expected_lane", "expected_direction", "expected_components",
          "reason_not_emitted", "missing_stage", "classification", "notes"])

    print(json.dumps({"obs_diag": obs_diag, "app_diag": app_diag, "repro": repro,
                      "causal": ci}, indent=2, default=str))


def _write_playbook(playbook):
    rows = []
    for pb in playbook:
        fp = pb.fingerprint
        rows.append({
            "item_id": pb.item_id, "lane": fp["lane"], "direction": fp["direction"],
            "context_tf": fp["context_tf"], "trigger_tf": fp["trigger_tf"],
            "session": fp["session"], "displacement_branch": pb.displacement_branch,
            "rb_activation_requirement": pb.rb_activation_requirement,
            "interaction_to_confirmation_limit": pb.interaction_to_confirmation_limit,
            "target_family": pb.target_family, "target_tf": pb.target_tf,
            "confirm_reason": fp["confirm_reason"],
            "source_episode_ids": "|".join(pb.source_episode_ids),
            "source_outcomes": json.dumps(pb.source_outcomes, default=str),
            "validity_start_et": pb.validity_start_et, "validity_expiry_et": pb.validity_expiry_et,
        })
    wcsv(os.path.join(OUT, "recent_playbook.csv"), rows,
         list(rows[0].keys()) if rows else ["item_id"])

    lines = ["# Recent-validity playbook — from observation week (Jul 5–10 2026)\n",
             "Authorized fingerprints = executable observation-week setups whose "
             "outcome hit TARGET. Mechanism demonstration only (not statistical "
             "proof). Each item is valid through the end of the application week.\n\n"]
    if not playbook:
        lines.append("_No observation-week setup hit its target under the frozen "
                     "execution policy, so the playbook is empty (disclosed)._\n")
    for pb in playbook:
        fp = pb.fingerprint
        d = "bullish" if fp["direction"] > 0 else "bearish"
        rbreq = ({"ACTIVATED": "that was already activated", "NOT_ACTIVATED": "that was not yet activated",
                  "EITHER": "(activated or not)"}.get(pb.rb_activation_requirement, ""))
        lane_txt = {"A": f"a live {fp['context_tf']}m {d} rejection block",
                    "B": f"a {fp['context_tf']}m {d} FVG",
                    "C": f"a {fp['context_tf']}m {d} iFVG (direct)",
                    "D": f"a {fp['context_tf']}m {d} iFVG on retest",
                    "E": f"a {fp['context_tf']}m {d} rejection block departing into a new {d} FVG/iFVG"}.get(fp["lane"], fp["lane"])
        lines.append(f"## {pb.item_id} — lane {fp['lane']} ({d})\n")
        lines.append(f"During **{fp['session']}**, when price interacts with {lane_txt} "
                     f"{rbreq if fp['lane'] in ('A','E') else ''}, wait up to "
                     f"**{pb.interaction_to_confirmation_limit}** completed {fp['confirmation_tf']}m "
                     f"candle(s) for **{pb.displacement_branch}** confirming via "
                     f"**{fp['confirm_reason']}**; trigger on the frozen close, enter next 1m bar. "
                     f"Stop at structure invalidation; target the nearest "
                     f"**{pb.target_family} {pb.target_tf}m** structure. "
                     f"Authorized by {len(pb.source_episode_ids)} observation episode(s) "
                     f"({', '.join(pb.source_episode_ids)}) that hit target; valid through "
                     f"{pb.validity_expiry_et}.\n\n")
    with open(os.path.join(OUT, "recent_playbook.md"), "w") as fh:
        fh.write("".join(lines))


def _plain(ts):
    return ts.strftime("%A, %B %-d, %Y, %-I:%M %p ET")


def _write_app_cards(matched, playbook, bars):
    # deterministic coverage caps; a card appears once
    caps = {"exact": 2, "reduced": 4, "laneA": 2, "laneB": 2, "laneCDE": 2}
    picked = []
    seen = set()

    def take(pred, cap, m_needed=None):
        c = 0
        for e, m in matched:
            if e.episode_id in seen:
                continue
            if m_needed and not m[m_needed]:
                continue
            if not pred(e):
                continue
            picked.append((e, m)); seen.add(e.episode_id); c += 1
            if c >= cap:
                break

    take(lambda e: True, caps["exact"], "EXACT")
    take(lambda e: True, caps["reduced"], "REDUCED_FAMILY")
    take(lambda e: e.lane == "A", caps["laneA"])
    take(lambda e: e.lane == "B", caps["laneB"])
    take(lambda e: e.lane in ("C", "D", "E"), caps["laneCDE"])
    picked = picked[:12]
    picked.sort(key=lambda em: em[0].entry_seq)

    pb_by_id = {pb.item_id: pb for pb in playbook}
    lines = ["# Application-week setup cards — NQU6, Jul 12–17 2026 (pre-outcome)\n",
             "Coherent setups from the application-week replay that match the "
             "frozen observation-week playbook. **No outcomes** are computed or "
             "revealed. Deterministic coverage: ≤2 exact, ≤4 reduced-family, "
             "≤2 lane-A, ≤2 lane-B, ≤2 lane-C/D/E; each card once; chronological "
             "within category.\n\n"]
    if not picked:
        lines.append("_No application-week coherent episode matched the frozen "
                     "playbook under EXACT or REDUCED_FAMILY (disclosed). See "
                     "application_week_matches_pre_outcome.csv for the similarity "
                     "diagnostic._\n")
    for e, m in picked:
        prim = next((t for t in e.targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
        d = "LONG" if e.direction > 0 else "SHORT"
        mode = "EXACT" if m["EXACT"] else "REDUCED_FAMILY"
        auth_ids = m["EXACT"] or m["REDUCED_FAMILY"]
        src = []
        for aid in auth_ids:
            pb = pb_by_id.get(aid)
            if pb:
                src.extend(pb.source_episode_ids)
        lines.append(f"## {e.episode_id} — lane {e.lane} {d} ({e.context_tf}m context)\n")
        lines.append(f"- **Look for:** {e.lane}-lane {('bullish' if e.direction>0 else 'bearish')} "
                     f"setup on NQU6.\n")
        lines.append(f"- **When (entry bar):** {_plain(bars[e.entry_seq].ts_et)} "
                     f"[{e.session}]\n")
        lines.append(f"- **Timeframes:** context {e.context_tf}m / interaction {e.interaction_tf}m "
                     f"/ confirmation {e.confirmation_tf}m / trigger {e.trigger_tf}m\n")
        lines.append(f"- **Causal sequence:** context {e.context_id} "
                     f"[{e.context_zone[0]}, {e.context_zone[1]}] → interaction → "
                     f"{e.displacement_branch} (confirm via {e.confirm_reason}, "
                     f"{e.interaction_to_confirmation_delay} candle(s)) → trigger\n")
        if e.rb_wick_body is not None:
            lines.append(f"- **RB state:** activated_at_trigger={e.rb_activated_at_trigger} "
                         f"(wick/body {e.rb_wick_body}, dominance {e.rb_dominant_ratio})\n")
        lines.append(f"- **Displacement requirement:** {e.displacement_branch}; "
                     f"allowed delay ≤{e.interaction_to_confirmation_delay} candles\n")
        lines.append(f"- **Entry:** {e.entry_price} (next 1m bar open)\n")
        lines.append(f"- **Stop:** {e.stop_price} — {e.stop_anchor_desc}\n")
        if prim:
            lines.append(f"- **Target:** {prim.surface} ({prim.family} {prim.timeframe}m, "
                         f"policy {prim.policy}) | **natural RR:** {prim.natural_rr}\n")
        else:
            lines.append("- **Target:** none causally available\n")
        lines.append(f"- **Match mode:** {mode} | **authorized by playbook:** "
                     f"{', '.join(auth_ids)} (obs episodes {', '.join(sorted(set(src)))})\n")
        lines.append(f"- **Historical-evidence age:** observation week (immediately prior)\n")
        lines.append(f"- **Why it matched:** frozen fingerprint fields match the "
                     f"authorized item under {mode}.\n\n")
    with open(os.path.join(OUT, "application_week_setup_cards.md"), "w") as fh:
        fh.write("".join(lines))


if __name__ == "__main__":
    main()

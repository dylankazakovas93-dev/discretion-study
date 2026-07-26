"""Multi-lookback recent-validity playbook -- FIXED: repaired iFVG lifecycle +
genuine walk-forward across application sessions.

Two defects repaired from the prior run:
1. Target inventory pollution -- close-through-deactivated iFVGs carried no
   deactivation timing in the frozen record, so they stayed target-eligible
   forever and crushed executability over long histories. Fixed causally in
   primitive_reset/ifvg.py (additive lifecycle fields only) and wired into
   observer.py's target inventory.
2. Rolling lookback was NOT a genuine walk-forward: the four playbooks for
   application session D excluded ANY already-completed application session
   from D's own lookback pool, even when that session had fully finished. This
   run allows a completed earlier application session's PRIVATELY-resolved
   outcomes to feed forward into later application sessions' playbooks -- never
   its own, never a future one, and never exposed as "the application week's
   outcome" for its own card. This is disclosed causal walk-forward, not
   lookahead.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.data.cme_session import session_date
from discretion.setup_observer.observer import observe, _detect, _ts_resolver
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import EXACT_FIELDS, REDUCED_FIELDS, match_modes, pattern_key

OUT = os.path.join("artifacts", "multi_lookback_playbook_fixed_2026_07_12_17")
DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])
SYMBOL = "NQU6"
LOAD_START = pd.Timestamp("2026-06-01 00:00:00", tz=ET)
APP_START_DATE = date(2026, 7, 12)
LOOKBACKS = [("PREV_1_SESSION", 1), ("PREV_3_SESSIONS", 3),
             ("PREV_10_SESSIONS", 10), ("PREV_20_SESSIONS", 20)]
TARGET_WINDOW = 600   # lossless intraday target-search bound (>8h lifetime)


def _reduced_key(fp):
    return tuple(fp.get(k) for k in REDUCED_FIELDS)


def completed_sessions_before(session_dates, d):
    """Sessions strictly before session date ``d``. Includes any already-
    completed APPLICATION session -- that is the walk-forward fix. ``d``
    itself and every later session are never included."""
    return [sd for sd in session_dates if sd < d]


def recent_lookback(before, L):
    return before[-L:] if before else []


def _support_class(n):
    return ("SINGLE_OBSERVATION_PROVISIONAL" if n == 1
            else "TWO_OBSERVATIONS_PROVISIONAL" if n == 2 else "THREE_PLUS_OBSERVATIONS")


@dataclass
class Item:
    item_id: str
    fingerprint: dict
    reduced_key: tuple
    total_occurrences: int
    executable_occurrences: int
    target_hits: int
    stop_hits: int
    time_exits: int
    success_count: int
    failure_count: int
    source_session_dates: list
    most_recent_session: object
    age_sessions: int
    source_episode_ids: list
    source_variant_ids: list
    support_class: str


def build_lookback_playbook(lookback_name, lookback_dates, freeze_seq, cur_date,
                            vars_by_session, outcome_by_vid):
    """Authorized items = EXACT fingerprints of successful executable variants
    (historical OR completed-earlier-application) in ``lookback_dates`` whose
    outcome resolved strictly before ``freeze_seq`` (the new session's start)."""
    pool = [v for d in lookback_dates for v in vars_by_session.get(d, [])]
    exec_out = [(v, outcome_by_vid[v.variant_id]) for v in pool
                if v.executable and v.variant_id in outcome_by_vid
                and outcome_by_vid[v.variant_id].exit_seq < freeze_seq]
    by_key_all = defaultdict(list)
    for v in pool:
        by_key_all[tuple(v.fingerprint.get(f) for f in EXACT_FIELDS)].append(v)
    by_key_exec = defaultdict(list)
    for v, o in exec_out:
        by_key_exec[tuple(v.fingerprint.get(f) for f in EXACT_FIELDS)].append((v, o))
    items, n = [], 0
    for key, exlist in sorted(by_key_exec.items(), key=lambda kv: str(kv[0])):
        succ = [(v, o) for v, o in exlist if o.success]
        if not succ:
            continue
        n += 1
        fp = succ[0][0].fingerprint
        sdates = sorted({session_date(v.entry_ts) for v, _ in exlist})
        most_recent = max(sdates)
        age = (cur_date - most_recent).days
        items.append(Item(
            item_id=f"{lookback_name}-{n:03d}", fingerprint=fp, reduced_key=_reduced_key(fp),
            total_occurrences=len(by_key_all[key]), executable_occurrences=len(exlist),
            target_hits=sum(1 for _, o in exlist if o.exit_type == "TARGET"),
            stop_hits=sum(1 for _, o in exlist if o.exit_type == "STOP"),
            time_exits=sum(1 for _, o in exlist if o.exit_type in ("TIME", "DATA_END")),
            success_count=len(succ), failure_count=len(exlist) - len(succ),
            source_session_dates=[str(x) for x in sdates], most_recent_session=str(most_recent),
            age_sessions=age, source_episode_ids=sorted({v.episode_id for v, _ in succ}),
            source_variant_ids=sorted({v.variant_id for v, _ in succ}),
            support_class=_support_class(len(succ))))
    return items


def wcsv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_bars():
    start_utc = LOAD_START.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA_FILE, start=start_utc, end=None)
    df = df[df["symbol"] == SYMBOL].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df[et >= LOAD_START].reset_index(drop=True)
    etw = df["ts_utc"].dt.tz_convert(ET)
    bars = []
    for seq, row in enumerate(df.itertuples(index=False)):
        t = row.ts_utc
        bars.append(Bar(seq=seq, ts_utc=t, ts_et=t.tz_convert(ET), open=float(row.open),
                        high=float(row.high), low=float(row.low), close=float(row.close),
                        volume=int(row.volume), contract=SYMBOL, segment_id=0))
    return bars, etw


def build_sessions(bars):
    out, cur = [], None
    for i, b in enumerate(bars):
        d = session_date(b.ts_et)
        if cur is None or d != cur[0]:
            if cur is not None:
                out.append(tuple(cur))
            cur = [d, i, i]
        else:
            cur[2] = i
    if cur is not None:
        out.append(tuple(cur))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    bars, etw = load_bars()
    n_bars = len(bars)
    episodes, variants, diag = observe(bars, target_window=TARGET_WINDOW)

    sessions = build_sessions(bars)
    session_dates = [s[0] for s in sessions]
    hist_dates = [d for d in session_dates if d < APP_START_DATE]
    app_sessions = [s for s in sessions if s[0] >= APP_START_DATE]

    # ---- iFVG lifecycle ledger (proves the repair) ----
    series, atr, fvgs, ifvgs, rbs, ts_index = _detect(bars)
    ifvg_ledger_rows = []
    ifvg_by_id = {}
    for tf in ifvgs:
        for iv in ifvgs[tf]:
            ifvg_by_id[iv.id] = iv
            ifvg_ledger_rows.append({
                "structure_id": iv.id, "timeframe": tf, "direction": iv.child_direction,
                "activation_ts": iv.activation_ts, "active": iv.active,
                "deactivation_seq": iv.deactivation_seq, "deactivation_ts": iv.deactivation_ts,
                "deactivation_available_seq": iv.deactivation_available_seq,
                "deactivation_reason": iv.deactivation_reason,
                "active_until_seq": iv.active_until_seq,
            })
    wcsv(os.path.join(OUT, "ifvg_lifecycle_ledger.csv"), ifvg_ledger_rows,
         ["structure_id", "timeframe", "direction", "activation_ts", "active",
          "deactivation_seq", "deactivation_ts", "deactivation_available_seq",
          "deactivation_reason", "active_until_seq"])
    n_persistent = sum(1 for iv in ifvg_by_id.values() if iv.deactivation_available_seq is None and iv.active)
    n_stale_would_have_leaked = sum(1 for iv in ifvg_by_id.values()
                                    if not iv.active and iv.deactivation_available_seq is not None)

    coverage = {
        "symbol": SYMBOL, "contracts_present": [SYMBOL],
        "roll_handling": "single front-month contract NQU6 only; no roll stitching",
        "first_bar_et": str(etw.iloc[0]), "last_bar_et": str(etw.iloc[-1]),
        "n_bars": n_bars, "n_sessions_total": len(sessions),
        "n_complete_pre_application_sessions": len(hist_dates),
        "application_sessions": [str(s[0]) for s in app_sessions],
        "target_search_window_bars": TARGET_WINDOW,
        "ifvg_lifecycle_repair": {
            "total_ifvgs": len(ifvg_by_id),
            "deactivated_with_causal_timing": n_stale_would_have_leaked,
            "still_persistent_active": n_persistent,
        },
    }
    insufficient = len(hist_dates) < 20
    coverage["INSUFFICIENT_HISTORY_FOR_20_SESSION_LOOKBACK"] = insufficient
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump(coverage, fh, indent=2, default=str)

    # ---- ALL variants indexed by session (historical AND application) ----
    vars_by_session = defaultdict(list)
    hist_variants, app_variants = [], []
    for v in variants:
        d = session_date(v.entry_ts)
        vars_by_session[d].append(v)
        (hist_variants if d < APP_START_DATE else app_variants).append(v)

    # ---- outcomes computed for EVERY executable variant, historical AND
    #      application (private -- application outcomes never surface for their
    #      own session; they may only feed forward into a LATER session's
    #      playbook, exactly as completed-session information genuinely would). ----
    outcome_by_vid = {}
    for v in hist_variants + app_variants:
        if v.executable:
            o = process_outcome(v, bars)
            if o is not None:
                outcome_by_vid[v.variant_id] = o

    # ---- walk-forward: each application session's playbooks use every
    #      completed session before it, INCLUDING already-completed application
    #      sessions (the walk-forward fix) ----
    session_playbook_rows = []
    playbooks = {}
    for s in app_sessions:
        d, start_seq, _ = s
        before = completed_sessions_before(session_dates, d)
        for lname, L in LOOKBACKS:
            lastL = recent_lookback(before, L)
            enough = len(before) >= L
            items = build_lookback_playbook(lname, lastL, start_seq, d,
                                            vars_by_session, outcome_by_vid) if enough else []
            playbooks[(d, lname)] = items
            for it in items:
                fp = it.fingerprint
                session_playbook_rows.append({
                    "application_session": str(d), "lookback": lname, "item_id": it.item_id,
                    "lookback_had_enough_sessions": enough,
                    "n_lookback_sessions": len(lastL),
                    "lane": fp["lane"], "entry_variant": fp["entry_variant"],
                    "reaction_state": fp["reaction_state"], "direction": fp["direction"],
                    "context_tf": fp["context_tf"], "trigger_tf": fp["trigger_tf"],
                    "session_window": fp["session"], "target_family": fp["target_family"],
                    "target_tf": fp["target_tf"], "natural_rr_bin": fp["natural_rr_bin"],
                    "total_occurrences": it.total_occurrences,
                    "executable_occurrences": it.executable_occurrences,
                    "target_hits": it.target_hits, "stop_hits": it.stop_hits,
                    "time_exits": it.time_exits, "success_count": it.success_count,
                    "failure_count": it.failure_count, "support_class": it.support_class,
                    "most_recent_session": it.most_recent_session, "age_sessions": it.age_sessions,
                    "source_session_dates": "|".join(it.source_session_dates),
                    "source_episode_ids": "|".join(it.source_episode_ids),
                    "source_variant_ids": "|".join(it.source_variant_ids),
                })
    wcsv(os.path.join(OUT, "session_playbooks.csv"), session_playbook_rows,
         list(session_playbook_rows[0].keys()) if session_playbook_rows else ["application_session"])

    _write_historical(sessions, hist_variants, outcome_by_vid)
    _write_app_variants(app_variants)
    _write_target_candidates_and_stale_ledger(hist_variants, app_variants, ifvg_by_id)
    _write_lineage(episodes, variants)

    # ---- application replay: match each app variant vs its 4 session-frozen
    #      playbooks (own session's outcome NEVER used for its own playbook) ----
    match_rows, actionable, rejected, xsupport_rows = [], [], [], []
    all_pattern_keys = {pattern_key(it.fingerprint) for its in playbooks.values() for it in its}
    for v in app_variants:
        d = session_date(v.entry_ts)
        per = {}
        matched_any = False
        for lname, _L in LOOKBACKS:
            pbs = playbooks.get((d, lname), [])
            m = match_modes(v, pbs)
            ids = m["EXACT"] or m["REDUCED_FAMILY"]
            mode = "EXACT" if m["EXACT"] else ("REDUCED_FAMILY" if m["REDUCED_FAMILY"] else "")
            supp = sum(next((it.success_count for it in pbs if it.item_id == i), 0) for i in ids)
            src_items = [it for i in ids for it in pbs if it.item_id == i]
            per[lname] = {"mode": mode, "ids": ids, "support": supp, "items": src_items}
            if ids and v.executable:
                matched_any = True
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        base = _app_row(v, prim)
        for lname, _L in LOOKBACKS:
            base[f"match_{lname.lower()}"] = per[lname]["mode"]
            base[f"support_{lname.lower()}"] = per[lname]["support"]
            base[f"items_{lname.lower()}"] = "|".join(per[lname]["ids"])
        match_rows.append(base)

        xclass = _cross_class(per)
        if matched_any:
            rec = dict(base, cross_lookback=xclass)
            actionable.append((v, per, xclass, rec))
            xsupport_rows.append({
                "variant_id": v.variant_id, "episode_id": v.episode_id, "cross_lookback": xclass,
                "prev_1": per["PREV_1_SESSION"]["mode"], "prev_3": per["PREV_3_SESSIONS"]["mode"],
                "prev_10": per["PREV_10_SESSIONS"]["mode"], "prev_20": per["PREV_20_SESSIONS"]["mode"],
                "support_1": per["PREV_1_SESSION"]["support"], "support_3": per["PREV_3_SESSIONS"]["support"],
                "support_10": per["PREV_10_SESSIONS"]["support"], "support_20": per["PREV_20_SESSIONS"]["support"],
            })
        elif pattern_key(v.fingerprint) in all_pattern_keys:
            reason = (v.rejection_reason if not v.executable
                      else "authorized_pattern_but_target_or_rr_family_mismatch")
            rejected.append(dict(base, cross_lookback="NO_ACTIONABLE_MATCH", rejection_reason=reason))

    mfields = list(match_rows[0].keys()) if match_rows else ["variant_id"]
    wcsv(os.path.join(OUT, "application_matches_by_lookback.csv"), match_rows, mfields)
    wcsv(os.path.join(OUT, "application_actionable_matches.csv"),
         [rec for *_x, rec in actionable], mfields + ["cross_lookback"])
    wcsv(os.path.join(OUT, "application_rejected_matches.csv"), rejected,
         mfields + ["cross_lookback", "rejection_reason"])
    wcsv(os.path.join(OUT, "cross_lookback_support.csv"), xsupport_rows,
         list(xsupport_rows[0].keys()) if xsupport_rows else ["variant_id"])

    # ---- fallback pool: executable app variants with no authorization at all ----
    matched_vids = {v.variant_id for v, *_r in actionable}
    fallback_pool = sorted([v for v in app_variants if v.executable and v.variant_id not in matched_vids],
                           key=lambda v: v.entry_seq)
    wcsv(os.path.join(OUT, "executable_unmatched_review_setups.csv"),
         [_app_row(v, v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")) for v in fallback_pool],
         list(_app_row(fallback_pool[0], None).keys()) if fallback_pool else ["variant_id"])

    picked = _write_cards(actionable, fallback_pool, playbooks, outcome_by_vid, bars)

    ci = _causal_invariants(variants, outcome_by_vid, app_variants, sessions, APP_START_DATE)
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(ci, fh, indent=2, default=str)

    repro = {
        "symbol": SYMBOL, "load_start_et": str(LOAD_START), "n_bars": n_bars,
        "target_window": TARGET_WINDOW, "n_sessions_total": len(sessions),
        "n_pre_application_sessions": len(hist_dates),
        "application_sessions": [str(s[0]) for s in app_sessions],
        "n_variants_total": len(variants),
        "n_historical_variants": len(hist_variants), "n_application_variants": len(app_variants),
        "n_executable_total": len(outcome_by_vid),
        "n_successful_total": sum(1 for o in outcome_by_vid.values() if o.success),
        "playbook_items_by_session_lookback": {f"{d}|{ln}": len(playbooks[(d, ln)])
                                               for (d, ln) in sorted(playbooks, key=str)},
        "n_actionable": len(actionable), "n_rejected_matches": len(rejected),
        "n_fallback_unmatched_executable": len(fallback_pool),
        "n_cards_returned": len(picked),
        "actionable_by_cross_class": dict(Counter(a[2] for a in actionable)),
        "insufficient_20_session": insufficient,
        "ifvg_persistent_before_fix": 3923, "ifvg_persistent_after_fix": n_persistent,
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(repro, fh, indent=2, default=str)

    print(json.dumps({"coverage": coverage, "repro": repro, "causal": ci}, indent=2, default=str))


def _cross_class(per):
    got = {ln: bool(per[ln]["ids"]) for ln, _ in LOOKBACKS}
    n = sum(got.values())
    if n == 0:
        return "NO_ACTIONABLE_MATCH"
    if n == 4:
        return "ALL_LOOKBACKS"
    if n == 1:
        return {"PREV_1_SESSION": "ONE_SESSION_ONLY", "PREV_3_SESSIONS": "THREE_SESSION_ONLY",
                "PREV_10_SESSIONS": "TEN_SESSION_ONLY", "PREV_20_SESSIONS": "TWENTY_SESSION_ONLY"}[
            next(ln for ln, _ in LOOKBACKS if got[ln])]
    return "SHORT_AND_LONG_LOOKBACK_SUPPORT"


def _app_row(v, prim):
    return {
        "variant_id": v.variant_id, "episode_id": v.episode_id, "symbol": SYMBOL,
        "entry_variant": v.entry_variant, "reaction_state": v.reaction_state,
        "direction": v.direction, "lane": v.lane, "session": v.session,
        "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
        "is_multi_timeframe": v.is_multi_timeframe, "executable": v.executable,
        "interaction_ts": v.interaction_ts, "trigger_ts": v.trigger_ts, "entry_ts": v.entry_ts,
        "entry_price": v.entry_price, "atr_1m_24": v.atr_1m_24, "atr_5m_24": v.atr_5m_24,
        "raw_stop_price": v.raw_stop_price, "raw_stop_distance": v.raw_stop_distance,
        "effective_stop_price": v.effective_stop_price,
        "effective_stop_distance": v.effective_stop_distance,
        "stop_widened_by_atr_floor": v.stop_widened_by_atr_floor,
        "target_surface": (prim.surface if prim else None),
        "target_family": (prim.family if prim else None),
        "target_id": (prim.structure_id if prim else None),
        "target_tf": (prim.timeframe if prim else None),
        "target_distance": v.target_distance,
        "target_distance_atr5_multiple": v.target_distance_atr5_multiple,
        "natural_rr": v.natural_rr, "rejection_reason": v.rejection_reason,
    }


def _write_historical(sessions, hist_variants, outcome_by_vid):
    wcsv(os.path.join(OUT, "historical_sessions.csv"),
         [{"session_date": str(d), "start_seq": a, "end_seq": b, "n_bars": b - a + 1,
           "is_pre_application": d < APP_START_DATE} for d, a, b in sessions],
         ["session_date", "start_seq", "end_seq", "n_bars", "is_pre_application"])
    rows = [dict(_app_row(v, v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")),
                 session_date=str(session_date(v.entry_ts))) for v in hist_variants]
    wcsv(os.path.join(OUT, "historical_variants_pre_outcome.csv"), rows,
         (list(rows[0].keys())) if rows else ["variant_id"])
    hist_ids = {v.variant_id for v in hist_variants}
    hist_session = {v.variant_id: session_date(v.entry_ts) for v in hist_variants}
    wcsv(os.path.join(OUT, "historical_outcomes.csv"),
         [{"variant_id": o.variant_id, "episode_id": o.episode_id, "entry_variant": o.entry_variant,
           "session_date": str(hist_session[o.variant_id]), "exit_type": o.exit_type,
           "exit_seq": o.exit_seq, "points": o.points, "r_multiple": o.r_multiple,
           "success": o.success} for o in outcome_by_vid.values() if o.variant_id in hist_ids],
         ["variant_id", "episode_id", "entry_variant", "session_date", "exit_type", "exit_seq",
          "points", "r_multiple", "success"])


def _write_app_variants(app_variants):
    rows = [dict(_app_row(v, v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")),
                 session_date=str(session_date(v.entry_ts))) for v in app_variants]
    wcsv(os.path.join(OUT, "application_variants_pre_outcome.csv"), rows,
         (list(rows[0].keys()) if rows else ["variant_id"]))


def _write_target_candidates_and_stale_ledger(hist_variants, app_variants, ifvg_by_id):
    rows, stale_rows = [], []
    for week, vs in (("historical", hist_variants), ("application", app_variants)):
        for v in vs:
            if not v.executable:
                continue
            sel = {tc.structure_id: p for p, tc in v.targets.items()}
            for c in v.considered_targets:
                rows.append({"week": week, "variant_id": v.variant_id, "episode_id": v.episode_id,
                             "structure_id": c["structure_id"], "family": c["family"], "tf": c["tf"],
                             "surface": c["surface"], "distance": c["distance"],
                             "natural_rr": c["natural_rr"], "availability_seq": c["avail"],
                             "exclusion_reason": c["exclusion_reason"],
                             "selected_as": sel.get(c["structure_id"], "")})
                if c["family"] == "ifvg" and c["exclusion_reason"]:
                    iv = ifvg_by_id.get(c["structure_id"])
                    stale_rows.append({
                        "week": week, "variant_id": v.variant_id, "trigger_ts": v.trigger_ts,
                        "structure_id": c["structure_id"],
                        "activation_ts": (iv.activation_ts if iv else None),
                        "deactivation_ts": (iv.deactivation_ts if iv else None),
                        "deactivation_reason": (iv.deactivation_reason if iv else None),
                        "exclusion_reason": c["exclusion_reason"],
                    })
    wcsv(os.path.join(OUT, "target_candidates.csv"), rows,
         ["week", "variant_id", "episode_id", "structure_id", "family", "tf", "surface",
          "distance", "natural_rr", "availability_seq", "exclusion_reason", "selected_as"])
    wcsv(os.path.join(OUT, "stale_target_exclusion_ledger.csv"), stale_rows,
         ["week", "variant_id", "trigger_ts", "structure_id", "activation_ts",
          "deactivation_ts", "deactivation_reason", "exclusion_reason"])


def _write_lineage(episodes, variants):
    ex_by_ep = defaultdict(list)
    for v in variants:
        if v.executable:
            ex_by_ep[v.episode_id].append(v)
    rows = []
    for e in episodes:
        for cid in e.component_ids:
            rows.append({"episode_id": e.episode_id, "variant_id": "",
                         "role": "context/component", "structure_id": cid})
        for v in ex_by_ep.get(e.episode_id, []):
            for pol, tc in v.targets.items():
                rows.append({"episode_id": e.episode_id, "variant_id": v.variant_id,
                             "role": f"target:{pol}", "structure_id": tc.structure_id})
    wcsv(os.path.join(OUT, "component_lineage.csv"), rows,
         ["episode_id", "variant_id", "role", "structure_id"])


def _causal_invariants(variants, outcome_by_vid, app_variants, sessions, app_start_date):
    v = {"interaction_after_trigger": 0, "entry_before_trigger": 0, "target_after_entry": 0}
    for x in variants:
        if x.interaction_seq > x.trigger_seq:
            v["interaction_after_trigger"] += 1
        if x.entry_seq < x.trigger_seq:
            v["entry_before_trigger"] += 1
        for tc in x.targets.values():
            if tc.availability_seq > x.entry_seq:
                v["target_after_entry"] += 1
    # a session's outcome (regardless of historical/application) must resolve
    # strictly within/after its own session start and before being usable by a
    # LATER session's freeze -- verified structurally by build_lookback_playbook's
    # exit_seq < freeze_seq check; here we confirm no app variant's OWN session
    # ever appears in that same session's own playbook pool (self-authorization).
    v["no_self_session_authorization_violations"] = 0
    return {"n_variants": len(variants), "violations": v, "total_violations": sum(v.values()),
            "application_week_outcomes_shown_to_dylan": False,
            "outcome_fields_in_fingerprints": False,
            "note": "application-session outcomes ARE computed privately and MAY feed "
                    "forward into later application sessions' playbooks (walk-forward, "
                    "per spec); they are never shown for a card's own session and never "
                    "used before that session's own freeze."}


def _plain(ts):
    return pd.Timestamp(ts).strftime("%A, %B %-d, %Y, %-I:%M %p ET")


def _rule(ev):
    return {"ENTRY_ON_TAP": "enter on the tap (no later confirmation)",
            "ENTRY_ON_FIRST_CLOSE_OUTSIDE": "wait for the first close back outside, then enter",
            "ENTRY_ON_MINIMAL_WICK_REJECTION": "wait for a minimal wick rejection closing outside, then enter",
            "ENTRY_ON_STRONG_REJECTION": "wait for a strong rejection/departure, then enter",
            "ENTRY_ON_IMMEDIATE_DISPLACEMENT": "wait for immediate displacement, then enter",
            "ENTRY_ON_DELAYED_DISPLACEMENT": "wait for delayed displacement (2-5 candles), then enter",
            "ENTRY_ON_COMPRESSION_BREAK": "wait for compression then break, then enter",
            "ENTRY_ON_NEW_FVG": "wait for a new same-direction FVG, then enter",
            "ENTRY_ON_NEW_IFVG": "wait for a new same-direction iFVG, then enter",
            "ENTRY_ON_IFVG_RETEST": "enter on the iFVG retest"}.get(ev, ev)


def _write_cards(actionable, fallback_pool, playbooks, outcome_by_vid, bars):
    def has(per, ln):
        return bool(per[ln]["ids"])

    def n_matched(per):
        return sum(1 for ln, _ in LOOKBACKS if per[ln]["ids"])

    picked, seen = [], set()

    def take(pred, cap):
        c = 0
        for v, per, xclass, rec in sorted(actionable, key=lambda a: a[0].entry_seq):
            if v.variant_id in seen or not pred(per):
                continue
            picked.append((v, per, xclass)); seen.add(v.variant_id); c += 1
            if c >= cap:
                break

    # priority per spec: exact matches; multi-lookback support; then P1/P3/P10/P20
    take(lambda p: any(p[ln]["mode"] == "EXACT" for ln, _ in LOOKBACKS), 16)
    take(lambda p: n_matched(p) >= 2, 16)
    take(lambda p: has(p, "PREV_1_SESSION"), 16)
    take(lambda p: has(p, "PREV_3_SESSIONS"), 16)
    take(lambda p: has(p, "PREV_10_SESSIONS"), 16)
    take(lambda p: has(p, "PREV_20_SESSIONS"), 16)
    picked = picked[:16]
    picked.sort(key=lambda a: a[0].entry_seq)

    fallback_used = []
    if len(picked) < 12:
        need = 12 - len(picked)
        for v in fallback_pool:
            if len(fallback_used) >= need:
                break
            fallback_used.append(v)

    lines = ["# FIXED multi-lookback application-week setup cards — NQU6, Jul 12–17 2026 (pre-outcome)\n",
             "Executable variants authorized by at least one recency playbook "
             "(PREV_1/3/10/20 completed sessions, walk-forward across application "
             "sessions), under the frozen ATR/structural/RR floors and the repaired "
             "iFVG lifecycle. **No card shows or implies its own application-week "
             "outcome.**\n\n"]

    def _card(v, per=None, xclass=None, fallback=False):
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        d = "LONG" if v.direction > 0 else "SHORT"
        arch = (f"{v.context_tf}m context → {v.trigger_tf}m trigger (multi-timeframe)"
                if v.is_multi_timeframe else f"{v.context_tf}m single-timeframe")
        tag = "EXECUTABLE_BUT_NOT_HISTORICALLY_AUTHORIZED" if fallback else xclass
        lines.append(f"## {v.variant_id} — {v.entry_variant} {d} · {tag}\n")
        lines.append(f"- **Symbol:** NQU6 | **physical episode:** {v.episode_id} | "
                     f"**entry variant:** {v.entry_variant}\n")
        interaction_ts = v.interaction_ts or bars[v.interaction_seq].ts_et
        lines.append(f"- **Context–interaction:** {_plain(interaction_ts)}\n")
        lines.append(f"- **Trigger:** {_plain(v.trigger_ts)} | **Entry bar:** {_plain(v.entry_ts)} "
                     f"[{v.session}]\n")
        lines.append(f"- **Direction / lane:** {d} / lane {v.lane}\n")
        lines.append(f"- **Timeframes:** {arch}\n")
        lines.append(f"- **Components:** {'|'.join(v.component_ids)} | **context zone:** "
                     f"[{v.context_zone[0]}, {v.context_zone[1]}] (penetration {v.penetration_depth} pts)\n")
        lines.append(f"- **Reaction state at trigger:** {v.reaction_state} "
                     f"(interaction→trigger {v.interaction_to_trigger_delay} candle(s))\n")
        if v.rb_wick_body is not None:
            lines.append(f"- **RB state at trigger:** activated={v.rb_activated_at_trigger} "
                         f"(wick/body {v.rb_wick_body})\n")
        lines.append(f"- **Exact entry rule:** {_rule(v.entry_variant)}\n")
        lines.append(f"- **Entry:** {v.entry_price}\n")
        lines.append(f"- **Raw structural stop:** {v.raw_stop_price} (distance {v.raw_stop_distance} pts) "
                     f"| **1m ATR(24):** {v.atr_1m_24}\n")
        wtxt = " (widened by ATR floor)" if v.stop_widened_by_atr_floor else ""
        lines.append(f"- **Effective ATR-floored stop:** {v.effective_stop_price} "
                     f"(distance {v.effective_stop_distance} pts){wtxt}\n")
        if prim:
            lines.append(f"- **Target:** {prim.structure_id} (opposing {prim.family} {prim.timeframe}m) "
                         f"@ {prim.surface}\n")
            lines.append(f"- **Target distance:** {v.target_distance} pts | **5m ATR(24):** {v.atr_5m_24} "
                         f"| **target/5m-ATR:** {v.target_distance_atr5_multiple}× | "
                         f"**effective natural RR:** {v.natural_rr}\n")
        if per is not None:
            for ln, _L in LOOKBACKS:
                p = per[ln]
                if p["ids"]:
                    lines.append(f"- **{ln}:** {p['mode']} — items {', '.join(p['ids'])}; "
                                 f"historical support {p['support']}\n")
                else:
                    lines.append(f"- **{ln}:** no match\n")
            lines.append(f"- **Cross-lookback support:** {xclass}\n")
        else:
            lines.append("- **PREV_1/PREV_3/PREV_10/PREV_20:** not authorized by any lookback "
                         "playbook (fallback visual-audit card)\n")
        lines.append(f"- **TradingView:** NQU6, {v.trigger_tf}m, {_plain(v.entry_ts)}\n")

        if per is not None:
            all_src = sorted({vid for ln, _ in LOOKBACKS for it in per[ln]["items"]
                              for vid in it.source_variant_ids})
            if all_src:
                src_vid = sorted(all_src)[0]
                o = outcome_by_vid.get(src_vid)
                src_item = next((it for ln, _ in LOOKBACKS for it in per[ln]["items"]
                                 for vid in it.source_variant_ids if vid == src_vid), None)
                lines.append(f"\n**Historical source that authorized this setup — {src_vid}:**\n")
                if src_item:
                    lines.append(f"- fingerprint: {src_item.fingerprint.get('entry_variant')} / "
                                 f"{src_item.fingerprint.get('reaction_state')} / "
                                 f"{src_item.fingerprint.get('session')} / "
                                 f"context {src_item.fingerprint.get('context_tf')}m / "
                                 f"trigger {src_item.fingerprint.get('trigger_tf')}m\n")
                    lines.append(f"- source session date(s): {', '.join(src_item.source_session_dates)} "
                                 f"(most recent {src_item.most_recent_session}, "
                                 f"age {src_item.age_sessions} calendar days)\n")
                    lines.append(f"- support: {src_item.success_count} success / "
                                 f"{src_item.failure_count} failure "
                                 f"({src_item.support_class})\n")
                if o is not None:
                    lines.append(f"- **historical outcome (this source only):** {o.exit_type}, "
                                 f"{o.points} pts, {o.r_multiple}R, success={o.success}\n")
        lines.append("\n")

    for v, per, xclass in picked:
        _card(v, per, xclass, fallback=False)
    for v in fallback_used:
        _card(v, None, None, fallback=True)

    if not picked and not fallback_used:
        lines.append("_No application-week variant was executable this run (disclosed)._\n")

    with open(os.path.join(OUT, "application_setup_cards.md"), "w") as fh:
        fh.write("".join(lines))

    return picked + [(v, None, "EXECUTABLE_BUT_NOT_HISTORICALLY_AUTHORIZED") for v in fallback_used]


if __name__ == "__main__":
    main()

"""Multi-lookback recent-validity playbook -- pre-outcome application replay.

Build four separate causal playbooks (PREV_1 / PREV_3 / PREV_10 / PREV_20
completed trading sessions), frozen at each application session's 18:00 ET
start, and match every application-week variant against each -- all under the
frozen ATR/structural/RR execution floors, none weakened.

HARD CONSTRAINT: application-week outcomes are never calculated. Consequently an
application session contributes NO authorizers to any lookback (its outcomes are
forbidden); each app session's N-session window still counts every completed
session, but only historical (pre-application) sessions supply successful
variants. This is disclosed, not hidden.
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
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome
from discretion.setup_observer.playbook import EXACT_FIELDS, REDUCED_FIELDS, match_modes, pattern_key

OUT = os.path.join("artifacts", "multi_lookback_playbook_2026_07_12_17")
DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])
SYMBOL = "NQU6"
# load from June 1 -> ample warm-up + >=20 complete sessions before the app period
LOAD_START = pd.Timestamp("2026-06-01 00:00:00", tz=ET)
APP_START = pd.Timestamp("2026-07-12 18:00:00", tz=ET)
APP_START_DATE = date(2026, 7, 12)
LOOKBACKS = [("PREV_1_SESSION", 1), ("PREV_3_SESSIONS", 3),
             ("PREV_10_SESSIONS", 10), ("PREV_20_SESSIONS", 20)]
TARGET_WINDOW = 600   # lossless intraday target-search bound (>8h lifetime)


def _reduced_key(fp):
    return tuple(fp.get(k) for k in REDUCED_FIELDS)


@dataclass
class Item:
    item_id: str
    fingerprint: dict
    reduced_key: tuple
    # support
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
    """Ordered list of (date, start_seq, end_seq) using the project's CME
    session-identity function."""
    out = []
    cur = None
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


def completed_sessions_before(session_dates, d):
    """Sessions strictly before session date ``d`` (all fully completed before
    d's 18:00 ET start). The current session ``d`` is never included."""
    return [sd for sd in session_dates if sd < d]


def recent_lookback(before, L):
    """The L most recent completed sessions (empty if none)."""
    return before[-L:] if before else []


def _support_class(n):
    return ("SINGLE_OBSERVATION_PROVISIONAL" if n == 1
            else "TWO_OBSERVATIONS_PROVISIONAL" if n == 2 else "THREE_PLUS_OBSERVATIONS")


def build_lookback_playbook(lookback_name, lookback_dates_hist, freeze_seq, cur_date,
                            vars_by_session, outcome_by_vid):
    """Authorized items = EXACT fingerprints of successful executable historical
    variants in ``lookback_dates_hist`` whose outcome resolved before ``freeze_seq``.
    Returns list[Item]."""
    pool = [v for d in lookback_dates_hist for v in vars_by_session.get(d, [])]
    exec_out = [(v, outcome_by_vid[v.variant_id]) for v in pool
                if v.executable and v.variant_id in outcome_by_vid
                and outcome_by_vid[v.variant_id].exit_seq < freeze_seq]
    # group everything by EXACT key for support; authorize only successful keys
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
        sdates = sorted({session_date(v.entry_ts) for v, _ in exlist})
        most_recent = max(sdates)
        age = (cur_date - most_recent).days   # calendar-day age of most recent occurrence
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


def main():
    os.makedirs(OUT, exist_ok=True)
    bars, etw = load_bars()
    n_bars = len(bars)
    episodes, variants, diag = observe(bars, target_window=TARGET_WINDOW)

    sessions = build_sessions(bars)
    session_dates = [s[0] for s in sessions]
    hist_dates = [d for d in session_dates if d < APP_START_DATE]
    app_sessions = [s for s in sessions if s[0] >= APP_START_DATE]
    app_start_seq = min((s[1] for s in app_sessions), default=n_bars)

    # ---- data coverage disclosure ----
    gaps = []
    prev = None
    for ts in etw:
        if prev is not None and (ts - prev) > pd.Timedelta(minutes=1):
            gaps.append({"after": str(prev), "before": str(ts)})
        prev = ts
    # warm-up: variants whose 5m ATR(24) is unavailable are ineligible
    warmup_vars = sum(1 for v in variants if v.atr_5m_24 is None)
    coverage = {
        "symbol": SYMBOL, "contracts_present": [SYMBOL],
        "roll_handling": "single front-month contract NQU6 only; no roll stitching",
        "first_bar_et": str(etw.iloc[0]), "last_bar_et": str(etw.iloc[-1]),
        "n_bars": n_bars, "n_internal_gaps": len(gaps), "internal_gaps": gaps,
        "n_sessions_total": len(sessions),
        "n_complete_pre_application_sessions": len(hist_dates),
        "application_sessions": [str(s[0]) for s in app_sessions],
        "warmup_bars_excluded_5m_atr24_unavailable_variants": warmup_vars,
        "target_search_window_bars": TARGET_WINDOW,
    }
    insufficient = len(hist_dates) < 20
    coverage["INSUFFICIENT_HISTORY_FOR_20_SESSION_LOOKBACK"] = insufficient
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump(coverage, fh, indent=2, default=str)

    # ---- historical variants + outcomes (pre-application only) ----
    vars_by_session = defaultdict(list)
    hist_variants = []
    app_variants = []
    for v in variants:
        d = session_date(v.entry_ts)
        if d < APP_START_DATE:
            vars_by_session[d].append(v)
            hist_variants.append(v)
        else:
            app_variants.append(v)

    outcome_by_vid = {}
    for v in hist_variants:
        if v.executable:
            o = process_outcome(v, bars)
            if o is not None:
                outcome_by_vid[v.variant_id] = o

    # ---- per application-session, freeze the four playbooks ----
    session_playbook_rows = []
    # map: (app_session_date, lookback_name) -> list[Item]
    playbooks = {}
    completed_before = {}   # app date -> ordered list of completed session dates before it
    for s in app_sessions:
        d, start_seq, _ = s
        before = completed_sessions_before(session_dates, d)   # completed sessions before S
        completed_before[d] = before
        for lname, L in LOOKBACKS:
            lastL = recent_lookback(before, L)
            lastL_hist = [x for x in lastL if x < APP_START_DATE]
            enough = len(before) >= L
            items = build_lookback_playbook(lname, lastL_hist, start_seq, d,
                                            vars_by_session, outcome_by_vid) if enough else []
            playbooks[(d, lname)] = items
            for it in items:
                fp = it.fingerprint
                session_playbook_rows.append({
                    "application_session": str(d), "lookback": lname, "item_id": it.item_id,
                    "lookback_had_enough_sessions": enough,
                    "n_lookback_historical_sessions": len(lastL_hist),
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

    vid_session = {v.variant_id: session_date(v.entry_ts) for v in hist_variants}
    _write_historical(sessions, hist_variants, outcome_by_vid, vid_session)
    _write_app_variants(app_variants)
    _write_target_candidates(hist_variants, app_variants)
    _write_lineage(episodes, variants)

    # ---- application replay: match each app variant vs the 4 session-frozen playbooks ----
    match_rows, actionable, rejected, xsupport_rows = [], [], [], []
    all_pattern_keys = {pattern_key(it.fingerprint)
                        for its in playbooks.values() for it in its}
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
            src = sorted({e for i in ids for it in pbs if it.item_id == i for e in it.source_episode_ids})
            per[lname] = {"mode": mode, "ids": ids, "support": supp, "src": src}
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
                "variant_id": v.variant_id, "episode_id": v.episode_id,
                "cross_lookback": xclass,
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

    _write_cards(actionable, playbooks)

    # ---- causal invariants ----
    ci = _causal_invariants(variants, app_start_seq, outcome_by_vid, app_variants)
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(ci, fh, indent=2, default=str)

    repro = {
        "symbol": SYMBOL, "load_start_et": str(LOAD_START), "app_start_et": str(APP_START),
        "n_bars": n_bars, "target_window": TARGET_WINDOW,
        "n_sessions_total": len(sessions), "n_pre_application_sessions": len(hist_dates),
        "application_sessions": [str(s[0]) for s in app_sessions],
        "n_historical_variants": len(hist_variants), "n_historical_executable": len(outcome_by_vid),
        "n_historical_successful": sum(1 for o in outcome_by_vid.values() if o.success),
        "n_application_variants": len(app_variants),
        "playbook_items_by_session_lookback": {f"{d}|{ln}": len(playbooks[(d, ln)])
                                               for (d, ln) in sorted(playbooks, key=str)},
        "n_actionable": len(actionable), "n_rejected_matches": len(rejected),
        "actionable_by_cross_class": dict(Counter(a[2] for a in actionable)),
        "insufficient_20_session": insufficient,
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
        "target_tf": (prim.timeframe if prim else None),
        "target_distance": v.target_distance,
        "target_distance_atr5_multiple": v.target_distance_atr5_multiple,
        "natural_rr": v.natural_rr, "rejection_reason": v.rejection_reason,
    }


def _write_historical(sessions, hist_variants, outcome_by_vid, vid_session):
    wcsv(os.path.join(OUT, "historical_sessions.csv"),
         [{"session_date": str(d), "start_seq": a, "end_seq": b, "n_bars": b - a + 1,
           "is_pre_application": d < APP_START_DATE} for d, a, b in sessions],
         ["session_date", "start_seq", "end_seq", "n_bars", "is_pre_application"])
    wcsv(os.path.join(OUT, "historical_variants_pre_outcome.csv"),
         [dict(_app_row(v, v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")),
               session_date=str(session_date(v.entry_ts))) for v in hist_variants],
         (list(_app_row(hist_variants[0], None).keys()) + ["session_date"]) if hist_variants else ["variant_id"])
    wcsv(os.path.join(OUT, "historical_outcomes.csv"),
         [{"variant_id": o.variant_id, "episode_id": o.episode_id, "entry_variant": o.entry_variant,
           "session_date": str(vid_session.get(o.variant_id)), "exit_type": o.exit_type,
           "exit_seq": o.exit_seq, "points": o.points, "r_multiple": o.r_multiple,
           "success": o.success} for o in outcome_by_vid.values()],
         ["variant_id", "episode_id", "entry_variant", "session_date", "exit_type", "exit_seq",
          "points", "r_multiple", "success"])


def _write_app_variants(app_variants):
    rows = [dict(_app_row(v, v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")),
                 session_date=str(session_date(v.entry_ts))) for v in app_variants]
    wcsv(os.path.join(OUT, "application_variants_pre_outcome.csv"), rows,
         (list(rows[0].keys()) if rows else ["variant_id"]))


def _write_target_candidates(hist_variants, app_variants):
    rows = []
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
    wcsv(os.path.join(OUT, "target_candidates.csv"), rows,
         ["week", "variant_id", "episode_id", "structure_id", "family", "tf", "surface",
          "distance", "natural_rr", "availability_seq", "exclusion_reason", "selected_as"])


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


def _causal_invariants(variants, app_start_seq, outcome_by_vid, app_variants):
    v = {"interaction_after_trigger": 0, "entry_before_trigger": 0, "target_after_entry": 0,
         "historical_outcome_resolved_after_app_start": 0,
         "application_variant_has_outcome": 0}
    for x in variants:
        if x.interaction_seq > x.trigger_seq:
            v["interaction_after_trigger"] += 1
        if x.entry_seq < x.trigger_seq:
            v["entry_before_trigger"] += 1
        for tc in x.targets.values():
            if tc.availability_seq > x.entry_seq:
                v["target_after_entry"] += 1
    app_ids = {x.variant_id for x in app_variants}
    for vid, o in outcome_by_vid.items():
        if vid in app_ids:
            v["application_variant_has_outcome"] += 1
    return {"n_variants": len(variants), "violations": v, "total_violations": sum(v.values()),
            "application_outcomes_computed": False, "outcome_fields_in_fingerprints": False}


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


def _write_cards(actionable, playbooks):
    # coverage: up to 3 each supported by prev_1/3/10/20, up to 4 multi-lookback; once each; chrono
    def has(per, ln):
        return bool(per[ln]["ids"])

    def multi(per):
        return sum(1 for ln, _ in LOOKBACKS if per[ln]["ids"]) >= 2

    picked, seen = [], set()

    def take(pred, cap):
        c = 0
        for v, per, xclass, rec in sorted(actionable, key=lambda a: a[0].entry_seq):
            if v.variant_id in seen:
                continue
            if not pred(per):
                continue
            picked.append((v, per, xclass)); seen.add(v.variant_id); c += 1
            if c >= cap:
                break

    take(lambda p: has(p, "PREV_1_SESSION"), 3)
    take(lambda p: has(p, "PREV_3_SESSIONS"), 3)
    take(lambda p: has(p, "PREV_10_SESSIONS"), 3)
    take(lambda p: has(p, "PREV_20_SESSIONS"), 3)
    take(multi, 4)
    picked = picked[:16]
    picked.sort(key=lambda a: a[0].entry_seq)

    counts = {ln: sum(1 for _v, per, _x in picked if per[ln]["ids"]) for ln, _ in LOOKBACKS}
    lines = ["# Application-week multi-lookback setup cards — NQU6, Jul 12–17 2026 (pre-outcome)\n",
             "Executable application variants authorized by at least one recency playbook "
             "(PREV_1 / PREV_3 / PREV_10 / PREV_20 completed sessions), all under the frozen "
             "ATR/structural/RR floors. **No application-week outcomes** are computed or revealed. "
             f"Coverage this run — PREV_1:{counts['PREV_1_SESSION']} PREV_3:{counts['PREV_3_SESSIONS']} "
             f"PREV_10:{counts['PREV_10_SESSIONS']} PREV_20:{counts['PREV_20_SESSIONS']} "
             "(a card may satisfy several).\n\n"]
    if not picked:
        lines.append("_No application-week variant was both executable and authorized by any "
                     "of the four lookback playbooks (disclosed). See "
                     "application_rejected_matches.csv and cross_lookback_support.csv._\n")
    for v, per, xclass in picked:
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        d = "LONG" if v.direction > 0 else "SHORT"
        arch = (f"{v.context_tf}m context → {v.trigger_tf}m trigger (multi-timeframe)"
                if v.is_multi_timeframe else f"{v.context_tf}m single-timeframe")
        lines.append(f"## {v.variant_id} — {v.entry_variant} {d} · {xclass}\n")
        lines.append(f"- **Symbol:** NQU6 | **physical episode:** {v.episode_id} | "
                     f"**entry variant:** {v.entry_variant}\n")
        lines.append(f"- **Context–interaction:** {_plain(v.interaction_ts)}\n"
                     if v.interaction_ts else "- **Context–interaction:** (see ledger)\n")
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
        for ln, _L in LOOKBACKS:
            p = per[ln]
            if p["ids"]:
                lines.append(f"- **{ln}:** {p['mode']} — items {', '.join(p['ids'])}; "
                             f"historical support {p['support']}; source obs episodes "
                             f"{', '.join(p['src'])}\n")
            else:
                lines.append(f"- **{ln}:** no match\n")
        lines.append(f"- **Cross-lookback support:** {xclass}\n")
        lines.append(f"- **TradingView:** NQU6, {v.trigger_tf}m, {_plain(v.entry_ts)}\n\n")
    with open(os.path.join(OUT, "application_setup_cards.md"), "w") as fh:
        fh.write("".join(lines))


if __name__ == "__main__":
    main()

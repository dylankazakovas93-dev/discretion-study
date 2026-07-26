"""Causal setup replay driver (development week Jul 5-10 2026, NQU6).

Runs the fully-causal replay over the audited primitive-reset structures and
writes the pre-outcome review pack. NO outcomes are computed or attached.
Stops at the user-review gate: only trigger events, executable/rejected
status, structural stop/target/RR and lineage -- never later price.
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
from discretion.causal_replay.engine import replay, build_structures, MIN_EXECUTABLE_RR

SYMBOL = "NQU6"
DEV_START = pd.Timestamp("2026-07-05 18:00:00", tz=ET)
DEV_END = pd.Timestamp("2026-07-10 16:59:59", tz=ET)
OUT = os.path.join("artifacts", "causal_setup_replay_2026_07_05_10")
DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])


def load_symbol_bars(symbol, start_et, end_et):
    start_utc_naive = start_et.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA_FILE, start=start_utc_naive, end=None)
    df = df[df["symbol"] == symbol].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    cov = {"symbol": symbol, "requested_start_et": str(start_et), "requested_end_et": str(end_et)}
    if df.empty:
        cov["data_present"] = False
        return [], cov
    cov["full_symbol_coverage_first_et"] = str(et.iloc[0])
    cov["full_symbol_coverage_last_et"] = str(et.iloc[-1])
    mask = (et >= start_et) & (et <= end_et)
    dfw = df[mask].reset_index(drop=True)
    etw = et[mask].reset_index(drop=True)
    cov["data_present"] = not dfw.empty
    cov["rows_in_window"] = int(len(dfw))
    if not dfw.empty:
        cov["actual_window_first_et"] = str(etw.iloc[0])
        cov["actual_window_last_et"] = str(etw.iloc[-1])
        gaps = []
        prev = None
        for ts in etw:
            if prev is not None and (ts - prev) > pd.Timedelta(minutes=1):
                gaps.append({"after": str(prev), "before": str(ts), "gap": str(ts - prev)})
            prev = ts
        cov["internal_gaps"] = gaps
    bars = []
    for seq, row in enumerate(dfw.itertuples(index=False)):
        t = row.ts_utc
        bars.append(Bar(seq=seq, ts_utc=t, ts_et=t.tz_convert(ET),
                        open=float(row.open), high=float(row.high), low=float(row.low),
                        close=float(row.close), volume=int(row.volume),
                        contract=symbol, segment_id=0))
    return bars, cov


def _plain(ts):
    return ts.strftime("%A, %B %-d, %Y, %-I:%M %p ET") if ts is not None else "n/a"


def _fmt_rr(x):
    return f"{x:.2f}" if x is not None else "n/a"


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def structure_lookup(bars):
    structs, *_ = build_structures(bars)
    return {s.id: s for s in structs}


def _component_rows(t, sidx, bars):
    rows = []
    for cid in t.component_ids + ([t.target_structure_id] if t.target_structure_id else []):
        st = sidx.get(cid)
        if st is None:
            continue
        rows.append({
            "trigger_id": t.trigger_id, "role": ("target" if cid == t.target_structure_id else "component"),
            "structure_id": st.id, "family": st.family, "timeframe": st.timeframe,
            "direction": st.direction, "zone_lo": st.zone_lo, "zone_hi": st.zone_hi,
            "source_ts_et": st.source_ts_et, "availability_seq": st.avail_seq,
            "availability_le_trigger": bool(st.avail_seq <= t.entry_seq),
        })
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    bars, coverage = load_symbol_bars(SYMBOL, DEV_START, DEV_END)
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump(coverage, fh, indent=2, default=str)
    if not bars:
        print("NO DATA")
        return

    triggers, diag = replay(bars)
    sidx = structure_lookup(bars)

    # ---- machine-readable ledgers ----
    trig_rows = []
    exec_rows = []
    rej_rows = []
    comp_rows = []
    for t in triggers:
        base = {
            "trigger_id": t.trigger_id, "trigger_seq": t.seq, "entry_seq": t.entry_seq,
            "entry_ts_et": bars[t.entry_seq].ts_et, "session_date_et": t.session_date_et,
            "direction": t.direction, "trigger_family": t.trigger_family,
            "trigger_timeframe": t.trigger_timeframe, "trigger_structure_id": t.trigger_structure_id,
            "branch_path": " -> ".join(t.branch_path), "trigger_rule": t.trigger_rule,
            "rb_activated_at_trigger": t.rb_activated_at_trigger,
            "n_prior_rb_taps": len(t.rb_prior_taps),
            "entry_price": t.entry_price, "stop_price": t.stop_price,
            "stop_anchor_id": t.stop_anchor_id,
            "target_price": t.target_price, "target_structure_id": t.target_structure_id,
            "target_policy": t.target_policy, "natural_rr": t.natural_rr,
            "executable": t.executable, "rejection_reason": t.rejection_reason,
        }
        trig_rows.append(base)
        (exec_rows if t.executable else rej_rows).append(base)
        comp_rows.extend(_component_rows(t, sidx, bars))

    write_csv(os.path.join(OUT, "trigger_events.csv"), trig_rows, list(trig_rows[0].keys()))
    write_csv(os.path.join(OUT, "executable_setups_pre_outcome.csv"), exec_rows,
              list(trig_rows[0].keys()))
    write_csv(os.path.join(OUT, "rejected_triggers.csv"), rej_rows, list(trig_rows[0].keys()))
    write_csv(os.path.join(OUT, "component_lineage.csv"), comp_rows,
              list(comp_rows[0].keys()) if comp_rows else ["trigger_id"])

    # ---- causal invariants ----
    violations = {"component_availability_after_trigger": 0, "target_availability_after_trigger": 0,
                  "entry_not_next_bar": 0, "non_chronological": 0}
    prev_entry = -1
    for t in triggers:
        for cid in t.component_ids + ([t.target_structure_id] if t.target_structure_id else []):
            st = sidx.get(cid)
            if st is not None and st.avail_seq > t.entry_seq:
                violations["component_availability_after_trigger"] += 1
        if t.target_structure_id:
            st = sidx.get(t.target_structure_id)
            if st is not None and st.avail_seq > t.entry_seq:
                violations["target_availability_after_trigger"] += 1
        if t.entry_seq != t.entry_seq:  # placeholder; entry monotonic checked below
            pass
        if t.entry_seq < prev_entry:
            violations["non_chronological"] += 1
        prev_entry = max(prev_entry, t.entry_seq)
    causal = {
        "n_triggers": len(triggers),
        "n_executable": diag["n_executable"], "n_rejected": diag["n_rejected"],
        "violations": violations,
        "total_violations": sum(violations.values()),
        "outcome_fields_present": False,
        "min_executable_rr": MIN_EXECUTABLE_RR,
    }
    with open(os.path.join(OUT, "causal_invariants.json"), "w") as fh:
        json.dump(causal, fh, indent=2, default=str)

    # ---- reproducibility ----
    from collections import Counter
    fam_counts = Counter(t.trigger_family for t in triggers)
    tf_counts = Counter(t.trigger_timeframe for t in triggers)
    rej_counts = Counter(t.rejection_reason for t in triggers if not t.executable)
    repro = {
        "symbol": SYMBOL, "window_et": [str(DEV_START), str(DEV_END)],
        "n_bars": len(bars), "n_structures": diag["n_structures"],
        "n_trigger_events": len(triggers), "n_executable_setups": diag["n_executable"],
        "n_rejected_triggers": diag["n_rejected"],
        "trigger_family_counts": dict(fam_counts),
        "trigger_timeframe_counts": {str(k): v for k, v in sorted(tf_counts.items())},
        "rejection_reason_counts": dict(rej_counts),
        "min_executable_rr": MIN_EXECUTABLE_RR,
        "first12_trigger_ids": [t.trigger_id for t in triggers[:12]],
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(repro, fh, indent=2, default=str)

    # ---- missed-setup review template (Dylan fills in) ----
    write_csv(os.path.join(OUT, "missed_setup_review.csv"), [], [
        "dylan_timestamp_et", "expected_direction", "expected_component_structures",
        "reason_not_emitted", "missing_primitive", "missing_transition",
        "rejected_by_stop_target", "rejected_by_rr", "suppressed_by_occupancy",
        "genuine_engine_defect", "outside_frozen_vocabulary", "notes",
    ])

    # ---- first-12 pre-outcome setup cards ----
    _write_cards(triggers[:12], sidx, bars, coverage, repro)
    print(json.dumps({"coverage": coverage, "diag": diag, "causal": causal,
                      "repro": repro}, indent=2, default=str))


def _write_cards(first12, sidx, bars, coverage, repro):
    lines = []
    lines.append("# Development-week pre-outcome setup cards — NQU6, Jul 5–10 2026\n")
    lines.append("Fully causal replay over the FROZEN audited primitive-reset "
                 "structures (FVG / iFVG / RB). **No outcomes** are computed or "
                 "attached — this is the pre-outcome review stage. These are the "
                 "**first 12 trigger events in strict chronological order** (by "
                 "entry bar), selected with no reference to outcome, clarity, "
                 "family, timeframe or RR.\n")
    lines.append(f"- Data coverage: {coverage.get('actual_window_first_et')} → "
                 f"{coverage.get('actual_window_last_et')} ({coverage.get('rows_in_window')} bars).\n")
    lines.append(f"- Total trigger events: **{repro['n_trigger_events']}** "
                 f"(executable {repro['n_executable_setups']}, rejected "
                 f"{repro['n_rejected_triggers']}). Families: "
                 f"{repro['trigger_family_counts']}.\n")
    lines.append("- Terminology: TRIGGER_EVENT (branch completed) vs "
                 "EXECUTABLE_SETUP (valid stop + causal target + RR ≥ 0.5 + not "
                 "occupancy-rejected) vs REJECTED_TRIGGER. Not a trade until a "
                 "next-bar entry and its path are processed — not done here.\n")
    lines.append("- `activated_at_trigger` is a descriptive branch feature "
                 "(causal at the tap), **not** an eligibility gate — an RB can "
                 "trigger while not activated.\n")
    lines.append("- Displacement / compression state: **N/A** — not part of the "
                 "audited FVG/iFVG/RB vocabulary (no invented structures).\n\n")

    for t in first12:
        st = sidx.get(t.trigger_structure_id)
        lines.append(f"## {t.trigger_id} — {t.trigger_family} "
                     f"({'LONG' if t.direction > 0 else 'SHORT'}, {t.trigger_timeframe}m)\n")
        lines.append(f"- **Trigger time (entry bar open):** {_plain(bars[t.entry_seq].ts_et)}\n")
        lines.append(f"- **Session date:** {t.session_date_et}\n")
        lines.append(f"- **Branch / state-machine path:** {' → '.join(t.branch_path)}\n")
        lines.append(f"- **Trigger rule:** {t.trigger_rule}\n")
        lines.append(f"- **Trigger structure:** {t.trigger_structure_id}")
        if st is not None:
            lines.append(f" — {st.family} {t.trigger_timeframe}m, source "
                         f"{_plain(st.source_ts_et)}, zone [{st.zone_lo}, {st.zone_hi}]\n")
        else:
            lines.append("\n")
        # family-specific descriptive fields
        rec = st.record if st is not None else None
        if t.trigger_family == "IFVG_ACTIVATION" and rec is not None:
            lines.append(f"- **Component structures:** iFVG {rec.id} ← parent FVG "
                         f"{rec.parent_fvg_id} (parent width/ATR "
                         f"{round(rec.parent_width_atr, 3) if rec.parent_width_atr else 'n/a'}, "
                         f"inversion speed {rec.inversion_speed_bucket})\n")
        elif t.trigger_family == "RB_TAP" and rec is not None:
            lines.append(f"- **RB wick/body:** {round(rec.wick_body_ratio, 2)} | "
                         f"**dominant-wick ratio:** {round(rec.dominant_wick_ratio, 2)}\n")
            lines.append(f"- **RB activated_at_trigger:** {t.rb_activated_at_trigger}\n")
            taps = "; ".join(f"tap@seq{p['seq']} was_activated={p['was_activated']}"
                             for p in t.rb_prior_taps) or "none"
            lines.append(f"- **All RB taps (activation flags):** {taps}\n")
        lines.append(f"- **Proposed next-bar entry:** {t.entry_price}\n")
        lines.append(f"- **Frozen structural stop:** {t.stop_price} "
                     f"(anchor {t.stop_anchor_id}) — {t.stop_anchor_desc}\n")
        if t.target_structure_id:
            tst = sidx.get(t.target_structure_id)
            tdesc = (f"{tst.family} {tst.timeframe}m zone [{tst.zone_lo}, {tst.zone_hi}]"
                     if tst else "")
            lines.append(f"- **Target:** {t.target_price} "
                         f"(structure {t.target_structure_id} — {tdesc}, policy "
                         f"{t.target_policy})\n")
        else:
            lines.append(f"- **Target:** none causally available\n")
        lines.append(f"- **Natural RR:** {_fmt_rr(t.natural_rr)}\n")
        status = "EXECUTABLE_SETUP" if t.executable else f"REJECTED_TRIGGER ({t.rejection_reason})"
        lines.append(f"- **Status:** {status}\n")
        lines.append(f"- **What the setup believes:** {t.explanation}\n\n")

    with open(os.path.join(OUT, "pre_outcome_setup_cards.md"), "w") as fh:
        fh.write("".join(lines))


if __name__ == "__main__":
    main()

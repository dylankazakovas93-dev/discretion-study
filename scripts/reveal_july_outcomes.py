"""PART A — reveal the frozen July 12-17 2026 application outcomes.

Reproduces the exact frozen application variants (observe() is deterministic,
already proven byte-identical across reruns) and scores them with the existing,
unmodified process_outcome() -- next-bar entry, effective ATR-floored stop,
genuine nearest opposing target, stop-first same-bar resolution, session/time
exit. No fingerprint, entry, stop, target, playbook match, lookback support or
entry variant is altered. This is an audit result only.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.setup_observer.observer import observe
from discretion.setup_observer.outcomes import process_outcome

SRC_DIR = os.path.join("artifacts", "multi_lookback_playbook_fixed_2026_07_12_17")
OUT = os.path.join("artifacts", "july_outcome_reveal_2026_07_12_17")
DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])
LOAD_START = pd.Timestamp("2026-06-01 00:00:00", tz=ET)
TARGET_WINDOW = 600


def wcsv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    os.makedirs(OUT, exist_ok=True)
    start_utc = LOAD_START.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(DATA_FILE, start=start_utc, end=None)
    df = df[df["symbol"] == "NQU6"].sort_values("ts_utc").drop_duplicates("ts_utc", keep="last").reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)
    df = df[et >= LOAD_START].reset_index(drop=True)
    bars = [Bar(seq=i, ts_utc=r.ts_utc, ts_et=r.ts_utc.tz_convert(ET), open=float(r.open),
                high=float(r.high), low=float(r.low), close=float(r.close), volume=int(r.volume),
                contract="NQU6", segment_id=0) for i, r in enumerate(df.itertuples(index=False))]

    _, variants, _ = observe(bars, target_window=TARGET_WINDOW)
    vby = {v.variant_id: v for v in variants}

    # ---- load the frozen selections; verify byte-identity, never alter them ----
    actionable_rows = list(csv.DictReader(open(os.path.join(SRC_DIR, "application_actionable_matches.csv"))))
    reviewed_ids = []
    with open(os.path.join(SRC_DIR, "application_setup_cards.md")) as fh:
        for line in fh:
            if line.startswith("## "):
                reviewed_ids.append(line[3:].split(" ")[0])

    def _feq(a, b):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return str(a) == str(b)

    mismatches = []
    for r in actionable_rows:
        vid = r["variant_id"]
        v = vby.get(vid)
        if v is None:
            mismatches.append((vid, "not_reproduced")); continue
        prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE")
        checks = [
            ("entry_variant", v.entry_variant, r["entry_variant"]),
            ("direction", v.direction, r["direction"]),
            ("effective_stop_price", v.effective_stop_price, r["effective_stop_price"]),
            ("target_surface", (prim.surface if prim else None), r["target_surface"]),
        ]
        for field, cur, frozen in checks:
            if not _feq(cur, frozen):
                mismatches.append((vid, field))
    integrity = {"actionable_checked": len(actionable_rows), "mismatches": mismatches,
                "byte_identical": len(mismatches) == 0}

    # ---- score the 16 reviewed setups ----
    reviewed_rows = []
    for vid in reviewed_ids:
        v = vby[vid]
        o = process_outcome(v, bars)
        reviewed_rows.append({
            "variant_id": vid, "episode_id": v.episode_id, "entry_variant": v.entry_variant,
            "direction": v.direction, "entry_price": v.entry_price,
            "target_price": (o.target_price if o else None),
            "stop_price": v.effective_stop_price,
            "exit_type": (o.exit_type if o else None), "exit_price": (o.exit_price if o else None),
            "points": (o.points if o else None), "gross_r": (o.r_multiple if o else None),
            "mfe_points": (o.mfe_points if o else None), "mae_points": (o.mae_points if o else None),
            "success": (o.success if o else None),
        })
    wcsv(os.path.join(OUT, "reviewed_16_outcomes.csv"), reviewed_rows, list(reviewed_rows[0].keys()))

    # ---- score all 131 actionable ----
    all_rows = []
    for r in actionable_rows:
        v = vby[r["variant_id"]]
        o = process_outcome(v, bars)
        modes = [r["match_prev_1_session"], r["match_prev_3_sessions"],
                r["match_prev_10_sessions"], r["match_prev_20_sessions"]]
        overall_mode = "EXACT" if "EXACT" in modes else ("REDUCED_FAMILY" if "REDUCED_FAMILY" in modes else "")
        all_rows.append({
            "variant_id": v.variant_id, "episode_id": v.episode_id, "entry_variant": v.entry_variant,
            "reaction_state": v.reaction_state, "direction": v.direction, "lane": v.lane,
            "session": v.session, "context_tf": v.context_tf, "trigger_tf": v.trigger_tf,
            "match_mode": overall_mode, "cross_lookback": r.get("cross_lookback", ""),
            "match_prev_1_session": r["match_prev_1_session"], "match_prev_3_sessions": r["match_prev_3_sessions"],
            "match_prev_10_sessions": r["match_prev_10_sessions"], "match_prev_20_sessions": r["match_prev_20_sessions"],
            "entry_price": v.entry_price, "effective_stop_price": v.effective_stop_price,
            "target_price": (o.target_price if o else None),
            "exit_type": (o.exit_type if o else None), "points": (o.points if o else None),
            "gross_r": (o.r_multiple if o else None), "mfe_points": (o.mfe_points if o else None),
            "mae_points": (o.mae_points if o else None), "success": (o.success if o else None),
        })
    wcsv(os.path.join(OUT, "all_131_actionable_outcomes.csv"), all_rows, list(all_rows[0].keys()))

    def agg(rows):
        n = len(rows)
        hits_t = sum(1 for r in rows if r["exit_type"] == "TARGET")
        hits_s = sum(1 for r in rows if r["exit_type"] == "STOP")
        hits_time = sum(1 for r in rows if r["exit_type"] in ("TIME", "DATA_END"))
        rs = [r["gross_r"] for r in rows if r["gross_r"] is not None]
        gross_pos = sum(r for r in rs if r > 0)
        gross_neg = -sum(r for r in rs if r < 0)
        pf = (gross_pos / gross_neg) if gross_neg > 0 else (float("inf") if gross_pos > 0 else None)
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        return {
            "n": n, "target_hits": hits_t, "stop_hits": hits_s, "time_exits": hits_time,
            "gross_net_r": round(sum(rs), 4) if rs else None,
            "pf": (round(pf, 4) if pf not in (None, float("inf")) else pf),
            "win_rate": round(hits_t / n, 4) if n else None,
            "avg_r": round(sum(rs) / len(rs), 4) if rs else None,
        }

    overall = agg(all_rows)

    def breakdown(key_fn):
        groups = defaultdict(list)
        for r in all_rows:
            groups[key_fn(r)].append(r)
        return {str(k): agg(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}

    breakdowns = {
        "by_prev_1": breakdown(lambda r: r["match_prev_1_session"] or "no_match"),
        "by_prev_3": breakdown(lambda r: r["match_prev_3_sessions"] or "no_match"),
        "by_prev_10": breakdown(lambda r: r["match_prev_10_sessions"] or "no_match"),
        "by_prev_20": breakdown(lambda r: r["match_prev_20_sessions"] or "no_match"),
        "by_overall_match_mode": breakdown(lambda r: r["match_mode"]),
        "by_entry_variant": breakdown(lambda r: r["entry_variant"]),
        "by_lane": breakdown(lambda r: r["lane"]),
        "by_session": breakdown(lambda r: r["session"]),
        "by_context_tf": breakdown(lambda r: r["context_tf"]),
        "by_trigger_tf": breakdown(lambda r: r["trigger_tf"]),
    }

    # max drawdown in R (chronological, treated as a diagnostic hypothesis-level sequence)
    ordered = sorted(all_rows, key=lambda r: r["variant_id"])
    eq, peak, mdd = 0.0, 0.0, 0.0
    for r in ordered:
        if r["gross_r"] is None:
            continue
        eq += r["gross_r"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)

    summary = {"overall": overall, "max_drawdown_r_diagnostic": round(mdd, 4), **breakdowns}
    with open(os.path.join(OUT, "outcome_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    with open(os.path.join(OUT, "integrity_check.json"), "w") as fh:
        json.dump(integrity, fh, indent=2, default=str)

    print(json.dumps({"integrity": integrity, "overall": overall}, indent=2, default=str))


if __name__ == "__main__":
    main()

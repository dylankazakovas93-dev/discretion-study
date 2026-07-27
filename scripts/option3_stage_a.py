"""Option 3 Stage A: baseline reproduction + variant/session ablation.

HOLDOUT: hard ingest boundary at final 2025 session. No 2026 row is loaded,
scored, or summarised anywhere in this module. See HOLDOUT_ACCESS_LOG.csv.

Every ablation is applied to the COMPLETE chronological actionable-candidate
stream and then re-run through deterministic ordering + one-global-position
occupancy, so candidates previously blocked by a removed candidate are released
and allowed to trade. Nothing is deleted from the executed-trade ledger.
"""
from __future__ import annotations
import pickle, importlib.util, sys, os, glob, csv, json
from collections import defaultdict

spec = importlib.util.spec_from_file_location("mv2", "scripts/multiyear_validation_v2.py")
_m = importlib.util.module_from_spec(spec); sys.modules["mv2"] = _m; sys.modules["__main__"] = _m
spec.loader.exec_module(_m)

CKPT = os.path.join("artifacts", "multiyear_validation_v2", "checkpoints")
OUT = os.path.join("artifacts", "option3_study")
os.makedirs(OUT, exist_ok=True)

# ---- frozen Option 3 (docs/FROZEN_MANUAL_RULE_V1.md, commit e1b468c) ----
SESSIONS = {"NY_AM", "LONDON", "NY_PM"}
VARIANTS = {"ENTRY_ON_IMMEDIATE_DISPLACEMENT", "ENTRY_ON_MINIMAL_WICK_REJECTION",
            "ENTRY_ON_STRONG_REJECTION", "ENTRY_ON_FIRST_CLOSE_OUTSIDE",
            "ENTRY_ON_NEW_FVG"}
MIN_STOP_PTS = 12.0
DEV_YEARS = (2018, 2025)          # HARD BOUNDARY -- 2026 never ingested
COSTS = (0.0, 1.0, 2.0)           # full round-trip NQ index points


def load_candidate_stream():
    """Complete chronological actionable-candidate stream, 2018-2025 only."""
    stream, dropped_2026 = [], 0
    for p in sorted(glob.glob(os.path.join(CKPT, "*.pkl"))):
        ck = pickle.load(open(p, "rb"))
        orecs = {x.gvid: x for x in ck["orecs"]}
        for v in ck["vrecs"]:
            o = orecs.get(v.gvid)
            if o is None or o.r_multiple == 0:
                continue
            # INGEST BOUNDARY: drop every non-development session before any
            # feature or performance value is computed from it.
            if not (DEV_YEARS[0] <= v.session_date.year <= DEV_YEARS[1]):
                dropped_2026 += 1
                continue
            risk = abs(o.points / o.r_multiple)
            if risk <= 0:
                continue
            stream.append({"gvid": v.gvid, "sd": v.session_date, "entry_ts": v.entry_ts,
                           "exit_ts": o.exit_ts, "fkey": v.fkey, "r": o.r_multiple,
                           "points": o.points, "risk": risk, "session": v.session,
                           "entry_variant": v.entry_variant, "direction": v.direction,
                           "exit_type": o.exit_type, "context_tf": v.context_tf,
                           "trigger_tf": v.trigger_tf, "target_family": v.target_family,
                           "target_tf": v.target_tf, "natural_rr": v.natural_rr,
                           "reaction_state": v.reaction_state, "lane": v.lane})
    stream.sort(key=lambda c: (c["entry_ts"], c["gvid"]))
    return stream, dropped_2026


def eligible(c, sessions=SESSIONS, variants=VARIANTS, min_stop=MIN_STOP_PTS):
    return (c["session"] in sessions and c["entry_variant"] in variants
            and c["risk"] >= min_stop)


def occupancy(cands):
    """Deterministic earliest-actionable, one global position. Re-run from the
    candidate stream every time -- releasing previously blocked candidates."""
    chosen, until = [], None
    for c in sorted(cands, key=lambda z: (z["entry_ts"], z["gvid"])):
        if until is not None and c["entry_ts"] < until:
            continue
        chosen.append(c); until = c["exit_ts"]
    return chosen


def r_at_cost(t, cost):
    return (t["points"] - cost) / t["risk"]


def pf(rs):
    p = sum(x for x in rs if x > 0); n = -sum(x for x in rs if x <= 0)
    return (p / n) if n > 0 else (float("inf") if p > 0 else 0.0)


def metrics(trades, label):
    if not trades:
        return None
    weeks = (trades[-1]["sd"] - trades[0]["sd"]).days / 7
    m = {"label": label, "trades": len(trades), "trades_per_week": round(len(trades) / weeks, 2)}
    for cost in COSTS:
        rs = [r_at_cost(t, cost) for t in trades]
        eq = peak = mdd = 0.0
        for x in rs:
            eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        yrs = defaultdict(float)
        for t, x in zip(trades, rs):
            yrs[t["sd"].year] += x
        tag = f"{cost:g}pt"
        m[f"pf_{tag}"] = round(pf(rs), 4)
        m[f"net_r_{tag}"] = round(sum(rs), 2)
        m[f"exp_r_{tag}"] = round(sum(rs) / len(rs), 4)
        m[f"exp_week_{tag}"] = round(sum(rs) / weeks, 4)
        m[f"mdd_{tag}"] = round(mdd, 2)
        m[f"pos_years_{tag}"] = sum(1 for y in yrs.values() if y > 0)
        m[f"by_year_{tag}"] = {y: round(v, 2) for y, v in sorted(yrs.items())}
    m["win_rate"] = round(sum(1 for t in trades if t["r"] > 0) / len(trades), 4)
    return m


if __name__ == "__main__":
    stream, dropped = load_candidate_stream()
    print(f"candidate stream (2018-2025 only): {len(stream):,}")
    print(f"rows refused by ingest boundary (non-development years): {dropped:,}")
    base_c = [c for c in stream if eligible(c)]
    base_t = occupancy(base_c)
    print(f"Option 3 actionable candidates: {len(base_c):,}  ->  executed: {len(base_t):,}")
    bm = metrics(base_t, "FROZEN_OPTION_3")
    print(json.dumps({k: v for k, v in bm.items() if not k.startswith("by_year")}, indent=2))
    pickle.dump({"stream": stream, "base_trades": base_t}, open(os.path.join(OUT, "_stream.pkl"), "wb"))
    json.dump(bm, open(os.path.join(OUT, "baseline_metrics.json"), "w"), indent=2, default=str)

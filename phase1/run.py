"""
Phase 1 driver: execute audit + all primitives, write machine-readable
ledgers (CSV + JSON) and a summary. Deterministic; no randomness.

Usage: python run.py <decompressed_csv> <original_file_for_hash>
"""
import json
import os
import sys
import pandas as pd

import core
import primitives as P

OUT = os.path.join(os.path.dirname(__file__), "outputs")
LED = os.path.join(OUT, "ledgers")


def jdefault(o):
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return str(o)


def write_ledger(df: pd.DataFrame, name: str):
    # CSV is the canonical machine-readable ledger format. JSON is emitted only
    # for compact ledgers (<= 5000 rows) to avoid multi-MB redundant duplicates.
    path_csv = os.path.join(LED, name + ".csv")
    df.to_csv(path_csv, index=False)
    if len(df) <= 5000:
        df.to_json(os.path.join(LED, name + ".json"),
                   orient="records", date_format="iso", indent=1)
    return len(df)


def main(csv_path, orig_path, extra_csvs=None, extra_origs=None):
    os.makedirs(LED, exist_ok=True)
    roll_ledger = seg_ledger = None
    if extra_csvs:
        et, audit, tf_ledgers, roll_ledger, seg_ledger = core.build_combined(
            csv_path, extra_csvs, orig_path, extra_origs)
    else:
        et, audit, tf_ledgers = core.build_all(csv_path, orig_path)

    # daily completeness note: first globex day misses 18:00-20:00 ET warm-up
    daily = tf_ledgers["daily"]
    audit["daily_candles"] = [{
        "globex_day": str(pd.Timestamp(r.bucket_open_et).date()) + "->" + str(pd.Timestamp(r.bucket_close_et).date()),
        "open_et": pd.Timestamp(r.bucket_open_et).isoformat(),
        "close_et": pd.Timestamp(r.bucket_close_et).isoformat(),
        "n_source_minutes": int(r.n_source_minutes),
        "first_source": pd.Timestamp(r.source_first_ts).isoformat(),
    } for r in daily.itertuples()]

    # persist context CSVs. The full combined frame spans 2025-2026; to keep
    # deliverables small we persist the ET-normalized minutes and the fast
    # intraday HTF candles only from 2026-07-04 (discovery-relevant), and keep
    # daily/4h/1h fully for higher-timeframe chart context.
    ctx_start = pd.Timestamp("2026-07-04", tz="America/New_York")
    et_out = et[et["ts_open_et"] >= ctx_start].copy()
    for col in ["ts_utc", "ts_open_et", "ts_close_et"]:
        et_out[col] = et_out[col].astype(str)
    et_out.to_csv(os.path.join(OUT, "nq_1m_et_normalized.csv"), index=False)
    FULL_TFS = {"1h", "4h", "daily"}
    for name, led in tf_ledgers.items():
        l2 = led.copy()
        if name not in FULL_TFS:
            l2 = l2[l2["bucket_open_et"] >= ctx_start]
        l2 = l2.copy()
        for col in l2.columns:
            if pd.api.types.is_datetime64_any_dtype(l2[col]) or l2[col].dtype == object:
                try:
                    l2[col] = l2[col].astype(str)
                except Exception:
                    pass
        l2.to_csv(os.path.join(OUT, f"htf_candles_{name}.csv"), index=False)

    counts = {}
    all_fvgs = {}
    tf_candles = {}
    for tf in core.TIMEFRAMES:
        cd = P.make_candles(tf_ledgers[tf.name], tf.name)
        tf_candles[tf.name] = cd
        fvgs = P.detect_fvgs(cd)
        all_fvgs[tf.name] = fvgs
        ifvg = P.detect_ifvg(cd, fvgs)
        # emission filters (discovery week)
        fvg_emit = fvgs[fvgs["availability_et"].apply(P.in_discovery)] if not fvgs.empty else fvgs
        ifvg_emit = ifvg[ifvg["conversion_et"].apply(P.in_discovery)] if not ifvg.empty else ifvg
        counts[f"fvg_{tf.name}"] = write_ledger(fvg_emit, f"fvg_{tf.name}")
        counts[f"ifvg_{tf.name}"] = write_ledger(ifvg_emit, f"ifvg_{tf.name}")
        rb = P.detect_rejection_blocks(cd)
        counts[f"rejection_blocks_{tf.name}"] = write_ledger(rb, f"rejection_blocks_{tf.name}")
        disp = P.detect_displacement(cd, fvgs)
        counts[f"displacement_{tf.name}"] = write_ledger(disp, f"displacement_{tf.name}")

    # liquidity references (session/1m sourced)
    liq = P.detect_liquidity(et)
    counts["liquidity"] = write_ledger(liq, "liquidity_references")

    # frozen roll schedule + continuity-segment ledgers
    if roll_ledger is not None:
        counts["roll_schedule"] = write_ledger(roll_ledger.copy(), "roll_schedule")
        counts["continuity_segments"] = write_ledger(seg_ledger.copy(), "continuity_segments")

    # per-timeframe trailing-feature validity table (discovery week)
    vt_rows = []
    for tf in core.TIMEFRAMES:
        vt_rows.extend(P.validity_table(tf_candles[tf.name]))
    vt = pd.DataFrame(vt_rows)
    write_ledger(vt, "trailing_validity_table")
    audit["trailing_validity_summary"] = json.loads(vt.to_json(orient="records", date_format="iso"))

    with open(os.path.join(OUT, "data_quality_report.json"), "w") as f:
        json.dump(audit, f, indent=2, default=jdefault)

    with open(os.path.join(OUT, "ledger_counts.json"), "w") as f:
        json.dump(counts, f, indent=2)

    print(json.dumps(counts, indent=2))
    print("\n=== trailing validity (discovery week) ===")
    print(vt.to_string(index=False))
    return audit, counts


if __name__ == "__main__":
    # usage: run.py <disc_csv> <disc_hash> [ctx_csv ctx_hash]...
    csv_path = sys.argv[1]
    orig_path = sys.argv[2]
    rest = sys.argv[3:]
    extra_csvs = rest[0::2] if rest else None
    extra_origs = rest[1::2] if rest else None
    main(csv_path, orig_path, extra_csvs, extra_origs)

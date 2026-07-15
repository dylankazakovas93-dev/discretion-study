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


def main(csv_path, orig_path):
    os.makedirs(LED, exist_ok=True)
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

    # persist the ET-normalized minute frame + HTF ledgers
    et_out = et.copy()
    for col in ["ts_utc", "ts_open_et", "ts_close_et"]:
        et_out[col] = et_out[col].astype(str)
    et_out.to_csv(os.path.join(OUT, "nq_1m_et_normalized.csv"), index=False)
    for name, led in tf_ledgers.items():
        l2 = led.copy()
        for col in l2.columns:
            if pd.api.types.is_datetime64_any_dtype(l2[col]) or l2[col].dtype == object:
                try:
                    l2[col] = l2[col].astype(str)
                except Exception:
                    pass
        l2.to_csv(os.path.join(OUT, f"htf_candles_{name}.csv"), index=False)

    with open(os.path.join(OUT, "data_quality_report.json"), "w") as f:
        json.dump(audit, f, indent=2, default=jdefault)

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

    with open(os.path.join(OUT, "ledger_counts.json"), "w") as f:
        json.dump(counts, f, indent=2)

    print(json.dumps(counts, indent=2))
    return audit, counts


if __name__ == "__main__":
    csv_path = sys.argv[1]
    orig_path = sys.argv[2]
    main(csv_path, orig_path)

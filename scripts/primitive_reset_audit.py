"""Narrow NQU6 timestamp audit for the primitive reset (spec Part 11/12).

Coded detectors only -- no chart rendering, no visual pattern selection.
Loads the literal symbol "NQU6" (not front-month-by-volume) for the
requested window, discloses exact coverage, runs the reset FVG/iFVG/RB
detectors on every governing timeframe, and writes timestamp-based CSV/JSON
artifacts so Dylan can inspect structures directly on his own chart.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, "src")

from discretion.data.loader import read_raw_csv, DATA_FILES, ET
from discretion.data.bars import Bar
from discretion.primitive_reset.timeframes import candle_series, atr_series, TIMEFRAMES, candle_ts_et
from discretion.primitive_reset.registry import ResetRegistry
from discretion.primitive_reset.fvg import detect_fvgs, size_bin, SIZE_BINS
from discretion.primitive_reset.ifvg import detect_ifvgs
from discretion.primitive_reset.rejection_block import detect_rejection_blocks

DATA_FILE = os.path.join("data", "raw", DATA_FILES["2025-2026"])
SYMBOL = "NQU6"
REQ_START_ET = pd.Timestamp("2026-07-12 18:00:00", tz=ET)
REQ_END_ET = pd.Timestamp("2026-07-17 17:59:59", tz=ET)

OUT = os.path.join("artifacts", "primitive_reset_nqu6_2026_07_12_17")


def load_symbol_bars(zst_path: str, symbol: str, start_et, end_et) -> tuple[list[Bar], dict]:
    """Load the *literal* symbol's own 1m rows -- no front-month-by-volume
    selection -- single segment (one explicit contract, no rolls)."""
    start_utc_naive = start_et.tz_convert("UTC").tz_localize(None)
    df = read_raw_csv(zst_path, start=start_utc_naive, end=None)
    df = df[df["symbol"] == symbol].copy()
    df = df.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="last")
    df = df.reset_index(drop=True)
    et = df["ts_utc"].dt.tz_convert(ET)

    coverage = {
        "requested_start_et": str(start_et), "requested_end_et": str(end_et),
        "symbol": symbol,
    }
    if df.empty:
        coverage["data_present"] = False
        return [], coverage

    full_first_et, full_last_et = et.iloc[0], et.iloc[-1]
    coverage["full_symbol_coverage_first_et"] = str(full_first_et)
    coverage["full_symbol_coverage_last_et"] = str(full_last_et)

    mask = (et >= start_et) & (et <= end_et)
    df_win = df[mask].reset_index(drop=True)
    et_win = et[mask].reset_index(drop=True)
    coverage["data_present"] = not df_win.empty
    coverage["rows_in_requested_window"] = int(len(df_win))
    if not df_win.empty:
        coverage["actual_window_first_et"] = str(et_win.iloc[0])
        coverage["actual_window_last_et"] = str(et_win.iloc[-1])
        missing_tail = end_et - et_win.iloc[-1]
        coverage["missing_at_window_end"] = str(missing_tail) if missing_tail > pd.Timedelta(0) else None
        missing_head = et_win.iloc[0] - start_et
        coverage["missing_at_window_start"] = str(missing_head) if missing_head > pd.Timedelta(0) else None
        # internal gap check (any jump > 1 minute within the window)
        gaps = []
        prev = None
        for ts in et_win:
            if prev is not None:
                delta = ts - prev
                if delta > pd.Timedelta(minutes=1):
                    gaps.append({"after": str(prev), "before": str(ts), "gap": str(delta)})
            prev = ts
        coverage["internal_gaps"] = gaps

    bars: list[Bar] = []
    for seq, row in enumerate(df_win.itertuples(index=False)):
        ts_utc = row.ts_utc
        bars.append(Bar(
            seq=seq, ts_utc=ts_utc, ts_et=ts_utc.tz_convert(ET),
            open=float(row.open), high=float(row.high), low=float(row.low),
            close=float(row.close), volume=int(row.volume),
            contract=symbol, segment_id=0,
        ))
    return bars, coverage


def _fvg_row(f):
    return {
        "id": f.id, "timeframe": f.timeframe, "direction": f.direction,
        "a_seq": f.a_seq, "b_seq": f.b_seq, "c_seq": f.c_seq,
        "a_ts_et": f.a_ts, "b_ts_et": f.b_ts, "c_ts_et": f.c_ts,
        "a_open": f.a_ohlc[0], "a_high": f.a_ohlc[1], "a_low": f.a_ohlc[2], "a_close": f.a_ohlc[3],
        "b_open": f.b_ohlc[0], "b_high": f.b_ohlc[1], "b_low": f.b_ohlc[2], "b_close": f.b_ohlc[3],
        "c_open": f.c_ohlc[0], "c_high": f.c_ohlc[1], "c_low": f.c_ohlc[2], "c_close": f.c_ohlc[3],
        "a_colour": f.a_colour, "b_colour": f.b_colour, "c_colour": f.c_colour,
        "zone_lo": f.lo, "zone_hi": f.hi,
        "width_points": f.width_points, "width_ticks": f.width_ticks,
        "atr_at_c_close": f.atr_at_c_close, "width_atr": f.width_atr, "size_bin": f.size_bin,
        "formation_ts_et": f.formation_ts,
        "first_touch_ts_et": f.first_touch_ts, "midpoint_ts_et": f.midpoint_ts,
        "full_fill_ts_et": f.full_fill_ts, "inversion_ts_et": f.inversion_ts,
        "expiry_ts_et": f.expiry_ts, "deactivation_reason": f.deactivation_reason,
        "child_ifvg_id": f.child_ifvg_id,
    }


def _ifvg_row(iv):
    return {
        "id": iv.id, "parent_fvg_id": iv.parent_fvg_id, "timeframe": iv.timeframe,
        "parent_direction": iv.parent_direction, "child_direction": iv.child_direction,
        "parent_formation_ts_et": iv.parent_formation_ts,
        "parent_width_points": iv.parent_width_points, "parent_width_atr": iv.parent_width_atr,
        "parent_first_touch_ts_et": iv.parent_first_touch_ts,
        "inversion_ts_et": iv.inversion_ts,
        "inversion_open": iv.inversion_ohlc[0], "inversion_high": iv.inversion_ohlc[1],
        "inversion_low": iv.inversion_ohlc[2], "inversion_close": iv.inversion_ohlc[3],
        "close_through_boundary": iv.close_through_boundary,
        "atr_at_inversion": iv.atr_at_inversion,
        "inversion_body_atr": iv.inversion_body_atr, "inversion_range_atr": iv.inversion_range_atr,
        "bars_from_formation_to_inversion": iv.bars_from_formation_to_inversion,
        "bars_from_first_touch_to_inversion": iv.bars_from_first_touch_to_inversion,
        "inversion_speed_bucket": iv.inversion_speed_bucket,
        "max_penetration_before_inversion": iv.max_penetration_before_inversion,
        "distance_through_zone": iv.distance_through_zone,
        "distance_through_zone_over_width": iv.distance_through_zone_over_width,
        "n_scraping_candles": iv.n_scraping_candles, "avg_scraping_body": iv.avg_scraping_body,
        "activation_ts_et": iv.activation_ts, "expiry_ts_et": iv.expiry_ts,
        "deactivation_reason": iv.deactivation_reason,
    }


def _rb_row(r):
    return {
        "id": r.id, "timeframe": r.timeframe, "direction": r.direction,
        "source_seq": r.source_seq, "source_ts_et": r.source_ts,
        "source_open": r.source_ohlc[0], "source_high": r.source_ohlc[1],
        "source_low": r.source_ohlc[2], "source_close": r.source_ohlc[3],
        "relevant_wick_length": r.relevant_wick_length, "real_body_length": r.real_body_length,
        "body_was_zero": r.body_was_zero, "total_range": r.total_range,
        "wick_body_ratio": r.wick_body_ratio, "wick_range_ratio": r.wick_range_ratio,
        "atr_at_source_close": r.atr_at_source_close,
        "zone_lo": r.zone_lo, "zone_hi": r.zone_hi,
        "mfe_after_1": r.mfe_after_1, "mfe_after_2": r.mfe_after_2, "mfe_after_3": r.mfe_after_3,
        "mfe_after_1_atr": r.mfe_after_1_atr, "mfe_after_2_atr": r.mfe_after_2_atr,
        "mfe_after_3_atr": r.mfe_after_3_atr,
        "confirming_candle_number": r.confirming_candle_number,
        "confirmed": r.confirmed, "rejection_reason": r.rejection_reason,
        "activation_ts_et": r.activation_ts, "first_tap_ts_et": r.first_tap_ts,
        "max_penetration_after_activation": r.max_penetration_after_activation,
        "deactivation_ts_et": r.deactivation_ts, "deactivation_reason_final": r.deactivation_reason,
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    bars, coverage = load_symbol_bars(DATA_FILE, SYMBOL, REQ_START_ET, REQ_END_ET)
    with open(os.path.join(OUT, "data_coverage.json"), "w") as fh:
        json.dump(coverage, fh, indent=2, default=str)
    print("data coverage:", json.dumps(coverage, indent=2, default=str))
    if not bars:
        print("NO DATA -- aborting audit")
        return

    all_fvgs, all_ifvgs, all_rbs = [], [], []
    per_tf_counts = {}
    for tf in TIMEFRAMES:
        reg = ResetRegistry()
        series = candle_series(bars, tf)
        atr = atr_series(series)
        fvgs = detect_fvgs(bars, tf, reg)
        ifvgs = detect_ifvgs(bars, tf, fvgs, atr, series, reg)
        rbs = detect_rejection_blocks(bars, tf, series, atr, reg)
        all_fvgs += fvgs
        all_ifvgs += ifvgs
        all_rbs += rbs
        per_tf_counts[tf] = {
            "n_completed_candles": len(series), "n_fvgs": len(fvgs),
            "n_ifvgs": len(ifvgs), "n_rb_candidates": len(rbs),
            "n_rb_confirmed": sum(1 for r in rbs if r.confirmed),
        }

    import csv as csvmod

    def write_csv(path, rows, fieldnames):
        with open(path, "w", newline="") as fh:
            w = csvmod.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)

    fvg_rows = [_fvg_row(f) for f in all_fvgs]
    write_csv(os.path.join(OUT, "fvg_candidates.csv"), fvg_rows,
              list(fvg_rows[0].keys()) if fvg_rows else
              ["id", "timeframe", "direction"])

    ifvg_rows = [_ifvg_row(i) for i in all_ifvgs]
    write_csv(os.path.join(OUT, "ifvg_candidates.csv"), ifvg_rows,
              list(ifvg_rows[0].keys()) if ifvg_rows else ["id", "parent_fvg_id"])

    rb_confirmed_rows = [_rb_row(r) for r in all_rbs if r.confirmed]
    rb_rejected_rows = [_rb_row(r) for r in all_rbs if not r.confirmed]
    write_csv(os.path.join(OUT, "rb_confirmed_candidates.csv"), rb_confirmed_rows,
              list(rb_confirmed_rows[0].keys()) if rb_confirmed_rows else ["id"])
    write_csv(os.path.join(OUT, "rb_rejected_candidates.csv"), rb_rejected_rows,
              list(rb_rejected_rows[0].keys()) if rb_rejected_rows else ["id"])

    # ATR-bin summary (Part 2)
    bin_rows = []
    for tf in TIMEFRAMES:
        tf_fvgs = [f for f in all_fvgs if f.timeframe == tf]
        for label, _, _ in SIZE_BINS:
            n = sum(1 for f in tf_fvgs if f.size_bin == label)
            bin_rows.append({"timeframe": tf, "size_bin": label, "count": n})
        n_none = sum(1 for f in tf_fvgs if f.size_bin is None)
        bin_rows.append({"timeframe": tf, "size_bin": "no_atr_available", "count": n_none})
    write_csv(os.path.join(OUT, "fvg_atr_bin_summary.csv"), bin_rows,
              ["timeframe", "size_bin", "count"])

    # structure lifecycle events (flattened, one row per notable timestamp)
    lifecycle_rows = []
    for f in all_fvgs:
        for kind, ts in [
            ("FORMED", f.formation_ts), ("FIRST_TOUCH", f.first_touch_ts),
            ("MIDPOINT", f.midpoint_ts), ("FULL_FILL", f.full_fill_ts),
            ("INVERSION", f.inversion_ts), ("EXPIRY", f.expiry_ts),
        ]:
            if ts is not None:
                lifecycle_rows.append({"family": "FVG", "id": f.id, "timeframe": f.timeframe,
                                        "event": kind, "ts_et": ts,
                                        "deactivation_reason": f.deactivation_reason})
    for iv in all_ifvgs:
        for kind, ts in [
            ("ACTIVATED", iv.activation_ts), ("FIRST_TOUCH", iv.first_touch_ts),
            ("EXPIRY", iv.expiry_ts),
        ]:
            if ts is not None:
                lifecycle_rows.append({"family": "IFVG", "id": iv.id, "timeframe": iv.timeframe,
                                        "event": kind, "ts_et": ts,
                                        "deactivation_reason": iv.deactivation_reason})
    for r in all_rbs:
        for kind, ts in [
            ("SOURCE", r.source_ts), ("ACTIVATED", r.activation_ts),
            ("FIRST_TAP", r.first_tap_ts), ("DEACTIVATED", r.deactivation_ts),
        ]:
            if ts is not None:
                lifecycle_rows.append({"family": "RB", "id": r.id, "timeframe": r.timeframe,
                                        "event": kind, "ts_et": ts,
                                        "deactivation_reason": r.deactivation_reason})
    write_csv(os.path.join(OUT, "structure_lifecycle_events.csv"), lifecycle_rows,
              ["family", "id", "timeframe", "event", "ts_et", "deactivation_reason"])

    # representative examples
    def pick_fvg_examples(fvgs, n=5):
        by_bin = {}
        for f in fvgs:
            by_bin.setdefault(f.size_bin, []).append(f)
        out = []
        for label, _, _ in SIZE_BINS:
            if label in by_bin and by_bin[label]:
                out.append(by_bin[label][0])
            if len(out) >= n:
                break
        return out[:n]

    def pick_ifvg_examples(ifvgs, n=5):
        by_speed = {}
        for iv in ifvgs:
            by_speed.setdefault(iv.inversion_speed_bucket, []).append(iv)
        out = []
        for bucket in ("1_candles", "2_candles", "3_candles", "4_candles", "5plus_candles"):
            if bucket in by_speed and by_speed[bucket]:
                out.append(by_speed[bucket][0])
            if len(out) >= n:
                break
        return out[:n]

    RB_RATIO_BINS = ((0.20, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, float("inf")))

    def pick_rb_confirmed(rbs, n=5):
        # Spread across wick/body ratio bins (not just the extreme near-doji
        # spikes that dominate a plain sort-by-ratio, since eff_body floors
        # at one tick and inflates ratios for tiny-bodied candles).
        confirmed = [r for r in rbs if r.confirmed]
        out = []
        seen_tf = set()
        for lo, hi in RB_RATIO_BINS:
            bucket = [r for r in confirmed if lo <= (r.wick_body_ratio or 0) < hi]
            bucket.sort(key=lambda r: r.timeframe not in seen_tf, reverse=True)
            if bucket:
                out.append(bucket[0])
                seen_tf.add(bucket[0].timeframe)
            if len(out) >= n:
                break
        return out[:n]

    def pick_rb_rejected(rbs, n=5):
        rejected = [r for r in rbs if not r.confirmed]
        by_reason = {}
        for r in rejected:
            by_reason.setdefault(r.rejection_reason, []).append(r)
        out = []
        for reason, items in by_reason.items():
            if items:
                out.append(items[0])
            if len(out) >= n:
                break
        return out[:n]

    fvg_examples = pick_fvg_examples(all_fvgs)
    ifvg_examples = pick_ifvg_examples(all_ifvgs)
    rb_confirmed_examples = pick_rb_confirmed(all_rbs)
    rb_rejected_examples = pick_rb_rejected(all_rbs)

    n_fvg_missing_atr = sum(1 for f in all_fvgs if f.atr_at_c_close is None)

    reproducibility = {
        "data_file": DATA_FILE, "symbol": SYMBOL,
        "requested_window_et": [str(REQ_START_ET), str(REQ_END_ET)],
        "governing_timeframes": list(TIMEFRAMES),
        "per_timeframe_counts": per_tf_counts,
        "n_fvg_total": len(all_fvgs), "n_ifvg_total": len(all_ifvgs),
        "n_rb_candidates_total": len(all_rbs),
        "n_rb_confirmed_total": sum(1 for r in all_rbs if r.confirmed),
        "n_rb_rejected_total": sum(1 for r in all_rbs if not r.confirmed),
        "n_fvg_examples_provided": len(fvg_examples),
        "n_ifvg_examples_provided": len(ifvg_examples),
        "n_rb_confirmed_examples_provided": len(rb_confirmed_examples),
        "n_rb_rejected_examples_provided": len(rb_rejected_examples),
    }
    with open(os.path.join(OUT, "reproducibility.json"), "w") as fh:
        json.dump(reproducibility, fh, indent=2, default=str)

    print(json.dumps(reproducibility, indent=2, default=str))

    return {
        "coverage": coverage, "per_tf_counts": per_tf_counts,
        "fvg_examples": fvg_examples, "ifvg_examples": ifvg_examples,
        "rb_confirmed_examples": rb_confirmed_examples,
        "rb_rejected_examples": rb_rejected_examples,
        "n_fvg_missing_atr": n_fvg_missing_atr,
    }


if __name__ == "__main__":
    main()

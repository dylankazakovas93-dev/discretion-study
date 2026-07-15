"""
Phase 1 core: deterministic loader, data audit, timezone conversion, and
causal higher-timeframe aggregation for the NQ 1-minute OHLCV research trial.

PARAMETER VERSION: phase1-v1.0.0

Frozen conventions (see task specification):
  * Instrument: NQ front-month outright (selected by total traded volume).
  * IANA timezone: America/New_York (DST-aware).
  * Databento ohlcv-1m ts_event marks the OPENING (start) time of the bar's
    1-minute interval. A bar labeled 09:30 covers [09:30:00, 09:31:00) ET and
    becomes AVAILABLE (complete) at 09:31:00 ET (label + 1 minute).
  * Globex trading day: 18:00 ET -> 17:00 ET next calendar day.
  * Overnight: 18:00-09:29 ET.  RTH: 09:30-16:00 ET.
  * HTF boundaries are fixed ET clock boundaries; a HTF candle is available
    only when its complete interval has ended. No synthetic maintenance bars.
"""

import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

PARAM_VERSION = "phase1-v1.0.0"
TZ = "America/New_York"
INSTRUMENT_LABEL = "NQ (front-month outright)"

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw(csv_path: str) -> pd.DataFrame:
    """Load the raw decompressed CSV exactly as delivered (no repair)."""
    df = pd.read_csv(csv_path)
    return df


def select_front_month(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Select the outright front-month contract by total traded volume.

    Calendar spreads (symbols containing '-') are excluded from the study
    instrument; the outright with the greatest total volume is the front month.
    """
    outrights = df[~df["symbol"].str.contains("-", na=False)].copy()
    vol_by_symbol = outrights.groupby("symbol")["volume"].sum().sort_values(ascending=False)
    front = vol_by_symbol.index[0]
    sel = df[df["symbol"] == front].copy()
    info = {
        "selected_symbol": front,
        "selected_instrument_id": int(sel["instrument_id"].iloc[0]),
        "volume_by_symbol": {k: int(v) for k, v in df.groupby("symbol")["volume"].sum().items()},
        "outright_volume_ranking": {k: int(v) for k, v in vol_by_symbol.items()},
    }
    return sel, info


# ---------------------------------------------------------------------------
# Timezone & time labelling
# ---------------------------------------------------------------------------

def to_et(df: pd.DataFrame) -> pd.DataFrame:
    """Parse ts_event (UTC) and add America/New_York wall-clock columns.

    ts_open_et  : bar opening (interval start) in ET (tz-aware)
    ts_close_et : bar closing (interval end = availability) in ET
    """
    out = df.copy()
    ts = pd.to_datetime(out["ts_event"], utc=True, format="ISO8601")
    out["ts_utc"] = ts
    out["ts_open_et"] = ts.dt.tz_convert(TZ)
    out["ts_close_et"] = out["ts_open_et"] + pd.Timedelta(minutes=1)
    out = out.sort_values(["ts_open_et"]).reset_index(drop=True)
    return out


def et_session_tag(ts_open_et: pd.Series) -> pd.DataFrame:
    """Assign Globex trading-day date and session (overnight/rth/maintenance).

    Globex day D runs 18:00 ET (day D-1... labelled by the CME date) through
    17:00 ET. We label a bar's globex_day as the CME trading date:
      * bars with ET time >= 18:00 belong to the NEXT calendar day's Globex day.
      * bars with ET time < 17:00 belong to the current calendar day's Globex day.
      * 17:00-17:59 ET is the daily maintenance break (no RTH/ON classification).
    Session:
      * overnight : 18:00-09:29 ET
      * rth       : 09:30-16:00 ET  (through 15:59 open; 16:00 bar is the close)
      * maintenance/other otherwise
    """
    t = ts_open_et.dt.time
    hour = ts_open_et.dt.hour
    minute = ts_open_et.dt.minute
    date = ts_open_et.dt.normalize()

    # Globex day date
    globex_day = date.copy()
    is_evening = hour >= 18
    globex_day = globex_day.where(~is_evening, date + pd.Timedelta(days=1))
    # bars 17:00-17:59 belong to no globex day cleanly (maintenance); keep the
    # calendar date's globex day for reference but tag session as maintenance.

    minutes_of_day = hour * 60 + minute
    # overnight: [18:00, 24:00) OR [00:00, 09:30)
    overnight = (minutes_of_day >= 18 * 60) | (minutes_of_day < 9 * 60 + 30)
    # rth: [09:30, 16:00)  -- 16:00 open bar is the closing minute of RTH
    rth = (minutes_of_day >= 9 * 60 + 30) & (minutes_of_day < 16 * 60)
    # rth close bar (16:00) treated as RTH terminal minute
    rth_close = minutes_of_day == 16 * 60
    # maintenance: [17:00, 18:00)
    maintenance = (minutes_of_day >= 17 * 60) & (minutes_of_day < 18 * 60)

    session = pd.Series("post_close", index=ts_open_et.index, dtype=object)
    session[overnight] = "overnight"
    session[rth] = "rth"
    session[rth_close] = "rth"  # 16:00 minute included as RTH's last minute
    session[maintenance] = "maintenance"

    return pd.DataFrame({
        "globex_day": globex_day.dt.date.astype(str),
        "session": session,
        "minutes_of_day": minutes_of_day,
    }, index=ts_open_et.index)


# ---------------------------------------------------------------------------
# Data audit
# ---------------------------------------------------------------------------

def data_audit(raw: pd.DataFrame, sel_et: pd.DataFrame, file_path: str) -> dict:
    """Produce the full data-quality report (no repair performed)."""
    rep = {}
    rep["file_path"] = file_path
    rep["file_sha256"] = sha256_file(file_path)
    rep["raw_columns"] = list(raw.columns)
    rep["raw_row_count"] = int(len(raw))

    # timestamp facts (on selected instrument, ET)
    rep["timestamp_timezone_source"] = "UTC (ts_event, ISO8601 'Z')"
    rep["timestamp_marks"] = ("bar OPENING (interval start); Databento ohlcv-1m "
                              "convention. Availability = open + 1 minute.")
    rep["converted_timezone"] = TZ

    et = sel_et
    rep["selected_row_count"] = int(len(et))
    rep["first_ts_utc"] = str(et["ts_utc"].min())
    rep["last_ts_utc"] = str(et["ts_utc"].max())
    rep["first_ts_open_et"] = str(et["ts_open_et"].min())
    rep["last_ts_open_et"] = str(et["ts_open_et"].max())

    # duplicates on the selected instrument (by open timestamp)
    dup_mask = et["ts_open_et"].duplicated(keep=False)
    rep["duplicate_timestamp_count"] = int(dup_mask.sum())
    rep["duplicate_timestamps"] = [str(x) for x in et.loc[dup_mask, "ts_open_et"].unique()][:50]

    # missing intervals: expected 1-minute grid from first to last open
    full_index = pd.date_range(et["ts_open_et"].min(), et["ts_open_et"].max(),
                               freq="1min", tz=TZ)
    present = pd.DatetimeIndex(et["ts_open_et"].unique())
    missing = full_index.difference(present)
    rep["expected_minutes_full_grid"] = int(len(full_index))
    rep["present_unique_minutes"] = int(len(present))
    rep["missing_interval_count_full_grid"] = int(len(missing))

    # Classify missing minutes: maintenance (17:00-17:59) vs weekend vs other
    def classify_gap(ix):
        mm = ix.hour * 60 + ix.minute
        dow = ix.dayofweek  # Mon=0
        maint = (mm >= 17 * 60) & (mm < 18 * 60)
        # weekend gap: Fri 17:00 -> Sun 18:00
        weekend = ((dow == 4) & (mm >= 17 * 60)) | (dow == 5) | ((dow == 6) & (mm < 18 * 60))
        return maint, weekend

    maint_mask, weekend_mask = classify_gap(missing)
    other = missing[~(maint_mask | weekend_mask)]
    rep["missing_maintenance_minutes"] = int(maint_mask.sum())
    rep["missing_weekend_minutes"] = int(weekend_mask.sum())
    rep["missing_other_minutes"] = int(len(other))
    rep["missing_other_examples"] = [str(x) for x in other[:50]]

    # malformed OHLCV
    o, h, l, c, v = (et["open"], et["high"], et["low"], et["close"], et["volume"])
    nan_rows = et[[ "open","high","low","close","volume"]].isna().any(axis=1)
    rep["nan_ohlcv_row_count"] = int(nan_rows.sum())
    nonpos_vol = v <= 0
    rep["nonpositive_volume_count"] = int(nonpos_vol.sum())
    rep["nonpositive_volume_examples"] = [str(x) for x in et.loc[nonpos_vol, "ts_open_et"][:50]]

    hi_viol = h < np.maximum(o, c)
    lo_viol = l > np.minimum(o, c)
    hl_viol = h < l
    rep["high_lt_max_oc_count"] = int(hi_viol.sum())
    rep["low_gt_min_oc_count"] = int(lo_viol.sum())
    rep["high_lt_low_count"] = int(hl_viol.sum())
    rep["high_lt_max_oc_examples"] = [str(x) for x in et.loc[hi_viol, "ts_open_et"][:50]]
    rep["low_gt_min_oc_examples"] = [str(x) for x in et.loc[lo_viol, "ts_open_et"][:50]]

    # warm-up requirement check
    discovery_start = pd.Timestamp("2026-07-06", tz=TZ)
    pre = et[et["ts_open_et"] < discovery_start]
    rep["warmup_rows_before_2026_07_06_ET"] = int(len(pre))
    rep["warmup_sessions_before_discovery"] = int(pre["globex_day"].nunique()) if len(pre) else 0
    rep["warmup_requirement_met"] = bool(rep["warmup_sessions_before_discovery"] >= 40)

    return rep


# ---------------------------------------------------------------------------
# Higher-timeframe aggregation (causal, fixed ET clock boundaries)
# ---------------------------------------------------------------------------

@dataclass
class TF:
    name: str
    minutes: int | None  # None for daily (calendar Globex day)


TIMEFRAMES = [
    TF("1m", 1),
    TF("5m", 5),
    TF("15m", 15),
    TF("30m", 30),
    TF("1h", 60),
    TF("4h", 240),
    TF("daily", None),
]


def _bucket_start_intraday(ts_open_et: pd.Timestamp, minutes: int) -> pd.Timestamp:
    """Fixed ET clock bucket start for an intraday timeframe.

    5/15/30/60: anchored at midnight ET. 240 (4h): boundaries at
    00,04,08,12,16,20 ET (also a midnight-anchored 4-hour grid).
    """
    midnight = ts_open_et.normalize()
    mins_since_midnight = (ts_open_et - midnight).total_seconds() / 60.0
    bstart_min = int(mins_since_midnight // minutes) * minutes
    return midnight + pd.Timedelta(minutes=bstart_min)


def aggregate_tf(min_bars: pd.DataFrame, tf: TF) -> pd.DataFrame:
    """Aggregate completed 1-minute bars into a completed-HTF-candle ledger.

    Returns one row per COMPLETE higher-timeframe candle with:
      tf, bucket_open_et, bucket_close_et (exclusive end = availability),
      open, high, low, close, volume, n_source_minutes, source_first_ts,
      source_last_ts, complete (all expected minutes present?).

    A candle is emitted only if at least one source minute exists in the
    bucket. 'complete' flags whether the bucket's full theoretical minute
    count was present (maintenance/weekend minutes are legitimately absent,
    so completeness is judged against the SESSION-VALID minute grid, not raw).
    Availability timestamp = bucket_close_et (interval end).
    """
    b = min_bars.copy()
    if tf.name == "1m":
        b["bucket_open_et"] = b["ts_open_et"]
        b["bucket_close_et"] = b["ts_close_et"]
        out = b[["bucket_open_et", "bucket_close_et", "open", "high", "low",
                 "close", "volume"]].copy()
        out.insert(0, "tf", tf.name)
        out["n_source_minutes"] = 1
        out["source_first_ts"] = b["ts_open_et"]
        out["source_last_ts"] = b["ts_open_et"]
        out["availability_et"] = b["ts_close_et"]
        out["complete"] = True
        return out.reset_index(drop=True)

    if tf.name == "daily":
        # Globex day already tagged; a daily candle covers 18:00 ET -> 17:00 ET.
        # Exclude maintenance minutes (they are outside the OHLC day per spec:
        # 18:00-17:00 spans overnight+rth; the 17:00-18:00 break is the gap
        # BETWEEN days). Group by globex_day but only session in overnight/rth.
        gb = b[b["session"].isin(["overnight", "rth"])].copy()
        grp = gb.groupby("globex_day", sort=True)
        rows = []
        for day, g in grp:
            g = g.sort_values("ts_open_et")
            # availability = end of the RTH/overnight span = last source close,
            # but formally the Globex day ends at 17:00 ET of the calendar day
            # equal to `day`.
            day_date = pd.Timestamp(day, tz=TZ)
            bucket_open = day_date - pd.Timedelta(days=1) + pd.Timedelta(hours=18)
            bucket_close = day_date + pd.Timedelta(hours=17)
            rows.append({
                "tf": "daily",
                "bucket_open_et": bucket_open,
                "bucket_close_et": bucket_close,
                "open": g["open"].iloc[0],
                "high": g["high"].max(),
                "low": g["low"].min(),
                "close": g["close"].iloc[-1],
                "volume": g["volume"].sum(),
                "n_source_minutes": len(g),
                "source_first_ts": g["ts_open_et"].iloc[0],
                "source_last_ts": g["ts_open_et"].iloc[-1],
                "availability_et": bucket_close,
                "complete": None,  # completeness judged externally
            })
        return pd.DataFrame(rows).reset_index(drop=True)

    # intraday HTF
    starts = b["ts_open_et"].apply(lambda t: _bucket_start_intraday(t, tf.minutes))
    b["bucket_open_et"] = starts
    b["bucket_close_et"] = b["bucket_open_et"] + pd.Timedelta(minutes=tf.minutes)
    rows = []
    for bstart, g in b.groupby("bucket_open_et", sort=True):
        g = g.sort_values("ts_open_et")
        bclose = bstart + pd.Timedelta(minutes=tf.minutes)
        rows.append({
            "tf": tf.name,
            "bucket_open_et": bstart,
            "bucket_close_et": bclose,
            "open": g["open"].iloc[0],
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].iloc[-1],
            "volume": g["volume"].sum(),
            "n_source_minutes": len(g),
            "source_first_ts": g["ts_open_et"].iloc[0],
            "source_last_ts": g["ts_open_et"].iloc[-1],
            "availability_et": bclose,
            "complete": len(g) == tf.minutes,
        })
    return pd.DataFrame(rows).reset_index(drop=True)


def build_all(csv_path: str, file_path_for_hash: str):
    raw = load_raw(csv_path)
    sel, sel_info = select_front_month(raw)
    et = to_et(sel)
    tags = et_session_tag(et["ts_open_et"])
    et = pd.concat([et, tags], axis=1)
    audit = data_audit(raw, et, file_path_for_hash)
    audit.update({"instrument_selection": sel_info})
    tf_ledgers = {tf.name: aggregate_tf(et, tf) for tf in TIMEFRAMES}
    return et, audit, tf_ledgers


if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
    orig = sys.argv[2] if len(sys.argv) > 2 else csv
    et, audit, tfl = build_all(csv, orig)
    print(json.dumps(audit, indent=2, default=str))
    for k, v in tfl.items():
        print(k, len(v), "candles")

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


def _globex_day_series(et_ts: pd.Series) -> pd.Series:
    """Globex trading-day date (string) for an ET timestamp series."""
    h = et_ts.dt.hour
    date = et_ts.dt.normalize()
    gday = np.where(h >= 18, (date + pd.Timedelta(days=1)).dt.date, date.dt.date)
    return pd.Series(gday.astype(str), index=et_ts.index)


_MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}  # NQ quarterly cycle


def _third_friday(year: int, month: int):
    import datetime as _dt
    d = _dt.date(year, month, 1)
    offset = (4 - d.weekday()) % 7          # weekday: Mon=0 .. Fri=4
    return d + _dt.timedelta(days=offset + 14)


def roll_cutoff(year: int, month: int) -> pd.Timestamp:
    """FROZEN, predetermined quarterly roll cutoff: the Globex session open
    (18:00 ET) on the MONDAY of the week containing the third-Friday expiry of
    the given quarter. Independent of volume. This is the instant we roll OUT of
    that quarter's contract into the next quarter's contract."""
    import datetime as _dt
    tf = _third_friday(year, month)
    monday = tf - _dt.timedelta(days=4)     # Friday - 4 = Monday of that week
    return pd.Timestamp(monday.year, monday.month, monday.day, 18, 0, tz=TZ)


def _quarter_cycle(start_year=2024, end_year=2027):
    q = []
    for y in range(start_year, end_year + 1):
        for m in (3, 6, 9, 12):
            q.append((y, m, f"NQ{_MONTH_CODE[m]}{str(y)[-1]}"))
    return q


def roll_schedule(min_ts: pd.Timestamp, max_ts: pd.Timestamp) -> pd.DataFrame:
    """Frozen roll schedule covering [min_ts, max_ts]: for each quarter, the
    contract that is front and the exact cutoff at which it rolls out."""
    cyc = _quarter_cycle(min_ts.year - 1, max_ts.year + 1)
    rows = []
    for (y, m, contract) in cyc:
        cutoff = roll_cutoff(y, m)          # roll OUT of `contract` here
        rows.append({"expiry_year": y, "expiry_month": m, "contract": contract,
                     "third_friday": str(_third_friday(y, m)),
                     "roll_out_cutoff_et": cutoff,
                     "roll_out_cutoff_utc": cutoff.tz_convert("UTC")})
    df = pd.DataFrame(rows).sort_values("roll_out_cutoff_et").reset_index(drop=True)
    df["rolls_into"] = df["contract"].shift(-1)
    df["instrument"] = "NQ"
    df["param_version"] = PARAM_VERSION
    df["rule"] = "Globex open (18:00 ET) on the Monday of the third-Friday expiry week"
    return df[(df["roll_out_cutoff_et"] >= min_ts - pd.Timedelta(days=120)) &
              (df["roll_out_cutoff_et"] <= max_ts + pd.Timedelta(days=120))].reset_index(drop=True)


def frozen_front_contract(et_ts: pd.Series, sched: pd.DataFrame) -> pd.Series:
    """Front contract per bar by FROZEN cutoffs: the contract of the earliest
    quarter whose roll-out cutoff is strictly after the bar's open time."""
    cuts = sched["roll_out_cutoff_et"].to_numpy()
    contracts = sched["contract"].to_numpy()
    tvals = et_ts.to_numpy()
    # for each t, first index with cutoff > t
    idx = np.array([np.searchsorted(cuts, t, side="right") for t in tvals])
    idx = np.clip(idx, 0, len(contracts) - 1)
    return pd.Series(contracts[idx], index=et_ts.index)


def frozen_roll_selection(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select the front-month contract per bar by the FROZEN quarterly roll
    cutoffs (not volume). Returns (continuous_1m_rows, roll_schedule_ledger).
    Volumes around each cutoff are recorded for transparency only; they do NOT
    drive the decision."""
    r = raw.copy()
    ts = pd.to_datetime(r["ts_event"], utc=True, format="ISO8601")
    r["ts_utc"] = ts
    r["_et"] = ts.dt.tz_convert(TZ)
    out = r[~r["symbol"].str.contains("-", na=False)].copy()  # outrights only
    out["gday"] = _globex_day_series(out["_et"])
    sched = roll_schedule(out["_et"].min(), out["_et"].max())
    out["selected"] = frozen_front_contract(out["_et"], sched)
    sel_df = out[out["symbol"] == out["selected"]].copy()

    # annotate the schedule with the observed pre/post-cutoff session volumes
    vol = out.groupby(["gday", "symbol"])["volume"].sum()
    def vnear(cut, contract):
        d = (cut - pd.Timedelta(days=1)).date().isoformat()
        try:
            return int(vol.get((d, contract), 0))
        except Exception:
            return 0
    sched = sched.copy()
    sched["ref_vol_from_before"] = [vnear(c, fr) for c, fr in
                                    zip(sched["roll_out_cutoff_et"], sched["contract"])]
    sched["ref_vol_into_before"] = [vnear(c, to) if isinstance(to, str) else 0 for c, to in
                                    zip(sched["roll_out_cutoff_et"], sched["rolls_into"])]
    return sel_df, sched


def _gap_is_calendar(a: pd.Timestamp, b: pd.Timestamp) -> bool:
    """True if every missing minute strictly between a and b is non-tradeable
    (daily maintenance 17:00-18:00 ET, or the weekend Fri 17:00 -> Sun 18:00)."""
    rng = pd.date_range(a + pd.Timedelta(minutes=1), b - pd.Timedelta(minutes=1),
                        freq="1min", tz=TZ)
    if len(rng) == 0:
        return True
    mm = rng.hour * 60 + rng.minute
    dow = rng.dayofweek
    maint = (mm >= 17 * 60) & (mm < 18 * 60)
    weekend = ((dow == 4) & (mm >= 17 * 60)) | (dow == 5) | ((dow == 6) & (mm < 18 * 60))
    return bool((maint | weekend).all())


DATA_GAP_MAX_DAYS = 4.0  # a gap longer than this is a genuine data outage (a
                         # real discontinuity). Weekends, daily maintenance, and
                         # US market holidays / early closes are all shorter, so
                         # they are scheduled closures -- NOT breaks. This makes
                         # scale-invariant normalization continuous through
                         # scheduled closures without needing a holiday calendar.


def assign_segments(sel_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign TWO segment ids per bar:

    * segment_id (ABSOLUTE): resets at every FROZEN contract roll and at every
      genuine data outage (> DATA_GAP_MAX_DAYS). Absolute structures (FVGs,
      liquidity levels, rejection zones, displacement legs) are confined to one
      absolute segment -- NO absolute structure survives a roll.
    * norm_segment_id (SCALE-INVARIANT): resets ONLY at a genuine data outage,
      NOT at a contract roll. Trailing size percentiles (scale-invariant)
      continue ACROSS contracts, breaking only at real discontinuities.

    Every absolute segment lies within exactly one normalization segment.
    Returns (frame_with_both_ids, absolute_segments_ledger).
    """
    s = sel_df.sort_values("_et").reset_index(drop=True)
    et = s["_et"]
    sel = s["selected"].to_numpy()
    abs_seg = np.zeros(len(s), dtype=int)
    norm_seg = np.zeros(len(s), dtype=int)
    boundaries = []
    a = n = 0
    gap_days_thresh = DATA_GAP_MAX_DAYS * 24 * 60
    for i in range(1, len(s)):
        gap = (et[i] - et[i - 1]).total_seconds() / 60.0
        roll = sel[i] != sel[i - 1]
        outage = gap > gap_days_thresh
        if outage:
            n += 1        # genuine outage breaks BOTH
        if roll or outage:
            a += 1        # roll or outage breaks ABSOLUTE
            reason = ("contract_roll+data_outage" if (roll and outage)
                      else "contract_roll" if roll else "data_outage")
            boundaries.append({"start_index": i, "reason": reason, "boundary_et": et[i],
                               "prev_contract": sel[i - 1], "new_contract": sel[i],
                               "gap_minutes": gap})
        abs_seg[i] = a
        norm_seg[i] = n
    s["segment_id"] = abs_seg
    s["norm_segment_id"] = norm_seg
    rows = []
    for sid, g in s.groupby("segment_id"):
        reason = "data_start" if sid == 0 else boundaries[sid - 1]["reason"]
        rows.append({
            "segment_id": int(sid), "instrument": "NQ", "param_version": PARAM_VERSION,
            "contract": g["selected"].iloc[0], "norm_segment_id": int(g["norm_segment_id"].iloc[0]),
            "start_et": g["_et"].iloc[0], "end_et": g["_et"].iloc[-1],
            "n_bars": int(len(g)), "n_globex_sessions": int(g["gday"].nunique()),
            "boundary_reason": reason,
        })
    return s, pd.DataFrame(rows)


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
    if "segment_id" not in b.columns:
        b["segment_id"] = 0
    if "norm_segment_id" not in b.columns:
        b["norm_segment_id"] = 0

    if tf.name == "1m":
        out = b[["ts_open_et", "ts_close_et", "open", "high", "low",
                 "close", "volume", "segment_id", "norm_segment_id"]].copy()
        out = out.rename(columns={"ts_open_et": "bucket_open_et",
                                  "ts_close_et": "bucket_close_et"})
        out.insert(0, "tf", tf.name)
        out["n_source_minutes"] = 1
        out["source_first_ts"] = b["ts_open_et"].to_numpy()
        out["source_last_ts"] = b["ts_open_et"].to_numpy()
        out["availability_et"] = b["ts_close_et"].to_numpy()
        out["complete"] = True
        out["spans_segment_boundary"] = False
        return out.reset_index(drop=True)

    if tf.name == "daily":
        # A daily candle covers the Globex day 18:00 ET -> 17:00 ET. Include all
        # tradeable minutes of the session (overnight + RTH + post-RTH to 16:59);
        # only the 17:00-18:00 maintenance break is excluded. Grouped per
        # (globex_day, segment_id) so no candle spans a segment boundary.
        gb = b[b["session"] != "maintenance"].copy()
        gb = gb.sort_values("ts_open_et")
        agg = (gb.groupby(["globex_day", "segment_id"], sort=True)
                 .agg(open=("open", "first"), high=("high", "max"),
                      low=("low", "min"), close=("close", "last"),
                      volume=("volume", "sum"), n_source_minutes=("open", "size"),
                      norm_segment_id=("norm_segment_id", "first"),
                      source_first_ts=("ts_open_et", "first"),
                      source_last_ts=("ts_open_et", "last"))
                 .reset_index())
        day_date = pd.to_datetime(agg["globex_day"]).dt.tz_localize(TZ)
        agg["bucket_open_et"] = day_date - pd.Timedelta(days=1) + pd.Timedelta(hours=18)
        agg["bucket_close_et"] = day_date + pd.Timedelta(hours=17)
        agg["availability_et"] = agg["bucket_close_et"]
        agg["tf"] = "daily"
        # complete iff session starts at 18:00 and last tradeable minute is 16:59
        first_ok = agg["source_first_ts"].dt.strftime("%H:%M") == "18:00"
        last_ok = agg["source_last_ts"].dt.strftime("%H:%M") == "16:59"
        # a globex_day appearing in >1 segment means a boundary split it
        dup = agg["globex_day"].duplicated(keep=False)
        agg["spans_segment_boundary"] = dup
        agg["complete"] = first_ok & last_ok & (~dup)
        return agg.reset_index(drop=True)

    # intraday HTF (vectorized, per (bucket, segment_id))
    midnight = b["ts_open_et"].dt.normalize()
    mins = (b["ts_open_et"] - midnight).dt.total_seconds() / 60.0
    bstart_min = (mins // tf.minutes).astype("int64") * tf.minutes
    b = b.assign(bucket_open_et=midnight + pd.to_timedelta(bstart_min, unit="m"))
    b = b.sort_values("ts_open_et")
    agg = (b.groupby(["bucket_open_et", "segment_id"], sort=True)
             .agg(open=("open", "first"), high=("high", "max"),
                  low=("low", "min"), close=("close", "last"),
                  volume=("volume", "sum"), n_source_minutes=("open", "size"),
                  norm_segment_id=("norm_segment_id", "first"),
                  source_first_ts=("ts_open_et", "first"),
                  source_last_ts=("ts_open_et", "last"))
             .reset_index())
    agg["bucket_close_et"] = agg["bucket_open_et"] + pd.Timedelta(minutes=tf.minutes)
    agg["availability_et"] = agg["bucket_close_et"]
    agg["tf"] = tf.name
    dup = agg["bucket_open_et"].duplicated(keep=False)
    agg["spans_segment_boundary"] = dup
    agg["complete"] = (agg["n_source_minutes"] == tf.minutes) & (~dup)
    return agg.reset_index(drop=True)


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


BASE_COLS = ["ts_event", "rtype", "publisher_id", "instrument_id",
             "open", "high", "low", "close", "volume", "symbol"]


def build_combined(discovery_csv: str, extra_csvs: list[str],
                   discovery_hash_path: str, extra_hash_paths: list[str]):
    """Discovery + all context files combined with a FROZEN quarterly roll and a
    DUAL segment model (absolute vs. scale-invariant normalization).

    Returns (et_frame, audit, tf_ledgers, roll_schedule, segments_ledger). The
    et_frame carries segment_id (absolute) and norm_segment_id per bar.
    """
    raw_d = load_raw(discovery_csv)
    raws = [load_raw(p) for p in extra_csvs]
    raw = pd.concat(raws + [raw_d], ignore_index=True)

    # FROZEN roll contract selection + dual (abs / norm) segments
    sel_df, roll_sched = frozen_roll_selection(raw)
    seg_df, seg_ledger = assign_segments(sel_df)

    et = seg_df.rename(columns={"_et": "ts_open_et"}).copy()
    et["ts_close_et"] = et["ts_open_et"] + pd.Timedelta(minutes=1)
    et = et.sort_values("ts_open_et").reset_index(drop=True)
    tags = et_session_tag(et["ts_open_et"])
    et = pd.concat([et.drop(columns=[c for c in ("globex_day", "session",
                    "minutes_of_day") if c in et.columns]), tags], axis=1)

    # discovery-only data-quality audit (authoritative for the study week)
    sel_d, sel_info = select_front_month(raw_d)
    et_d = to_et(sel_d)
    et_d = pd.concat([et_d, et_session_tag(et_d["ts_open_et"])], axis=1)
    audit = data_audit(raw_d, et_d, discovery_hash_path)
    audit["instrument_selection"] = sel_info

    # discovery ABSOLUTE segment = the segment containing 2026-07-06
    disc_mask = et["ts_open_et"] >= pd.Timestamp("2026-07-06 00:00", tz=TZ)
    disc_seg = int(et.loc[disc_mask, "segment_id"].min())
    disc_norm = int(et.loc[disc_mask, "norm_segment_id"].min())
    disc_abs_start = et.loc[et["segment_id"] == disc_seg, "ts_open_et"].min()
    norm_start = et.loc[et["norm_segment_id"] == disc_norm, "ts_open_et"].min()
    june_cut = roll_cutoff(2026, 6)

    audit["context_files"] = [{"hash_path": p, "file_sha256": sha256_file(p)}
                              for p in extra_hash_paths]
    audit["roll_model"] = {
        "type": "FROZEN predetermined quarterly roll (not volume-based)",
        "june_2026_cutoff_et": str(june_cut),
        "june_2026_cutoff_utc": str(june_cut.tz_convert("UTC")),
        "rule": "Globex open (18:00 ET) on the Monday of the third-Friday expiry week",
        "switch": "NQM6 -> NQU6 at the cutoff; absolute structures reset there",
    }
    audit["segments"] = {
        "n_absolute_segments": int(seg_ledger["segment_id"].max() + 1),
        "discovery_absolute_segment_id": disc_seg,
        "discovery_absolute_segment_start_et": str(disc_abs_start),
        "discovery_norm_segment_id": disc_norm,
        "discovery_norm_segment_start_et": str(norm_start),
        "data_gap_outage_threshold_days": DATA_GAP_MAX_DAYS,
        "model": ("ABSOLUTE segments reset at every frozen roll and every >"
                  f"{DATA_GAP_MAX_DAYS}-day data outage; no absolute structure "
                  "spans one. NORMALIZATION segments reset ONLY at a data outage, "
                  "so scale-invariant trailing percentiles continue ACROSS the "
                  "contract roll. Weekends / maintenance / holidays / early closes "
                  "are scheduled closures (< threshold) and do not break either."),
    }
    tf_ledgers = {tf.name: aggregate_tf(et, tf) for tf in TIMEFRAMES}
    return et, audit, tf_ledgers, roll_sched, seg_ledger


if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
    orig = sys.argv[2] if len(sys.argv) > 2 else csv
    et, audit, tfl = build_all(csv, orig)
    print(json.dumps(audit, indent=2, default=str))
    for k, v in tfl.items():
        print(k, len(v), "candles")

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


def causal_contract_selection(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select the front-month contract per Globex session WITHOUT intra-session
    look-ahead.

    The contract used for session S is decided from the PREVIOUS completed
    session S-1's outright volume (frozen at S-1's close, 17:00 ET). The current
    session never participates in its own decision. If the previous session's
    winner is not traded in S (expired across a gap/seam), the decision is a
    disclosed BOOTSTRAP that falls back to S's own dominant outright (this
    happens only at the data start and immediately after the seam).

    Returns (continuous_1m_rows, roll_decision_ledger).
    """
    r = raw.copy()
    ts = pd.to_datetime(r["ts_event"], utc=True, format="ISO8601")
    r["ts_utc"] = ts
    r["_et"] = ts.dt.tz_convert(TZ)
    out = r[~r["symbol"].str.contains("-", na=False)].copy()  # outrights only
    out["gday"] = _globex_day_series(out["_et"])
    vol = out.groupby(["gday", "symbol"])["volume"].sum().reset_index()
    days = sorted(vol["gday"].unique())

    selmap, ledger = {}, []
    for i, day in enumerate(days):
        cur = vol[vol.gday == day]
        cur_comp = {s: int(v) for s, v in zip(cur.symbol, cur.volume)}
        if i == 0:
            sel = cur.loc[cur.volume.idxmax(), "symbol"]
            ev, boot = None, True
            ev_comp, sel_vol, dec_ts = {}, None, None
        else:
            prev_day = days[i - 1]
            pv = vol[vol.gday == prev_day]
            ev_comp = {s: int(v) for s, v in zip(pv.symbol, pv.volume)}
            cand = pv.loc[pv.volume.idxmax(), "symbol"]
            dec_ts = (pd.Timestamp(day, tz=TZ) - pd.Timedelta(days=1)
                      + pd.Timedelta(hours=17))  # S-1 close = 17:00 ET, 1h pre-open
            if cur_comp.get(cand, 0) > 0:
                sel, boot = cand, False
                sel_vol = int(pv[pv.symbol == cand].volume.iloc[0])
            else:  # winner expired / not trading now -> disclosed bootstrap
                sel, boot = cur.loc[cur.volume.idxmax(), "symbol"], True
                sel_vol = None
            ev = prev_day
        selmap[day] = sel
        ledger.append({
            "instrument": "NQ", "param_version": PARAM_VERSION,
            "session_globex_day": day, "selected_contract": sel,
            "evidence_session": ev, "is_bootstrap": boot,
            "decision_timestamp_et": dec_ts,
            "selected_evidence_volume": sel_vol,
            "evidence_session_volumes": ev_comp,
            "current_session_volumes": cur_comp,
        })
    out["selected"] = out["gday"].map(selmap)
    sel_df = out[out["symbol"] == out["selected"]].copy()
    return sel_df, pd.DataFrame(ledger)


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


SEGMENT_GAP_MIN_MINUTES = 60.0  # non-calendar gaps <= this are illiquidity, not
                                # a continuity break (single no-trade minutes etc.)


def assign_segments(sel_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign continuity-segment ids to the continuous 1m series.

    A new segment begins after (a) a contract roll, (b) the seam, or (c) a
    substantial unexplained (non-calendar) data gap exceeding
    SEGMENT_GAP_MIN_MINUTES. Sub-threshold non-calendar gaps are counted as
    minor illiquidity gaps but do NOT break continuity (OHLCV omits no-trade
    minutes; treating each as a boundary would shatter normalization).
    Returns (frame_with_segment_id, segments_ledger).
    """
    s = sel_df.sort_values("_et").reset_index(drop=True)
    et = s["_et"]
    sel = s["selected"].to_numpy()
    seg = np.zeros(len(s), dtype=int)
    minor = np.zeros(len(s), dtype=bool)
    boundaries = []
    cur = 0
    for i in range(1, len(s)):
        reason = None
        gap = (et[i] - et[i - 1]).total_seconds() / 60.0
        roll = sel[i] != sel[i - 1]
        noncal = gap > 1.5 and not _gap_is_calendar(et[i - 1], et[i])
        biggap = noncal and gap > SEGMENT_GAP_MIN_MINUTES
        if roll and biggap:
            reason = "contract_roll+data_gap(seam)"
        elif roll:
            reason = "contract_roll"
        elif biggap:
            reason = "data_gap"
        elif noncal:
            minor[i] = True
        if reason is not None:
            cur += 1
            boundaries.append({"start_index": i, "reason": reason,
                               "boundary_et": et[i],
                               "prev_contract": sel[i - 1], "new_contract": sel[i],
                               "gap_minutes": gap})
        seg[i] = cur
    s["minor_gap_before"] = minor
    s["segment_id"] = seg
    # segments ledger
    rows = []
    for sid, g in s.groupby("segment_id"):
        reason = "data_start" if sid == 0 else boundaries[sid - 1]["reason"]
        rows.append({
            "segment_id": int(sid), "instrument": "NQ", "param_version": PARAM_VERSION,
            "contract": g["selected"].iloc[0],
            "start_et": g["_et"].iloc[0], "end_et": g["_et"].iloc[-1],
            "n_bars": int(len(g)), "n_globex_sessions": int(g["gday"].nunique()),
            "n_minor_illiquidity_gaps": int(g["minor_gap_before"].sum()),
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

    if tf.name == "1m":
        out = b[["ts_open_et", "ts_close_et", "open", "high", "low",
                 "close", "volume", "segment_id"]].copy()
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


def build_combined(discovery_csv: str, warmup_csv: str,
                   discovery_hash_path: str, warmup_hash_path: str):
    """Discovery + warm-up combined with CAUSAL contract selection and explicit
    continuity segments.

    Returns (et_frame, audit, tf_ledgers, roll_ledger, segments_ledger). The
    et_frame carries segment_id per bar. HTF construction and trailing
    normalization respect segment boundaries; the warm-up never serves as an
    immediate predecessor across the seam.
    """
    raw_d = load_raw(discovery_csv)
    raw_w = load_raw(warmup_csv)
    raw = pd.concat([raw_w, raw_d], ignore_index=True)

    # causal contract decision (no intra-session look-ahead) + segments
    sel_df, roll_ledger = causal_contract_selection(raw)
    seg_df, seg_ledger = assign_segments(sel_df)

    # build the ET minute frame directly from the segmented continuous series
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

    # discovery continuity segment = the post-seam NQU6 segment
    disc_mask = et["ts_open_et"] >= pd.Timestamp("2026-07-05 00:00", tz=TZ)
    disc_seg = int(et.loc[disc_mask, "segment_id"].min()) if disc_mask.any() else None
    warm_last = et.loc[et["segment_id"] < disc_seg, "ts_open_et"].max()
    disc_first = et.loc[et["segment_id"] == disc_seg, "ts_open_et"].min()

    audit["warmup"] = {
        "hash_path": warmup_hash_path,
        "file_sha256": sha256_file(warmup_hash_path),
        "rows_selected_continuous": int(len(sel_df)),
        "symbols_used": sorted(seg_ledger["contract"].unique().tolist()),
        "warmup_globex_sessions": int(seg_df.loc[seg_df["segment_id"] < disc_seg, "gday"].nunique()),
        "n_segments": int(seg_ledger["segment_id"].max() + 1),
        "discovery_segment_id": disc_seg,
        "seam": {
            "last_pre_discovery_bar_et": str(warm_last),
            "first_discovery_bar_et": str(disc_first),
            "gap_days": float((disc_first - warm_last).total_seconds() / 86400.0),
            "note": ("Warm-up ends on NQM6; discovery is NQU6. The seam is a new "
                     "continuity segment (contract change + ~28-day gap). Trailing "
                     "10/20/40 statistics require that many completed candles FROM "
                     "THE DISCOVERY SEGMENT; warm-up observations are NOT used as "
                     "immediate predecessors of July. Older observations existing "
                     "does NOT make daily/4h histories available in July."),
        },
        "nominal_sessions_before_discovery": int(seg_df.loc[seg_df["segment_id"] < disc_seg, "gday"].nunique()),
        "requirement_note": ("Nominal >=40 pre-July sessions exist, but they are in "
                             "prior segments; per-segment continuity governs feature "
                             "validity, so daily/4h 40-candle histories remain "
                             "unavailable in the July week."),
    }
    tf_ledgers = {tf.name: aggregate_tf(et, tf) for tf in TIMEFRAMES}
    return et, audit, tf_ledgers, roll_ledger, seg_ledger


if __name__ == "__main__":
    import sys
    csv = sys.argv[1] if len(sys.argv) > 1 else "data.csv"
    orig = sys.argv[2] if len(sys.argv) > 2 else csv
    et, audit, tfl = build_all(csv, orig)
    print(json.dumps(audit, indent=2, default=str))
    for k, v in tfl.items():
        print(k, len(v), "candles")

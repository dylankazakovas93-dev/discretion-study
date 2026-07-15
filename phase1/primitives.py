"""
Phase 1 frozen primitives, implemented causally on completed candles.

PARAMETER VERSION: phase1-v1.0.0

Every primitive is detected using ONLY candles completed at or before the
detection point. Later state-changes (retests, sweeps, invalidations,
conversions) are recorded but NEVER used to decide whether the original
structure existed. No centered windows; no future look-back to move a
boundary; current event excluded from its own trailing history.

Discovery-week emission window (ledger rows): a structure is EMITTED if its
availability timestamp falls in [2026-07-06 00:00 ET, 2026-07-11 00:00 ET).
Earlier candles (from 2026-07-05 20:00 ET) are retained only as warm-up for
trailing comparisons / HTF construction / pre-existing-structure maintenance.
"""

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

PARAM_VERSION = "phase1-v1.0.0"
TZ = "America/New_York"
DISC_START = pd.Timestamp("2026-07-06 00:00", tz=TZ)
DISC_END = pd.Timestamp("2026-07-11 00:00", tz=TZ)   # exclusive
JUL10_END = pd.Timestamp("2026-07-10 23:59", tz=TZ)  # "end of July 10"
# Seam between the warm-up series (ends 2026-06-07, NQM6) and the discovery
# series (starts 2026-07-05 20:00 ET, NQU6). Structural detection (FVG triples,
# displacement legs) must not straddle this seam; only trailing SIZE percentiles
# may reach across it. Any candle at/after POST_SEAM is on the discovery side.
POST_SEAM = pd.Timestamp("2026-07-01 00:00", tz=TZ)


def in_discovery(ts) -> bool:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return DISC_START <= ts < DISC_END


def _np_utc(ts_aware) -> np.datetime64:
    return np.datetime64(ts_aware.tz_convert("UTC").tz_localize(None))


def _disc_bounds(t_avail: np.ndarray) -> tuple[int, int]:
    """[start, end) index range of candles whose availability is in discovery."""
    lo, hi = _np_utc(DISC_START), _np_utc(DISC_END)
    idx = np.where((t_avail >= lo) & (t_avail < hi))[0]
    return (int(idx[0]), int(idx[-1] + 1)) if len(idx) else (0, 0)


def _postseam_first(t_open: np.ndarray) -> int:
    idx = np.where(t_open >= _np_utc(POST_SEAM))[0]
    return int(idx[0]) if len(idx) else len(t_open)


# ---------------------------------------------------------------------------
# canonical per-timeframe candle array
# ---------------------------------------------------------------------------

@dataclass
class Candles:
    tf: str
    t_open: np.ndarray       # tz-aware Timestamps (bar interval start), for output
    t_avail: np.ndarray      # tz-aware availability = interval end, for output
    t_open_utc: np.ndarray   # datetime64[ns] UTC, for fast vectorized bounds
    t_avail_utc: np.ndarray  # datetime64[ns] UTC, for fast vectorized bounds
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    segment_id: np.ndarray       # ABSOLUTE segment (resets at roll+outage)
    norm_segment_id: np.ndarray  # NORMALIZATION segment (resets at outage only)
    complete: np.ndarray         # bool: full interval, single segment (usable history)

    @property
    def n(self):
        return len(self.o)


def make_candles(ledger: pd.DataFrame, tf: str) -> Candles:
    d = ledger.sort_values(["bucket_open_et", "segment_id"]).reset_index(drop=True)
    comp = d["complete"]
    comp = comp.fillna(False) if comp.dtype == object else comp
    return Candles(
        tf=tf,
        t_open=d["bucket_open_et"].to_numpy(),
        t_avail=d["availability_et"].to_numpy(),
        t_open_utc=d["bucket_open_et"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
        t_avail_utc=d["availability_et"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(),
        o=d["open"].to_numpy(float),
        h=d["high"].to_numpy(float),
        l=d["low"].to_numpy(float),
        c=d["close"].to_numpy(float),
        v=d["volume"].to_numpy(float),
        segment_id=d["segment_id"].to_numpy(int),
        norm_segment_id=d["norm_segment_id"].to_numpy(int),
        complete=d["complete"].astype(bool).to_numpy(),
    )


def pct_rank(x: float, hist: np.ndarray) -> float:
    """Mid-rank percentile (0-100) of x within hist (current already excluded)."""
    if len(hist) == 0:
        return np.nan
    less = np.sum(hist < x)
    eq = np.sum(hist == x)
    return 100.0 * (less + 0.5 * eq) / len(hist)


def _n_same_seg_complete_preds(seg, complete, i, N):
    cnt, j, si = 0, i - 1, seg[i]
    while j >= 0 and cnt < N:
        if seg[j] != si:
            break
        if complete[j]:
            cnt += 1
        j -= 1
    return cnt


def validity_table(cd: "Candles") -> list:
    """Per-horizon feature validity for the discovery week: how many discovery
    candles lack N same-segment complete predecessors, and the first July
    availability at which the trailing-N feature becomes valid."""
    d0, d1 = _disc_bounds(cd.t_avail_utc)
    total = d1 - d0
    rows = []
    for N in (10, 20, 40):
        nnull = 0
        first_valid = None
        for i in range(d0, d1):
            ok = _n_same_seg_complete_preds(cd.norm_segment_id, cd.complete, i, N) >= N
            if ok and first_valid is None:
                first_valid = cd.t_avail[i]
            if not ok:
                nnull += 1
        rows.append({
            "tf": cd.tf, "horizon_N": N, "param_version": PARAM_VERSION,
            "discovery_candles": int(total),
            "null_count": int(nnull), "valid_count": int(total - nnull),
            "first_valid_july_availability_et": first_valid,
            "discovery_norm_segment_id": int(cd.norm_segment_id[d0]) if total else None,
            "exclusion_reason": ("insufficient_same_norm_segment_complete_predecessors"
                                 if nnull else ""),
        })
    return rows


def seg_hist(values: np.ndarray, seg: np.ndarray, complete: np.ndarray,
             i: int, N: int):
    """The N most recent COMPLETE predecessors of i that are IN THE SAME
    (normalization) segment. Returns None if fewer than N exist (-> null).

    The current candle i is excluded. Scanning stops at the segment boundary;
    for scale-invariant percentiles this is the NORMALIZATION segment, which
    crosses contract rolls and breaks only at a genuine data outage. Incomplete
    (boundary) candles are skipped, not counted.
    """
    out = []
    j = i - 1
    si = seg[i]
    while j >= 0 and len(out) < N:
        if seg[j] != si:
            break
        if complete[j]:
            out.append(values[j])
        j -= 1
    if len(out) < N:
        return None
    return np.asarray(out)


# ---------------------------------------------------------------------------
# 1. FAIR VALUE GAP
# ---------------------------------------------------------------------------

def detect_fvgs(cd: Candles) -> pd.DataFrame:
    rows = []
    o, h, l, c = cd.o, cd.h, cd.l, cd.c
    seg = cd.segment_id
    # confine detection to the discovery ABSOLUTE segment (the one containing the
    # discovery week). Absolute structures reset at the roll, so this segment is
    # the post-roll NQU6 run; nothing before the roll can form part of a July FVG.
    d0, d1 = _disc_bounds(cd.t_avail_utc)
    if d0 == d1:
        return pd.DataFrame()
    disc_abs = seg[d0]
    start = max(2, int(np.searchsorted(seg, disc_abs, side="left")) + 2)
    for i in range(start, cd.n):
        A, B, C = i - 2, i - 1, i
        if not (seg[A] == seg[B] == seg[C] == disc_abs):  # single abs segment only
            continue
        b_lo, b_hi = min(o[B], c[B]), max(o[B], c[B])
        # ---- bullish ----
        if h[A] < l[C] and c[B] > o[B] and b_lo <= h[A] and b_hi >= l[C]:
            rows.append(_fvg_record(cd, "bull", A, B, C, lower=h[A], upper=l[C]))
        # ---- bearish ----
        if l[A] > h[C] and c[B] < o[B] and b_lo <= h[C] and b_hi >= l[A]:
            rows.append(_fvg_record(cd, "bear", A, B, C, lower=h[C], upper=l[A]))
    df = pd.DataFrame(rows)
    return df


def _fvg_record(cd: Candles, direction, A, B, C, lower, upper):
    o, h, l, c = cd.o, cd.h, cd.l, cd.c
    avail = cd.t_avail[C]
    mid = 0.5 * (lower + upper)
    fid = f"FVG-{cd.tf}-{direction}-{pd.Timestamp(cd.t_open[C]).strftime('%Y%m%dT%H%M')}"

    first_wick = first_body = first_mid = full_fill = invalid = None
    # scan strictly-later candles (index > C); C cannot be its own retest
    for j in range(C + 1, cd.n):
        rng_lo, rng_hi = l[j], h[j]
        body_lo, body_hi = min(o[j], c[j]), max(o[j], c[j])
        # wick entry: candle range overlaps zone by positive amount
        if first_wick is None and rng_lo < upper and rng_hi > lower:
            first_wick = cd.t_avail[j]
        # body overlap
        if first_body is None and body_lo < upper and body_hi > lower:
            first_body = cd.t_avail[j]
        # midpoint touch
        if first_mid is None and rng_lo <= mid <= rng_hi:
            first_mid = cd.t_avail[j]
        # full fill
        if full_fill is None:
            if direction == "bull" and rng_lo <= lower:
                full_fill = cd.t_avail[j]
            if direction == "bear" and rng_hi >= upper:
                full_fill = cd.t_avail[j]
        if full_fill is not None:
            invalid = full_fill
            break
    return {
        "id": fid, "instrument": "NQ", "direction": direction, "tf": cd.tf,
        "param_version": PARAM_VERSION,
        "A_open_et": cd.t_open[A], "B_open_et": cd.t_open[B], "C_open_et": cd.t_open[C],
        "A_high": h[A], "A_low": l[A], "C_high": h[C], "C_low": l[C],
        "B_open": o[B], "B_close": c[B],
        "lower_boundary": lower, "upper_boundary": upper, "midpoint": mid,
        "availability_et": avail,
        "first_wick_entry_et": first_wick,
        "first_body_overlap_et": first_body,
        "midpoint_touch_et": first_mid,
        "full_fill_et": full_fill,
        "invalidation_et": invalid,
        "segment_id": int(cd.segment_id[C]),
        "C_index": C,
    }


# ---------------------------------------------------------------------------
# 2. INVERSE FVG
# ---------------------------------------------------------------------------

def detect_ifvg(cd: Candles, fvgs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if fvgs.empty:
        return pd.DataFrame(rows)
    c = cd.c
    for _, f in fvgs.iterrows():
        Ci = int(f["C_index"])
        conv = None
        for j in range(Ci + 1, cd.n):
            if f["direction"] == "bull" and c[j] < f["lower_boundary"]:
                conv = cd.t_avail[j]; conv_idx = j; break
            if f["direction"] == "bear" and c[j] > f["upper_boundary"]:
                conv = cd.t_avail[j]; conv_idx = j; break
        if conv is not None:
            rows.append({
                "ifvg_id": f["id"] + "-iFVG",
                "source_fvg_id": f["id"],
                "instrument": "NQ", "tf": cd.tf, "param_version": PARAM_VERSION,
                "original_direction": f["direction"],
                "ifvg_direction": "bear" if f["direction"] == "bull" else "bull",
                "source_lower": f["lower_boundary"], "source_upper": f["upper_boundary"],
                "conversion_close": cd.c[conv_idx],
                "conversion_et": conv,
                "source_availability_et": f["availability_et"],
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. LIQUIDITY REFERENCES
# ---------------------------------------------------------------------------

def detect_liquidity(et: pd.DataFrame) -> pd.DataFrame:
    """Build the frozen liquidity references from the 1-minute ET frame.

    Sources: previous completed RTH high/low, completed overnight high/low,
    09:00 / 09:30 / 10:00 ET one-minute candle high/low.
    Sweep scans use ALL later 1-minute bars (through end of data).
    """
    et = et.sort_values("ts_open_et").reset_index(drop=True)
    t = et["ts_open_et"]
    hi = et["high"].to_numpy(float)
    lo = et["low"].to_numpy(float)
    tarr = t.to_numpy()
    tclose = et["ts_close_et"].to_numpy()
    mod = et["minutes_of_day"].to_numpy()
    rows = []

    def scan(extreme, side, avail, source, tf, meta):
        """First exact touch / first wick passage / sweep after availability."""
        if not in_discovery(avail):   # emit + scan only discovery-week refs
            return None
        first_touch = first_wick = sweep = None
        start = np.searchsorted(tclose, avail)  # first bar available strictly after
        # ensure strictly-later availability
        while start < len(tclose) and tclose[start] <= avail:
            start += 1
        for j in range(start, len(hi)):
            if side == "high":
                if first_touch is None and hi[j] == extreme:
                    first_touch = tclose[j]
                if hi[j] > extreme:
                    first_wick = tclose[j]; sweep = tclose[j]; break
            else:
                if first_touch is None and lo[j] == extreme:
                    first_touch = tclose[j]
                if lo[j] < extreme:
                    first_wick = tclose[j]; sweep = tclose[j]; break
        rec = {
            "instrument": "NQ", "source": source, "side": side, "tf": tf,
            "param_version": PARAM_VERSION, "extreme": extreme,
            "availability_et": avail,
            "first_exact_touch_et": first_touch,
            "first_wick_passage_et": first_wick,
            "sweep_et": sweep,
            "unswept_through_end": bool(sweep is None),
        }
        rec.update(meta)
        return rec

    # --- per globex day sessions ---
    for gday, g in et.groupby("globex_day", sort=True):
        seg_g = int(g["segment_id"].iloc[0]) if "segment_id" in g.columns else 0
        # RTH high/low
        rth = g[g["session"] == "rth"]
        if len(rth):
            rth_hi = rth["high"].max(); rth_lo = rth["low"].min()
            rth_avail = rth["ts_close_et"].max()  # available after last RTH minute
            rows.append(scan(rth_hi, "high", rth_avail, "prev_rth_high", "rth_session",
                             {"session_globex_day": gday, "segment_id": seg_g}))
            rows.append(scan(rth_lo, "low", rth_avail, "prev_rth_low", "rth_session",
                             {"session_globex_day": gday, "segment_id": seg_g}))
        # overnight high/low
        on = g[g["session"] == "overnight"]
        if len(on):
            on_hi = on["high"].max(); on_lo = on["low"].min()
            on_avail = on["ts_close_et"].max()
            rows.append(scan(on_hi, "high", on_avail, "overnight_high", "overnight_session",
                             {"session_globex_day": gday, "segment_id": seg_g}))
            rows.append(scan(on_lo, "low", on_avail, "overnight_low", "overnight_session",
                             {"session_globex_day": gday, "segment_id": seg_g}))
        # specific one-minute candles by ET clock (09:00, 09:30, 10:00)
        for hhmm, label in [(9 * 60, "0900"), (9 * 60 + 30, "0930"), (10 * 60, "1000")]:
            bar = g[g["minutes_of_day"] == hhmm]
            # only the RTH-day instance (unique per day) -- pick the calendar
            # date matching this globex day's daytime
            if len(bar):
                bar = bar.iloc[[0]]
                bh = float(bar["high"].iloc[0]); bl = float(bar["low"].iloc[0])
                bavail = bar["ts_close_et"].iloc[0]
                rows.append(scan(bh, "high", bavail, f"candle_{label}_high", "1m",
                                 {"session_globex_day": gday, "segment_id": seg_g}))
                rows.append(scan(bl, "low", bavail, f"candle_{label}_low", "1m",
                                 {"session_globex_day": gday, "segment_id": seg_g}))
    rows = [r for r in rows if r is not None]
    df = pd.DataFrame(rows)
    # emit only references available during discovery week
    df = df[df["availability_et"].apply(in_discovery)].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 4. REJECTION-BLOCK CANDIDATES
# ---------------------------------------------------------------------------

def detect_rejection_blocks(cd: Candles) -> pd.DataFrame:
    o, h, l, c = cd.o, cd.h, cd.l, cd.c
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l
    body = np.abs(c - o)
    rng = h - l
    rows = []
    d0, d1 = _disc_bounds(cd.t_avail_utc)  # emit only discovery-week candidates;
    for i in range(d0, d1):             # history uses full array, scans use tail
        for direction in ("bear", "bull"):
            if direction == "bear":
                dwick = upper_wick[i]; owick = lower_wick[i]
                z_lo, z_hi = max(o[i], c[i]), h[i]        # wick zone
                far = h[i]; near = max(o[i], c[i])
                wick_hist_full = upper_wick
            else:
                dwick = lower_wick[i]; owick = upper_wick[i]
                z_lo, z_hi = l[i], min(o[i], c[i])
                far = l[i]; near = min(o[i], c[i])
                wick_hist_full = lower_wick

            def pctl(N):
                # scale-invariant normalization: same NORM segment (crosses the
                # contract roll), complete predecessors only.
                hist = seg_hist(wick_hist_full, cd.norm_segment_id, cd.complete, i, N)
                if hist is None:
                    return np.nan
                return pct_rank(dwick, hist)

            # ---- later state scan ----
            first_partial = first_body = first_traverse = None
            exact_boundary_touch = None
            invalid_reason = None; invalid_ts = None
            for j in range(i + 1, cd.n):
                rlo, rhi = l[j], h[j]
                blo, bhi = min(o[j], c[j]), max(o[j], c[j])
                # partial wick entry: range intersects zone (positive)
                if first_partial is None and rlo < z_hi and rhi > z_lo:
                    first_partial = cd.t_avail[j]
                # body overlap: body interval intersects zone positively
                if first_body is None and blo < z_hi and bhi > z_lo:
                    first_body = cd.t_avail[j]
                # exact-boundary body touch (touch a boundary w/o entering)
                if exact_boundary_touch is None and (bhi == z_lo or blo == z_hi):
                    exact_boundary_touch = cd.t_avail[j]
                # complete wick traversal beyond far boundary
                traversed = False
                if direction == "bear":
                    if rlo <= near and rhi > far:
                        traversed = True
                else:
                    if rhi >= near and rlo < far:
                        traversed = True
                if first_traverse is None and traversed:
                    first_traverse = cd.t_avail[j]
                # invalidation = first of (body overlap) or (complete traversal)
                if invalid_ts is None:
                    if first_body == cd.t_avail[j] and (blo < z_hi and bhi > z_lo):
                        invalid_reason = "body_overlap"; invalid_ts = cd.t_avail[j]
                    elif traversed:
                        invalid_reason = "wick_traversal_beyond_far"; invalid_ts = cd.t_avail[j]
                if invalid_ts is not None:
                    break

            # untested through end of July 10 (no partial/body/traverse by Jul10)
            untested_j10 = True
            for ev in (first_partial, first_body, first_traverse):
                if ev is not None and pd.Timestamp(ev) <= JUL10_END:
                    untested_j10 = False
            rows.append({
                "instrument": "NQ", "tf": cd.tf, "direction": direction,
                "param_version": PARAM_VERSION,
                "source_open_et": cd.t_open[i], "availability_et": cd.t_avail[i],
                "zone_lower": z_lo, "zone_upper": z_hi,
                "far_boundary": far, "near_boundary": near,
                "directional_wick_len": dwick, "opposite_wick_len": owick,
                "body_len": body[i], "total_range": rng[i],
                "dwick_body_ratio": (dwick / body[i]) if body[i] > 0 else np.nan,
                "dwick_range_ratio": (dwick / rng[i]) if rng[i] > 0 else np.nan,
                "dwick_pctile_prev10": pctl(10),
                "dwick_pctile_prev20": pctl(20),
                "dwick_pctile_prev40": pctl(40),
                "first_partial_wick_entry_et": first_partial,
                "first_body_overlap_et": first_body,
                "first_complete_traversal_et": first_traverse,
                "exact_boundary_body_touch_et": exact_boundary_touch,
                "invalidation_reason": invalid_reason,
                "invalidation_et": invalid_ts,
                "still_valid_end_of_data": bool(invalid_ts is None),
                "untested_through_jul10": untested_j10,
                "segment_id": int(cd.segment_id[i]),
                "source_complete": bool(cd.complete[i]),
                "source_index": i,
            })
    df = pd.DataFrame(rows)
    df = df[df["availability_et"].apply(in_discovery)].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 5. DISPLACEMENT QUALITY
# ---------------------------------------------------------------------------

def detect_displacement(cd: Candles, fvgs: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = cd.o, cd.h, cd.l, cd.c
    body = np.abs(c - o)
    # FVG creation index sets (by direction), keyed by B index (leg middle)
    fvg_by_C = {}
    if not fvgs.empty:
        for _, f in fvgs.iterrows():
            fvg_by_C.setdefault(f["direction"], set()).add(int(f["C_index"]))
    rows = []
    d0, d1 = _disc_bounds(cd.t_avail_utc)
    seg = cd.segment_id
    for end in range(d0, d1):
        for L in (1, 2, 3):
            start = end - L + 1
            if start < 0 or seg[start] != seg[end]:  # leg confined to one abs segment
                continue
            for direction in ("bull", "bear"):
                idx = list(range(start, end + 1))
                net = c[end] - o[start]  # signed
                if direction == "bear":
                    net = -net
                aligned = [(c[k] > o[k]) if direction == "bull" else (c[k] < o[k]) for k in idx]
                n_aligned = int(sum(aligned))
                prop_aligned = n_aligned / L
                aligned_bodies = [body[k] for k, a in zip(idx, aligned) if a]
                med_aligned_body = float(np.median(aligned_bodies)) if aligned_bodies else 0.0

                def med_body_pctile(N):
                    vals = []
                    for k in idx:
                        hist = seg_hist(body, cd.norm_segment_id, cd.complete, k, N)
                        if hist is None:
                            return np.nan
                        vals.append(pct_rank(body[k], hist))
                    return float(np.median(vals)) if vals else np.nan

                # adjacent-candle overlap (mean over consecutive pairs)
                overlaps = []
                for k in idx[:-1]:
                    ov = min(h[k], h[k + 1]) - max(l[k], l[k + 1])
                    overlaps.append(max(0.0, ov))
                adj_overlap = float(np.mean(overlaps)) if overlaps else np.nan

                # terminal close location within terminal candle
                rng_end = h[end] - l[end]
                if direction == "bull":
                    term_loc = (c[end] - l[end]) / rng_end if rng_end > 0 else np.nan
                else:
                    term_loc = (h[end] - c[end]) / rng_end if rng_end > 0 else np.nan

                total_distance = float(np.sum([h[k] - l[k] for k in idx]))
                path_eff = abs(net) / total_distance if total_distance > 0 else np.nan

                created_fvg = bool(L == 3 and end in fvg_by_C.get(direction, set()))

                rows.append({
                    "instrument": "NQ", "tf": cd.tf, "direction": direction,
                    "leg_len": L, "param_version": PARAM_VERSION,
                    "start_open_et": cd.t_open[start], "end_open_et": cd.t_open[end],
                    "availability_et": cd.t_avail[end],
                    "net_directional_move": net,
                    "n_bodies_aligned": n_aligned, "prop_bodies_aligned": prop_aligned,
                    "median_aligned_body": med_aligned_body,
                    "median_body_pctile_prev10": med_body_pctile(10),
                    "median_body_pctile_prev20": med_body_pctile(20),
                    "median_body_pctile_prev40": med_body_pctile(40),
                    "adjacent_overlap": adj_overlap,
                    "terminal_close_location": term_loc,
                    "path_efficiency": path_eff,
                    "total_distance": total_distance,
                    "created_fvg": created_fvg,
                    "segment_id": int(cd.segment_id[end]),
                    "end_index": end,
                })
    df = pd.DataFrame(rows)
    df = df[df["availability_et"].apply(in_discovery)].reset_index(drop=True)
    return df

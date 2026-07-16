"""
Causal recognizer engine: NY-session VWAP + bands, historical levels with state,
price-action helpers, and setup-GRAPH construction under the frozen grammar.

All quantities are causal (usable only after the contributing bar closes). Sizes
are ATR-normalized / dimensionless -- NO raw-point cross-contract magnitude is
used in the feature representation. Absolute structures never cross a roll
(everything is built inside one ABSOLUTE segment).
"""
import os
import sys
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # phase1/ (core, primitives)
sys.path.insert(0, _HERE)                     # recognizer/ (prereg)
import primitives as P
import prereg as PR

TZ = "America/New_York"


# ---------------------------------------------------------------------------
# Causal New York session VWAP + weighted-deviation bands
# ---------------------------------------------------------------------------

def compute_vwap_1m(et: pd.DataFrame) -> pd.DataFrame:
    """Causal NY-session VWAP on 1-minute bars, reset at 09:30 ET each day,
    accumulated within the ABSOLUTE segment. Typical price (H+L+C)/3 * volume;
    cumulative session volume. Weighted deviation gives the bands. A VWAP/band
    value is usable only AFTER the contributing bar closes (availability =
    ts_close_et)."""
    e = et.sort_values("ts_open_et").reset_index(drop=True).copy()
    mm = e["minutes_of_day"].to_numpy()
    seg = e["segment_id"].to_numpy()
    tp = ((e["high"] + e["low"] + e["close"]) / 3.0).to_numpy(float)
    vol = e["volume"].to_numpy(float)
    n = len(e)
    reset_min = 9 * 60 + 30
    # NY session id: increments at each 09:30 open within a segment (vectorized)
    reset = (mm == reset_min).astype(np.int64)
    e["_reset"] = reset
    sid = e.groupby("segment_id")["_reset"].cumsum().to_numpy()      # 0 before first 09:30
    valid = sid > 0
    grp = pd.Series(list(zip(seg, sid)))
    pv = pd.Series(tp * vol); v = pd.Series(vol); pv2 = pd.Series(tp * tp * vol)
    cum_pv = pv.groupby(grp).cumsum().to_numpy()
    cum_v = v.groupby(grp).cumsum().to_numpy()
    cum_pv2 = pv2.groupby(grp).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = np.where((cum_v > 0) & valid, cum_pv / cum_v, np.nan)
        var = np.maximum(0.0, np.where((cum_v > 0) & valid, cum_pv2 / cum_v - vwap * vwap, np.nan))
        sd = np.sqrt(var)
    band = {k: vwap + k * sd for k in PR.VWAP_BANDS}
    band_neg = {k: vwap - k * sd for k in PR.VWAP_BANDS}
    out = pd.DataFrame({"ts_open_et": e["ts_open_et"], "ts_close_et": e["ts_close_et"],
                        "vwap": vwap})
    for k in PR.VWAP_BANDS:
        out[f"vwap_+{k}"] = band[k]
        out[f"vwap_-{k}"] = band_neg[k]
    out["segment_id"] = seg
    return out


# ---------------------------------------------------------------------------
# Historical levels with causal state (age, freshness, touches, sweep)
# ---------------------------------------------------------------------------

def build_levels(et: pd.DataFrame) -> pd.DataFrame:
    """Per (segment, globex session) historical levels: prev RTH H/L, overnight
    H/L, prev-day H/L, prior 3/5/10/20-session H/L. Each is available at the
    session it applies to (18:00 ET open), carries age (sessions), and its
    first-sweep timestamp (scanned within the segment). Levels never cross a
    roll (computed inside one absolute segment)."""
    rows = []
    for seg_id, g in et.groupby("segment_id", sort=True):
        g = g.sort_values("ts_open_et")
        # per-session ranges
        sess = (g.groupby("globex_day")
                  .agg(high=("high", "max"), low=("low", "min"),
                       rth_high=("high", lambda s: s[g.loc[s.index, "session"] == "rth"].max() if (g.loc[s.index, "session"] == "rth").any() else np.nan),
                       start=("ts_open_et", "min"), end=("ts_close_et", "max"))
                  .reset_index())
        # simpler RTH/ON per session
        days = sorted(g["globex_day"].unique())
        rmap = {}
        for d in days:
            gd = g[g["globex_day"] == d]
            rth = gd[gd["session"] == "rth"]; on = gd[gd["session"] == "overnight"]
            rmap[d] = {
                "high": gd["high"].max(), "low": gd["low"].min(),
                "rth_high": rth["high"].max() if len(rth) else np.nan,
                "rth_low": rth["low"].min() if len(rth) else np.nan,
                "on_high": on["high"].max() if len(on) else np.nan,
                "on_low": on["low"].min() if len(on) else np.nan,
                "open_et": pd.Timestamp(d, tz=TZ) - pd.Timedelta(days=1) + pd.Timedelta(hours=18),
            }
        hi = g["high"].to_numpy(float); lo = g["low"].to_numpy(float)
        tclose = g["ts_close_et"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()

        def sweep_after(extreme, side, avail):
            av = np.datetime64(pd.Timestamp(avail).tz_convert("UTC").tz_localize(None))
            idx = np.searchsorted(tclose, av)
            for j in range(idx, len(hi)):
                if tclose[j] <= av:
                    continue
                if (side == "high" and hi[j] > extreme) or (side == "low" and lo[j] < extreme):
                    return pd.Timestamp(tclose[j]).tz_localize("UTC").tz_convert(TZ)
            return None

        for k, d in enumerate(days):
            avail = rmap[d]["open_et"]
            gd = g[g["globex_day"] == d]
            fam = []   # (source, extreme, side, age, family)
            if k >= 1:
                p = rmap[days[k - 1]]
                fam += [("prev_rth_high", p["rth_high"], "high", 1, "LIQ_SWEEP"),
                        ("prev_rth_low", p["rth_low"], "low", 1, "LIQ_SWEEP"),
                        ("prev_day_high", p["high"], "high", 1, "HIST_LEVEL"),
                        ("prev_day_low", p["low"], "low", 1, "HIST_LEVEL")]
            cur = rmap[d]
            fam += [("overnight_high", cur["on_high"], "high", 0, "LIQ_SWEEP"),
                    ("overnight_low", cur["on_low"], "low", 0, "LIQ_SWEEP")]
            # intraday liquidity candles (09:00/09:30/10:00 ET) high/low
            for hhmm, lab in [(540, "0900"), (570, "0930"), (600, "1000")]:
                bar = gd[gd["minutes_of_day"] == hhmm]
                if len(bar):
                    b = bar.iloc[0]
                    fam += [(f"candle_{lab}_high", b["high"], "high", 0, "LIQ_SWEEP"),
                            (f"candle_{lab}_low", b["low"], "low", 0, "LIQ_SWEEP")]
            for name, N in PR.LEVEL_LOOKBACKS.items():
                if name == "prev_day" or k < N:
                    continue
                window = [rmap[days[j]] for j in range(k - N, k)]
                fam += [(f"{name}_high", max(w["high"] for w in window), "high", N, "HIST_LEVEL"),
                        (f"{name}_low", min(w["low"] for w in window), "low", N, "HIST_LEVEL")]
            for (src, ext, side, age, family) in fam:
                if ext is None or (isinstance(ext, float) and np.isnan(ext)):
                    continue
                rows.append({
                    "segment_id": int(seg_id), "session_globex_day": d,
                    "source": src, "side": side, "extreme": float(ext),
                    "family": family, "age_sessions": age, "availability_et": avail,
                    "sweep_et": sweep_after(ext, side, avail),
                    "level_id": f"LVL-{seg_id}-{d}-{src}",
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _utc(ts):
    ts = pd.Timestamp(ts)
    return np.datetime64(ts.tz_convert("UTC").tz_localize(None)) if ts.tzinfo else np.datetime64(ts)


def session_of(ts):
    ts = pd.Timestamp(ts)
    h = ts.hour
    d = ts.normalize()
    return (d + pd.Timedelta(days=1)).date().isoformat() if h >= 18 else d.date().isoformat()


def time_anchor(ts):
    ts = pd.Timestamp(ts); mm = ts.hour * 60 + ts.minute
    for lab, m in [("midnight_open", 0), ("asia_open", 18 * 60), ("london_open", 3 * 60),
                   ("0900", 540), ("0930", 570), ("1000", 600), ("ny_open", 570)]:
        if mm == m:
            return lab
    if 570 <= mm < 16 * 60:
        return "rth"
    return "off_anchor"


def vwap_state_at(vwdf_idx, vwdf, ts, price, atr):
    """Return (vwap_side, nearest_band_label, nearest_band_dist_atr) causally."""
    key = _utc(ts)
    j = vwdf_idx.get(key)
    if j is None or np.isnan(vwdf["vwap"].iloc[j]):
        return (None, None, np.nan)
    vw = vwdf["vwap"].iloc[j]
    side = "above" if price >= vw else "below"
    best_lab, best = None, np.inf
    for k in PR.VWAP_BANDS:
        for sign in ("+", "-"):
            b = vwdf[f"vwap_{sign}{k}"].iloc[j]
            if np.isnan(b):
                continue
            dd = abs(price - b) / atr if atr and atr > 0 else np.inf
            if dd < best:
                best, best_lab = dd, f"{sign}{k}"
    return (side, best_lab, best if best != np.inf else np.nan)

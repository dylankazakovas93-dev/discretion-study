"""Stage 1 causal feature engine: anchored VWAP, EMA(21), Wilder ADX(14).

CAUSALITY CONTRACT
------------------
Every feature emitted for a candidate is computed from bars whose CLOSE is at
or before the last completed 1m bar prior to the decision timestamp, i.e. index
(entry_seq - 1), matching the existing atr_floors convention. The bar containing
the decision is never used. Higher-timeframe values become available only after
the corresponding higher-timeframe bar has closed.

HOLDOUT: only sessions in DEV_YEARS are emitted. No other year's rows are read
into any feature buffer.
"""
from __future__ import annotations
import numpy as np, pickle, os, glob, json, sys
from collections import defaultdict

DEV_YEARS = (2018, 2025)
SEGCACHE = os.path.join("artifacts", "multiyear_validation_v2", "segcache")
OUT = os.path.join("artifacts", "broad_discovery")
os.makedirs(OUT, exist_ok=True)

# ---- frozen anchor definitions (ET). Declared before any result inspected. ----
ANCHORS = {
    "GLOBEX_1800": (18, 0),
    "MIDNIGHT_0000": (0, 0),
    "LONDON_0300": (3, 0),
    "CASH_0930": (9, 30),
    "TEN_1000": (10, 0),
    "NYPM_1330": (13, 30),
}
BANDS = (1, 2, 3, 4)
EMA_TFS = (1, 3, 5, 15)
ADX_TFS = (1, 5, 15)
EMA_LEN, ADX_LEN = 21, 14


def _anchor_id(ts_et, hh, mm):
    """Session-anchored bucket id: increments each time we cross the anchor."""
    t = ts_et
    mins = t.hour * 60 + t.minute
    a = hh * 60 + mm
    d = t.date().toordinal()
    return d if mins >= a else d - 1


def anchored_vwap(ts_et, close, high, low, vol, hh, mm):
    """Causal anchored VWAP + weighted stdev. Value at index i uses bars 0..i,
    all of which are completed by construction (caller shifts by one)."""
    n = len(close)
    tp = (high + low + close) / 3.0
    vw = np.empty(n); sd = np.empty(n)
    cum_pv = cum_v = cum_p2v = 0.0
    cur = None
    for i in range(n):
        aid = _anchor_id(ts_et[i], hh, mm)
        if aid != cur:
            cur = aid; cum_pv = cum_v = cum_p2v = 0.0
        v = float(vol[i]) if vol[i] > 0 else 1.0
        cum_pv += tp[i] * v; cum_v += v; cum_p2v += tp[i] * tp[i] * v
        m = cum_pv / cum_v
        var = max(0.0, cum_p2v / cum_v - m * m)
        vw[i] = m; sd[i] = var ** 0.5
    return vw, sd


def ema(x, length):
    a = 2.0 / (length + 1.0)
    out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def wilder_adx(high, low, close, length=ADX_LEN):
    n = len(close)
    tr = np.zeros(n); pdm = np.zeros(n); ndm = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]; dn = low[i - 1] - low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    def rma(v):
        o = np.zeros(n); s = 0.0
        for i in range(n):
            s = v[i] if i == 0 else (s * (length - 1) + v[i]) / length
            o[i] = s
        return o
    atr = rma(tr); pdi = np.where(atr > 0, 100 * rma(pdm) / atr, 0.0)
    ndi = np.where(atr > 0, 100 * rma(ndm) / atr, 0.0)
    dx = np.where((pdi + ndi) > 0, 100 * np.abs(pdi - ndi) / (pdi + ndi), 0.0)
    return rma(dx), pdi, ndi


def resample_last_closed(ts_et, arr_h, arr_l, arr_c, tf):
    """Map each 1m index to the value of the last CLOSED tf-minute bar.
    A tf bar closes at the end of its final minute, so its value is only
    available from the next 1m bar onward -- enforced by the +1 shift."""
    n = len(arr_c)
    bucket = np.array([(t.hour * 60 + t.minute) // tf for t in ts_et])
    day = np.array([t.date().toordinal() for t in ts_et])
    kid = day * 10000 + bucket
    hs, ls, cs, endi = [], [], [], []
    ch = cl = cc = None; cur = None
    for i in range(n):
        if kid[i] != cur:
            if cur is not None:
                hs.append(ch); ls.append(cl); cs.append(cc); endi.append(i - 1)
            cur = kid[i]; ch = arr_h[i]; cl = arr_l[i]; cc = arr_c[i]
        else:
            ch = max(ch, arr_h[i]); cl = min(cl, arr_l[i]); cc = arr_c[i]
    if cur is not None:
        hs.append(ch); ls.append(cl); cs.append(cc); endi.append(n - 1)
    return np.array(hs), np.array(ls), np.array(cs), np.array(endi)


def project_to_1m(vals, endi, n):
    """Value of the last closed tf bar, available strictly AFTER its close."""
    out = np.full(n, np.nan); k = 0
    for i in range(n):
        while k < len(endi) and endi[k] < i:
            k += 1
        j = k - 1                      # last bar that closed strictly before i
        if j >= 0:
            out[i] = vals[j]
    return out


def segment_features(bars):
    n = len(bars)
    ts = [b.ts_et for b in bars]
    o = np.array([b.open for b in bars]); h = np.array([b.high for b in bars])
    l = np.array([b.low for b in bars]); c = np.array([b.close for b in bars])
    v = np.array([b.volume for b in bars], dtype=float)
    F = {}
    for name, (hh, mm) in ANCHORS.items():
        vw, sd = anchored_vwap(ts, c, h, l, v, hh, mm)
        F[f"vwap_{name}"] = vw; F[f"vwsd_{name}"] = sd
        F[f"vwslope_{name}"] = np.concatenate([[0.0], np.diff(vw)])
    for tf in EMA_TFS:
        if tf == 1:
            e = ema(c, EMA_LEN)
            F[f"ema{EMA_LEN}_{tf}"] = e
            F[f"emaslope_{tf}"] = np.concatenate([[0.0], np.diff(e)])
        else:
            hh_, ll_, cc_, ei = resample_last_closed(ts, h, l, c, tf)
            e = ema(cc_, EMA_LEN)
            F[f"ema{EMA_LEN}_{tf}"] = project_to_1m(e, ei, n)
            sl = np.concatenate([[0.0], np.diff(e)])
            F[f"emaslope_{tf}"] = project_to_1m(sl, ei, n)
    for tf in ADX_TFS:
        if tf == 1:
            a, p, m = wilder_adx(h, l, c)
            F[f"adx_{tf}"] = a; F[f"pdi_{tf}"] = p; F[f"ndi_{tf}"] = m
        else:
            hh_, ll_, cc_, ei = resample_last_closed(ts, h, l, c, tf)
            a, p, m = wilder_adx(hh_, ll_, cc_)
            F[f"adx_{tf}"] = project_to_1m(a, ei, n)
            F[f"pdi_{tf}"] = project_to_1m(p, ei, n)
            F[f"ndi_{tf}"] = project_to_1m(m, ei, n)
    F["close"] = c; F["high"] = h; F["low"] = l
    return F


if __name__ == "__main__":
    man = json.load(open(os.path.join(SEGCACHE, "manifest.json")))
    nseg = man["n_segments"]
    done = 0
    for si in range(nseg):
        outp = os.path.join(OUT, f"feat_{si:03d}.pkl")
        if os.path.exists(outp):
            done += 1; continue
        bars = pickle.load(open(os.path.join(SEGCACHE, f"seg{si:03d}.pkl"), "rb"))
        keep = [i for i, b in enumerate(bars) if DEV_YEARS[0] <= b.ts_et.year <= DEV_YEARS[1]]
        if not keep:
            pickle.dump({"empty": True}, open(outp, "wb")); done += 1
            print(f"[{si+1}/{nseg}] seg{si:03d}: no development-year bars, skipped", flush=True)
            continue
        F = segment_features(bars)
        ts_index = {b.ts_et: i for i, b in enumerate(bars)}
        F32 = {k: (val.astype(np.float32) if isinstance(val, np.ndarray) else val)
               for k, val in F.items()}
        pickle.dump({"feat": F32, "ts_index": ts_index, "n": len(bars)}, open(outp, "wb"))
        done += 1
        print(f"[{si+1}/{nseg}] seg{si:03d}: {len(bars):,} bars, {len(F)} feature arrays", flush=True)
    print(f"feature engine complete: {done}/{nseg} segments", flush=True)

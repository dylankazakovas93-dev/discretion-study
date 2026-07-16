"""
Setup-GRAPH construction under the frozen grammar, structural scoring, and the
three permanent representations (exact graph / reduced graph / feature vector).

Every admissible setup = ORIGIN -> DIRECTIONAL TRANSITION (displacement,
mandatory) -> TRIGGER -> INVALIDATION -> TARGET/EXPIRY. Origins may be liquidity
sweeps, VWAP-band rejections, historical-level reactions, or FVG failures
(iFVG). No single primitive is universally required. Score is computed at the
trigger and NEVER uses the outcome.
"""
import os
import sys
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE)); sys.path.insert(0, _HERE)
import prereg as PR
import engine as E
import primitives as P

TZ = "America/New_York"


def _clip01(x):
    return float(max(0.0, min(1.0, x)))


def structural_score(disp_atr, path_eff, fvg_width_atr, risk_atr, target_R,
                     freshness_sessions, opp_dist_atr):
    """Component structural score in [0,100]; OUTCOME contributes zero."""
    w = PR.SCORE_WEIGHTS
    c = {}
    c["context_coherence"] = 1.0                      # admissible graph => coherent origin
    c["trigger_clarity"] = _clip01(1.0 - abs(np.log((fvg_width_atr + 1e-6) / 0.4)) / 3.0) if fvg_width_atr and fvg_width_atr > 0 else 0.3
    c["displacement_quality"] = _clip01(0.5 * _clip01(disp_atr / 1.5) + 0.5 * _clip01(path_eff))
    c["freshness"] = _clip01(1.0 - freshness_sessions / 20.0)
    c["invalidation_clarity"] = _clip01(1.0 - abs(np.log((risk_atr + 1e-6) / 0.6)) / 3.0) if risk_atr and risk_atr > 0 else 0.3
    c["target_room"] = _clip01((target_R if target_R and target_R > 0 else 0) / 3.0)
    contradiction = _clip01(1.0 - (opp_dist_atr / 1.0)) if (opp_dist_atr is not None and not np.isnan(opp_dist_atr)) else 0.0
    total = (w["context_coherence"] * c["context_coherence"] +
             w["trigger_clarity"] * c["trigger_clarity"] +
             w["displacement_quality"] * c["displacement_quality"] +
             w["freshness"] * c["freshness"] +
             w["invalidation_clarity"] * c["invalidation_clarity"] +
             w["target_room"] * c["target_room"] -
             w["contradiction_penalty"] * contradiction)
    comps = {f"sc_{k}": round(v, 4) for k, v in c.items()}
    comps["sc_contradiction"] = round(contradiction, 4)
    return round(float(max(0.0, total)), 3), comps


def _nearest_target(direction, entry, levels_lowhi, vw, bands, atr):
    """Nearest opposing structural target in the profit direction, per the frozen
    hierarchy. Returns (target_price, kind) or (None, None)."""
    cands = []
    for ext, side in levels_lowhi:
        if direction == "short" and side == "low" and ext < entry:
            cands.append((ext, "level"))
        if direction == "long" and side == "high" and ext > entry:
            cands.append((ext, "level"))
    if vw is not None and not np.isnan(vw):
        if direction == "short" and vw < entry:
            cands.append((vw, "vwap"))
        if direction == "long" and vw > entry:
            cands.append((vw, "vwap"))
    for b in bands:
        if np.isnan(b):
            continue
        if direction == "short" and b < entry:
            cands.append((b, "vwap_band"))
        if direction == "long" and b > entry:
            cands.append((b, "vwap_band"))
    if not cands:
        return (None, None)
    # nearest in profit direction
    if direction == "short":
        t = max(cands, key=lambda x: x[0])  # closest below entry = largest < entry
    else:
        t = min(cands, key=lambda x: x[0])
    return t


def construct(tf, cd, fvgs, ifvgs, levels, vwdf, vwdf_idx, disc_abs=None):
    """Construct admissible setups on one timeframe across ALL absolute segments
    (each segment is one contract). Returns (occurrences, n_rejected)."""
    occ = []
    rejected = 0
    seg = cd.segment_id
    o, h, l, c = cd.o, cd.h, cd.l, cd.c
    fv_by_C = {}
    if not fvgs.empty:
        for _, f in fvgs.iterrows():
            fv_by_C.setdefault((f["direction"], int(f["C_index"])), f)
    lev = levels[levels["sweep_et"].notna()].reset_index(drop=True).copy()
    lev_av = pd.to_datetime(lev["availability_et"], utc=True).dt.tz_localize(None).to_numpy()
    lev_sw = pd.to_datetime(lev["sweep_et"], utc=True).dt.tz_localize(None).to_numpy()
    lev_ext = lev["extreme"].to_numpy(float)
    lev_side = lev["side"].to_numpy()
    lev_fam = lev["family"].to_numpy()
    lev_seg = lev["segment_id"].to_numpy(int)
    lev_id = lev["level_id"].to_numpy()
    # all-levels arrays (for targets: opposing structure, regardless of swept)
    allv = levels.reset_index(drop=True)
    all_av = pd.to_datetime(allv["availability_et"], utc=True).dt.tz_localize(None).to_numpy()
    all_ext = allv["extreme"].to_numpy(float)
    all_side = allv["side"].to_numpy()

    # per-candle VWAP / band arrays (fast index, no .iloc)
    nvw = len(vwdf)
    jmap = np.array([vwdf_idx.get(x, -1) for x in cd.t_avail_utc])
    vwv = vwdf["vwap"].to_numpy()
    bpos = {k: vwdf[f"vwap_+{k}"].to_numpy() for k in PR.VWAP_BANDS}
    bneg = {k: vwdf[f"vwap_-{k}"].to_numpy() for k in PR.VWAP_BANDS}
    jc = np.clip(jmap, 0, nvw - 1)
    cvw = np.where(jmap >= 0, vwv[jc], np.nan)
    cbpos = {k: np.where(jmap >= 0, bpos[k][jc], np.nan) for k in PR.VWAP_BANDS}
    cbneg = {k: np.where(jmap >= 0, bneg[k][jc], np.nan) for k in PR.VWAP_BANDS}

    dedup = set()

    def emit(origin_family, origin_id, origin_extreme, direction, i, F):
        nonlocal rejected
        Cidx = int(F["C_index"])
        atr = cd.atr[Cidx]
        if not atr or atr <= 0 or np.isnan(atr):
            rejected += 1; return
        if direction == "short":
            entry = float(F["lower_boundary"]); stop = float(F["upper_boundary"])
            if not stop > entry:
                rejected += 1; return
        else:
            entry = float(F["upper_boundary"]); stop = float(F["lower_boundary"])
            if not stop < entry:
                rejected += 1; return
        trigger_id = F["id"]
        key = (tf, origin_id, trigger_id)
        if key in dedup:
            rejected += 1; return
        risk = abs(entry - stop)
        risk_atr = risk / atr
        # target: opposing active levels + vwap/bands at trigger close (numpy)
        t1u = cd.t_avail_utc[Cidx]
        amask = all_av <= t1u
        act_ext = all_ext[amask]; act_sd = all_side[amask]
        vw = cvw[Cidx]
        bands = [cbpos[k][Cidx] for k in PR.VWAP_BANDS] + [cbneg[k][Cidx] for k in PR.VWAP_BANDS]
        # vwap side + nearest band (dimensionless)
        vside = ("above" if entry >= vw else "below") if not np.isnan(vw) else None
        nb_lab, nb_dist = None, np.nan
        for k in PR.VWAP_BANDS:
            for sign, arr in (("+", cbpos), ("-", cbneg)):
                b = arr[k][Cidx]
                if np.isnan(b):
                    continue
                dd = abs(entry - b) / atr
                if np.isnan(nb_dist) or dd < nb_dist:
                    nb_dist, nb_lab = dd, f"{sign}{k}"
        tgt, tkind = _nearest_target(direction, entry,
                                     list(zip(act_ext, act_sd)), vw, bands, atr)
        if tgt is None:
            target = entry - PR.FIXED_R_FALLBACK * risk if direction == "short" else entry + PR.FIXED_R_FALLBACK * risk
            tkind = "fixed_R_fallback"
        else:
            target = float(tgt)
        target_R = abs(target - entry) / risk if risk > 0 else np.nan
        opp_dist_atr = abs(target - entry) / atr if atr > 0 else np.nan
        # transition/displacement metrics (the leg that made F)
        A, B = Cidx - 2, Cidx - 1
        net = abs(c[Cidx] - o[A])
        disp_atr = net / atr
        tot = sum(h[k] - l[k] for k in (A, B, Cidx))
        path_eff = net / tot if tot > 0 else np.nan
        fw_atr = float(F["fvg_width_atr"]) if pd.notna(F["fvg_width_atr"]) else np.nan
        # freshness: sessions since origin object availability
        freshness = 0.0
        # score (no outcome)
        score, comps = structural_score(disp_atr, path_eff, fw_atr, risk_atr,
                                        target_R, freshness, opp_dist_atr)
        Topen = pd.Timestamp(cd.t_open[i])
        sess = E.session_of(Topen)
        anchor = E.time_anchor(Topen)
        _src = origin_id.split('-')[-1] if '-' in origin_id else origin_id
        exact_sig = f"{origin_family}({_src})|{direction}|{tf}->DISP->FVG_{F['direction']}->FILL"
        reduced_sig = f"ORIGIN_{origin_family}|{direction}|{tf}->DISPLACEMENT->FVG_RETEST"
        broad_family = f"{origin_family}|{direction}"
        oid = f"OC-{tf}-{Topen.strftime('%Y%m%dT%H%M')}-{direction[0].upper()}-{origin_family[:3]}"
        feat = {
            "direction": direction, "session": sess, "origin_family": origin_family,
            "time_anchor": anchor, "displacement_atr": round(disp_atr, 3),
            "path_efficiency": round(path_eff, 3) if not np.isnan(path_eff) else None,
            "fvg_tf": tf, "fvg_width_atr": round(fw_atr, 3) if not np.isnan(fw_atr) else None,
            "vwap_side": vside, "nearest_vwap_band": nb_lab,
            "nearest_band_dist_atr": round(nb_dist, 3) if nb_dist == nb_dist else None,
            "level_family": origin_family if origin_family in ("HIST_LEVEL", "LIQ_SWEEP") else None,
            "target_distance_R": round(target_R, 3) if target_R == target_R else None,
            "opposing_distance_atr": round(opp_dist_atr, 3) if opp_dist_atr == opp_dist_atr else None,
            "volatility_bucket": _vol_bucket(atr, cd, Cidx),
            "risk_atr": round(risk_atr, 3),
        }
        # up to THREE entry-context conditions (descriptive, not retro filters)
        ctx = [f"origin={origin_family}", f"anchor={anchor}"]
        if vside:
            ctx.append(f"vwap_{vside}")
        ctx = ctx[:PR.MAX_CONTEXT_CONDITIONS]
        dedup.add(key)
        occ.append({
            "context_conditions": " | ".join(ctx), "n_context_conditions": len(ctx),
            "occurrence_id": oid, "setup_def_version": PR.SETUP_DEF_VERSION,
            "tf": tf, "session_globex_day": sess, "segment_id": int(seg[i]),
            "direction": direction, "origin_family": origin_family,
            "origin_object_id": origin_id, "origin_extreme": origin_extreme,
            "trigger_object_id": trigger_id, "trigger_index": int(i), "C_index": Cidx,
            "trigger_ts_et": Topen, "availability_et": pd.Timestamp(cd.t_avail[Cidx]),
            "entry": entry, "structural_stop": stop, "structural_target": target,
            "target_kind": tkind, "risk_points": risk, "risk_atr": round(risk_atr, 3),
            "target_R": round(target_R, 3) if target_R == target_R else np.nan,
            "expiry_E_bars": PR.E_BARS, "resolve_H_1m": PR.H_BARS_1M,
            "exact_graph": exact_sig, "reduced_graph": reduced_sig,
            "broad_family": broad_family,
            "structural_score": score, **comps,
            "primitive_ids": f"ORIGIN:{origin_id} ; TRIGGER_FVG:{trigger_id}",
            "features": feat,
        })

    # ---- A+B) LIQ_SWEEP / HIST_LEVEL origins: bucket level sweeps into candles ----
    t_open_u = cd.t_open_utc; t_avail_u = cd.t_avail_utc
    buckets = {}
    for r in range(len(lev)):
        sw = lev_sw[r]
        i = int(np.searchsorted(t_open_u, sw, side="right")) - 1  # candle with open<=sw
        if i < 0 or i >= cd.n:
            continue
        if sw < t_avail_u[i] and lev_av[r] <= t_open_u[i] and lev_seg[r] == seg[i]:
            buckets.setdefault(i, []).append(r)
    for i, rs in buckets.items():
        for fam in ("LIQ_SWEEP", "HIST_LEVEL"):
            for side in ("high", "low"):
                sel = [r for r in rs if lev_fam[r] == fam and lev_side[r] == side]
                if not sel:
                    continue
                r = max(sel, key=lambda r: lev_ext[r]) if side == "high" else min(sel, key=lambda r: lev_ext[r])
                direction = "short" if side == "high" else "long"
                fdir = "bear" if side == "high" else "bull"
                F = _first_fvg_after(fv_by_C, fdir, i, cd.n)
                if F is None:
                    rejected += 1; continue
                emit(fam, str(lev_id[r]), float(lev_ext[r]), direction, i, F)

    # ---- C) VWAP_BAND origins (band rejection), vectorized over candles ----
    atr = cd.atr
    valid = (atr > 0) & ~np.isnan(atr)
    tol = PR.VWAP_BAND_TOUCH_ATR * 4
    for k in PR.VWAP_BANDS:
        bp = cbpos[k]; bn = cbneg[k]
        up_mask = valid & ~np.isnan(bp) & (cd.h >= bp) & (cd.c < bp) & ((cd.h - bp) <= tol * atr)
        dn_mask = valid & ~np.isnan(bn) & (cd.l <= bn) & (cd.c > bn) & ((bn - cd.l) <= tol * atr)
        for i in np.where(up_mask)[0]:
            F = _first_fvg_after(fv_by_C, "bear", int(i), cd.n)
            if F is not None:
                emit("VWAP_BAND", f"VWAP+{k}-{E.session_of(cd.t_open[int(i)])}", float(bp[i]), "short", int(i), F)
        for i in np.where(dn_mask)[0]:
            F = _first_fvg_after(fv_by_C, "bull", int(i), cd.n)
            if F is not None:
                emit("VWAP_BAND", f"VWAP-{k}-{E.session_of(cd.t_open[int(i)])}", float(bn[i]), "long", int(i), F)
    # D) FVG_FAILURE -> iFVG retest origin
    if ifvgs is not None and not ifvgs.empty:
        avail_to_idx = {t: i for i, t in enumerate(cd.t_avail_utc)}
        for _, iv in ifvgs.iterrows():
            ci = avail_to_idx.get(_utc_ts(pd.Timestamp(iv["conversion_et"])))
            if ci is None:
                continue
            direction = "long" if iv["ifvg_direction"] == "bull" else "short"
            fdir = iv["ifvg_direction"]
            F = _first_fvg_after(fv_by_C, fdir, ci, cd.n)
            if F is None:
                continue
            emit("FVG_FAILURE", str(iv["source_fvg_id"]), float(iv.get("source_upper", np.nan)),
                 direction, ci, F)
    return occ, rejected


# ---- small helpers ----
def _utc_ts(ts):
    ts = pd.Timestamp(ts)
    return np.datetime64(ts.tz_convert("UTC").tz_localize(None)) if ts.tzinfo else np.datetime64(ts)


def _first_fvg_after(fv_by_C, direction, i, n):
    for cidx in range(i + 1, min(i + 1 + PR.R_WINDOW, n)):
        if (direction, cidx) in fv_by_C:
            return fv_by_C[(direction, cidx)]
    return None


def _vwap_val(idx, vwdf, ts):
    j = idx.get(_utc_ts(ts))
    return float(vwdf["vwap"].iloc[j]) if j is not None else np.nan


def _band_vals(idx, vwdf, ts):
    j = idx.get(_utc_ts(ts))
    if j is None:
        return [np.nan] * (2 * len(PR.VWAP_BANDS))
    return [float(vwdf[f"vwap_+{k}"].iloc[j]) for k in PR.VWAP_BANDS] + \
           [float(vwdf[f"vwap_-{k}"].iloc[j]) for k in PR.VWAP_BANDS]


def _vol_bucket(atr, cd, i):
    # dimensionless volatility state: current ATR vs its own trailing median
    hist = P.seg_hist(cd.atr, cd.norm_segment_id, cd.complete, i, 20)
    if hist is None:
        return "unknown"
    med = np.nanmedian(hist)
    if not med or med <= 0:
        return "unknown"
    r = atr / med
    return "low" if r < 0.8 else "high" if r > 1.25 else "normal"

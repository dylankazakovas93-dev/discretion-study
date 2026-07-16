"""
Rolling prior-evidence engine: hierarchical empirical-Bayes shrinkage and the
frozen predicted classification. Operates on RUNNING aggregates (n, wins, sumR)
accumulated ONLY from completed occurrences of strictly earlier trading sessions.
Diagnostic horizons (1/3/5/10/20/all) are reported but NEVER summed as
independent samples.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import prereg as PR


def stats(agg):
    """agg = dict(n, wins, sumR) -> add fav_rate, mean_R."""
    n = agg["n"]
    return {"n": n, "wins": agg["wins"], "losses": n - agg["wins"],
            "fav_rate": (agg["wins"] / n) if n else None,
            "mean_R": (agg["sumR"] / n) if n else None}


def _shrink(child, parent_p, parent_R, K):
    n = child["n"]
    w = n / (n + K) if (n + K) > 0 else 0.0
    p = w * child["fav_rate"] + (1 - w) * parent_p if n > 0 else parent_p
    R = w * child["mean_R"] + (1 - w) * parent_R if n > 0 else parent_R
    return p, R, w


def evaluate(exact_agg, reduced_agg, broad_agg, global_agg):
    ex, red, bro, glo = (stats(exact_agg), stats(reduced_agg),
                         stats(broad_agg), stats(global_agg))
    p0 = glo["fav_rate"] if glo["n"] > 0 else 0.5
    R0 = glo["mean_R"] if glo["n"] > 0 else 0.0
    p_b, R_b, w_b = _shrink(bro, p0, R0, PR.SHRINK_K_BROAD)
    p_r, R_r, w_r = _shrink(red, p_b, R_b, PR.SHRINK_K_REDUCED)
    p_e, R_e, w_e = _shrink(ex, p_r, R_r, PR.SHRINK_K_EXACT)
    # evidence_count = completed EXACT-graph priors (very specific, often sparse);
    # effective_sample_size = completed REDUCED-family priors -- the operating
    # similarity class that drives the shrunk estimate and the classification gate.
    evidence_count = float(ex["n"])
    ess = float(red["n"])
    denom = max(ess, 1.0)
    unc = float(1.96 * ((max(p_e * (1 - p_e), 0.01) / denom) ** 0.5))
    out = {
        "prior_global_p": round(p0, 4), "prior_global_R": round(R0, 4),
        "exact_n": ex["n"], "exact_wins": ex["wins"], "exact_losses": ex["losses"],
        "exact_fav_rate": _r(ex["fav_rate"]), "exact_mean_R": _r(ex["mean_R"]),
        "reduced_n": red["n"], "reduced_fav_rate": _r(red["fav_rate"]), "reduced_mean_R": _r(red["mean_R"]),
        "broad_n": bro["n"], "broad_fav_rate": _r(bro["fav_rate"]), "broad_mean_R": _r(bro["mean_R"]),
        "global_n": glo["n"],
        "w_exact": round(w_e, 3), "w_reduced": round(w_r, 3), "w_broad": round(w_b, 3),
        "shrunk_favorable_probability": round(p_e, 4),
        "shrunk_expected_R": round(R_e, 4),
        "evidence_count": evidence_count,
        "effective_sample_size": ess,
        "uncertainty_halfwidth": round(unc, 4),
    }
    out["final_predicted_class"] = classify(p_e, R_e, ess)
    return out


def classify(p, R, ess):
    if ess < PR.MIN_ESS:
        return "INSUFFICIENT_EVIDENCE"
    if p >= PR.FAVORABLE_PROB and R >= PR.FAVORABLE_R:
        return "FAVORABLE"
    if p <= PR.ADVERSE_PROB or R <= PR.ADVERSE_R:
        return "ADVERSE"
    return "NEUTRAL"


def horizon_summary(session_aggs):
    """session_aggs: ordered list (oldest->newest) of (sess_idx, n, wins, sumR)
    for the reduced family, strictly earlier than the current session. Returns
    diagnostic (non-summed) aggregates for each horizon."""
    out = {}
    for H in PR.EVIDENCE_HORIZONS:
        sel = session_aggs if H == "all" else session_aggs[-H:]
        n = sum(a[1] for a in sel); w = sum(a[2] for a in sel); sr = sum(a[3] for a in sel)
        out[str(H)] = {"sessions": len(sel), "n": n, "wins": w, "losses": n - w,
                       "fav_rate": round(w / n, 4) if n else None,
                       "mean_R": round(sr / n, 4) if n else None}
    return out


def _r(x):
    return round(float(x), 4) if x is not None else None

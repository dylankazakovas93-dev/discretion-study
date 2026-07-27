"""Stage 3/4: bounded predeclared event-sequence grammar search.

Every configuration is a STANDALONE strategy: its predicate is applied to the
complete chronological candidate stream, then one-global-position occupancy is
re-run from scratch. Nothing is sliced out of the Option 3 ledger.

Predicates are frozen below BEFORE any result is inspected. Development years
only (2018-2025).
"""
from __future__ import annotations
import pickle, os, numpy as np, itertools, csv, json
from collections import defaultdict

OUT = "artifacts/broad_discovery"
ANCHORS = ["GLOBEX_1800", "MIDNIGHT_0000", "LONDON_0300", "CASH_0930", "TEN_1000", "NYPM_1330"]
SESSIONS = ["NY_AM", "LONDON", "NY_PM"]
EMA_TFS = [1, 3, 5, 15]
ADX_TFS = [1, 5, 15]
ADX_STATES = [("adx_lt15", 0, 15), ("adx_15_20", 15, 20), ("adx_20_25", 20, 25),
              ("adx_25_35", 25, 35), ("adx_ge35", 35, 1e9)]
BAND_STATES = ["beyond_1sd", "beyond_2sd", "inside_1sd", "reverting_1sd"]
MIN_STOP = 12.0

C = pickle.load(open(os.path.join(OUT, "candidates_with_features.pkl"), "rb"))
C = [c for c in C if c["risk"] >= MIN_STOP]
C.sort(key=lambda z: (z["entry_ts"], z["fkey"]))
n = len(C)
print(f"stream (risk>={MIN_STOP:g}): {n:,}", flush=True)

ent = np.array([c["entry_ts"].value for c in C], dtype=np.int64)
ext = np.array([c["exit_ts"].value for c in C], dtype=np.int64)
pts = np.array([c["points"] for c in C]); rsk = np.array([c["risk"] for c in C])
yr  = np.array([c["sd"].year for c in C])
dirn= np.array([c["direction"] for c in C])
sess= np.array([c["session"] for c in C])
evar= np.array([c["entry_variant"] for c in C])
px  = np.array([c["_px"] for c in C])
FEAT = {k: np.array([c[k] for c in C]) for k in C[0] if k.startswith(("vwap_","vwsd_","vwslope_","ema21_","emaslope_","adx_","pdi_","ndi_"))}
VARIANTS = sorted(set(evar.tolist()))
weeks_total = (C[-1]["sd"] - C[0]["sd"]).days / 7

def band_mask(anchor, state, d):
    vw = FEAT[f"vwap_{anchor}"]; sd = np.maximum(FEAT[f"vwsd_{anchor}"], 1e-9)
    z = (px - vw) / sd
    if state == "beyond_1sd":   return np.where(d > 0, z <= -1.0, z >= 1.0)
    if state == "beyond_2sd":   return np.where(d > 0, z <= -2.0, z >= 2.0)
    if state == "inside_1sd":   return np.abs(z) < 1.0
    if state == "reverting_1sd":return np.where(d > 0, (z > -2.0) & (z < -0.5), (z < 2.0) & (z > 0.5))
    raise ValueError(state)

def occupancy_metrics(mask):
    idx = np.flatnonzero(mask)
    if idx.size < 200: return None
    chosen = []; until = -1
    for i in idx:
        if ent[i] < until: continue
        chosen.append(i); until = ext[i]
    if len(chosen) < 200: return None
    ci = np.array(chosen)
    o = {"trades": len(ci), "per_week": len(ci) / weeks_total}
    for cost in (0.0, 1.0, 2.0):
        r = (pts[ci] - cost) / rsk[ci]
        pos = r[r > 0].sum(); neg = -r[r <= 0].sum()
        eq = np.cumsum(r); mdd = float((eq - np.maximum.accumulate(eq)).min())
        yv = defaultdict(float)
        for y, x in zip(yr[ci], r): yv[y] += x
        t = f"{cost:g}"
        o[f"pf{t}"] = float(pos / neg) if neg > 0 else 0.0
        o[f"net{t}"] = float(r.sum()); o[f"exp{t}"] = float(r.mean())
        o[f"expwk{t}"] = float(r.sum() / weeks_total)
        o[f"mdd{t}"] = mdd
        o[f"posyr{t}"] = int(sum(1 for v in yv.values() if v > 0))
        o[f"yr{t}"] = {int(k): round(v, 2) for k, v in sorted(yv.items())}
    o["win_rate"] = float((pts[ci] > 0).mean())
    return o

results = []
def run(cfg_id, family, desc, mask):
    m = occupancy_metrics(mask)
    rec = {"config_id": cfg_id, "family": family, "description": desc,
           "status": "EVALUATED" if m else "BELOW_MIN_TRADES"}
    if m: rec.update(m)
    results.append(rec)

cid = 0
base = np.ones(n, dtype=bool)
# ---- Family G: existing structure + one market-state predicate + session ----
for s in SESSIONS:
    ms = (sess == s)
    for v in VARIANTS:
        mv = ms & (evar == v)
        if mv.sum() < 200: continue
        cid += 1; run(f"G{cid:05d}", "G", f"{s} | {v} | (no market state)", mv)
        for a in ANCHORS:
            for st in BAND_STATES:
                cid += 1
                run(f"G{cid:05d}", "G", f"{s} | {v} | VWAP({a}) {st}", mv & band_mask(a, st, dirn))
        for tf in EMA_TFS:
            e = FEAT[f"ema21_{tf}"]; sl = FEAT[f"emaslope_{tf}"]
            cid += 1; run(f"G{cid:05d}", "G", f"{s} | {v} | px vs EMA21({tf}m) aligned",
                          mv & np.where(dirn > 0, px > e, px < e))
            cid += 1; run(f"G{cid:05d}", "G", f"{s} | {v} | EMA21({tf}m) slope aligned",
                          mv & np.where(dirn > 0, sl > 0, sl < 0))
        for tf in ADX_TFS:
            ax = FEAT[f"adx_{tf}"]
            for nm, lo, hi in ADX_STATES:
                cid += 1; run(f"G{cid:05d}", "G", f"{s} | {v} | ADX({tf}m) {nm}",
                              mv & (ax >= lo) & (ax < hi))
            cid += 1; run(f"G{cid:05d}", "G", f"{s} | {v} | DI({tf}m) aligned",
                          mv & np.where(dirn > 0, FEAT[f"pdi_{tf}"] > FEAT[f"ndi_{tf}"],
                                                  FEAT[f"ndi_{tf}"] > FEAT[f"pdi_{tf}"]))
print(f"Family G configs: {cid}", flush=True)
# ---- Family H: market state only, structure-agnostic entry trigger ----
for s in SESSIONS:
    ms = (sess == s)
    for a in ANCHORS:
        for st in BAND_STATES:
            bm = ms & band_mask(a, st, dirn)
            cid += 1; run(f"H{cid:05d}", "H", f"{s} | VWAP({a}) {st} | any structure", bm)
            for tf in EMA_TFS:
                e = FEAT[f"ema21_{tf}"]
                cid += 1; run(f"H{cid:05d}", "H", f"{s} | VWAP({a}) {st} | px vs EMA21({tf}m)",
                              bm & np.where(dirn > 0, px > e, px < e))
            for tf in ADX_TFS:
                ax = FEAT[f"adx_{tf}"]
                for nm, lo, hi in ADX_STATES:
                    cid += 1; run(f"H{cid:05d}", "H", f"{s} | VWAP({a}) {st} | ADX({tf}m) {nm}",
                                  bm & (ax >= lo) & (ax < hi))
print(f"total configs: {cid}", flush=True)
json.dump(results, open(os.path.join(OUT, "all_configuration_results.json"), "w"), default=str)
ev = [r for r in results if r["status"] == "EVALUATED"]
print(f"evaluated (>=200 trades): {len(ev)}", flush=True)
surv = [r for r in ev if r["posyr1"] == 8 and r["pf1"] > 1.10 and r["per_week"] >= 1.5 and r["trades"] >= 500]
print(f"8/8 survivors (PF@1>1.10, >=1.5/wk, >=500 trades): {len(surv)}", flush=True)
surv.sort(key=lambda r: -r["pf1"])
for r in surv[:25]:
    print(f"  {r['config_id']} {r['description'][:66]:<66} n={r['trades']:>5} "
          f"/wk={r['per_week']:>5.1f} PF1={r['pf1']:.4f} PF2={r['pf2']:.4f} py2={r['posyr2']}/8")

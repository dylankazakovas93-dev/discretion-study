"""
Invariant tests for the rolling recognizer prototype. Mixes unit tests on the
pure causal functions with assertions against the committed replay outputs.
Exits non-zero on any failure.
"""
import os
import sys
import inspect
import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE)); sys.path.insert(0, _HERE)
import primitives as P
import prereg as PR
import engine as E
import graph as G
import evidence as EV

OUT = os.path.join(_HERE, "outputs")
TZ = "America/New_York"
ROLL = pd.Timestamp(PR.ROLL_CUTOFF_ET, tz=TZ)
res = []


def chk(name, cond, detail=""):
    res.append((name, bool(cond), detail))


def ts(col):
    return pd.to_datetime(col, utc=True).dt.tz_convert(TZ)


# ---------- unit: ATR excludes current candle ----------
def _mk_candles(h, l, c, seg=None, norm=None):
    n = len(c); o = np.array(c, float)
    seg = np.zeros(n, int) if seg is None else np.array(seg)
    norm = np.zeros(n, int) if norm is None else np.array(norm)
    comp = np.ones(n, bool)
    to = np.array([np.datetime64("2026-01-01T00:00") + np.timedelta64(i, "m") for i in range(n)])
    atr, av = P.compute_atr(o, np.array(h, float), np.array(l, float), np.array(c, float),
                            seg, norm, comp, to, period=3)
    return atr


atr = _mk_candles(h=[10, 11, 12, 13, 14, 15], l=[9, 10, 11, 12, 13, 14],
                  c=[9.5, 10.5, 11.5, 12.5, 13.5, 14.5])
# TR for i>=1 within same seg = max(H-L, |H-Cprev|, |L-Cprev|); here ~ constant 2 after first
chk("ATR excludes current candle (period-3 mean of prior TRs)",
    np.isnan(atr[0]) and np.isnan(atr[2]) and not np.isnan(atr[3]),
    f"atr={np.round(atr,3)}")
# changing current candle must NOT change its own ATR (ATR uses only predecessors)
atr2 = _mk_candles(h=[10, 11, 12, 13, 14, 999], l=[9, 10, 11, 12, 13, 14],
                   c=[9.5, 10.5, 11.5, 12.5, 13.5, 14.5])
chk("current candle cannot change its own ATR", atr[5] == atr2[5] or (np.isnan(atr[5]) and np.isnan(atr2[5])))

# ---------- unit: same-1m-bar ambiguity ----------
import replay as RP
o_amb = {"segment_id": 0, "entry": 100.0, "structural_stop": 102.0,
         "structural_target": 98.0, "risk_points": 2.0, "direction": "short",
         "availability_et": pd.Timestamp("2026-07-06 10:00", tz=TZ), "tf": "5m"}
seg1m = {0: {"t": np.array([np.datetime64("2026-07-06T14:00") + np.timedelta64(i, "m") for i in range(30)]),
             "h": np.array([100.5] * 5 + [103.0] + [100.5] * 24),   # bar 5 spans stop+target
             "l": np.array([99.5] * 5 + [97.0] + [99.5] * 24),
             "c": np.array([100.0] * 30)}}
chk("same-1m-bar stop+target => AMBIGUOUS", RP.evaluate_outcome(o_amb, seg1m)["outcome"] == "AMBIGUOUS")

# ---------- unit: shrinkage ----------
zero = {"n": 0, "wins": 0, "sumR": 0.0}
big = {"n": 100, "wins": 80, "sumR": 40.0}
ev_sparse = EV.evaluate(zero, zero, zero, big)   # only global evidence
chk("empty exact/reduced shrink toward parent/global",
    abs(ev_sparse["shrunk_favorable_probability"] - 0.8) < 1e-6)
p, R, w = EV._shrink({"n": 0, "wins": 0, "fav_rate": None, "mean_R": None}, 0.3, 0.1, 10)
chk("shrink with n=0 returns parent", p == 0.3 and w == 0.0)
p2, R2, w2 = EV._shrink({"n": 1000, "wins": 900, "fav_rate": 0.9, "mean_R": 0.5}, 0.3, 0.1, 10)
chk("shrink with large n approaches child", abs(p2 - 0.9) < 0.02)

# ---------- unit: classification / insufficient evidence ----------
chk("ESS<MIN => INSUFFICIENT_EVIDENCE", EV.classify(0.9, 0.5, PR.MIN_ESS - 1) == "INSUFFICIENT_EVIDENCE")
chk("favorable gate", EV.classify(0.6, 0.2, 50) == "FAVORABLE")
chk("adverse gate (low prob)", EV.classify(0.4, 0.2, 50) == "ADVERSE")
chk("adverse gate (neg R)", EV.classify(0.6, -0.2, 50) == "ADVERSE")
chk("neutral", EV.classify(0.5, 0.05, 50) == "NEUTRAL")

# ---------- unit: outcome cannot affect structural score ----------
sig = inspect.signature(G.structural_score)
chk("structural_score takes NO outcome argument",
    not any("outcome" in p or "win" in p or "realized" in p for p in sig.parameters))

# ---------- unit: causal VWAP + bands + reset ----------
et = pd.DataFrame({
    "ts_open_et": pd.date_range("2026-07-06 09:28", periods=6, freq="1min", tz=TZ),
    "high": [10, 10, 12, 12, 12, 12], "low": [10, 10, 8, 8, 8, 8],
    "close": [10, 10, 10, 10, 10, 10], "volume": [1, 1, 1, 1, 1, 1],
    "segment_id": [6] * 6})
et["ts_close_et"] = et["ts_open_et"] + pd.Timedelta(minutes=1)
et["minutes_of_day"] = et["ts_open_et"].dt.hour * 60 + et["ts_open_et"].dt.minute
vw = E.compute_vwap_1m(et)
chk("VWAP undefined before 09:30 reset", np.isnan(vw["vwap"].iloc[0]))
chk("VWAP resets at 09:30 (first session bar = its own TP)",
    abs(vw["vwap"].iloc[2] - 10.0) < 1e-9, f'{vw["vwap"].iloc[2]}')
for k in (1.618, 2.618, 3.618):
    chk(f"VWAP band +/-{k} present", f"vwap_+{k}" in vw.columns and f"vwap_-{k}" in vw.columns)
chk("VWAP band available only after bar close (ts_close_et column present)", "ts_close_et" in vw.columns)

# ================= assertions against committed replay outputs =================
jp = os.path.join(OUT, "setup_occurrences_july.csv")
if os.path.exists(jp):
    j = pd.read_csv(jp)
    allo = pd.read_csv(os.path.join(OUT, "setup_occurrences_all.csv"))

    chk("July occurrences exist", len(j) > 0)
    # graph ordering + coherence
    chk("exact graph ordering ORIGIN->DISP->FVG->FILL",
        j["exact_graph"].str.contains("->DISP").all() and j["exact_graph"].str.endswith("FILL").all())
    chk("reduced graph ordering", j["reduced_graph"].str.startswith("ORIGIN_").all() and
        j["reduced_graph"].str.endswith("FVG_RETEST").all())
    sh = j[j.direction == "short"]; lo = j[j.direction == "long"]
    chk("coherent geometry short stop>entry", (sh.structural_stop > sh.entry).all() if len(sh) else True)
    chk("coherent geometry long stop<entry", (lo.structural_stop < lo.entry).all() if len(lo) else True)
    # <=3 context conditions
    chk("<=3 context conditions", (j.n_context_conditions <= 3).all())
    # absolute structures do not cross the roll: all July occ in the NQU6 segment
    chk("July occurrences all in discovery abs segment (6)", (j.segment_id == 6).all())
    # active post-roll NQU6 structures only: no referenced ts before roll cutoff
    for col in ["trigger_ts_et", "availability_et"]:
        chk(f"July {col} after roll cutoff", (ts(j[col]) >= ROLL).all())
    # dedup: unique (tf, origin_object_id, trigger_object_id)
    chk("deterministic dedup (unique origin+trigger episode)",
        not allo.duplicated(["tf", "origin_object_id", "trigger_object_id"]).any())
    # no raw-point cross-contract magnitude fields in feature vector
    feat_cols = [c for c in j.columns if c.startswith("feat_")]
    banned = [c for c in feat_cols if c.endswith(("_points",)) or c in ("feat_entry", "feat_price")]
    chk("feature vector has no raw-point magnitude", len(banned) == 0, f"{banned}")
    chk("feature vector uses ATR/dimensionless magnitudes",
        "feat_displacement_atr" in j.columns and "feat_fvg_width_atr" in j.columns and "feat_risk_atr" in j.columns)
    # losing setups retained
    chk("losing setups retained in ledger", (j.outcome == "LOSS").sum() > 0)
    chk("all outcome categories valid",
        set(j.outcome) <= {"WIN", "LOSS", "AMBIGUOUS", "EXPIRED", "INCOMPLETE"})
    # incomplete/expired/ambiguous excluded from evidence: realized_R only for WIN/LOSS
    comp = j[j.outcome.isin(["WIN", "LOSS"])]
    noncomp = j[~j.outcome.isin(["WIN", "LOSS"])]
    chk("only WIN/LOSS carry realized_R", comp.realized_R.notna().all() and noncomp.realized_R.isna().all())
    # prediction fields present and separated
    for c in ["structural_score", "shrunk_expected_R", "shrunk_favorable_probability",
              "evidence_count", "effective_sample_size", "uncertainty_halfwidth", "final_predicted_class"]:
        chk(f"prediction field {c} present", c in j.columns)
    chk("classes within frozen set",
        set(j.final_predicted_class) <= {"FAVORABLE", "NEUTRAL", "ADVERSE", "INSUFFICIENT_EVIDENCE"})
    # prior evidence uses only earlier sessions: ESS non-decreasing over sessions
    fam = j.reduced_graph.value_counts().idxmax()
    sub = allo[allo.reduced_graph == fam].sort_values("trigger_ts_et")
    ess_by_sess = sub.groupby("session_globex_day")["effective_sample_size"].max()
    chk("ESS non-decreasing across sessions (earlier-only evidence)",
        (np.diff(ess_by_sess.values) >= 0).all() if len(ess_by_sess) > 1 else True)
else:
    chk("replay outputs present", False, "run replay.py first")

npass = sum(1 for _, ok, _ in res if ok)
for n, ok, d in res:
    if not ok:
        print(f"FAIL: {n}  {d}")
print(f"\n{npass}/{len(res)} recognizer checks passed; {len(res) - npass} failed.")
sys.exit(1 if npass != len(res) else 0)

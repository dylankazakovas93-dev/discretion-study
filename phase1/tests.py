"""
Phase 1 invariant tests. Run after run.py. Asserts the causal/continuity
guarantees the study depends on. Exits non-zero on any failure.
"""
import glob
import json
import os
import sys
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), "outputs")
LED = os.path.join(OUT, "ledgers")
TZ = "America/New_York"
# Post-seam threshold: nothing emitted may reference data from before the seam
# (warm-up ends 2026-06-07). July 1 sits inside the 28-day seam gap, so any
# emitted timestamp >= this proves no warm-up interaction. (Daily buckets are
# labelled by their 18:00 ET open, so a hard 20:00 cutoff would false-positive.)
SEG_START = pd.Timestamp("2026-07-01 00:00", tz=TZ)
DISC_SEG = 25

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def ts(col):
    return pd.to_datetime(col, utc=True).dt.tz_convert(TZ)


# ---- expected discovery structural counts (must be stable vs causal changes) ----
EXPECT = {
    "fvg_1m": 1136, "ifvg_1m": 1103, "fvg_5m": 274, "fvg_15m": 90,
    "fvg_30m": 40, "fvg_1h": 22, "fvg_4h": 5, "fvg_daily": 2,
    "rejection_blocks_1m": 13082, "displacement_1m": 39246, "liquidity": 50,
}
counts = json.load(open(os.path.join(OUT, "ledger_counts.json")))
for k, v in EXPECT.items():
    check(f"count {k}=={v}", counts.get(k) == v, f"got {counts.get(k)}")

# ---- all HTF candle ledgers carry completeness + availability + segment ----
for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "daily"]:
    d = pd.read_csv(os.path.join(OUT, f"htf_candles_{tf}.csv"))
    for col in ["complete", "availability_et", "segment_id", "spans_segment_boundary",
                "bucket_open_et", "bucket_close_et", "n_source_minutes"]:
        check(f"{tf} has {col}", col in d.columns)

# ---- daily span fix: full discovery days = 1380 min, 18:00->16:59, complete ----
dd = pd.read_csv(os.path.join(OUT, "htf_candles_daily.csv"))
dd["bo"] = ts(dd["bucket_open_et"])
full = dd[(dd.bo >= pd.Timestamp("2026-07-06 18:00", tz=TZ)) &
          (dd.bo <= pd.Timestamp("2026-07-09 18:00", tz=TZ))]
check("daily full days == 1380 min", (full.n_source_minutes == 1380).all(),
      f"{sorted(full.n_source_minutes.unique())}")
check("daily full days complete", full.complete.astype(str).isin(["True", "true"]).all())

# ---- every emitted structure is in the discovery segment; none pre-seam ----
def all_ts_after_seam(df, cols):
    ok = True
    for c in cols:
        if c in df.columns and df[c].notna().any():
            tmin = ts(df[df[c].notna()][c]).min()
            if tmin < SEG_START:
                ok = False
    return ok

for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "daily"]:
    f = pd.read_csv(os.path.join(LED, f"fvg_{tf}.csv"))
    if not f.empty:
        check(f"fvg_{tf} all segment=={DISC_SEG}", (f.segment_id == DISC_SEG).all())
        check(f"fvg_{tf} A/C/avail/fill after seam",
              all_ts_after_seam(f, ["A_open_et", "C_open_et", "availability_et",
                                     "full_fill_et", "invalidation_et", "first_wick_entry_et"]))
    rb = pd.read_csv(os.path.join(LED, f"rejection_blocks_{tf}.csv"))
    if not rb.empty:
        check(f"rej_{tf} all segment=={DISC_SEG}", (rb.segment_id == DISC_SEG).all())
        check(f"rej_{tf} source/invalidation after seam",
              all_ts_after_seam(rb, ["source_open_et", "availability_et",
                                      "invalidation_et", "first_body_overlap_et"]))
    dp = pd.read_csv(os.path.join(LED, f"displacement_{tf}.csv"))
    if not dp.empty:
        check(f"disp_{tf} all segment=={DISC_SEG}", (dp.segment_id == DISC_SEG).all())
        check(f"disp_{tf} start/end after seam",
              all_ts_after_seam(dp, ["start_open_et", "end_open_et", "availability_et"]))

liq = pd.read_csv(os.path.join(LED, "liquidity_references.csv"))
check("liquidity all segment==disc", (liq.segment_id == DISC_SEG).all())
check("liquidity availability after seam", all_ts_after_seam(liq, ["availability_et", "sweep_et"]))

# ---- roll decision: current session never in its own decision ----
rl = pd.read_csv(os.path.join(LED, "roll_decisions.csv"))
nonboot = rl[~rl.is_bootstrap]
check("roll: evidence != own session (non-bootstrap)",
      (nonboot.evidence_session != nonboot.session_globex_day).all())
check("roll: only disclosed bootstraps at data-start and seam",
      set(rl[rl.is_bootstrap].session_globex_day) <= {"2025-01-02", "2026-07-06"},
      f"{sorted(rl[rl.is_bootstrap].session_globex_day)}")
check("roll: July sessions all NQU6",
      (rl[rl.session_globex_day.between('2026-07-06', '2026-07-13')].selected_contract == "NQU6").all())

# ---- validity: daily prev10/20/40 all null; 4h prev40 all null in July ----
vt = pd.read_csv(os.path.join(LED, "trailing_validity_table.csv"))
dn = vt[vt.tf == "daily"]
check("daily prev10/20/40 all null in July", (dn.valid_count == 0).all())
h4 = vt[(vt.tf == "4h") & (vt.horizon_N == 40)]
check("4h prev40 all null in July", (h4.valid_count == 0).all())
h1 = vt[(vt.tf == "1m")]
check("1m prev10/20/40 fully valid", (h1.null_count == 0).all())

# ---- iFVG conversions reference same-segment source FVGs ----
for tf in ["1m", "5m"]:
    fv = pd.read_csv(os.path.join(LED, f"fvg_{tf}.csv"))
    iv = pd.read_csv(os.path.join(LED, f"ifvg_{tf}.csv"))
    if not iv.empty:
        check(f"ifvg_{tf} conversion after seam", all_ts_after_seam(iv, ["conversion_et"]))

# ---- report ----
npass = sum(1 for _, ok, _ in results if ok)
nfail = len(results) - npass
for name, ok, detail in results:
    if not ok:
        print(f"FAIL: {name}  {detail}")
print(f"\n{npass}/{len(results)} checks passed; {nfail} failed.")
sys.exit(1 if nfail else 0)

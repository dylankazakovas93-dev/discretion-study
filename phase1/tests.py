"""
Phase 1 invariant tests (frozen-roll + dual-segment model). Run after run.py.
Asserts the causal / continuity / roll guarantees. Exits non-zero on failure.
"""
import json
import os
import sys
import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), "outputs")
LED = os.path.join(OUT, "ledgers")
TZ = "America/New_York"
ROLL_CUTOFF = pd.Timestamp("2026-06-15 18:00", tz=TZ)   # frozen June roll
DISC_ABS_SEG = 6      # NQU6 absolute segment
DISC_NORM_SEG = 0     # single normalization segment across all contracts

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def ts(col):
    return pd.to_datetime(col, utc=True).dt.tz_convert(TZ)


counts = json.load(open(os.path.join(OUT, "ledger_counts.json")))

# FVG + rejection + liquidity counts are STABLE (July source candles unchanged)
STABLE = {
    "fvg_1m": 1136, "fvg_5m": 274, "fvg_15m": 90, "fvg_30m": 40, "fvg_1h": 22,
    "fvg_4h": 5, "fvg_daily": 2,
    "rejection_blocks_1m": 13082, "rejection_blocks_5m": 2618,
    "rejection_blocks_daily": 10, "liquidity": 50,
}
for k, v in STABLE.items():
    check(f"stable count {k}=={v}", counts.get(k) == v, f"got {counts.get(k)}")

# iFVG / displacement legitimately INCREASE (pre-July NQU6 context now in-segment)
check("ifvg_daily grew (pre-roll NQU6 maintained)", counts["ifvg_daily"] >= 1)
check("displacement_daily grew (legs no longer seam-clipped)", counts["displacement_daily"] >= 24)

# HTF candle ledgers carry completeness + availability + BOTH segment ids
for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "daily"]:
    d = pd.read_csv(os.path.join(OUT, f"htf_candles_{tf}.csv"))
    for col in ["complete", "availability_et", "segment_id", "norm_segment_id",
                "spans_segment_boundary", "bucket_open_et", "n_source_minutes"]:
        check(f"{tf} has {col}", col in d.columns)

# daily span fix: full discovery days = 1380 min, complete
dd = pd.read_csv(os.path.join(OUT, "htf_candles_daily.csv"))
dd["bo"] = ts(dd["bucket_open_et"])
full = dd[(dd.bo >= pd.Timestamp("2026-07-06 18:00", tz=TZ)) &
          (dd.bo <= pd.Timestamp("2026-07-09 18:00", tz=TZ))]
check("daily full days == 1380 min", (full.n_source_minutes == 1380).all())
check("daily full days complete", full.complete.astype(str).isin(["True", "true"]).all())

# every emitted structure is in the discovery ABSOLUTE segment (NQU6, id 6),
# and references NO data before the frozen roll cutoff (no NQM6 leak).
def none_before_roll(df, cols):
    for c in cols:
        if c in df.columns and df[c].notna().any():
            if ts(df[df[c].notna()][c]).min() < ROLL_CUTOFF:
                return False
    return True

for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "daily"]:
    f = pd.read_csv(os.path.join(LED, f"fvg_{tf}.csv"))
    if not f.empty:
        check(f"fvg_{tf} abs segment=={DISC_ABS_SEG}", (f.segment_id == DISC_ABS_SEG).all())
        check(f"fvg_{tf} no data before roll",
              none_before_roll(f, ["A_open_et", "C_open_et", "availability_et",
                                    "full_fill_et", "invalidation_et"]))
    rb = pd.read_csv(os.path.join(LED, f"rejection_blocks_{tf}.csv"))
    if not rb.empty:
        check(f"rej_{tf} abs segment=={DISC_ABS_SEG}", (rb.segment_id == DISC_ABS_SEG).all())
        check(f"rej_{tf} no data before roll",
              none_before_roll(rb, ["source_open_et", "availability_et", "invalidation_et"]))
    dp = pd.read_csv(os.path.join(LED, f"displacement_{tf}.csv"))
    if not dp.empty:
        check(f"disp_{tf} abs segment=={DISC_ABS_SEG}", (dp.segment_id == DISC_ABS_SEG).all())
        check(f"disp_{tf} no data before roll",
              none_before_roll(dp, ["start_open_et", "end_open_et", "availability_et"]))

liq = pd.read_csv(os.path.join(LED, "liquidity_references.csv"))
check("liquidity abs segment==disc", (liq.segment_id == DISC_ABS_SEG).all())
check("liquidity no data before roll", none_before_roll(liq, ["availability_et", "sweep_et"]))

# iFVG conversions reference NQU6 (post-roll) FVGs only
for tf in ["1m", "5m", "daily"]:
    iv = pd.read_csv(os.path.join(LED, f"ifvg_{tf}.csv"))
    if not iv.empty:
        check(f"ifvg_{tf} conversion after roll", none_before_roll(iv, ["conversion_et"]))
        check(f"ifvg_{tf} source after roll", none_before_roll(iv, ["source_availability_et"]))

# frozen roll schedule: exact June cutoff, NQM6 -> NQU6
rs = pd.read_csv(os.path.join(LED, "roll_schedule.csv"))
june = rs[rs.contract == "NQM6"]
check("june cutoff == 2026-06-15 18:00 ET",
      not june.empty and ts(june.roll_out_cutoff_et).iloc[0] == ROLL_CUTOFF,
      f"{ts(june.roll_out_cutoff_et).iloc[0] if not june.empty else 'missing'}")
check("june rolls NQM6 -> NQU6", not june.empty and june.rolls_into.iloc[0] == "NQU6")

# validity: scale-invariant normalization crosses contracts -> ALL horizons valid
vt = pd.read_csv(os.path.join(LED, "trailing_validity_table.csv"))
check("all trailing horizons fully valid (0 null)", (vt.null_count == 0).all(),
      f"{int(vt.null_count.sum())} nulls remain")
check("daily prev40 valid", (vt[(vt.tf == "daily") & (vt.horizon_N == 40)].valid_count > 0).all())
check("discovery norm segment == 0 (spans contracts)",
      (vt.discovery_norm_segment_id == DISC_NORM_SEG).all())

# ---- Phase 1B: ATR normalization ----
rb5 = pd.read_csv(os.path.join(LED, "rejection_blocks_5m.csv"))
for col in ["atr_value", "atr_availability_et", "body_atr", "range_atr", "dwick_atr"]:
    check(f"rejection has {col}", col in rb5.columns)
check("rejection ATR-normalized non-null in July", rb5.body_atr.notna().all())
# causal: ATR availability (candle open) strictly precedes the candle availability (close)
check("ATR availability precedes candle availability",
      (ts(rb5.atr_availability_et) < ts(rb5.availability_et)).all())
d5 = pd.read_csv(os.path.join(LED, "displacement_5m.csv"))
for col in ["net_move_atr", "total_distance_atr", "atr_value", "atr_availability_et"]:
    check(f"displacement has {col}", col in d5.columns)
f5 = pd.read_csv(os.path.join(LED, "fvg_5m.csv"))
check("fvg has fvg_width_atr", "fvg_width_atr" in f5.columns and f5.fvg_width_atr.notna().all())

# ---- Phase 1B: candidate setups ----
sp = os.path.join(OUT, "candidate_setups", "candidate_setups.csv")
if os.path.exists(sp):
    cs = pd.read_csv(sp)
    check("5-10 candidate setups", 5 <= len(cs) <= 10, f"got {len(cs)}")
    for col in ["candidate_id", "direction", "trigger_ts_et", "swept_source", "entry",
                "structural_stop", "structural_target", "expiry_bars_E", "outcome",
                "primitive_ids", "context_conditions", "fvg_id"]:
        check(f"setup has {col}", col in cs.columns)
    check("setup outcomes in allowed set",
          set(cs.outcome) <= {"win", "loss", "ambiguous", "incomplete"}, f"{set(cs.outcome)}")
    # coherent geometry per direction
    sh = cs[cs.direction == "short"]; lo = cs[cs.direction == "long"]
    check("short stop above entry", (sh.structural_stop > sh.entry).all() if len(sh) else True)
    check("long stop below entry", (lo.structural_stop < lo.entry).all() if len(lo) else True)
    # selected chronologically (not by outcome)
    check("setups chronological", (ts(cs.trigger_ts_et).is_monotonic_increasing))
    # all triggers in the July discovery week
    check("setup triggers in July 6-10",
          ((ts(cs.trigger_ts_et) >= pd.Timestamp("2026-07-06", tz=TZ)) &
           (ts(cs.trigger_ts_et) < pd.Timestamp("2026-07-11", tz=TZ))).all())
    # no data before the roll referenced
    check("setup swept levels after roll (NQU6 initial state)",
          none_before_roll(cs, ["fvg_avail_et"]))

npass = sum(1 for _, ok, _ in results if ok)
nfail = len(results) - npass
for name, ok, detail in results:
    if not ok:
        print(f"FAIL: {name}  {detail}")
print(f"\n{npass}/{len(results)} checks passed; {nfail} failed.")
sys.exit(1 if nfail else 0)

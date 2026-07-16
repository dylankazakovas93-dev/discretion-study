"""
PREREGISTERED FROZEN PARAMETERS for the rolling causal pattern-recognizer.

Committed BEFORE any July outcome is exposed to the recognizer. No value in this
file may be tuned on July data. See PREREGISTRATION.md for the prose protocol.
"""

SETUP_DEF_VERSION = "cg-recognizer-v1.0.0"

# ---- data / timeframes ----
# BOUNDED prototype window: setups are instantiated on trigger sessions at/after
# this date (full data before it still feeds ATR/level/VWAP lookback). This is a
# preregistered scope bound, NOT a July tuning choice.
PRIOR_WINDOW_START_ET = "2026-01-01 00:00"
SETUP_TFS = ["5m", "15m"]          # timeframes on which setups are instantiated
HTF_STATE_TFS = ["1h", "4h"]        # higher-timeframe context state
ATR_PERIOD = 14                     # inherited from Phase 1B (frozen)

# ---- July forward-demonstration boundary (untouched until replay) ----
JULY_START_ET = "2026-07-06 00:00"
JULY_END_ET = "2026-07-11 00:00"    # exclusive
ROLL_CUTOFF_ET = "2026-06-15 18:00" # NQM6 -> NQU6

# ---- graph grammar ----
R_WINDOW = 5      # bars after origin within which the transition FVG must form
E_BARS = 20       # entry must fill within E tf-bars of trigger availability
H_BARS_1M = 120   # outcome resolution horizon (1-minute bars) after entry fill
MAX_CONTEXT_CONDITIONS = 3

# origin families the grammar admits (a setup need NOT start with liquidity)
ORIGIN_FAMILIES = ["LIQ_SWEEP", "VWAP_BAND", "HIST_LEVEL", "FVG_FAILURE"]

# ---- VWAP (causal NY session) ----
VWAP_RESET = "0930"                 # New York session open (RTH), ET
VWAP_BANDS = [1.0, 1.618, 2.0, 2.618, 3.0, 3.618]  # 1.618/2.618/3.618 required
VWAP_BAND_TOUCH_ATR = 0.15          # band interaction tolerance in ATR units

# ---- historical level families ----
LEVEL_LOOKBACKS = {                 # prior-session windows for high/low levels
    "prev_day": 1, "prior_3": 3, "prior_5": 5, "prior_10": 10, "prior_20": 20}

# ---- structural score (components sum to 100; OUTCOME contributes ZERO) ----
SCORE_WEIGHTS = {
    "context_coherence": 20,
    "trigger_clarity": 15,
    "displacement_quality": 25,     # good displacement materially contributes
    "freshness": 10,
    "invalidation_clarity": 10,
    "target_room": 15,
    "contradiction_penalty": 5,     # subtracted if contradictory nearby structure
}

# ---- outcome & R ----
FIXED_R_FALLBACK = 2.0              # diagnostic target only when no structural one
AMBIGUOUS_SAME_1M_BAR = True       # stop+target in one 1m bar -> AMBIGUOUS

# ---- rolling prior-evidence horizons (DIAGNOSTIC, overlapping, not summed) ----
EVIDENCE_HORIZONS = [1, 3, 5, 10, 20, "all"]  # completed prior sessions
RECENCY_HALFLIFE_SESSIONS = 10     # for recency-weighted expectancy

# ---- hierarchical empirical-Bayes shrinkage (frozen pseudo-counts) ----
#   exact-graph  --K_EXACT-->  reduced-family  --K_REDUCED-->  broad-family
#                                              --K_BROAD-->    global prior
SHRINK_K_EXACT = 10.0
SHRINK_K_REDUCED = 20.0
SHRINK_K_BROAD = 40.0

# ---- predicted classification thresholds (frozen a priori) ----
MIN_ESS = 8.0                      # below -> INSUFFICIENT_EVIDENCE
FAVORABLE_PROB = 0.55
FAVORABLE_R = 0.10
ADVERSE_PROB = 0.45
ADVERSE_R = -0.10

# ---- graph deduplication ----
# same interaction episode = (tf, origin_object_id, trigger_object_id); keep the
# earliest trigger; later duplicates are rejected.
DEDUP_KEYS = ["tf", "origin_object_id", "trigger_object_id"]

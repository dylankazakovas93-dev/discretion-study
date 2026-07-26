"""Rejection-block detector for the primitive reset (spec Parts 6-7),
FROZEN as of the activation-rule change described below.

Lifecycle model (updated per Dylan, then frozen):

  * A source candle whose DOMINANT wick clears the 0.20x-real-body floor
    (spec Part 4, frozen) becomes a LIVE rejection block the instant that
    candle closes -- it is a usable structure from the next candle onward,
    NO LONGER gated on the 1.5x-ATR / next-three-candle confirmation.
  * "Activation" (the frozen 1.5x-ATR maximum-favourable-excursion over the
    next three candles) is still computed and tracked, but purely as a
    descriptive status: a live RB is either ACTIVATED (its MFE reached the
    threshold within its 3-candle window) or NOT-ACTIVATED, and every tap it
    receives is stamped with whether it was activated AT THAT MOMENT.
  * Causality: activation is decided incrementally during forward processing
    (set on the exact candle where MFE first crosses the threshold, never by
    reading past the current candle). ``was_activated`` on a tap is simply
    ``rb.activated`` at the tap candle -- monotonic and set causally, so a
    tap that occurs before activation is correctly recorded as not-activated,
    and a setup taken at that tap can be labelled without look-ahead.

Frozen and unchanged: the 0.20 dominant-wick floor, dominant-wick direction
selection, equal-wick ambiguity, the 1.5x-ATR / next-three-candle MFE
computation itself, the common 0.20W traversal/deactivation contract, and
the 8-hour intraday lifetime DURATION. The only lifecycle re-anchoring is
that a live RB's 8h clock now starts at its source-candle close (when it
becomes usable) rather than at activation (which is no longer its birth).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import NQ_TICK
from .timeframes import candle_ts_et, INTRADAY_LIFETIME_TFS
from .traversal import zone_step

CANDIDATE_FLOOR = 0.20
CONFIRM_ATR_MULT = 1.5      # frozen activation threshold (descriptive only now)
CONFIRM_WINDOW = 3          # frozen activation window (next 3 completed candles)
LIFETIME_HOURS = 8


@dataclass
class RBCandidateRecord:
    id: str
    timeframe: int
    segment_id: int
    direction: str            # "bullish" / "bearish"
    source_seq: int
    source_ts: object
    source_ohlc: tuple

    relevant_wick_length: float
    opposite_wick_length: float
    real_body_length: float
    body_was_zero: bool
    total_range: float
    wick_body_ratio: float
    wick_range_ratio: float
    dominant_wick_ratio: float   # relevant_wick / max(opposite_wick, 1 tick) -- grading only
    atr_at_source_close: float | None

    zone_lo: float
    zone_hi: float

    # --- activation (descriptive status, NOT a gate) ---
    mfe_after_1: float | None = None
    mfe_after_2: float | None = None
    mfe_after_3: float | None = None
    mfe_after_1_atr: float | None = None
    mfe_after_2_atr: float | None = None
    mfe_after_3_atr: float | None = None
    activated: bool = False
    activation_candle_number: int | None = None   # 1/2/3 within the window
    activation_seq: int | None = None
    activation_ts: object = None

    # --- live lifecycle (from source-candle close) ---
    live: bool = True
    first_tap_ts: object = None
    first_tap_seq: int | None = None
    first_tap_was_activated: bool | None = None
    tap_events: list = field(default_factory=list)   # [{seq, ts, was_activated}]
    max_penetration: float = 0.0
    deactivation_ts: object = None
    deactivation_reason: str | None = None
    touched: bool = False

    # internal running state for causal activation (not serialized)
    _proximal: float = 0.0
    _run_extreme: float | None = None

    def was_activated_at(self, seq: int) -> bool:
        """Causal query: was this RB activated as of completed candle ``seq``?
        Safe for setup construction -- never reports activation before it
        actually occurred."""
        return self.activation_seq is not None and self.activation_seq <= seq


def _lifetime_check(tf: int, anchor_ts, now_ts, touched: bool) -> str | None:
    if tf not in INTRADAY_LIFETIME_TFS:
        return None
    elapsed = now_ts - anchor_ts
    if elapsed >= __import__("pandas").Timedelta(hours=LIFETIME_HOURS):
        return "EXPIRED_ACTIVE_8H" if touched else "EXPIRED_UNTOUCHED_8H"
    return None


def detect_rejection_blocks(bars, tf: int, series, atr, registry) -> list[RBCandidateRecord]:
    """Every dominant-wick floor-passing source candle becomes a live RB from
    its close; activation is tracked descriptively and never gates usability.
    Tracking of a new RB begins at the candle after its source (it is never
    processed against its own source candle)."""
    out: list[RBCandidateRecord] = []
    active: list[RBCandidateRecord] = []

    for i, c in enumerate(series):
        # 1) advance live RBs under activation + traversal, oldest first
        still: list[RBCandidateRecord] = []
        tapped_rbs: list[RBCandidateRecord] = []
        for rb in active:
            if c.segment_id != rb.segment_id:
                rb.deactivation_ts = candle_ts_et(series[i - 1]) if i > 0 else rb.source_ts
                rb.deactivation_reason = "DATA_END_ACTIVE"
                rb.live = False
                continue
            ts = candle_ts_et(c)
            lo, hi = rb.zone_lo, rb.zone_hi
            sign = 1 if rb.direction == "bullish" else -1

            # (a) causal activation: frozen 1.5-ATR next-3-candle MFE, applied
            # incrementally on the candle where the threshold is first crossed.
            pos = i - rb.source_seq   # 1, 2, 3, ... candles after source
            if not rb.activated and 1 <= pos <= CONFIRM_WINDOW:
                a = rb.atr_at_source_close
                if rb.direction == "bullish":
                    rb._run_extreme = c.high if rb._run_extreme is None else max(rb._run_extreme, c.high)
                    mfe = rb._run_extreme - rb._proximal
                else:
                    rb._run_extreme = c.low if rb._run_extreme is None else min(rb._run_extreme, c.low)
                    mfe = rb._proximal - rb._run_extreme
                mfe_atr = (mfe / a) if a else None
                if pos == 1:
                    rb.mfe_after_1, rb.mfe_after_1_atr = mfe, mfe_atr
                elif pos == 2:
                    rb.mfe_after_2, rb.mfe_after_2_atr = mfe, mfe_atr
                elif pos == 3:
                    rb.mfe_after_3, rb.mfe_after_3_atr = mfe, mfe_atr
                if mfe_atr is not None and mfe_atr >= CONFIRM_ATR_MULT:
                    rb.activated = True
                    rb.activation_candle_number = pos
                    rb.activation_seq = i
                    rb.activation_ts = ts

            # (b) tap / traversal under the common contract
            if rb.direction == "bullish":
                reached = c.low <= hi
                pen = max(0.0, lo - c.low)
            else:
                reached = c.high >= lo
                pen = max(0.0, c.high - hi)
            if reached:
                tapped_rbs.append(rb)
                was_act = rb.activated   # causal: set on this or an earlier candle
                rb.tap_events.append({"seq": i, "ts": ts, "was_activated": was_act})
                if rb.first_tap_ts is None:
                    rb.first_tap_ts = ts
                    rb.first_tap_seq = i
                    rb.first_tap_was_activated = was_act
                    rb.touched = True
                if pen > rb.max_penetration:
                    rb.max_penetration = pen

            step = zone_step(sign, lo, hi, c)
            if step.deactivated:
                rb.deactivation_ts = ts
                rb.deactivation_reason = step.reason
                rb.live = False
                continue
            expiry = _lifetime_check(tf, rb.source_ts, ts, rb.touched)   # anchored at source close
            if expiry is not None:
                rb.deactivation_ts = ts
                rb.deactivation_reason = expiry
                rb.live = False
                continue
            still.append(rb)
        active = still

        # 2) new RB candidate on this completed bar
        a = atr[i]
        if a is None or a <= 0:
            continue
        body = abs(c.close - c.open)
        body_lo = min(c.open, c.close)
        body_hi = max(c.open, c.close)
        lower_wick = body_lo - c.low
        upper_wick = c.high - body_hi
        rng = c.high - c.low
        eff_body = max(body, NQ_TICK)  # numerical-stability floor for the ratio only
        eps = 1e-9
        one_tick = NQ_TICK

        # Dominant-wick direction selection (frozen): direction follows the
        # strictly-longer wick; equal-length wicks emit no active RB.
        candidates = []
        if lower_wick > upper_wick and lower_wick > 0 and (lower_wick / eff_body) >= CANDIDATE_FLOOR - eps:
            candidates.append(("bullish", lower_wick, upper_wick, c.low, body_lo))
        elif upper_wick > lower_wick and upper_wick > 0 and (upper_wick / eff_body) >= CANDIDATE_FLOOR - eps:
            candidates.append(("bearish", upper_wick, lower_wick, body_hi, c.high))
        elif lower_wick == upper_wick and lower_wick > 0 and (lower_wick / eff_body) >= CANDIDATE_FLOOR - eps:
            registry.equal_wick_ambiguous_rbs.append({
                "timeframe": tf, "source_seq": i, "source_ts": candle_ts_et(c),
                "source_ohlc": (c.open, c.high, c.low, c.close),
                "lower_wick": lower_wick, "upper_wick": upper_wick,
                "wick_body_ratio": lower_wick / eff_body,
                "reason": "equal_wick_ambiguous",
            })

        # Existing-structure precedence (frozen): suppress a new candidate only
        # when a tapped same-direction LIVE RB's zone actually overlaps the
        # proposed zone (inclusive interval intersection).
        filtered = []
        for cand in candidates:
            direction, wick, opposite_wick, zlo, zhi = cand
            overlapped = next(
                (rb for rb in tapped_rbs
                 if rb.direction == direction
                 and max(zlo, rb.zone_lo) <= min(zhi, rb.zone_hi)),
                None)
            if overlapped is not None:
                registry.precedence_suppressed_rbs.append({
                    "timeframe": tf, "source_seq": i, "source_ts": candle_ts_et(c),
                    "direction": direction, "source_ohlc": (c.open, c.high, c.low, c.close),
                    "proposed_zone_lo": zlo, "proposed_zone_hi": zhi,
                    "overlapping_rb_id": overlapped.id,
                    "overlapping_rb_zone_lo": overlapped.zone_lo,
                    "overlapping_rb_zone_hi": overlapped.zone_hi,
                    "reason": "overlapping_active_same_direction_rb_tapped",
                })
                continue
            filtered.append(cand)
        candidates = filtered

        for direction, wick, opposite_wick, zlo, zhi in candidates:
            pid = registry.new_id("RB2")
            proximal = zhi if direction == "bullish" else zlo   # frozen MFE proximal
            rec = RBCandidateRecord(
                id=pid, timeframe=tf, segment_id=c.segment_id, direction=direction,
                source_seq=i, source_ts=candle_ts_et(c),
                source_ohlc=(c.open, c.high, c.low, c.close),
                relevant_wick_length=wick, opposite_wick_length=opposite_wick,
                real_body_length=body,
                body_was_zero=(body == 0.0), total_range=rng,
                wick_body_ratio=wick / eff_body,
                wick_range_ratio=(wick / rng) if rng > 0 else None,
                dominant_wick_ratio=wick / max(opposite_wick, one_tick),
                atr_at_source_close=a, zone_lo=zlo, zone_hi=zhi,
                _proximal=proximal,
            )
            registry.register_rb(rec)
            out.append(rec)
            active.append(rec)   # live immediately; first advanced at candle i+1

    if series:
        last_ts = candle_ts_et(series[-1])
        for rb in active:
            rb.deactivation_ts = last_ts
            rb.deactivation_reason = "DATA_END_ACTIVE"
            rb.live = False
    return out

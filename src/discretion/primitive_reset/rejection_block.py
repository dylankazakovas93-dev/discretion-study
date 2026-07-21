"""Exact RB candidate + confirmation detector for the primitive reset
(spec Parts 6-7). No classical local-pivot/swing requirement -- any source
candle whose relevant wick clears the 0.20x-real-body floor is a candidate;
confirmation is decided purely by next-three-candle maximum favourable
excursion against 1.5x same-timeframe ATR.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.bars import NQ_TICK
from .timeframes import candle_ts_et, INTRADAY_LIFETIME_TFS
from .traversal import zone_step

CANDIDATE_FLOOR = 0.20
CONFIRM_ATR_MULT = 1.5
CONFIRM_WINDOW = 3
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

    mfe_after_1: float | None = None
    mfe_after_2: float | None = None
    mfe_after_3: float | None = None
    mfe_after_1_atr: float | None = None
    mfe_after_2_atr: float | None = None
    mfe_after_3_atr: float | None = None
    confirming_candle_number: int | None = None   # 1/2/3 within the window

    confirmed: bool = False
    rejection_reason: str | None = None

    activation_ts: object = None      # == confirmation timestamp
    first_tap_ts: object = None
    max_penetration_after_activation: float = 0.0
    deactivation_ts: object = None
    deactivation_reason: str | None = None
    active: bool = False
    touched: bool = False


def _lifetime_check(tf: int, activation_ts, now_ts, touched: bool) -> str | None:
    if tf not in INTRADAY_LIFETIME_TFS:
        return None
    elapsed = now_ts - activation_ts
    if elapsed >= __import__("pandas").Timedelta(hours=LIFETIME_HOURS):
        return "EXPIRED_ACTIVE_8H" if touched else "EXPIRED_UNTOUCHED_8H"
    return None


def detect_rejection_blocks(bars, tf: int, series, atr, registry) -> list[RBCandidateRecord]:
    """Causally safe two-stage tracking (pending-activation queue, spec
    option B): a candidate confirmed on candle ``j`` (the confirming candle
    itself) is only scheduled to *start* being tracked at candle ``j + 1`` --
    it is never processed against any candle from its own source candle
    through ``j`` inclusive. This is what guarantees
    ``source_ts < activation_ts <= first_tap_ts/deactivation_ts`` for every
    confirmed RB; the frozen confirmation/MFE lookahead computation itself is
    unchanged (it still reads candles ``i+1..i+3`` to decide *whether and
    when* confirmation happens -- only when the resulting object joins the
    causally-processed ``active`` list changes).
    """
    out: list[RBCandidateRecord] = []
    active: list[RBCandidateRecord] = []
    # index (the first candle a confirmed RB may be tracked against) -> [recs]
    pending_by_start_index: dict[int, list[RBCandidateRecord]] = {}

    for i, c in enumerate(series):
        # 0) activate anything scheduled to start tracking at this index --
        # added to `active` before step 1 so it's tracked against candle i
        # itself (the first candle strictly after its confirmation candle).
        starting = pending_by_start_index.pop(i, [])
        for rb in starting:
            if c.segment_id != rb.segment_id:
                # confirmation candle was the last of its segment; there is
                # no same-segment candle to ever track this RB against.
                rb.deactivation_ts = rb.activation_ts
                rb.deactivation_reason = "DATA_END_ACTIVE"
                rb.active = False
                continue
            active.append(rb)

        # 1) advance confirmed/active RBs under the common traversal contract
        still: list[RBCandidateRecord] = []
        tapped_directions: set[str] = set()   # existing-structure precedence (spec Part 5)
        for rb in active:
            if c.segment_id != rb.segment_id:
                rb.deactivation_ts = candle_ts_et(series[i - 1]) if i > 0 else rb.activation_ts
                rb.deactivation_reason = "DATA_END_ACTIVE"
                rb.active = False
                continue
            lo, hi = rb.zone_lo, rb.zone_hi
            ts = candle_ts_et(c)
            direction_sign = 1 if rb.direction == "bullish" else -1
            if rb.direction == "bullish":
                reached = c.low <= hi
                pen = max(0.0, lo - c.low)
            else:
                reached = c.high >= lo
                pen = max(0.0, c.high - hi)
            if reached:
                tapped_directions.add(rb.direction)
                if rb.first_tap_ts is None:
                    rb.first_tap_ts = ts
                    rb.touched = True
                if pen > rb.max_penetration_after_activation:
                    rb.max_penetration_after_activation = pen
            step = zone_step(direction_sign, lo, hi, c)
            if step.deactivated:
                rb.deactivation_ts = ts
                rb.deactivation_reason = step.reason
                rb.active = False
                continue
            expiry = _lifetime_check(tf, rb.activation_ts, ts, rb.touched)
            if expiry is not None:
                rb.deactivation_ts = ts
                rb.deactivation_reason = expiry
                rb.active = False
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
        eps = 1e-9  # absorb float arithmetic drift at an exact-floor edge
        one_tick = NQ_TICK

        # Dominant-wick direction selection (spec Part 4): the candle's
        # direction follows whichever wick is strictly longer, never both.
        # Equal-length wicks are diagnostic/ambiguous only -- no active RB.
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

        # Existing-structure precedence (spec Part 5): a candle whose wick
        # only reproduces a tap/reaction against an already-active
        # same-direction RB must not spawn a new overlapping RB from that
        # reaction -- the tap was already recorded on the original RB in
        # step 1 above (rb.first_tap_ts/max_penetration_after_activation).
        filtered = []
        for cand in candidates:
            direction = cand[0]
            if direction in tapped_directions:
                registry.precedence_suppressed_rbs.append({
                    "timeframe": tf, "source_seq": i, "source_ts": candle_ts_et(c),
                    "direction": direction, "source_ohlc": (c.open, c.high, c.low, c.close),
                    "reason": "existing_active_same_direction_rb_tapped",
                })
                continue
            filtered.append(cand)
        candidates = filtered

        for direction, wick, opposite_wick, zlo, zhi in candidates:
            pid = registry.new_id("RB2")
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
            )
            window_raw = series[i + 1:i + 1 + CONFIRM_WINDOW]
            window = []
            for wbar in window_raw:
                if wbar.segment_id != c.segment_id:
                    break
                window.append(wbar)
            proximal = zhi if direction == "bullish" else zlo
            running_extreme = None
            for k, wbar in enumerate(window, start=1):
                if direction == "bullish":
                    running_extreme = wbar.high if running_extreme is None else max(running_extreme, wbar.high)
                    mfe = running_extreme - proximal
                else:
                    running_extreme = wbar.low if running_extreme is None else min(running_extreme, wbar.low)
                    mfe = proximal - running_extreme
                mfe_atr = mfe / a
                if k == 1:
                    rec.mfe_after_1, rec.mfe_after_1_atr = mfe, mfe_atr
                elif k == 2:
                    rec.mfe_after_2, rec.mfe_after_2_atr = mfe, mfe_atr
                elif k == 3:
                    rec.mfe_after_3, rec.mfe_after_3_atr = mfe, mfe_atr
                if mfe_atr >= CONFIRM_ATR_MULT:
                    rec.confirmed = True
                    rec.confirming_candle_number = k
                    rec.activation_ts = candle_ts_et(wbar)
                    rec.active = True
                    confirming_index = i + k  # == j: the confirming candle's own index
                    break
                invalidated = (wbar.close < zlo) if direction == "bullish" else (wbar.close > zhi)
                if invalidated:
                    rec.rejection_reason = "invalidated_before_confirmation"
                    break
            if not rec.confirmed and rec.rejection_reason is None:
                if len(window) < CONFIRM_WINDOW:
                    rec.rejection_reason = "insufficient_data_for_confirmation_window"
                else:
                    rec.rejection_reason = "threshold_not_reached_in_3_candles"

            registry.register_rb(rec)
            out.append(rec)
            if rec.confirmed:
                # Never tracked against its own source candle, any scrape
                # candle, or the confirming candle itself -- tracking starts
                # strictly at the candle after confirmation closes.
                start_index = confirming_index + 1
                pending_by_start_index.setdefault(start_index, []).append(rec)

    if series:
        last_ts = candle_ts_et(series[-1])
        for rb in active:
            rb.deactivation_ts = last_ts
            rb.deactivation_reason = "DATA_END_ACTIVE"
            rb.active = False
    # Any RB confirmed on the series' final candle has no candle j+1 to ever
    # track it against -- data simply ended at the instant it activated.
    for pending_list in pending_by_start_index.values():
        for rb in pending_list:
            rb.deactivation_ts = rb.activation_ts
            rb.deactivation_reason = "DATA_END_ACTIVE"
            rb.active = False
    return out

"""Setup model, frozen reward-to-risk policy, and (separate) outcome evaluation.

The RR policy is frozen and applied identically to every candidate:

  natural_rr = |target - entry| / |entry - stop|
    natural_rr < 0.5  -> REJECT (INSUFFICIENT_NATURAL_RR); never executed
    natural_rr >= 1.0 -> eligible, executed target capped to exactly 1.0R
    0.5 <= rr < 1.0   -> eligible, natural target used as-is

Entry, stop, target and expiry are frozen at construction time. Outcome is
computed *afterwards* by a separate function and is never allowed to influence
any of those numbers. Same-bar stop/target collision is AMBIGUOUS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_RR = 0.5
CAP_RR = 1.0


@dataclass
class Setup:
    id: str
    direction: str            # "long" | "short"
    path_family: str          # formation_continuation | retracement_continuation | fade | ...
    graph: str                # human-readable causal path
    entry_mode: str           # formation_close | next_bar | first_touch | midpoint | full_fill | retest
    origin_id: str
    transition_ids: list       # meaningful transition primitive ids
    primitive_ids: list        # full provenance path
    context_conditions: list   # <= 3 contextual eligibility conditions

    entry_seq: int
    entry_ts: object
    entry_price: float
    structural_stop: float
    structural_target: float   # natural structural target (diagnostic-retained)
    expiry_seq: int
    expiry_rule: str
    segment_id: int

    # feature flags for coverage counting
    has_fvg: bool = False
    has_ifvg: bool = False
    has_rb: bool = False
    has_sweep: bool = False
    continuation_or_fade: str = "continuation"  # "continuation" | "fade"

    # filled by RR policy
    natural_rr: float = 0.0
    executed_target: float = 0.0
    executed_rr: float = 0.0
    eligible: bool = False
    rejected: bool = False
    rejection_reason: str = ""

    # dedup
    episode_key: tuple = ()

    # outcome (computed separately, never feeds the above)
    outcome: str = "UNEVALUATED"   # WIN | LOSS | AMBIGUOUS | EXPIRED | OPEN
    outcome_seq: int | None = None

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.structural_stop)


def apply_rr_policy(s: Setup) -> Setup:
    """Freeze RR numbers and eligibility. Pure function of frozen prices."""
    dir_sign = 1.0 if s.direction == "long" else -1.0
    risk = abs(s.entry_price - s.structural_stop)
    if risk <= 0:
        s.rejected = True
        s.eligible = False
        s.rejection_reason = "DEGENERATE_STOP"
        return s
    natural_rr = abs(s.structural_target - s.entry_price) / risk
    s.natural_rr = natural_rr

    # frozen geometry: long stop<entry<target; short target<entry<stop.
    # stop must sit on the opposite side of entry from the target.
    stop_side = 1.0 if s.structural_stop > s.entry_price else -1.0
    if s.structural_stop != s.entry_price and stop_side == dir_sign:
        s.rejected = True
        s.eligible = False
        s.rejection_reason = "STOP_WRONG_SIDE"
        return s

    # target must be on the correct side of entry for the direction
    target_side = 1.0 if s.structural_target > s.entry_price else -1.0
    if s.structural_target != s.entry_price and target_side != dir_sign:
        s.rejected = True
        s.eligible = False
        s.rejection_reason = "TARGET_WRONG_SIDE"
        return s

    if natural_rr < MIN_RR:
        s.rejected = True
        s.eligible = False
        s.rejection_reason = "INSUFFICIENT_NATURAL_RR"
        return s

    if natural_rr >= CAP_RR:
        s.executed_target = s.entry_price + dir_sign * risk * CAP_RR
        s.executed_rr = CAP_RR
    else:
        s.executed_target = s.structural_target
        s.executed_rr = natural_rr
    s.eligible = True
    return s


def evaluate_outcome(s: Setup, bars) -> Setup:
    """Simulate forward from entry+1 using executed target and structural stop.

    Diagnostic only. Never mutates entry/stop/target/RR. Same-bar hit of both
    the executed target and the stop is AMBIGUOUS.
    """
    if not s.eligible:
        return s
    dir_long = s.direction == "long"
    tgt = s.executed_target
    stop = s.structural_stop
    for i in range(s.entry_seq + 1, len(bars)):
        b = bars[i]
        if b.segment_id != s.segment_id:
            s.outcome = "EXPIRED"
            s.outcome_seq = i - 1
            return s
        if i > s.expiry_seq:
            s.outcome = "EXPIRED"
            s.outcome_seq = s.expiry_seq
            return s
        if dir_long:
            hit_t = b.high >= tgt
            hit_s = b.low <= stop
        else:
            hit_t = b.low <= tgt
            hit_s = b.high >= stop
        if hit_t and hit_s:
            s.outcome = "AMBIGUOUS"
            s.outcome_seq = i
            return s
        if hit_t:
            s.outcome = "WIN"
            s.outcome_seq = i
            return s
        if hit_s:
            s.outcome = "LOSS"
            s.outcome_seq = i
            return s
    s.outcome = "OPEN"
    return s

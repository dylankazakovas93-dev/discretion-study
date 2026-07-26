"""Observation-week outcome processing (spec Part 6). Runs ONLY after the
pre-outcome variant ledger is immutable, and ONLY for the observation week.
Deterministic, stop-first on same-bar ambiguity. Records MFE/MAE/points/R and
the exit type per FROZEN entry variant. A fingerprint is NEVER changed after
seeing its outcome; outcomes attach to a separate record keyed by variant_id.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_HOLD_BARS = 480   # frozen: 8h, aligned with intraday structure lifetime


@dataclass
class Outcome:
    variant_id: str
    episode_id: str
    entry_variant: str
    entry_price: float
    stop_price: float
    target_price: float
    direction: int
    exit_type: str        # TARGET / STOP / TIME / DATA_END
    exit_seq: int
    exit_price: float
    mfe_points: float
    mae_points: float
    points: float
    r_multiple: float
    success: bool         # target reached before stop


def process_outcome(v, bars):
    """Only for executable variants (valid entry/stop/opposing target). Returns
    Outcome or None."""
    prim = v.targets.get("NEAREST_OPPOSING_VALID_STRUCTURE") if v.targets else None
    if not v.executable or prim is None:
        return None
    # execution uses the EFFECTIVE (ATR-floored) stop, never the raw structural one
    direction, entry, stop, target = v.direction, v.entry_price, v.effective_stop_price, prim.surface
    risk = v.effective_stop_distance
    if risk <= 0:
        return None
    n = len(bars)
    end = min(n - 1, v.entry_seq + MAX_HOLD_BARS)
    mfe = mae = 0.0
    exit_type = None
    for s in range(v.entry_seq, end + 1):
        b = bars[s]
        if direction > 0:
            mfe = max(mfe, b.high - entry)
            mae = min(mae, b.low - entry)
            hit_stop, hit_tgt = b.low <= stop, b.high >= target
        else:
            mfe = max(mfe, entry - b.low)
            mae = min(mae, entry - b.high)
            hit_stop, hit_tgt = b.high >= stop, b.low <= target
        if hit_stop:                      # stop-first on same-bar ambiguity
            exit_type, exit_seq, exit_price = "STOP", s, stop
            break
        if hit_tgt:
            exit_type, exit_seq, exit_price = "TARGET", s, target
            break
    if exit_type is None:
        exit_type = "TIME" if end < n - 1 else "DATA_END"
        exit_seq, exit_price = end, bars[end].close
    points = (exit_price - entry) if direction > 0 else (entry - exit_price)
    return Outcome(
        variant_id=v.variant_id, episode_id=v.episode_id, entry_variant=v.entry_variant,
        entry_price=entry, stop_price=stop, target_price=target, direction=direction,
        exit_type=exit_type, exit_seq=exit_seq, exit_price=exit_price,
        mfe_points=round(mfe, 4), mae_points=round(mae, 4), points=round(points, 4),
        r_multiple=round(points / risk, 4), success=(exit_type == "TARGET"))

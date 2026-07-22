"""Observation-week outcome processing (spec: runs ONLY after the episode
ledger is immutable, and ONLY for the observation week). Deterministic,
stop-first on same-bar ambiguity. Records MFE/MAE/points/R and the exit type.
A fingerprint is NEVER changed after seeing its outcome; outcomes are attached
to a separate record keyed by episode_id.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_HOLD_BARS = 480   # frozen: 8h, aligned with intraday structure lifetime


@dataclass
class Outcome:
    episode_id: str
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


def process_outcome(ep, bars):
    """Only for executable episodes (valid entry/stop/target). Returns Outcome
    or None."""
    prim = next((t for t in ep.targets if t.policy == "NEAREST_VALID_STRUCTURE"), None)
    if not ep.executable or prim is None:
        return None
    direction = ep.direction
    entry = ep.entry_price
    stop = ep.stop_price
    target = prim.surface
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    n = len(bars)
    end = min(n - 1, ep.entry_seq + MAX_HOLD_BARS)
    mfe = 0.0
    mae = 0.0
    exit_type = None
    exit_seq = end
    exit_price = bars[end].close
    for s in range(ep.entry_seq, end + 1):
        b = bars[s]
        if direction > 0:
            mfe = max(mfe, b.high - entry)
            mae = min(mae, b.low - entry)
            hit_stop = b.low <= stop
            hit_tgt = b.high >= target
        else:
            mfe = max(mfe, entry - b.low)
            mae = min(mae, entry - b.high)
            hit_stop = b.high >= stop
            hit_tgt = b.low <= target
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
        episode_id=ep.episode_id, entry_price=entry, stop_price=stop, target_price=target,
        direction=direction, exit_type=exit_type, exit_seq=exit_seq, exit_price=exit_price,
        mfe_points=round(mfe, 4), mae_points=round(mae, 4), points=round(points, 4),
        r_multiple=round(points / risk, 4), success=(exit_type == "TARGET"),
    )

"""Core bar model.

A Bar is one completed 1-minute OHLCV candle for a single futures contract.
Bars are the atomic unit the causal engine consumes chronologically. Everything
downstream (primitives, setups) may only read bars whose close is already known.
"""

from __future__ import annotations

from dataclasses import dataclass

# NQ E-mini tick size in index points.
NQ_TICK = 0.25


@dataclass(frozen=True)
class Bar:
    """One completed 1-minute candle.

    Attributes
    ----------
    seq : int
        0-based sequential index within a single contract segment. Resets at
        each contract-roll boundary so absolute structures never cross rolls.
    ts_utc : pandas.Timestamp
        Bar-open timestamp, timezone-aware UTC. The bar is only "complete"
        (knowable) after ts_utc + 1 minute.
    ts_et : pandas.Timestamp
        Same instant in America/New_York (DST-aware). Used for time anchors.
    open, high, low, close : float
        Prices in index points.
    volume : int
    contract : str
        Specific contract symbol, e.g. "NQU5".
    segment_id : int
        Monotonic id of the contract segment this bar belongs to. Two bars with
        different segment_id are separated by a contract roll.
    """

    seq: int
    ts_utc: object
    ts_et: object
    open: float
    high: float
    low: float
    close: float
    volume: int
    contract: str
    segment_id: int

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_up(self) -> bool:
        return self.close > self.open

    @property
    def is_down(self) -> bool:
        return self.close < self.open

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0

"""HTF fair-value-gap and inverse-FVG target inventory.

FVGs are detected **independently** on completed 5m/15m/30m/60m candles using the
canonical three-candle definition (A,B,C in one segment; bullish `C.low > A.high`,
bearish `C.high < A.low`) — not by grouping 1-minute FVGs. Each gap becomes usable
only after its C candle closes (`available_seq` = C's 1-minute availability index).

Lifecycle states are stamped on completed **1-minute** bars after availability
(the finest causal granularity the target resolver reads): first touch, first
positive fill, midpoint (consequent encroachment), full fill, and failure (a
1-minute body close through the far edge). A failed HTF FVG inverts into an HTF
iFVG carrying parent lineage; the iFVG activates at the same 1-minute failure bar.

Target surfaces per zone: PROXIMAL_EDGE (default — price may react on first entry),
MIDPOINT, DISTAL_EDGE. Objects are never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import NQ_TICK


@dataclass
class HTFFVG:
    id: str
    timeframe: int
    direction: int                 # +1 bullish, -1 bearish
    subtype: str
    a_candle_id: str
    b_candle_id: str
    c_candle_id: str
    segment_id: int
    created_seq: int               # 1m index at which it becomes knowable (C close)
    created_ts: str
    availability_ts: str
    lo: float                      # gap zone
    hi: float
    width_atr: float | None
    source_fvg_id: str | None = None   # set on iFVG children (parent lineage)
    # lifecycle state (1m seq stamps; None until it happens)
    first_touch_seq: int | None = None
    first_fill_seq: int | None = None
    midpoint_seq: int | None = None
    full_fill_seq: int | None = None
    failed_seq: int | None = None
    invalidation_seq: int | None = None
    invalidation_ts: str | None = None
    interaction_count: int = 0
    active: bool = True
    metrics: dict = field(default_factory=dict)

    @property
    def family(self):
        return "htf_fvg"

    @property
    def available_seq(self):
        return self.created_seq

    @property
    def midpoint(self):
        return (self.lo + self.hi) / 2.0

    @property
    def width(self):
        return self.hi - self.lo

    @property
    def proximal(self):
        """Edge price first reaches when it returns toward the gap."""
        return self.hi if self.direction > 0 else self.lo

    @property
    def distal(self):
        """Edge reached on a full fill."""
        return self.lo if self.direction > 0 else self.hi

    def surface(self, name: str) -> float:
        if name == "PROXIMAL_EDGE":
            return self.proximal
        if name == "MIDPOINT":
            return self.midpoint
        if name == "DISTAL_EDGE":
            return self.distal
        raise ValueError(f"unknown target surface {name!r}")

    def fresh_at(self, seq: int) -> bool:
        """Available, not positively filled and not failed by ``seq``."""
        if self.available_seq > seq:
            return False
        for s in (self.first_fill_seq, self.failed_seq):
            if s is not None and s <= seq:
                return False
        return True


@dataclass
class HTFIFVG:
    id: str
    timeframe: int
    direction: int                 # +1 bullish iFVG, -1 bearish iFVG
    subtype: str
    source_fvg_id: str             # parent lineage
    segment_id: int
    created_seq: int               # 1m activation index (parent failure bar)
    created_ts: str
    lo: float
    hi: float
    width_atr: float | None
    first_touch_seq: int | None = None
    rejection_seq: int | None = None
    reinversion_seq: int | None = None
    invalidation_seq: int | None = None
    invalidation_ts: str | None = None
    interaction_count: int = 0
    active: bool = True

    @property
    def family(self):
        return "htf_ifvg"

    @property
    def available_seq(self):
        return self.created_seq

    @property
    def midpoint(self):
        return (self.lo + self.hi) / 2.0

    @property
    def proximal(self):
        # bullish iFVG (support below price) is first reached at its top edge;
        # bearish iFVG (resistance above price) is first reached at its bottom edge
        return self.hi if self.direction > 0 else self.lo

    @property
    def distal(self):
        return self.lo if self.direction > 0 else self.hi

    def surface(self, name: str) -> float:
        if name == "PROXIMAL_EDGE":
            return self.proximal
        if name == "MIDPOINT":
            return self.midpoint
        if name == "DISTAL_EDGE":
            return self.distal
        raise ValueError(f"unknown target surface {name!r}")

    def fresh_at(self, seq: int) -> bool:
        if self.available_seq > seq:
            return False
        if self.reinversion_seq is not None and self.reinversion_seq <= seq:
            return False
        return True


def detect_htf_fvgs(bars, agg, reg):
    """Detect HTF FVGs + iFVGs across all timeframes; track 1-minute lifecycle.

    ``agg`` is ``{tf: [HTFBar]}``; ``bars`` is the same global 1-minute list the
    aggregation indices reference. Returns ``(fvgs, ifvgs)`` — nothing discarded.
    """
    fvgs: list[HTFFVG] = []
    for tf, candles in agg.items():
        for k in range(2, len(candles)):
            a, b, c = candles[k - 2], candles[k - 1], candles[k]
            if not (a.segment_id == b.segment_id == c.segment_id):
                continue
            if c.low > a.high:
                direction, lo, hi = 1, a.high, c.low
            elif c.high < a.low:
                direction, lo, hi = -1, c.high, a.low
            else:
                continue
            width = hi - lo
            width_atr = round(width / c.atr, 4) if c.atr and c.atr > 0 else None
            fvgs.append(HTFFVG(
                id=reg.new_id(f"HTFFVG{tf}"), timeframe=tf, direction=direction,
                subtype="bullish" if direction > 0 else "bearish",
                a_candle_id=a.candle_id, b_candle_id=b.candle_id,
                c_candle_id=c.candle_id, segment_id=c.segment_id,
                created_seq=c.available_seq, created_ts=c.open_ts,
                availability_ts=c.close_ts, lo=lo, hi=hi, width_atr=width_atr,
                metrics={"width": width}))

    ifvgs = _track_and_invert(fvgs, bars, reg)
    return fvgs, ifvgs


def _track_and_invert(fvgs, bars, reg):
    """Stamp FVG lifecycle on 1m bars; spawn iFVG children on failures."""
    n = len(bars)
    ifvgs: list[HTFIFVG] = []
    for f in fvgs:
        for i in range(f.available_seq, n):
            bar = bars[i]
            if bar.segment_id != f.segment_id:
                break
            if f.direction < 0:
                # bearish gap: price rises into it from below (a long's target)
                touched = bar.high >= f.proximal - NQ_TICK / 2
                filled = bar.high > f.lo + 1e-9
                mid = bar.high >= f.midpoint
                full = bar.high >= f.hi - 1e-9
                failed = bar.close > f.hi + 1e-9
            else:
                # bullish gap: price falls into it from above (a short's target)
                touched = bar.low <= f.proximal + NQ_TICK / 2
                filled = bar.low < f.hi - 1e-9
                mid = bar.low <= f.midpoint
                full = bar.low <= f.lo + 1e-9
                failed = bar.close < f.lo - 1e-9
            if touched:
                f.interaction_count += 1
                if f.first_touch_seq is None:
                    f.first_touch_seq = i
            if filled and f.first_fill_seq is None:
                f.first_fill_seq = i
            if mid and f.midpoint_seq is None:
                f.midpoint_seq = i
            if full and f.full_fill_seq is None:
                f.full_fill_seq = i
            if failed:
                f.failed_seq = i
                f.invalidation_seq = i
                f.invalidation_ts = str(bar.ts_et)
                f.active = False
                ifvgs.append(_spawn_ifvg(f, i, bar, reg))
                break

    _track_ifvgs(ifvgs, bars)
    return ifvgs


def _spawn_ifvg(f, i, bar, reg):
    direction = -f.direction
    return HTFIFVG(
        id=reg.new_id(f"HTFIFVG{f.timeframe}"), timeframe=f.timeframe,
        direction=direction, subtype="bullish" if direction > 0 else "bearish",
        source_fvg_id=f.id, segment_id=f.segment_id, created_seq=i,
        created_ts=str(bar.ts_et), lo=f.lo, hi=f.hi, width_atr=f.width_atr)


def _track_ifvgs(ifvgs, bars):
    n = len(bars)
    for iv in ifvgs:
        for i in range(iv.available_seq + 1, n):
            bar = bars[i]
            if bar.segment_id != iv.segment_id:
                break
            if iv.direction < 0:
                # bearish iFVG: resistance above; retest from below
                if bar.high >= iv.lo:
                    iv.interaction_count += 1
                    if iv.first_touch_seq is None:
                        iv.first_touch_seq = i
                    if bar.close < iv.lo and iv.rejection_seq is None:
                        iv.rejection_seq = i
                if bar.close > iv.hi + 1e-9:      # accepted back above -> failed
                    iv.reinversion_seq = i
                    iv.invalidation_seq = i
                    iv.invalidation_ts = str(bar.ts_et)
                    iv.active = False
                    break
            else:
                # bullish iFVG: support below; retest from above
                if bar.low <= iv.hi:
                    iv.interaction_count += 1
                    if iv.first_touch_seq is None:
                        iv.first_touch_seq = i
                    if bar.close > iv.hi and iv.rejection_seq is None:
                        iv.rejection_seq = i
                if bar.close < iv.lo - 1e-9:
                    iv.reinversion_seq = i
                    iv.invalidation_seq = i
                    iv.invalidation_ts = str(bar.ts_et)
                    iv.active = False
                    break

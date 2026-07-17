"""Prominent-wick liquidity inventory over completed HTF candles.

A ProminentWickLiquidity object is liquidity at the *exposed* wick of a completed
5m/15m/30m/60m candle — not every candle high/low. Prominence is a causal 0-100
score from prior same-timeframe distributions (current candle excluded); only
MEDIUM/HIGH are default executable targets. Interaction states (touch / positive
overlap / midpoint overlap / extreme sweep / body close-through) are tracked on
completed 1-minute bars after availability; the object is never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import NQ_TICK

PROM_HIGH = 80.0
PROM_MEDIUM = 65.0
PCT_LOOKBACK = 40
EXPOSED_N = (3, 5, 10)
# score weights: wick/ATR pct, wick/range, range/ATR pct, exposed-protrusion pct,
# close-away-from-wick
W = (0.30, 0.20, 0.20, 0.20, 0.10)


@dataclass
class ProminentWickLiquidity:
    id: str
    source_candle_id: str
    timeframe: int
    side: str                      # "upper" | "lower"
    segment_id: int
    created_seq: int               # 1m index at which it becomes knowable
    created_ts: str
    availability_ts: str
    full_lo: float                 # full wick zone
    full_hi: float
    exposed: dict                  # {N: (lo,hi) | None}
    proximal: float                # body-edge boundary (nearest price first)
    extreme: float                 # candle high (upper) / low (lower)
    midpoint: float
    prominence_score: float
    prominence_grade: str
    metrics: dict = field(default_factory=dict)
    # interaction state (seq stamps; None until it happens). freshness at a query
    # seq T = available and none of overlap/sweep/close-through happened by T.
    first_touch_seq: int | None = None
    positive_overlap_seq: int | None = None
    midpoint_overlap_seq: int | None = None
    swept_seq: int | None = None
    closed_through_seq: int | None = None
    interaction_count: int = 0
    invalidation_ts: str | None = None
    active: bool = True

    @property
    def lo(self):
        return self.full_lo

    @property
    def hi(self):
        return self.full_hi

    @property
    def family(self):
        return "wick_liquidity"

    def fresh_at(self, seq: int) -> bool:
        if self.available_seq > seq:
            return False
        for s in (self.positive_overlap_seq, self.swept_seq, self.closed_through_seq):
            if s is not None and s <= seq:
                return False
        return True

    @property
    def available_seq(self):
        return self.created_seq


def _pct(value, history):
    """Fraction of prior values <= value (empty history -> neutral 0.5)."""
    if not history:
        return 0.5
    return sum(1 for h in history if h <= value) / len(history)


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def detect_wick_liquidity(bars, agg, reg):
    """Detect prominent-wick liquidity across all timeframes and track states."""
    out = []
    for tf, candles in agg.items():
        hist_wick_atr = {"upper": [], "lower": []}
        hist_range_atr = []
        hist_exposed = {"upper": [], "lower": []}
        seg_start = 0
        for k, c in enumerate(candles):
            if k == 0 or candles[k - 1].segment_id != c.segment_id:
                seg_start = k
                hist_wick_atr = {"upper": [], "lower": []}
                hist_range_atr = []
                hist_exposed = {"upper": [], "lower": []}
            atr = c.atr
            rng = c.high - c.low
            if atr is None or atr <= 0 or rng <= 0:
                # still update history minimally (no percentiles without ATR)
                continue
            body_top = max(c.open, c.close)
            body_bottom = min(c.open, c.close)
            body = abs(c.open - c.close)
            close_loc = (c.close - c.low) / rng
            prev = candles[seg_start:k]
            for side in ("upper", "lower"):
                if side == "upper":
                    wick = c.high - body_top
                    proximal, extreme = body_top, c.high
                    full_lo, full_hi = body_top, c.high
                    close_away = 1.0 - close_loc
                else:
                    wick = body_bottom - c.low
                    proximal, extreme = body_bottom, c.low
                    full_lo, full_hi = c.low, body_bottom
                    close_away = close_loc
                if wick <= 0:
                    continue
                wick_atr = wick / atr
                wick_range = wick / rng
                # exposed zones for N in EXPOSED_N (immutable variants)
                exposed = {}
                exposed_prot = 0.0
                for N in EXPOSED_N:
                    pn = prev[-N:] if N <= len(prev) else prev
                    if side == "upper":
                        bnd = max([body_top] + [b.high for b in pn])
                        exposed[N] = (bnd, c.high) if bnd < c.high - 1e-9 else None
                        if N == 5 and exposed[N]:
                            exposed_prot = (c.high - bnd)
                    else:
                        bnd = min([body_bottom] + [b.low for b in pn])
                        exposed[N] = (c.low, bnd) if c.low < bnd - 1e-9 else None
                        if N == 5 and exposed[N]:
                            exposed_prot = (bnd - c.low)
                exposed_prot_atr = exposed_prot / atr
                # causal percentiles from prior same-tf same-side history
                wick_atr_pct = _pct(wick_atr, hist_wick_atr[side][-PCT_LOOKBACK:])
                range_atr_pct = _pct(rng / atr, hist_range_atr[-PCT_LOOKBACK:])
                # a wick with no exposed surface is buried -> zero exposed prominence
                exposed_pct = (_pct(exposed_prot_atr, hist_exposed[side][-PCT_LOOKBACK:])
                               if exposed_prot_atr > 0 else 0.0)
                score = 100.0 * (
                    W[0] * wick_atr_pct + W[1] * _clamp01(wick_range)
                    + W[2] * range_atr_pct + W[3] * exposed_pct
                    + W[4] * _clamp01(close_away))
                grade = ("HIGH" if score >= PROM_HIGH else
                         "MEDIUM" if score >= PROM_MEDIUM else "LOW")
                obj = ProminentWickLiquidity(
                    id=reg.new_id(f"WICK{tf}"), source_candle_id=c.candle_id,
                    timeframe=tf, side=side, segment_id=c.segment_id,
                    created_seq=c.available_seq, created_ts=c.open_ts,
                    availability_ts=c.close_ts, full_lo=full_lo, full_hi=full_hi,
                    exposed=exposed, proximal=proximal, extreme=extreme,
                    midpoint=(full_lo + full_hi) / 2.0,
                    prominence_score=round(score, 2), prominence_grade=grade,
                    metrics={"wick": wick, "wick_atr": round(wick_atr, 4),
                             "wick_range": round(wick_range, 4),
                             "wick_body": round(wick / max(body, NQ_TICK), 4),
                             "range_atr": round(rng / atr, 4),
                             "close_loc": round(close_loc, 4),
                             "exposed_prot_atr": round(exposed_prot_atr, 4),
                             "wick_atr_pct": round(wick_atr_pct, 4),
                             "range_atr_pct": round(range_atr_pct, 4),
                             "exposed_pct": round(exposed_pct, 4)})
                reg.register(obj)
                out.append(obj)
                hist_exposed[side].append(exposed_prot_atr)
                hist_wick_atr[side].append(wick_atr)
            hist_range_atr.append(rng / atr)

    _track_interactions(out, bars)
    return out


def _track_interactions(objs, bars):
    """Stamp state seqs from completed 1-minute bars after availability."""
    n = len(bars)
    for o in objs:
        # exposed(5) is the default reference surface for overlap/close-through
        ez = o.exposed.get(5) or (o.full_lo, o.full_hi)
        ez_lo, ez_hi = ez
        for i in range(o.available_seq, n):
            b = bars[i]
            if b.segment_id != o.segment_id:
                break
            if o.side == "upper":
                touched = b.high >= o.proximal - NQ_TICK / 2
                overlap = b.high > ez_lo + 1e-9
                mid_ov = b.high >= o.midpoint
                swept = b.high > o.extreme + 1e-9
                closed = b.close > o.extreme + 1e-9
            else:
                touched = b.low <= o.proximal + NQ_TICK / 2
                overlap = b.low < ez_hi - 1e-9
                mid_ov = b.low <= o.midpoint
                swept = b.low < o.extreme - 1e-9
                closed = b.close < o.extreme - 1e-9
            if touched:
                o.interaction_count += 1
                if o.first_touch_seq is None:
                    o.first_touch_seq = i
            if overlap and o.positive_overlap_seq is None:
                o.positive_overlap_seq = i
            if mid_ov and o.midpoint_overlap_seq is None:
                o.midpoint_overlap_seq = i
            if swept and o.swept_seq is None:
                o.swept_seq = i
            if closed and o.closed_through_seq is None:
                o.closed_through_seq = i
                o.active = False
                o.invalidation_ts = str(b.ts_et)
                break

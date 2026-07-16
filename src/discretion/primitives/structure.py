"""Structure primitives: confirmed swings, equal H/L clusters, compression,
expansion, range break / failed break.

Causality on swings: a swing high at pivot bar ``j`` is only *confirmed* once
``K`` later bars fail to exceed it. We therefore stamp its knowable seq at
``j + K`` (the right edge), never at ``j``. This is not a centered calculation
used as-of ``j`` — the level simply does not exist until confirmation.

Confirmed swings and equal-H/L clusters are emitted as :class:`Level` objects so
they share the level interaction engine (sweep/break/reclaim/reject). Compression
and expansion are their own primitives carrying the range band for range-break
and failed-break detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import Bar, NQ_TICK
from .base import IdRegistry, Primitive
from .levels import Level

SWING_K = 2             # bars each side to confirm a pivot
EQUAL_TOL_TICKS = 3     # equal-high/low tolerance
COMPRESSION_W = 6       # window bars for a compression cluster
COMPRESSION_MAX_ATR = 1.2   # span <= this * ATR to be "compressed"
EXPANSION_MIN_ATR = 1.5     # bar range >= this * ATR to be an expansion


@dataclass
class StructureZone(Primitive):
    direction: int = 0
    band_lo: float = 0.0
    band_hi: float = 0.0
    features: dict = field(default_factory=dict)


def detect_swings(bars: list[Bar], reg: IdRegistry, k: int = SWING_K) -> list[Level]:
    """Confirmed swing highs/lows as liquidity Levels (knowable at pivot+k)."""
    out: list[Level] = []
    n = len(bars)
    for j in range(k, n - k):
        seg = bars[j].segment_id
        window = bars[j - k:j + k + 1]
        if any(b.segment_id != seg for b in window):
            continue
        hj, lj = bars[j].high, bars[j].low
        if all(bars[j].high >= b.high for b in window) and \
           any(bars[j].high > b.high for b in window[:k] + window[k + 1:]):
            conf = j + k
            lv = Level(
                id=reg.new_id("LVL"),
                family="liquidity",
                subtype="swing_high",
                segment_id=seg,
                created_seq=conf,
                created_ts=bars[conf].ts_utc,
                lo=hj, hi=hj, price_ref=hj, source="swing",
            )
            lv.add_event("CONFIRMED", conf, bars[conf].ts_utc, price=hj,
                         note=f"pivot@{j}")
            reg.register(lv)
            out.append(lv)
        if all(bars[j].low <= b.low for b in window) and \
           any(bars[j].low < b.low for b in window[:k] + window[k + 1:]):
            conf = j + k
            lv = Level(
                id=reg.new_id("LVL"),
                family="liquidity",
                subtype="swing_low",
                segment_id=seg,
                created_seq=conf,
                created_ts=bars[conf].ts_utc,
                lo=lj, hi=lj, price_ref=lj, source="swing",
            )
            lv.add_event("CONFIRMED", conf, bars[conf].ts_utc, price=lj,
                         note=f"pivot@{j}")
            reg.register(lv)
            out.append(lv)
    return out


def detect_equal_levels(swings: list[Level], reg: IdRegistry) -> list[Level]:
    """Frozen equal-high / equal-low clusters from confirmed swings."""
    tol = EQUAL_TOL_TICKS * NQ_TICK
    out: list[Level] = []
    for sub, fam in (("swing_high", "equal_highs"), ("swing_low", "equal_lows")):
        pts = sorted((s for s in swings if s.subtype == sub),
                     key=lambda s: s.created_seq)
        used = [False] * len(pts)
        for a in range(len(pts)):
            if used[a]:
                continue
            cluster = [pts[a]]
            for b in range(a + 1, len(pts)):
                if used[b]:
                    continue
                if pts[b].segment_id == pts[a].segment_id and \
                        abs(pts[b].price_ref - pts[a].price_ref) <= tol:
                    cluster.append(pts[b])
                    used[b] = True
            if len(cluster) >= 2:
                used[a] = True
                price = sum(c.price_ref for c in cluster) / len(cluster)
                conf = max(c.created_seq for c in cluster)
                seg = pts[a].segment_id
                lv = Level(
                    id=reg.new_id("LVL"),
                    family="liquidity",
                    subtype=fam,
                    segment_id=seg,
                    created_seq=conf,
                    created_ts=cluster[-1].created_ts,
                    lo=price, hi=price, price_ref=price, source="equal_cluster",
                )
                lv.add_event("CONFIRMED", conf, cluster[-1].created_ts, price=price,
                             note=f"n={len(cluster)}")
                reg.register(lv)
                out.append(lv)
    return out


def detect_compression_expansion(
    bars: list[Bar],
    atr: list[float | None],
    reg: IdRegistry,
) -> list[StructureZone]:
    """Compression clusters and expansion legs, with range-break tracking."""
    out: list[StructureZone] = []
    n = len(bars)

    # Compression: rolling window whose full span is tight vs ATR.
    i = COMPRESSION_W
    while i < n:
        a = atr[i]
        seg = bars[i].segment_id
        window = bars[i - COMPRESSION_W + 1:i + 1]
        if a and all(b.segment_id == seg for b in window):
            span = max(b.high for b in window) - min(b.low for b in window)
            if span <= COMPRESSION_MAX_ATR * a:
                band_lo = min(b.low for b in window)
                band_hi = max(b.high for b in window)
                z = StructureZone(
                    id=reg.new_id("STRUCT"),
                    family="structure",
                    subtype="compression",
                    segment_id=seg,
                    created_seq=i,
                    created_ts=bars[i].ts_utc,
                    lo=band_lo, hi=band_hi,
                    band_lo=band_lo, band_hi=band_hi,
                    features={"span_atr": span / a},
                )
                z.add_event("COMPRESSION", i, bars[i].ts_utc, price=(band_lo + band_hi) / 2)
                reg.register(z)
                out.append(z)
                # track resolution: expansion / range break / failed break
                _track_range(z, bars, atr, i + 1)
                i = i + COMPRESSION_W  # skip past this cluster to avoid overlap spam
                continue
        i += 1

    # Standalone expansion legs (strong range vs ATR), independent of compression.
    for j in range(n):
        a = atr[j]
        if not a:
            continue
        rng = bars[j].high - bars[j].low
        if rng >= EXPANSION_MIN_ATR * a and bars[j].body >= 0.5 * rng:
            direction = 1 if bars[j].close > bars[j].open else -1
            z = StructureZone(
                id=reg.new_id("STRUCT"),
                family="structure",
                subtype="expansion",
                segment_id=bars[j].segment_id,
                created_seq=j,
                created_ts=bars[j].ts_utc,
                lo=bars[j].low, hi=bars[j].high,
                direction=direction,
                features={"range_atr": rng / a},
            )
            z.add_event("EXPANSION", j, bars[j].ts_utc, price=bars[j].close)
            reg.register(z)
            out.append(z)
    return out


def _track_range(z: StructureZone, bars, atr, start_i, max_age: int = 120) -> None:
    """After a compression band, stamp expansion/break/failed-break/return."""
    broke_side = 0
    for i in range(start_i, min(len(bars), start_i + max_age)):
        b = bars[i]
        if b.segment_id != z.segment_id:
            z.add_event("EXPIRY", i - 1, bars[i - 1].ts_utc, note="segment_end")
            return
        if broke_side == 0:
            if b.close > z.band_hi:
                broke_side = 1
                z.add_event("BREAK", i, b.ts_utc, price=b.close, note="up")
                a = atr[i]
                if a and (b.high - b.low) >= EXPANSION_MIN_ATR * a:
                    z.add_event("EXPANSION", i, b.ts_utc, price=b.close)
            elif b.close < z.band_lo:
                broke_side = -1
                z.add_event("BREAK", i, b.ts_utc, price=b.close, note="down")
                a = atr[i]
                if a and (b.high - b.low) >= EXPANSION_MIN_ATR * a:
                    z.add_event("EXPANSION", i, b.ts_utc, price=b.close)
        else:
            # failed break = close back inside the band after breaking out
            if broke_side > 0 and b.close < z.band_hi:
                z.add_event("FAILED_CONTINUATION", i, b.ts_utc, price=b.close,
                            note="return_to_range")
                return
            if broke_side < 0 and b.close > z.band_lo:
                z.add_event("FAILED_CONTINUATION", i, b.ts_utc, price=b.close,
                            note="return_to_range")
                return
            z.add_event("CONTINUATION", i, b.ts_utc, price=b.close)
            return

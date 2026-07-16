"""Horizontal reference levels: time anchors and historical/liquidity levels.

Both families are horizontal prices with a shared, deterministic interaction
vocabulary, so one engine tracks them all. Each level becomes knowable only
after the bar/session that defines it has completed:

  * time anchors (midnight/Asia/London/09:00/09:30/10:00/NY-open, previous RTH
    close) are the open of the anchor minute, knowable after that bar closes;
  * session levels (previous RTH/ON/day/3-session/week/2-week/month high & low,
    plus the 09:00/09:30/10:00 one-minute highs & lows) are knowable after the
    defining session/bar completes.

Interaction states: FIRST_TOUCH/REVISIT, EXACT_TOUCH, SWEEP (pierce + close back),
BREAK (close through), RECLAIM (close back after a break), REJECTION,
ACCEPTANCE_ABOVE/BELOW (two closes beyond), CONTINUATION, EXPIRY.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.bars import Bar, NQ_TICK
from .base import IdRegistry, Primitive

ET = "America/New_York"

ANCHOR_TIMES = {
    "midnight_open": (0, 0),
    "asia_open": (20, 0),
    "london_open": (3, 0),
    "ny_session_open": (8, 30),
    "open_0900": (9, 0),
    "open_0930": (9, 30),
    "open_1000": (10, 0),
}

# One-minute high/low anchors captured at these ET times.
MINUTE_HL_TIMES = {
    "hl_0900": (9, 0),
    "hl_0930": (9, 30),
    "hl_1000": (10, 0),
}

MAX_LEVEL_AGE = 1440  # track a level for up to ~1 trading day of 1-min bars


@dataclass
class Level(Primitive):
    direction: int = 0        # 0 = neutral horizontal; sign is discovered on break
    price_ref: float = 0.0
    touched: bool = False
    broken_side: int = 0      # +1 accepted above, -1 accepted below, 0 none
    consec_above: int = 0
    consec_below: int = 0
    source: str = ""          # provenance family, e.g. "time_anchor"


def _et_date(bar: Bar):
    return bar.ts_et.date()


def _make_level(reg, family, subtype, source, price, seq, ts, seg) -> Level:
    lv = Level(
        id=reg.new_id("LVL"),
        family=family,
        subtype=subtype,
        segment_id=seg,
        created_seq=seq,
        created_ts=ts,
        lo=price,
        hi=price,
        price_ref=price,
        source=source,
    )
    lv.add_event("FORMED", seq, ts, price=price)
    reg.register(lv)
    return lv


def build_time_anchors(bars: list[Bar], reg: IdRegistry) -> list[Level]:
    """One anchor Level per (ET date, anchor) where the anchor minute exists."""
    levels: list[Level] = []
    seen: set[tuple] = set()
    # index first bar at-or-after each (date, h, m)
    for i, bar in enumerate(bars):
        d = _et_date(bar)
        hm = (bar.ts_et.hour, bar.ts_et.minute)
        for name, t in ANCHOR_TIMES.items():
            key = (d, name)
            if key in seen:
                continue
            if hm == t:
                seen.add(key)
                levels.append(
                    _make_level(reg, "time_anchor", name, "time_anchor",
                                bar.open, i, bar.ts_utc, bar.segment_id)
                )
        for name, t in MINUTE_HL_TIMES.items():
            key = (d, name)
            if key in seen or hm != t:
                continue
            seen.add(key)
            levels.append(
                _make_level(reg, "hist_level", name + "_high", "minute_hl",
                            bar.high, i, bar.ts_utc, bar.segment_id)
            )
            levels.append(
                _make_level(reg, "hist_level", name + "_low", "minute_hl",
                            bar.low, i, bar.ts_utc, bar.segment_id)
            )
    return levels


def _session_frames(bars: list[Bar]):
    """Yield (et_date, rth_stats, first_next_seq) per ET session.

    rth_stats holds high/low/close of the RTH window [09:30,16:00) and the
    seq/ts of the last RTH bar (when the session's levels become knowable).
    """
    by_date: dict = {}
    for i, bar in enumerate(bars):
        by_date.setdefault(_et_date(bar), []).append(i)
    frames = []
    for d in sorted(by_date):
        idxs = by_date[d]
        rth = [j for j in idxs
               if (9, 30) <= (bars[j].ts_et.hour, bars[j].ts_et.minute) < (16, 0)]
        if not rth:
            continue
        hi = max(bars[j].high for j in rth)
        lo = min(bars[j].low for j in rth)
        last = rth[-1]
        frames.append({
            "date": d,
            "rth_high": hi,
            "rth_low": lo,
            "rth_close": bars[last].close,
            "known_seq": last,          # levels knowable after this bar closes
            "known_ts": bars[last].ts_utc,
            "seg": bars[last].segment_id,
            "day_high": max(bars[j].high for j in idxs),
            "day_low": min(bars[j].low for j in idxs),
        })
    return frames


def build_session_levels(bars: list[Bar], reg: IdRegistry) -> list[Level]:
    """Previous RTH / day / multi-session high & low + previous RTH close."""
    frames = _session_frames(bars)
    levels: list[Level] = []

    def add(subtype, price, fr):
        # knowable at the first bar strictly after the defining session close
        seq = fr["known_seq"]
        levels.append(
            _make_level(reg, "hist_level", subtype, "session", price,
                        seq, fr["known_ts"], fr["seg"])
        )

    for k in range(1, len(frames)):
        prev = frames[k - 1]
        # previous RTH high/low/close and previous day high/low
        add("prev_rth_high", prev["rth_high"], prev)
        add("prev_rth_low", prev["rth_low"], prev)
        add("prev_rth_close", prev["rth_close"], prev)
        add("prev_day_high", prev["day_high"], prev)
        add("prev_day_low", prev["day_low"], prev)

    # multi-session lookbacks: previous N-session high/low (excluding current)
    for label, n in (("3session", 3), ("week5", 5), ("twoweek10", 10), ("month20", 20)):
        for k in range(n, len(frames)):
            window = frames[k - n:k]
            if len({f["seg"] for f in window} | {frames[k]["seg"]}) > 1:
                continue  # do not let an absolute level span a contract roll
            hi = max(f["day_high"] for f in window)
            lo = min(f["day_low"] for f in window)
            fr = frames[k - 1]
            add(f"prev_{label}_high", hi, fr)
            add(f"prev_{label}_low", lo, fr)
    return levels


def track_level_interactions(levels: list[Level], bars: list[Bar],
                             max_age: int = MAX_LEVEL_AGE) -> None:
    """Populate interaction events on each level via one causal pass."""
    # bucket levels by the seq at which they turn on (created_seq + 1)
    by_start: dict[int, list[Level]] = {}
    for lv in levels:
        by_start.setdefault(lv.created_seq + 1, []).append(lv)

    active: list[Level] = []
    for i, bar in enumerate(bars):
        active.extend(by_start.get(i, []))
        still: list[Level] = []
        for lv in active:
            if lv.segment_id != bar.segment_id or i - lv.created_seq >= max_age:
                lv.add_event("EXPIRY", i, bar.ts_utc)
                lv.active = False
                continue
            P = lv.price_ref
            touched = bar.low <= P <= bar.high
            if touched:
                if not lv.touched:
                    lv.add_event("FIRST_TOUCH", i, bar.ts_utc, price=P)
                    lv.touched = True
                else:
                    lv.add_event("REVISIT", i, bar.ts_utc, price=P)
                if abs(bar.high - P) < NQ_TICK / 2 or abs(bar.low - P) < NQ_TICK / 2:
                    lv.add_event("EXACT_TOUCH", i, bar.ts_utc, price=P)
                # sweep: pierced but closed back on approach side
                if bar.high > P and bar.close < P:
                    lv.add_event("SWEEP", i, bar.ts_utc, price=bar.high,
                                 note="above")
                    lv.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
                elif bar.low < P and bar.close > P:
                    lv.add_event("SWEEP", i, bar.ts_utc, price=bar.low,
                                 note="below")
                    lv.add_event("REJECTION", i, bar.ts_utc, price=bar.close)
            # break / acceptance / reclaim by close
            if bar.close > P:
                lv.consec_above += 1
                lv.consec_below = 0
                if lv.broken_side <= 0 and bar.close > P + NQ_TICK / 2:
                    if lv.broken_side < 0:
                        lv.add_event("RECLAIM", i, bar.ts_utc, price=bar.close)
                    else:
                        lv.add_event("BREAK", i, bar.ts_utc, price=bar.close,
                                     note="up")
                    lv.broken_side = 1
                if lv.consec_above == 2:
                    lv.add_event("ACCEPTANCE_ABOVE", i, bar.ts_utc, price=bar.close)
                if lv.consec_above >= 3:
                    lv.add_event("CONTINUATION", i, bar.ts_utc, price=bar.close)
            elif bar.close < P:
                lv.consec_below += 1
                lv.consec_above = 0
                if lv.broken_side >= 0 and bar.close < P - NQ_TICK / 2:
                    if lv.broken_side > 0:
                        lv.add_event("RECLAIM", i, bar.ts_utc, price=bar.close)
                    else:
                        lv.add_event("BREAK", i, bar.ts_utc, price=bar.close,
                                     note="down")
                    lv.broken_side = -1
                if lv.consec_below == 2:
                    lv.add_event("ACCEPTANCE_BELOW", i, bar.ts_utc, price=bar.close)
                if lv.consec_below >= 3:
                    lv.add_event("CONTINUATION", i, bar.ts_utc, price=bar.close)
            still.append(lv)
        active = still

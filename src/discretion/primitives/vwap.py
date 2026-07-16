"""Causal session VWAP with 1.618 / 2.618 / 3.618 std-dev bands.

Anchored at the CME daily session open (18:00 ET) so it runs continuously across
overnight and RTH, resetting each session. VWAP and its variance are pure
cumulative sums over completed bars, so ``vwap[i]`` is knowable at bar ``i``.

Because VWAP and its bands move each bar, a VWAP session is stored as arrays and
exposes ``value_at(seq)``. Discrete interaction events (bounce/reject, reclaim,
break, acceptance-outside, band rejection = fade back toward VWAP, continuation)
are stamped onto the session primitive with a ``note`` identifying the band.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..data.bars import Bar
from .base import IdRegistry, Primitive

BAND_MULTIPLIERS = (1.618, 2.618, 3.618)
SESSION_RESET_ET = (18, 0)  # CME daily open


@dataclass
class VWAPSession(Primitive):
    # seq -> (vwap, sd); bands are vwap ± m*sd
    vwap: dict = field(default_factory=dict)
    sd: dict = field(default_factory=dict)
    start_seq: int = -1

    def value_at(self, seq: int):
        if seq not in self.vwap:
            return None
        v = self.vwap[seq]
        s = self.sd[seq]
        bands = {}
        for m in BAND_MULTIPLIERS:
            bands[f"+{m}"] = v + m * s
            bands[f"-{m}"] = v - m * s
        return {"vwap": v, "sd": s, "bands": bands}


def _session_key(bar: Bar):
    """CME session date: bars at/after 18:00 ET belong to the next day's session."""
    t = (bar.ts_et.hour, bar.ts_et.minute)
    d = bar.ts_et.date()
    if t >= SESSION_RESET_ET:
        return (d, "next")
    return (d, "same")


def build_vwap_sessions(bars: list[Bar], reg: IdRegistry) -> list[VWAPSession]:
    """One VWAPSession per CME session; also stamps interaction events."""
    sessions: list[VWAPSession] = []
    cur: VWAPSession | None = None
    cum_pv = cum_v = cum_p2v = 0.0
    prev_side = 0
    consec_above = consec_below = 0

    def flush(s):
        if s is not None:
            sessions.append(s)

    prev_key = None
    for i, bar in enumerate(bars):
        key = (_session_key(bar), bar.segment_id)
        if key != prev_key:
            flush(cur)
            cur = VWAPSession(
                id=reg.new_id("VWAP"),
                family="vwap",
                subtype="session",
                segment_id=bar.segment_id,
                created_seq=i,
                created_ts=bar.ts_utc,
                lo=bar.low,
                hi=bar.high,
                start_seq=i,
            )
            reg.register(cur)
            cum_pv = cum_v = cum_p2v = 0.0
            prev_side = 0
            consec_above = consec_below = 0
            prev_key = key

        tp = (bar.high + bar.low + bar.close) / 3.0
        vol = bar.volume if bar.volume > 0 else 1
        cum_pv += tp * vol
        cum_v += vol
        cum_p2v += tp * tp * vol
        v = cum_pv / cum_v
        var = max(0.0, cum_p2v / cum_v - v * v)
        s = math.sqrt(var)
        cur.vwap[i] = v
        cur.sd[i] = s

        # --- VWAP interactions ---
        if bar.low <= v <= bar.high:
            if bar.close > v and bar.low < v:
                cur.add_event("REJECTION", i, bar.ts_utc, price=v, note="vwap_bounce_up")
            elif bar.close < v and bar.high > v:
                cur.add_event("REJECTION", i, bar.ts_utc, price=v, note="vwap_bounce_down")
        side = 1 if bar.close > v else (-1 if bar.close < v else 0)
        if prev_side != 0 and side != 0 and side != prev_side:
            if side > 0:
                cur.add_event("RECLAIM" if prev_side < 0 else "BREAK", i, bar.ts_utc,
                              price=bar.close, note="vwap_up")
            else:
                cur.add_event("BREAK" if prev_side > 0 else "RECLAIM", i, bar.ts_utc,
                              price=bar.close, note="vwap_down")
        if side > 0:
            consec_above += 1
            consec_below = 0
            if consec_above == 2:
                cur.add_event("ACCEPTANCE_ABOVE", i, bar.ts_utc, price=bar.close,
                              note="vwap")
            if consec_above >= 3:
                cur.add_event("CONTINUATION", i, bar.ts_utc, price=bar.close,
                              note="vwap_above")
        elif side < 0:
            consec_below += 1
            consec_above = 0
            if consec_below == 2:
                cur.add_event("ACCEPTANCE_BELOW", i, bar.ts_utc, price=bar.close,
                              note="vwap")
            if consec_below >= 3:
                cur.add_event("CONTINUATION", i, bar.ts_utc, price=bar.close,
                              note="vwap_below")
        prev_side = side if side != 0 else prev_side

        # --- band interactions (fade back toward vwap = REJECTION at band) ---
        for m in BAND_MULTIPLIERS:
            upper = v + m * s
            lower = v - m * s
            if bar.high >= upper and bar.close < upper:
                cur.add_event("REJECTION", i, bar.ts_utc, price=upper,
                              note=f"band_reject_+{m}")
            if bar.low <= lower and bar.close > lower:
                cur.add_event("REJECTION", i, bar.ts_utc, price=lower,
                              note=f"band_reject_-{m}")

    flush(cur)
    return sessions

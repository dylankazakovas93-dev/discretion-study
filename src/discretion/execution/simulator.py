"""Canonical production execution functions.

All analysis scripts and tests must import from here. No second implementation
anywhere else.
"""

from __future__ import annotations


def limit_fill_long(o: float, h: float, l: float, zone_hi: float):
    """Correct limit-buy fill at zone_hi.

    Returns (fill_price, mode) or None if the bar never traded at zone_hi.
      GAP_THROUGH_OPEN  — open <= zone_hi (opened at or through the limit)
      INTRABAR_TOUCH    — open > zone_hi but low <= zone_hi (bar traded down to limit)
    """
    if o <= zone_hi:
        return (o, "GAP_THROUGH_OPEN")
    if l <= zone_hi:
        return (zone_hi, "INTRABAR_TOUCH")
    return None


def limit_fill_short(o: float, h: float, l: float, zone_lo: float):
    """Correct limit-sell fill at zone_lo.

    Returns (fill_price, mode) or None if the bar never traded at zone_lo.
      GAP_THROUGH_OPEN  — open >= zone_lo
      INTRABAR_TOUCH    — open < zone_lo but high >= zone_lo
    """
    if o >= zone_lo:
        return (o, "GAP_THROUGH_OPEN")
    if h >= zone_lo:
        return (zone_lo, "INTRABAR_TOUCH")
    return None


def simulate_trade(bars, ep: float, direction: int, tp_pts: float, sl_orig: float,
                   be_bar: int = 30, max_hold: int = 480,
                   skip_first_bar: bool = False):
    """Correct intrabar-aware simulation with proper BE30.

    Args:
        bars: sequence of bar objects with .open/.high/.low/.close
        ep: entry price (bar open of entry bar for SIM, limit price for LIMIT)
        direction: +1 long, -1 short
        tp_pts: target distance in points
        sl_orig: original stop price
        be_bar: bar offset (from start of evaluated bars) at which BE activates
        max_hold: maximum bars to hold before TIME exit
        skip_first_bar: True for intrabar limit fills — no TP/SL credit on bar 0

    Returns:
        (exit_type, bar_idx, exit_price, r_multiple)
        exit_type: "TARGET" | "STOP" | "TIME"

    Chronology guarantees:
        - Stop active at bar open governs the entire bar (no same-bar BE activation and test)
        - BE stop activates at end of be_bar, takes effect at be_bar+1's open
        - Timeout exits at bars[end].close (not open)
        - Stop-first on same-bar ambiguity (stop check before target check)
    """
    risk = abs(ep - sl_orig)
    tgt = ep + direction * tp_pts
    stp_next = sl_orig
    stp_at_open = sl_orig
    be_triggered = False
    n = len(bars)
    end = min(n - 1, max_hold)

    for idx in range(end + 1):
        if skip_first_bar and idx == 0:
            continue

        stp_at_open = stp_next
        b = bars[idx]

        if direction > 0:
            hs = b.low <= stp_at_open
            ht = b.high >= tgt
        else:
            hs = b.high >= stp_at_open
            ht = b.low <= tgt

        if hs:
            return ("STOP", idx, stp_at_open, -abs(ep - stp_at_open) / risk)
        if ht:
            return ("TARGET", idx, tgt, tp_pts / risk)

        # BE eligibility check AFTER evaluating this bar's exit; effect on NEXT bar only
        if not be_triggered and idx >= be_bar:
            cur = b.high if direction > 0 else b.low
            if (direction > 0 and cur > ep) or (direction < 0 and cur < ep):
                stp_next = ep
                be_triggered = True

    return ("TIME", end, bars[end].close, (bars[end].close - ep) * direction / risk)


def occupancy_filter(trades: list, sort_key=None) -> list:
    """Apply global one-position occupancy filter.

    Sorts by (entry_ts, episode_id) for deterministic tie-breaking.
    Blocks a trade whose entry_ts falls before the previous trade's exit_ts.

    trades: list of dicts with keys 'e' (entry_ts), 'xts' (exit_ts), 'episode_id'
    sort_key: optional callable override for sort key
    """
    if sort_key is None:
        sort_key = lambda t: (t["e"], t.get("episode_id", ""))
    tr = sorted(trades, key=sort_key)
    out = []
    until = None
    for t in tr:
        if until is not None and t["e"] < until:
            continue
        out.append(t)
        until = t["xts"]
    return out


def matched_fill_comparison(sim_trades: list, lim_trades: list,
                            key_fn=None) -> list:
    """ID-based fill comparison between SIM and LIMIT fills.

    Default key: (entry_ts, direction, episode_id) — immutable across both runs.
    Returns list of dicts with fields: key, sim_ep, lim_ep, diff, sim_pts, lim_pts.
    Trades present in only one list are recorded with the missing side as None.
    """
    if key_fn is None:
        def key_fn(t):
            return (t.get("e"), t.get("direction"), t.get("episode_id", ""))

    sim_map = {key_fn(t): t for t in sim_trades}
    lim_map = {key_fn(t): t for t in lim_trades}
    all_keys = sorted(set(sim_map) | set(lim_map), key=lambda k: (k[0], k[1] or 0, k[2] or ""))

    rows = []
    for k in all_keys:
        s = sim_map.get(k)
        l = lim_map.get(k)
        rows.append({
            "key": k,
            "sim_ep": s["ep"] if s else None,
            "lim_ep": l["ep"] if l else None,
            "fill_diff": (l["ep"] - s["ep"]) if (s and l) else None,
            "sim_pts": s.get("pts") if s else None,
            "lim_pts": l.get("pts") if l else None,
            "sim_only": l is None,
            "lim_only": s is None,
        })
    return rows

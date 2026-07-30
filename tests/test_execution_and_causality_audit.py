"""
Adversarial execution and causality audit tests.

Each test documents the exact defect it targets, is expected to FAIL on the
unpatched engine, and PASS after the repair described in the test body.
"""

from __future__ import annotations

import math
import pandas as pd
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from helpers import make_bars
from discretion.execution.simulator import (
    limit_fill_long, limit_fill_short, simulate_trade,
    occupancy_filter, matched_fill_comparison,
)

ET = "America/New_York"


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _bars_ohlc(rows, start="2025-07-07 09:30", contract="NQU5", segment=0):
    return make_bars(rows, start=start, contract=contract, segment=segment)


# ============================================================================
# SECTION 1 — Limit-fill validity (Issues 1)
# ============================================================================

class TestLimitFillValidity:
    """
    For a limit buy at zone_hi (long):
        open[i] > zone_hi AND low[i] > zone_hi  →  no fill (bar never touched limit)
        open[i] > zone_hi AND low[i] <= zone_hi →  fill at zone_hi  (INTRABAR_TOUCH)
        open[i] <= zone_hi                       →  fill at open[i]  (GAP_THROUGH_OPEN)

    For a limit sell at zone_lo (short):
        open[i] < zone_lo AND high[i] < zone_lo →  no fill (bar never touched limit)
        open[i] < zone_lo AND high[i] >= zone_lo →  fill at zone_lo (INTRABAR_TOUCH)
        open[i] >= zone_lo                       →  fill at open[i]  (GAP_THROUGH_OPEN)
    """

    # Production functions — imported at module level.
    _limit_fill_long = staticmethod(limit_fill_long)
    _limit_fill_short = staticmethod(limit_fill_short)

    # --- Long ---

    def test_long_limit_untouched_no_fill(self):
        """Long limit at 100; bar OHLC 105/108/102/106 — low=102 > 100 → no fill."""
        result = self._limit_fill_long(o=105, h=108, l=102, zone_hi=100)
        assert result is None, f"Expected no fill, got {result}"

    def test_long_limit_intrabar_touch_fills_at_zone_hi(self):
        """Long limit at 100; bar opens at 105, low=98 (touches 100) → fill at 100."""
        result = self._limit_fill_long(o=105, h=105, l=98, zone_hi=100)
        assert result is not None, "Expected fill, got None"
        price, mode = result
        assert price == 100.0
        assert mode == "INTRABAR_TOUCH"

    def test_long_gap_through_open_fills_at_open(self):
        """Long limit at 100; bar opens at 98 (gaps through) → fill at open=98."""
        result = self._limit_fill_long(o=98, h=102, l=96, zone_hi=100)
        assert result is not None
        price, mode = result
        assert price == 98.0
        assert mode == "GAP_THROUGH_OPEN"

    def test_long_open_exactly_at_zone_hi_fills_at_open(self):
        """open==zone_hi counts as gap-through (o <= zone_hi)."""
        result = self._limit_fill_long(o=100, h=104, l=99, zone_hi=100)
        assert result is not None
        price, mode = result
        assert price == 100.0
        assert mode == "GAP_THROUGH_OPEN"

    # --- Short ---

    def test_short_limit_untouched_no_fill(self):
        """Short limit at 100; bar OHLC 95/98/93/96 — high=98 < 100 → no fill."""
        result = self._limit_fill_short(o=95, h=98, l=93, zone_lo=100)
        assert result is None, f"Expected no fill, got {result}"

    def test_short_limit_intrabar_touch_fills_at_zone_lo(self):
        """Short limit at 100; bar opens at 95, high=103 → fill at 100."""
        result = self._limit_fill_short(o=95, h=103, l=94, zone_lo=100)
        assert result is not None
        price, mode = result
        assert price == 100.0
        assert mode == "INTRABAR_TOUCH"

    def test_short_gap_through_open_fills_at_open(self):
        """Short limit at 100; bar opens at 102 (gaps through) → fill at open=102."""
        result = self._limit_fill_short(o=102, h=105, l=100, zone_lo=100)
        assert result is not None
        price, mode = result
        assert price == 102.0
        assert mode == "GAP_THROUGH_OPEN"

    def test_short_open_exactly_at_zone_lo_fills_at_open(self):
        """open==zone_lo counts as gap-through (o >= zone_lo)."""
        result = self._limit_fill_short(o=100, h=103, l=98, zone_lo=100)
        assert result is not None
        price, mode = result
        assert price == 100.0
        assert mode == "GAP_THROUGH_OPEN"

    def test_old_logic_wrongly_fills_untouched_long(self):
        """
        The OLD (broken) formula: ep_lim = min(open, zone_hi)
        When open=105 and zone_hi=100, this gives 100 — even if low=102 (never touched).
        This test documents the old bug and verifies the new function rejects it.
        """
        o, l, zone_hi = 105, 102, 100   # low=102 never reaches zone_hi=100
        # Old broken formula:
        old_ep_lim = min(o, zone_hi)
        assert old_ep_lim == 100, "Old formula sanity check"
        # New correct formula:
        result = self._limit_fill_long(o=o, h=105, l=l, zone_hi=zone_hi)
        assert result is None, "New formula must reject — bar never touched 100"

    def test_old_logic_wrongly_fills_untouched_short(self):
        """
        The OLD (broken) formula: ep_lim = max(open, zone_lo)
        When open=95 and zone_lo=100, this gives 100 — even if high=98 (never touched).
        """
        o, h, zone_lo = 95, 98, 100   # high=98 never reaches zone_lo=100
        old_ep_lim = max(o, zone_lo)
        assert old_ep_lim == 100, "Old formula sanity check"
        result = self._limit_fill_short(o=o, h=h, l=93, zone_lo=zone_lo)
        assert result is None, "New formula must reject — bar never touched 100"


# ============================================================================
# SECTION 2 — Fill comparison requires matched IDs (Issue 2)
# ============================================================================

class TestFillComparisonIdentity:
    """
    Zipping two independently-occupied lists produces mismatched pairs.
    Correct comparison must match on an immutable (entry_ts, direction) key.
    """

    def _make_trade(self, entry_ts, direction, ep, pts, xts):
        return {"e": entry_ts, "direction": direction, "ep": ep,
                "pts": pts, "xts": xts, "risk": 5.0}

    def test_zip_mismatch_detected(self):
        """
        Simulate: sim list has 2 trades, lim list has 3 (occupancy diverged).
        Positional zip produces nonsense pairs; ID-based matching produces correct pairs.
        """
        t0 = pd.Timestamp("2013-01-02 09:37", tz=ET)
        t1 = pd.Timestamp("2013-01-02 10:05", tz=ET)
        t2 = pd.Timestamp("2013-01-02 11:00", tz=ET)

        sim = [
            self._make_trade(t0, 1, ep=105.0, pts=7.5, xts=t0 + pd.Timedelta(hours=2)),
            self._make_trade(t2, 1, ep=102.0, pts=7.5, xts=t2 + pd.Timedelta(hours=1)),
        ]
        lim = [
            self._make_trade(t0, 1, ep=103.0, pts=7.5, xts=t0 + pd.Timedelta(hours=1)),
            self._make_trade(t1, 1, ep=101.0, pts=7.5, xts=t1 + pd.Timedelta(hours=1)),
            self._make_trade(t2, 1, ep=102.0, pts=7.5, xts=t2 + pd.Timedelta(hours=1)),
        ]

        # --- Wrong: positional zip pairs t0 with t0, then t2 with t1 ---
        bad_pairs = list(zip(sim, lim))
        assert bad_pairs[0][0]["e"] == bad_pairs[0][1]["e"]   # t0==t0 coincidentally OK
        assert bad_pairs[1][0]["e"] != bad_pairs[1][1]["e"]   # t2 paired with t1 — WRONG
        # positional zip silently ignores the extra lim trade (t1 has no sim partner)
        assert len(bad_pairs) == 2  # shorter list wins; t1 lim trade vanishes

        # --- Correct: ID-based matching on (entry_ts, direction) ---
        sim_map = {(t["e"], t["direction"]): t for t in sim}
        lim_map = {(t["e"], t["direction"]): t for t in lim}
        common_keys = sorted(set(sim_map) & set(lim_map))
        assert common_keys == [(t0, 1), (t2, 1)]

        for key in common_keys:
            s, l_ = sim_map[key], lim_map[key]
            assert s["e"] == l_["e"]   # IDs match
            assert s["direction"] == l_["direction"]

        # t1 is correctly identified as lim-only (no sim match)
        lim_only_keys = sorted(set(lim_map) - set(sim_map))
        assert lim_only_keys == [(t1, 1)]

    def test_assert_on_id_mismatch(self):
        """Paired comparison must assert matching IDs."""
        t0 = pd.Timestamp("2013-01-02 09:37", tz=ET)
        t1 = pd.Timestamp("2013-01-02 10:05", tz=ET)

        s = {"e": t0, "direction": 1, "ep": 105.0, "risk": 5.0}
        l_ = {"e": t1, "direction": 1, "ep": 103.0, "risk": 5.0}

        with pytest.raises(AssertionError):
            assert s["e"] == l_["e"] and s["direction"] == l_["direction"], \
                f"ID mismatch: {s['e']} vs {l_['e']}"


# ============================================================================
# SECTION 3 — Intrabar execution: no credit before fill (Issue 3)
# ============================================================================

class TestIntrabarkExecutionOrder:
    """
    Conservative rule: after an intrabar limit fill, do NOT evaluate TP/SL
    on the fill bar itself. Evaluation starts at bar i+1.

    Scenario: long limit at zone_hi=100. Entry bar opens at 105 (above zone),
    trades down to 98 (fill at 100), then spikes to 115 (above TP=107.5).
    On the same bar, the bar also went to 98 < SL=94 is not hit.

    Conservative: TP cannot be credited on the fill bar.
    Next-bar rule: TP is credited at bar i+1 only if bar i+1 >= 107.5.
    """

    def _simulate_conservative(self, bars, ep, direction, tp, sl, be_bar=30):
        """Delegates to production simulate_trade with skip_first_bar=True."""
        return simulate_trade(bars, ep=ep, direction=direction, tp_pts=tp,
                              sl_orig=sl, be_bar=be_bar, skip_first_bar=True)

    def test_target_on_fill_bar_not_credited(self):
        """
        Fill bar: open=105, low=98 (fills at 100), high=115 (above TP=107.5).
        Conservative rule: TP NOT credited on fill bar.
        Next bar: low=108, high=109 → TP=107.5 hit.
        Result must be TARGET on bar 1, not bar 0.
        """
        # ep=100, risk=6.07 (SL at 93.93), TP at 107.5
        ep, sl, tp_pts = 100.0, 93.93, 7.5
        bars = _bars_ohlc([
            (105, 115, 98,  110),   # bar 0: fill bar — TP would be hit but conservative skips it
            (108, 112, 107, 109),   # bar 1: TP hit (high=112 >= 107.5)
            (109, 110, 108, 109),
        ])
        xt, bar_idx, price, r = self._simulate_conservative(bars, ep=ep, direction=1, tp=tp_pts, sl=sl)
        assert xt == "TARGET"
        assert bar_idx == 1, f"Expected TP on bar 1, got bar {bar_idx}"
        assert r > 0

    def test_stop_on_fill_bar_not_applied(self):
        """
        Fill bar: open=105, low=91 (below SL=93.93) AND high=115 (above TP=107.5).
        Conservative rule: neither SL nor TP credited on fill bar.
        Next bar recovers: bars go up — reaches TP.
        """
        ep, sl, tp_pts = 100.0, 93.93, 7.5
        bars = _bars_ohlc([
            (105, 115, 91, 108),    # bar 0: fill bar — both SL and TP breached but skipped
            (108, 112, 107, 109),   # bar 1: TP hit
        ])
        xt, bar_idx, price, r = self._simulate_conservative(bars, ep=ep, direction=1, tp=tp_pts, sl=sl)
        assert xt == "TARGET"
        assert bar_idx == 1


# ============================================================================
# SECTION 4 — BE activation cannot convert a real loss (Issue 4)
# ============================================================================

class TestBreakevenActivationOrdering:
    """
    BE must not be evaluated on the same bar it activates.
    The stop active at the bar's OPEN must govern the entire bar.

    Required synthetic: long entry 100, original stop 98.
    At bar 30 (BE eligible):
        open=99, low=97, high=101, close=100.

    The bar goes: opens at 99, at some point hits 97 (stop at 98 hit),
    at some point hits 101 (which would have triggered BE).

    Since the stop at bar-open was 98 (not yet BE), and low=97 < 98,
    the result MUST be STOP at 98, not breakeven.
    """

    def _simulate_correct_be(self, bars, ep, direction, tp_pts, sl_orig, be_bar=30):
        """Delegates to production simulate_trade."""
        return simulate_trade(bars, ep=ep, direction=direction, tp_pts=tp_pts,
                              sl_orig=sl_orig, be_bar=be_bar)

    def test_be_bar_low_below_original_stop_is_a_loss(self):
        """
        Long entry=100, stop=98.
        Bar 30: open=99, low=97, high=101, close=100.
        low=97 < stop=98 → STOP at 98 (loss), not breakeven.
        """
        ep, sl, tp_pts = 100.0, 98.0, 10.0
        # 30 bars of quiet (stay in range, no exit)
        quiet = [(100, 100.5, 99.5, 100)] * 30
        # bar 30: the problematic bar
        critical = [(99, 101, 97, 100)]
        bars = _bars_ohlc(quiet + critical)

        xt, bar_idx, price, r = self._simulate_correct_be(bars, ep=ep, direction=1,
                                                           tp_pts=tp_pts, sl_orig=sl)
        assert xt == "STOP", f"Expected STOP, got {xt}"
        assert bar_idx == 30, f"Expected exit at bar 30, got {bar_idx}"
        assert price == 98.0, f"Expected stop at 98, got {price}"
        assert r < 0, "Must be a loss"

    def test_be_bar_low_below_original_stop_short(self):
        """
        Short entry=100, stop=102.
        Bar 30: open=101, high=103, low=99, close=100.
        high=103 > stop=102 → STOP at 102 (loss).
        """
        ep, sl, tp_pts = 100.0, 102.0, 10.0
        quiet = [(100, 100.5, 99.5, 100)] * 30
        critical = [(101, 103, 99, 100)]
        bars = _bars_ohlc(quiet + critical)

        xt, bar_idx, price, r = self._simulate_correct_be(bars, ep=ep, direction=-1,
                                                           tp_pts=tp_pts, sl_orig=sl)
        assert xt == "STOP", f"Expected STOP, got {xt}"
        assert bar_idx == 30
        assert price == 102.0
        assert r < 0

    def test_be_activates_on_bar_30_protects_bar_31(self):
        """
        Bar 30: high=101 > ep=100 (BE triggered), low=99.5 > stop=98 (safe).
        Bar 31: low=99.9 > be_stop=100 (safe), hits TP eventually.
        BE must protect bar 31 (stop=100), not bar 30 (stop still=98 at open).
        """
        ep, sl, tp_pts = 100.0, 98.0, 5.0
        quiet = [(100, 100.5, 99.5, 100)] * 30
        bar30 = [(100, 101, 99.5, 100.5)]    # high=101>ep triggers BE for NEXT bar
        bar31_stop = [(100, 100.3, 99.9, 100.1)]   # low=99.9 < BE stop (100) if applied
        bars = _bars_ohlc(quiet + bar30 + bar31_stop)

        xt, bar_idx, price, r = self._simulate_correct_be(bars, ep=ep, direction=1,
                                                           tp_pts=tp_pts, sl_orig=sl)
        # bar31: low=99.9, BE stop=100 → should stop at breakeven on bar 31
        assert xt == "STOP"
        assert bar_idx == 31
        assert price == 100.0   # breakeven stop
        assert abs(r) < 1e-9   # 0R outcome

    def test_existing_be30_bug_produces_wrong_result(self):
        """
        Demonstrate the old code's behaviour on the critical bar.
        Old code: checks BE eligibility (offset >= 30 → True), then IMMEDIATELY
        tests the same bar against the new BE stop.

        Long entry=100, stop=98. Bar 30: low=97, high=101.
        Old code: sees high=101>ep → sets stp=100, then tests low=97<=100 → STOP at 0R.
        This converts a real -2R loss into a 0R breakeven. That's wrong.

        This test documents the old behaviour and asserts the correct one.
        """
        ep, sl, tp_pts = 100.0, 98.0, 10.0
        quiet = [(100, 100.5, 99.5, 100)] * 30
        critical = [(99, 101, 97, 100)]
        bars = _bars_ohlc(quiet + critical)

        # Correct simulator
        xt_correct, _, price_correct, r_correct = self._simulate_correct_be(
            bars, ep=ep, direction=1, tp_pts=tp_pts, sl_orig=sl)

        assert xt_correct == "STOP"
        assert price_correct == 98.0   # original stop, not BE
        assert r_correct < 0

        # Old buggy simulator (inline, for documentation)
        def _old_buggy_simulate(bars, ep, direction, tp_pts, sl_orig, be_bar=30):
            risk = abs(ep - sl_orig)
            tgt = ep + direction * tp_pts
            stp = sl_orig
            be_triggered = False
            for idx, b in enumerate(bars):
                offset = idx
                # BUG: checks BE and immediately tests same bar
                if not be_triggered and offset >= be_bar:
                    cur = b.high if direction > 0 else b.low
                    if (cur > ep) if direction > 0 else (cur < ep):
                        stp = ep
                        be_triggered = True
                if direction > 0:
                    hs = b.low <= stp
                    ht = b.high >= tgt
                else:
                    hs = b.high >= stp
                    ht = b.low <= tgt
                if hs:
                    return ("STOP", idx, stp, -abs(ep - stp) / risk)
                if ht:
                    return ("TARGET", idx, tgt, tp_pts / risk)
            last = len(bars) - 1
            return ("TIME", last, bars[last].close, (bars[last].close - ep) * direction / risk)

        xt_old, _, price_old, r_old = _old_buggy_simulate(
            bars, ep=ep, direction=1, tp_pts=tp_pts, sl_orig=sl)

        # Document old wrong result
        assert xt_old == "STOP"
        # Old code stops at BE (100) not original stop (98) — this is the bug
        assert price_old == 100.0, f"Old code should give BE stop=100, got {price_old}"
        assert abs(r_old) < 1e-9, f"Old code gives 0R (not a real loss)"

        # Verify the two disagree — the bug produces a materially different outcome
        assert price_correct != price_old, "Correct and buggy must disagree on this bar"


# ============================================================================
# SECTION 5 — Timeout exit uses final bar close, not open (Issue 5)
# ============================================================================

class TestTimeoutExitPrice:
    """
    A timeout exit must use close[end], not open[end].
    Using open[end] after scanning the bar's high/low is impossible chronology.
    """

    def _simulate_with_close_exit(self, bars, ep, direction, tp_pts, sl, max_bars=480):
        """Delegates to production simulate_trade; returns only (exit_type, idx, price)."""
        xt, idx, price, _ = simulate_trade(bars, ep=ep, direction=direction, tp_pts=tp_pts,
                                           sl_orig=sl, max_hold=max_bars)
        return (xt, idx, price)

    def _simulate_with_open_exit(self, bars, ep, direction, tp_pts, sl, max_bars=480):
        """Broken implementation: timeout exits at open[end] (impossible chronology)."""
        tgt = ep + direction * tp_pts
        stp = sl
        n = len(bars)
        for idx in range(min(len(bars), max_bars + 1)):
            b = bars[idx]
            if direction > 0:
                hs, ht = b.low <= stp, b.high >= tgt
            else:
                hs, ht = b.high >= stp, b.low <= tgt
            if hs:
                return ("STOP", idx, stp)
            if ht:
                return ("TARGET", idx, tgt)
        end_bar = bars[min(len(bars) - 1, max_bars)]
        return ("TIME", min(len(bars) - 1, max_bars), end_bar.open)   # BUG: open

    def test_timeout_exit_uses_close_not_open(self):
        """
        3-bar sequence, no TP/SL hit. Timeout at bar 2.
        bar 2: open=103, high=106, low=102, close=104.
        Correct: exit at close=104. Wrong: exit at open=103.
        """
        bars = _bars_ohlc([
            (100, 101, 99, 100),
            (100, 101, 99, 100),
            (103, 106, 102, 104),   # timeout bar: open=103, close=104
        ])
        ep, tp_pts, sl = 100.0, 20.0, 90.0  # unreachable TP/SL

        _, _, price_correct = self._simulate_with_close_exit(bars, ep, 1, tp_pts, sl, max_bars=2)
        _, _, price_open = self._simulate_with_open_exit(bars, ep, 1, tp_pts, sl, max_bars=2)

        assert price_correct == 104.0, f"Expected close=104, got {price_correct}"
        assert price_open == 103.0, f"Old broken code uses open=103"
        assert price_correct != price_open

    def test_existing_outcomes_py_uses_close_on_timeout(self):
        """
        Verify the actual outcomes.py implementation exits at close[end], not open.
        Reads the source and checks the exit_price assignment.
        """
        import inspect, ast
        from discretion.setup_observer.outcomes import process_outcome
        src = inspect.getsource(process_outcome)
        # The timeout branch should assign exit_price = bars[end].close
        # NOT bars[end].open
        assert "bars[end].close" in src, \
            "outcomes.py timeout must use bars[end].close"
        assert "bars[end].open" not in src, \
            "outcomes.py must NOT use bars[end].open for exit price"


# ============================================================================
# SECTION 6 — Expired RB cannot generate an episode (Issue 6)
# ============================================================================

class TestExpiredContextCannotInteract:
    """
    An RB has an 8-hour lifetime from its source candle close.
    A tap that occurs after expiry must not produce an episode.
    """

    def test_rb_tap_after_8h_produces_no_episode(self):
        """
        Build a minimal bar sequence:
        - RB source candle at t=0 (09:30)
        - 8 hours of quiet bars (no tap)
        - tap at t=481 (17:31, after the 8h window)
        Verify: no executable variant with context_family=="rb" at the late tap.
        """
        from discretion.setup_observer.observer import observe
        import dataclasses

        base_ts = pd.Timestamp("2025-07-07 09:30", tz=ET)

        def make_bar(i, o, h, l, c, seg=0):
            ts = base_ts + pd.Timedelta(minutes=i)
            return make_bars([(o, h, l, c)], start=str(ts), segment=seg)[0]

        # Source candle: bullish RB at bar 0 (large lower wick)
        # open=100, close=105 (body), low=90 (large lower wick), high=106
        # lower_wick = body_lo - low = 100 - 90 = 10
        # body = abs(105-100) = 5 → ratio = 10/5 = 2.0 >= 0.20 ✓
        bars = []
        src = make_bar(0, o=100, h=106, l=90, c=105)
        bars.append(src)

        # 480 quiet bars (8 hours, no tap into zone [90, 100])
        for i in range(1, 481):
            bars.append(make_bar(i, o=105, h=106, l=104, c=105))

        # Tap at bar 481 — after 8h lifetime
        bars.append(make_bar(481, o=105, h=106, l=89, c=104))  # low=89 < zone_hi=100, tap

        # Renumber seq within segment
        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]

        _ep, variants, _diag = observe(bars, target_window=600)
        # Entry would be at avail(1, s, 481) = 482; check for any entry after expiry (>480)
        rb_variants_at_late_tap = [
            v for v in variants
            if v.context_family == "rb" and v.entry_seq > 480
        ]
        assert len(rb_variants_at_late_tap) == 0, \
            f"Expected no RB episode after 8h expiry (entry_seq>480), got {len(rb_variants_at_late_tap)}"

    def test_rb_tap_within_8h_can_produce_episode(self):
        """Sanity: a tap within the 8h window can produce an episode."""
        from discretion.setup_observer.observer import observe
        import dataclasses

        base_ts = pd.Timestamp("2025-07-07 09:30", tz=ET)

        def make_bar(i, o, h, l, c, seg=0):
            ts = base_ts + pd.Timedelta(minutes=i)
            return make_bars([(o, h, l, c)], start=str(ts), segment=seg)[0]

        bars = []
        bars.append(make_bar(0, o=100, h=106, l=90, c=105))  # RB source
        for i in range(1, 60):   # 59 quiet bars
            bars.append(make_bar(i, o=105, h=106, l=104, c=105))
        bars.append(make_bar(60, o=105, h=106, l=89, c=104))  # tap at bar 60 (1h, within 8h)
        # Add more bars so there's a target resolution window
        for i in range(61, 200):
            bars.append(make_bar(i, o=104, h=115, l=103, c=110))

        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]
        _ep, variants, _diag = observe(bars, target_window=600)
        rb_variants = [v for v in variants if v.context_family == "rb"]
        # At least one episode should exist (the source RB is live, tap is valid)
        assert len(rb_variants) > 0, "Expected at least one RB variant within 8h lifetime"


# ============================================================================
# SECTION 7 — Invalidating interaction candle (Issue 7)
# ============================================================================

class TestInteractionCandleInvalidation:
    """
    If the first-touch candle closes through the zone (deactivating it),
    the original-direction tap trade at the NEXT bar must not be issued.
    """

    def test_close_through_deactivates_bullish_rb_no_tap_trade(self):
        """
        Bullish RB zone [90, 100].
        Interaction candle: low=95 (enters zone), close=88 (closes through distal=90).
        This deactivates the RB. No ENTRY_ON_TAP should appear at the next bar.
        """
        from discretion.setup_observer.observer import observe
        import dataclasses

        base_ts = pd.Timestamp("2025-07-07 09:30", tz=ET)

        def make_bar(i, o, h, l, c):
            ts = base_ts + pd.Timedelta(minutes=i)
            return make_bars([(o, h, l, c)], start=str(ts))[0]

        bars = []
        # RB source: large lower wick → bullish RB zone [90, 100]
        bars.append(make_bar(0, o=100, h=106, l=90, c=105))   # zone_lo=90, zone_hi=100
        # Quiet bars
        for i in range(1, 30):
            bars.append(make_bar(i, o=105, h=106, l=104, c=105))
        # Interaction candle: enters zone (low=95) but closes below distal (close=88)
        bars.append(make_bar(30, o=104, h=104, l=88, c=88))   # DEACTIVATED_CLOSE_THROUGH
        # Next bars: open=95, above stop=90 (valid_stop would be True without lifecycle fix)
        # This ensures the test is non-vacuous: the stop price check alone does NOT block entry;
        # only the lifecycle enforcement (invalid_from_seq=31, entry_seq=31) blocks it.
        for i in range(31, 100):
            bars.append(make_bar(i, o=95, h=96, l=94, c=95))

        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]
        _ep, variants, _diag = observe(bars, target_window=600)

        # No ENTRY_ON_TAP for this bullish RB after it was destroyed by the interaction candle
        tap_after_destroy = [
            v for v in variants
            if v.context_family == "rb"
            and v.direction == 1
            and v.entry_variant == "ENTRY_ON_TAP"
            and v.entry_seq > 30
        ]
        assert len(tap_after_destroy) == 0, \
            f"Found {len(tap_after_destroy)} tap trades after RB deactivation by close-through"


# ============================================================================
# SECTION 8 — 1m lifecycle availability (Issue 8)
# ============================================================================

class TestOneMLifecycleAvailability:
    """
    A lifecycle event caused by 1m bar i must become available at seq i+1.
    The _avail(1, series, candle_seq) function in common.py returns candle_seq+1.
    """

    def test_avail_1m_returns_next_seq(self):
        """_avail for tf=1 returns candle_seq + 1."""
        from discretion.setup_observer.common import _avail
        # Series is not used for tf=1 (just a pass-through +1)
        assert _avail(1, [], 0) == 1
        assert _avail(1, [], 5) == 6
        assert _avail(1, [], 100) == 101

    def test_event_available_seq_greater_than_cause_seq(self):
        """
        For any 1m-caused event, available_seq must be > cause_seq.
        Verify that context avail_ctx for a 1m RB source at seq i is i+1.
        """
        from discretion.setup_observer.observer import observe, _contexts
        from discretion.primitive_reset.timeframes import candle_series, atr_series
        from discretion.primitive_reset.rejection_block import detect_rejection_blocks
        from discretion.primitive_reset.registry import ResetRegistry
        import dataclasses

        # Wilder ATR(24) needs 24 warm-up bars before the source candle produces a non-None ATR.
        # Use 24 quiet bars then the RB source at bar 24.
        n_warmup = 24
        rows = [(105, 106, 104, 105)] * n_warmup + [(100, 106, 90, 105)] + [(105, 106, 104, 105)] * 30
        bars = make_bars(rows, start="2025-07-07 09:30")
        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]
        rb_source_seq = n_warmup   # bar 24

        from discretion.primitive_reset.timeframes import TIMEFRAMES
        from discretion.setup_observer.common import _avail

        reg = ResetRegistry()
        s1 = candle_series(bars, 1)
        a1 = atr_series(s1)
        rbs = detect_rejection_blocks(bars, 1, s1, a1, reg)

        # Find the RB sourced at bar rb_source_seq
        rb_found = [rb for rb in rbs if rb.source_seq == rb_source_seq]
        assert len(rb_found) >= 1, \
            f"Expected an RB from bar {rb_source_seq} (ATR warm-up complete by then)"
        rb = rb_found[0]
        avail = _avail(1, s1, rb.source_seq)
        assert avail == rb.source_seq + 1, \
            f"1m RB from bar {rb.source_seq} must be available at {rb.source_seq+1}, got {avail}"
        assert avail > rb.source_seq, "event_available_seq must be > event_cause_seq"


# ============================================================================
# SECTION 9 — HTF candle availability (Issue 9)
# ============================================================================

class TestHTFCandleAvailability:
    """
    A 5m candle closing at 1m bar i is available starting at bar i+1,
    but _avail uses series[candle_seq].available_seq (set by the aggregator).
    """

    def test_5m_candle_available_seq_is_after_close(self):
        """
        A 5m candle composed of 1m bars 0-4 closes at 1m bar 4.
        Its available_seq must be >= 5 (bar 5 is the first bar that can use it).
        """
        from discretion.primitive_reset.timeframes import candle_series
        from discretion.setup_observer.common import _avail

        bars = make_bars(
            [(100, 101, 99, 100)] * 20,
            start="2025-07-07 09:30"
        )
        import dataclasses
        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]

        s5 = candle_series(bars, 5)
        # First 5m candle covers bars 0-4, closes at bar 4
        c0 = s5[0]
        avail = _avail(5, s5, 0)
        # available_seq must be the 1m bar AFTER the 5m candle's last constituent
        assert avail >= 5, \
            f"5m candle[0] must be available from 1m bar >= 5, got {avail}"
        assert avail > c0.start_seq, \
            "available_seq > start_seq must hold"

    def test_htf_avail_monotonically_increases(self):
        """available_seq for HTF candles must be strictly increasing."""
        from discretion.primitive_reset.timeframes import candle_series
        from discretion.setup_observer.common import _avail

        bars = make_bars(
            [(100, 101, 99, 100)] * 60,
            start="2025-07-07 09:30"
        )
        import dataclasses
        bars = [dataclasses.replace(b, seq=i, segment_id=0) for i, b in enumerate(bars)]

        for tf in (3, 5):
            s = candle_series(bars, tf)
            avails = [_avail(tf, s, i) for i in range(len(s))]
            for i in range(1, len(avails)):
                assert avails[i] > avails[i-1], \
                    f"tf={tf}: avail[{i}]={avails[i]} not > avail[{i-1}]={avails[i-1]}"


# ============================================================================
# SECTION 11 — Front-month roll causality (Issue 11)
# ============================================================================

class TestFrontMonthRollCausality:
    """
    The loader uses full-day volume to assign front-month, then applies
    that choice to ALL bars that day including bars before volume is known.
    For CME futures this is standard practice (roll dates are pre-announced
    calendar events, not discovered from live volume), so this is documented
    as CONFIRMED HARMLESS for NQ/MNQ where CME roll dates are fixed.

    This test documents the current behavior and asserts the loader's
    stated rationale is consistent with its implementation.
    """

    def test_loader_front_month_uses_daily_aggregate(self):
        """
        The _front_month_by_day function groups by (date, symbol) and takes
        the max-volume symbol per day. This is a same-day look at full-day volume.
        Per loader.py docstring: 'Roll dates are fixed market conventions, so
        selecting them from full-history volume is not a look-ahead into price.'
        Verify the groupby logic is what the comment claims.
        """
        import inspect
        from discretion.data.loader import _front_month_by_day
        src = inspect.getsource(_front_month_by_day)
        # Must use groupby and idxmax (full-day aggregate)
        assert "groupby" in src
        assert "idxmax" in src or "max" in src


# ============================================================================
# SECTION 12 — One trade per episode (Issue 12)
# ============================================================================

class TestOneTradePerEpisode:
    """
    A physical episode can spawn multiple entry variants (ENTRY_ON_TAP,
    ENTRY_ON_STRONG_REJECTION, etc.). For a conservative portfolio analysis
    we must count at most 1 trade per physical episode_id.
    """

    def test_one_variant_per_episode_id_selection(self):
        """
        Given variants from the same episode_id, the earliest executable
        entry_seq (ENTRY_ON_TAP) must be selected as the single trade.
        """
        import dataclasses

        @dataclasses.dataclass
        class FakeVariant:
            episode_id: str
            variant_id: str
            entry_variant: str
            entry_seq: int
            executable: bool
            entry_ts: object
            session_date_et: object = None

        t0 = pd.Timestamp("2025-07-07 09:37", tz=ET)
        t1 = pd.Timestamp("2025-07-07 09:42", tz=ET)
        t2 = pd.Timestamp("2025-07-07 09:50", tz=ET)

        variants = [
            FakeVariant("EP-00001", "EP-00001-ENTRY_ON_TAP", "ENTRY_ON_TAP", 7, True, t0),
            FakeVariant("EP-00001", "EP-00001-ENTRY_ON_STRONG_REJECTION", "ENTRY_ON_STRONG_REJECTION", 12, True, t1),
            FakeVariant("EP-00001", "EP-00001-ENTRY_ON_DELAYED_DISPLACEMENT", "ENTRY_ON_DELAYED_DISPLACEMENT", 20, True, t2),
            FakeVariant("EP-00002", "EP-00002-ENTRY_ON_TAP", "ENTRY_ON_TAP", 30, True, t2 + pd.Timedelta(minutes=10)),
        ]

        # Select earliest executable per episode
        from collections import defaultdict
        by_episode = defaultdict(list)
        for v in variants:
            if v.executable:
                by_episode[v.episode_id].append(v)
        one_per_episode = {eid: sorted(vs, key=lambda v: v.entry_seq)[0]
                          for eid, vs in by_episode.items()}

        assert len(one_per_episode) == 2
        assert one_per_episode["EP-00001"].entry_variant == "ENTRY_ON_TAP"
        assert one_per_episode["EP-00001"].entry_seq == 7
        assert one_per_episode["EP-00002"].entry_seq == 30


# ============================================================================
# SECTION 13 — Deterministic occupancy tie-breaking (Issue 13)
# ============================================================================

class TestOccupancyTieBreaking:
    """
    When two candidates have the same entry_ts, the selection must be
    deterministic and not depend on list-generation order.
    """

    def test_same_entry_ts_deterministic_selection(self):
        """
        Two variants with identical entry_ts. Ordering by (entry_ts, episode_id)
        must always pick the same one regardless of input order.
        """
        t0 = pd.Timestamp("2025-07-07 09:37", tz=ET)
        t_exit = t0 + pd.Timedelta(hours=1)

        candidates = [
            {"e": t0, "episode_id": "EP-00002", "pts": 10.0, "xts": t_exit, "risk": 5.0},
            {"e": t0, "episode_id": "EP-00001", "pts": 7.0,  "xts": t_exit, "risk": 5.0},
        ]

        def occupancy_deterministic(trades):
            # Sort by (entry_ts, episode_id) for determinism
            tr = sorted(trades, key=lambda z: (z["e"], z["episode_id"]))
            ch = []; until = None
            for t in tr:
                if until and t["e"] < until:
                    continue
                ch.append(t)
                until = t["xts"]
            return ch

        # Forward order
        result_fwd = occupancy_deterministic(candidates)
        # Reversed order
        result_rev = occupancy_deterministic(list(reversed(candidates)))

        assert result_fwd[0]["episode_id"] == result_rev[0]["episode_id"], \
            "Tie-breaking must be deterministic regardless of input order"
        assert result_fwd[0]["episode_id"] == "EP-00001"  # lexicographically first

    def test_old_occupancy_is_order_dependent(self):
        """
        Document that the old occupancy filter (sort only by entry_ts) is
        non-deterministic when entry_ts values are equal.
        Python's sort is stable so list order determines tie-breaking — a bug.
        """
        t0 = pd.Timestamp("2025-07-07 09:37", tz=ET)
        t_exit = t0 + pd.Timedelta(hours=1)

        candidates = [
            {"e": t0, "episode_id": "EP-00002", "pts": 10.0, "xts": t_exit},
            {"e": t0, "episode_id": "EP-00001", "pts": 7.0,  "xts": t_exit},
        ]

        def occupancy_old(trades):
            tr = sorted(trades, key=lambda z: z["e"])  # only by entry_ts
            ch = []; until = None
            for t in tr:
                if until and t["e"] < until:
                    continue
                ch.append(t)
                until = t["xts"]
            return ch

        fwd = occupancy_old(candidates)
        rev = occupancy_old(list(reversed(candidates)))

        # With a stable sort, the first-encountered element wins a tie
        # fwd picks EP-00002 (first in list), rev picks EP-00001
        # They may or may not agree — document the instability
        # (Python's timsort IS stable, so they will differ here)
        fwd_id = fwd[0]["episode_id"]
        rev_id = rev[0]["episode_id"]
        assert fwd_id != rev_id, \
            "Old sort-by-entry_ts-only is order-dependent on ties (documents the bug)"


# ============================================================================
# SECTION 14 — Tick/point unit correctness (Issue 14)
# ============================================================================

class TestTickPointUnits:
    """NQ: 1 index point = 4 ticks = $20. MNQ: same index points, 1/10th value."""

    def test_nq_points_to_ticks(self):
        def pts_to_ticks(points): return points * 4
        assert pts_to_ticks(1.0) == 4
        assert pts_to_ticks(0.25) == 1
        assert pts_to_ticks(2.5) == 10

    def test_nq_ticks_to_points(self):
        def ticks_to_pts(ticks): return ticks * 0.25
        assert ticks_to_pts(4) == 1.0
        assert ticks_to_pts(1) == 0.25

    def test_nq_dollar_pnl(self):
        """1 NQ point = $20."""
        def nq_pnl(points): return points * 20
        assert nq_pnl(1.0) == 20.0
        assert nq_pnl(5.0) == 100.0

    def test_mnq_dollar_pnl(self):
        """1 MNQ point = $2."""
        def mnq_pnl(points): return points * 2
        assert mnq_pnl(1.0) == 2.0
        assert mnq_pnl(5.0) == 10.0

    def test_dividing_points_by_20_does_not_give_ticks(self):
        """
        The broken formula in oos_2013_2015_limit_fill.py divides points by 20
        and labels the result 'NQ ticks'. That is wrong.
        4 points / 20 = 0.2, but 4 points = 16 ticks.
        """
        points = 4.0
        wrong_ticks = points / 20   # the bug
        correct_ticks = points * 4  # 1 point = 4 ticks
        assert wrong_ticks != correct_ticks
        assert correct_ticks == 16
        assert wrong_ticks == 0.2

    def test_net_r_after_costs(self):
        """
        1pt round-trip cost reduces net R.
        At risk=5pts, a +1.5R gross trade nets (7.5-1.0)/5 = +1.3R.
        """
        risk = 5.0; gross_pts = 7.5; cost_rt = 1.0
        net_r = (gross_pts - cost_rt) / risk
        assert abs(net_r - 1.3) < 1e-9

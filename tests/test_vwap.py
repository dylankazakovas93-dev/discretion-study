"""Session VWAP computation and interaction events."""

from __future__ import annotations

from discretion.primitives.base import IdRegistry
from discretion.primitives.vwap import build_vwap_sessions
from helpers import make_bars


def test_vwap_first_bar_equals_typical_price():
    bars = make_bars([(100, 102, 98, 101)], start="2025-07-07 09:30")
    vs = build_vwap_sessions(bars, IdRegistry())[0]
    tp = (102 + 98 + 101) / 3
    assert abs(vs.value_at(0)["vwap"] - tp) < 1e-9


def test_vwap_uptrend_acceptance_and_continuation():
    rows = [(100, 100.2, 99.8, 100)]
    for k in range(1, 6):
        base = 100 + k  # marching up, staying above the (lagging) vwap
        rows.append((base, base + 0.3, base - 0.2, base + 0.2))
    bars = make_bars(rows, start="2025-07-07 09:30")
    vs = build_vwap_sessions(bars, IdRegistry())[0]
    assert vs.has_event("ACCEPTANCE_ABOVE")
    assert vs.has_event("CONTINUATION")


def test_vwap_session_resets_at_1800_et():
    rows = [(100, 100.2, 99.8, 100)] * 3
    bars = make_bars(rows, start="2025-07-07 17:59")  # crosses 18:00 boundary
    sessions = build_vwap_sessions(bars, IdRegistry())
    assert len(sessions) == 2  # one before 18:00, one at/after


def test_vwap_band_rejection():
    # Build a flat base (tiny sd), then a spike whose high pierces the band but
    # closes back below it -> band rejection (fade toward vwap).
    rows = [(100, 100.05, 99.95, 100)] * 8
    rows.append((100, 106, 99.9, 99.9))  # spike high 106, close back below
    bars = make_bars(rows, start="2025-07-07 09:30")
    vs = build_vwap_sessions(bars, IdRegistry())[0]
    band_rejects = [e for e in vs.events
                    if e.kind == "REJECTION" and e.note.startswith("band_reject")]
    assert band_rejects

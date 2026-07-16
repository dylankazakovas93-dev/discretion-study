"""Deterministic candlestick charts for review-pack examples.

Pure matplotlib (Agg), no external assets. Charts show the local 1-minute window
around a primitive or setup, with the relevant zone/level and — for setups — the
frozen entry, structural stop, natural target and executed (capped) target.
Outcome is not used to choose the window, only to mark where it resolved.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


def _candles(ax, bars, i0, i1):
    for k in range(i0, i1):
        b = bars[k]
        up = b.close >= b.open
        color = "#26a69a" if up else "#ef5350"
        ax.plot([k, k], [b.low, b.high], color=color, linewidth=0.6, zorder=1)
        lo = min(b.open, b.close)
        hi = max(b.open, b.close)
        ax.add_patch(Rectangle((k - 0.3, lo), 0.6, max(hi - lo, 0.01),
                               facecolor=color, edgecolor=color, zorder=2))
    # a few ET time labels
    ticks = list(range(i0, i1, max(1, (i1 - i0) // 6)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([bars[t].ts_et.strftime("%m-%d\n%H:%M") for t in ticks],
                       fontsize=7)


def _window(bars, center, back, fwd):
    i0 = max(0, center - back)
    i1 = min(len(bars), center + fwd)
    # keep within one segment
    seg = bars[center].segment_id
    while i0 < center and bars[i0].segment_id != seg:
        i0 += 1
    while i1 - 1 > center and bars[i1 - 1].segment_id != seg:
        i1 -= 1
    return i0, i1


def render_primitive_chart(bars, p, path, title):
    center = p.created_seq
    i0, i1 = _window(bars, center, 20, 45)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _candles(ax, bars, i0, i1)
    if p.is_zone:
        ax.add_patch(Rectangle((center - 0.5, p.lo), (i1 - 1) - center + 0.5,
                               p.hi - p.lo, facecolor="#42a5f5", alpha=0.20,
                               edgecolor="#1e88e5", zorder=0))
    else:
        ax.axhline(p.price_ref if hasattr(p, "price_ref") else p.price,
                   color="#1e88e5", linewidth=1.0, linestyle="--")
    ax.axvline(center, color="#616161", linewidth=0.8, linestyle=":")
    ax.set_title(title, fontsize=10)
    ax.set_ylabel("NQ points")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def render_setup_chart(bars, s, path, title):
    end = s.outcome_seq if s.outcome_seq else s.expiry_seq
    i0, i1 = _window(bars, s.entry_seq, 25, max(30, end - s.entry_seq + 10))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _candles(ax, bars, i0, i1)
    x_right = i1 - 1
    ax.axhline(s.entry_price, color="#1e88e5", lw=1.0, label=f"entry {s.entry_price:.2f}")
    ax.axhline(s.structural_stop, color="#ef5350", lw=1.0, ls="-",
               label=f"stop {s.structural_stop:.2f}")
    ax.axhline(s.executed_target, color="#26a69a", lw=1.2, ls="-",
               label=f"exec target {s.executed_target:.2f} ({s.executed_rr:.2f}R)")
    if abs(s.structural_target - s.executed_target) > 1e-6:
        ax.axhline(s.structural_target, color="#26a69a", lw=0.8, ls="--",
                   label=f"natural target {s.structural_target:.2f}")
    ax.axvline(s.entry_seq, color="#616161", lw=0.8, ls=":")
    marker = "^" if s.direction == "long" else "v"
    ax.scatter([s.entry_seq], [s.entry_price], marker=marker, s=80,
               color="#1e88e5", zorder=5)
    if s.outcome_seq:
        ax.axvline(s.outcome_seq, color="#9c27b0", lw=0.6, ls=":")
    ax.set_title(title, fontsize=9)
    ax.set_ylabel("NQ points")
    ax.legend(fontsize=6, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)

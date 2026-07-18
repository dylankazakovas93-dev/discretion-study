"""Stage 5 chart rendering for the review-week structure-and-setup atlas.

Every chart shows only what was causally available at the trigger normally, and
visually separates/labels anything used only for outcome evaluation:
`POST-TRIGGER OUTCOME -- NOT AVAILABLE TO DECISION`. No structure created after
the trigger is ever drawn into the pre-trigger portion of a chart.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from ..review.charts import _candles, _window

POST_LABEL = "POST-TRIGGER OUTCOME -- NOT AVAILABLE TO DECISION"


def _zone(ax, lo, hi, x0, x1, color, alpha=0.15, label=None):
    ax.add_patch(Rectangle((x0, lo), x1 - x0, max(hi - lo, 1e-9),
                           facecolor=color, alpha=alpha, edgecolor=color,
                           linewidth=0.6, zorder=0))
    if label:
        ax.text(x0, hi, label, fontsize=5, color=color, va="bottom")


def _overlay_stop_target_zones(ax, cand, ps, trig_x, x0, x1):
    """Draw the stop-anchor and target-anchor structures, restricted to the
    portion of the window at/before the trigger (they are causally available
    structures, never redrawn using post-trigger knowledge)."""
    for oid, color, label in ((cand.stop_anchor_object_id, "#ef5350", "stop anchor"),
                              (cand.target_anchor_object_id, "#26a69a", "target anchor")):
        if not oid or oid.startswith("branchobj:") or ":" in oid:
            continue
        try:
            obj = ps.registry.get(oid)
        except Exception:
            continue
        if getattr(obj, "created_seq", None) is not None and obj.created_seq > cand.setup.entry_seq:
            continue  # never draw a future-created structure pre-trigger
        lo = getattr(obj, "full_lo", getattr(obj, "lo", None))
        hi = getattr(obj, "full_hi", getattr(obj, "hi", None))
        if lo is None or hi is None or hi <= lo:
            continue
        _zone(ax, lo, hi, x0, trig_x, color, alpha=0.12, label=label)


def render_candidate_chart(bars, cand, ps, path, chart_id):
    """A materialized candidate (eligible or rejected). Shows entry/stop/
    natural+executed target, considered-target ledger summary, graph path,
    ids, and (if evaluated) the outcome in a visually separated post-trigger
    region."""
    s = cand.setup
    trig = s.entry_seq
    post_end = s.outcome_seq if s.outcome_seq else s.expiry_seq
    i0, i1 = _window(bars, trig, 30, max(30, post_end - trig + 15))
    fig, ax = plt.subplots(figsize=(11, 5.5))
    _candles(ax, bars, i0, i1)

    _overlay_stop_target_zones(ax, cand, ps, trig, i0, i1)

    ax.axhline(s.entry_price, color="#1e88e5", lw=1.1,
              label=f"entry {s.entry_price:.2f}")
    ax.axhline(s.structural_stop, color="#ef5350", lw=1.1,
              label=f"stop {s.structural_stop:.2f} ({cand.stop_anchor_type})")
    if s.eligible:
        ax.axhline(s.executed_target, color="#26a69a", lw=1.3,
                  label=f"executed target {s.executed_target:.2f} "
                        f"({s.executed_rr:.2f}R, {cand.target_anchor_type})")
        if abs(s.structural_target - s.executed_target) > 1e-6:
            ax.axhline(s.structural_target, color="#26a69a", lw=0.8, ls="--",
                      label=f"natural target {s.structural_target:.2f} "
                            f"({s.natural_rr:.2f}R)")
    else:
        ax.axhline(s.structural_target, color="#fb8c00", lw=1.0, ls="--",
                  label=f"natural target {s.structural_target:.2f} "
                        f"({s.natural_rr:.2f}R) -- REJECTED: {s.rejection_reason}")

    ax.axvline(trig, color="#212121", lw=1.2, ls="-")
    ax.text(trig, ax.get_ylim()[1], " TRIGGER", fontsize=7, va="top")
    marker = "^" if s.direction == "long" else "v"
    ax.scatter([trig], [s.entry_price], marker=marker, s=90, color="#1e88e5", zorder=5)

    if s.outcome not in ("UNEVALUATED", "OPEN") and post_end > trig:
        ax.axvspan(trig, i1 - 1, color="#9e9e9e", alpha=0.10, zorder=0)
        ax.text((trig + i1) / 2, ax.get_ylim()[0], POST_LABEL, fontsize=7,
                ha="center", va="bottom", color="#616161")
        if s.outcome_seq:
            ax.axvline(s.outcome_seq, color="#9c27b0", lw=0.8, ls=":",
                      label=f"outcome@{s.outcome_seq}: {s.outcome}")

    title = (f"{chart_id}  {cand.candidate_id}  branch={cand.source_branch_id}  "
            f"episode={cand.source_episode_id}\n{cand.exact_graph}")
    ax.set_title(title, fontsize=8)
    ax.set_ylabel("NQ points")
    ax.legend(fontsize=6, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def render_branch_chart(bars, branch, log, path, chart_id):
    """An unresolved/invalidated branch that correctly never emitted a
    trigger. Shows the causal path so far and why no trigger was permitted."""
    if not branch.ordered_event_ids:
        return False
    last_ev = log.get(branch.ordered_event_ids[-1])
    # ev.timestamp_et is already the exact str(bar.ts_et) the event was
    # stamped with (see events/adapter.py); index bars the same way the
    # materializer does (materializer.Materializer._seq), never reparsing.
    seq_map = {str(b.ts_et): i for i, b in enumerate(bars)}
    center = seq_map.get(last_ev.timestamp_et)
    if center is None:
        return False
    i0, i1 = _window(bars, center, 30, 20)
    fig, ax = plt.subplots(figsize=(10, 5))
    _candles(ax, bars, i0, i1)
    ax.axvline(center, color="#616161", lw=1.0, ls=":")
    title = (f"{chart_id}  branch={branch.branch_id}  episode={branch.episode_id}\n"
            f"{' -> '.join(branch.exact_graph_so_far)}\n"
            f"terminal_status={branch.terminal_status}  "
            f"terminal_reason={branch.terminal_reason}")
    ax.set_title(title, fontsize=8)
    ax.set_ylabel("NQ points")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return True


def render_primitive_object_chart(bars, obj, path, chart_id, label):
    center = obj.created_seq
    i0, i1 = _window(bars, center, 20, 40)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _candles(ax, bars, i0, i1)
    lo = getattr(obj, "full_lo", getattr(obj, "lo", None))
    hi = getattr(obj, "full_hi", getattr(obj, "hi", None))
    if lo is not None and hi is not None and hi > lo:
        ax.add_patch(Rectangle((center - 0.5, lo), (i1 - 1) - center + 0.5,
                               hi - lo, facecolor="#42a5f5", alpha=0.20,
                               edgecolor="#1e88e5", zorder=0))
    ax.axvline(center, color="#616161", lw=0.8, ls=":")
    ax.set_title(f"{chart_id}  {label}  {getattr(obj, 'id', '')}", fontsize=9)
    ax.set_ylabel("NQ points")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def render_vwap_interaction_chart(bars, vwap_session, event, path, chart_id):
    """A single VWAP-center or VWAP-band interaction event (no standalone
    zone object exists for these; the session's vwap/band values at the
    interaction bar are drawn as horizontal reference lines)."""
    center = event.seq
    i0, i1 = _window(bars, center, 25, 30)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    _candles(ax, bars, i0, i1)
    val = vwap_session.value_at(center)
    if val:
        ax.axhline(val["vwap"], color="#1e88e5", lw=1.0, ls="--",
                  label=f"vwap {val['vwap']:.2f}")
        for name, price in val["bands"].items():
            ax.axhline(price, color="#8e24aa", lw=0.6, ls=":", alpha=0.6)
    ax.axvline(center, color="#616161", lw=0.8, ls=":")
    ax.set_title(f"{chart_id}  {vwap_session.id}  {event.kind}  note={event.note}",
                fontsize=9)
    ax.set_ylabel("NQ points")
    ax.legend(fontsize=6, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)

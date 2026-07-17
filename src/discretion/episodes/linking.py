"""Causal edge rules for joining an event to an active episode.

Every rule is explicit and the *reason* a link is permitted (or the failing rule
id) is returned so it can be stored on the episode. No prose, no lookahead: only
availability-ordered, price-connected, direction-consistent structural links.
"""

from __future__ import annotations

# Constants come from docs/PREREGISTRATION.md (frozen).
LINK_PROXIMITY_ATR = 1.5
LINK_MAX_GAP_BARS = 120

# Event states that represent an explicit inversion/failure transition and are
# therefore allowed to join even when their direction opposes the branch.
INVERSION_STATES = {"FAILURE", "REINVERSION", "INVALIDATION", "SWEEP", "RECLAIM"}

# Only meaningful transitions may join an episode. Repetitive/registration states
# (REVISIT, EXACT_TOUCH, FORMED-of-unrelated, EXPIRY) are excluded so an episode
# tracks one interaction rather than absorbing every nearby label.
LINKABLE_STATES = {
    "FIRST_TOUCH", "FIRST_FILL", "MIDPOINT", "FULL_FILL", "FAILURE",
    "CONFIRMED", "INVALIDATION", "REINVERSION", "REJECTION", "SWEEP", "BREAK",
    "RECLAIM", "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW", "CONTINUATION",
    "FAILED_CONTINUATION", "COMPRESSION", "EXPANSION", "FORMED",
}


def link_reason(episode, ev, ev_seq, atr_at_ev) -> tuple[bool, str]:
    """Return (ok, reason). reason is the passing edge type or 'reject:ruleN'."""
    # Only meaningful transitions may join (displacement uses FORMED as its leg).
    if ev.state_after not in LINKABLE_STATES:
        return False, "reject:non_transition"
    if ev.state_after == "FORMED" and ev.event_type != "displacement":
        # a bare FVG/RB/level FORMED does not link into another episode; it may
        # only start its own episode (or link once it produces a transition).
        if ev.object_id not in episode.objects:
            return False, "reject:foreign_formation"
    # Rule 1: availability strictly after the origin became available.
    if ev_seq <= episode.origin_seq:
        return False, "reject:rule1_not_after_origin"
    # Rule 3: before episode expiry.
    if ev_seq >= episode.episode_expiry:
        return False, "reject:rule3_after_expiry"
    # Rule 4: parent structure not already invalidated / resolved.
    if episode.resolution is not None:
        return False, "reject:rule4_parent_resolved"
    # gap bound (part of controlling episode reach)
    if ev_seq - episode.last_seq > LINK_MAX_GAP_BARS:
        return False, "reject:rule3_gap_exceeded"

    # Rule 2: same object / child object / causal price response.
    same_object = ev.object_id in episode.objects
    child_object = ev.parent_object_id and ev.parent_object_id in episode.objects
    price_connected = False
    if atr_at_ev:
        price_connected = abs(ev.reference_price - episode.active_price) <= \
            LINK_PROXIMITY_ATR * atr_at_ev

    if not (same_object or child_object or price_connected):
        return False, "reject:rule2_unrelated"

    # Rule 5: direction consistent OR explicit inversion/failure transition.
    dir_ok = (ev.direction == 0 or episode.directional_context == 0
              or ev.direction == episode.directional_context)
    inversion = ev.state_after in INVERSION_STATES
    if not (dir_ok or inversion):
        return False, "reject:rule5_direction"

    # Rule 6: structural connection (direct reference OR price connection).
    if not (same_object or child_object or price_connected):
        return False, "reject:rule6_not_connected"

    if same_object:
        return True, "same_object"
    if child_object:
        return True, f"child_object:{ev.parent_object_id}"
    kind = "inversion" if inversion else "directional"
    return True, f"price_response:{kind}"

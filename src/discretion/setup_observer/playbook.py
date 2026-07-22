"""Recent-validity playbook: freeze successful observation-week fingerprints
into authorized playbook items, then match application-week episodes against
them under three explicitly separate modes (EXACT / REDUCED_FAMILY /
SIMILARITY_DIAGNOSTIC).

Mechanism demonstration only (two-week proof). No aggregate PF; no threshold
tuning; application-week outcomes never touch the playbook or the matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Categorical fields that must all match for EXACT.
EXACT_FIELDS = [
    "lane", "direction", "context_tf", "trigger_tf", "confirmation_tf", "interaction_tf",
    "session", "day_of_week", "context_family", "displacement_branch", "confirm_reason",
    "rb_activation_class", "interaction_to_confirmation_delay", "confluence",
    "target_family", "target_tf",
    "fvg_width_atr_bin", "rb_wick_body_bin", "natural_rr_bin", "ifvg_inversion_speed",
]
# Reduced-family subset.
REDUCED_FIELDS = [
    "lane", "direction", "context_tf", "trigger_tf", "session",
    "displacement_branch", "rb_activation_class", "target_family",
]
# Continuous features for the similarity diagnostic.
SIM_FIELDS = ["context_tf", "trigger_tf", "interaction_to_confirmation_delay"]


@dataclass
class PlaybookItem:
    item_id: str
    fingerprint: dict
    source_episode_ids: list
    source_outcomes: list        # [{episode_id, exit_type, r_multiple, points}]
    rb_activation_requirement: str   # ACTIVATED / NOT_ACTIVATED / EITHER
    displacement_branch: str
    interaction_to_confirmation_limit: int
    target_family: object
    target_tf: object
    validity_start_et: object
    validity_expiry_et: object
    reduced_key: tuple = field(default_factory=tuple)


def _reduced_key(fp):
    return tuple(fp.get(k) for k in REDUCED_FIELDS)


def build_playbook(obs_episodes, obs_outcomes, validity_start_et, validity_expiry_et):
    """Authorized playbook = fingerprints of executable observation episodes
    whose outcome hit TARGET (successful). Deduplicated by exact fingerprint."""
    out_by_ep = {o.episode_id: o for o in obs_outcomes}
    successful = [e for e in obs_episodes
                  if e.executable and out_by_ep.get(e.episode_id) is not None
                  and out_by_ep[e.episode_id].success]

    grouped = {}
    for e in successful:
        key = tuple(e.fingerprint.get(f) for f in EXACT_FIELDS)
        grouped.setdefault(key, []).append(e)

    items = []
    for n, (key, eps) in enumerate(sorted(grouped.items(), key=lambda kv: str(kv[0])), start=1):
        fp = eps[0].fingerprint
        acts = {e.fingerprint["rb_activation_class"] for e in eps}
        req = acts.pop() if len(acts) == 1 else "EITHER"
        items.append(PlaybookItem(
            item_id=f"PB-{n:04d}", fingerprint=fp,
            source_episode_ids=[e.episode_id for e in eps],
            source_outcomes=[{"episode_id": e.episode_id, "exit_type": out_by_ep[e.episode_id].exit_type,
                              "r_multiple": out_by_ep[e.episode_id].r_multiple,
                              "points": out_by_ep[e.episode_id].points} for e in eps],
            rb_activation_requirement=req,
            displacement_branch=fp["displacement_branch"],
            interaction_to_confirmation_limit=fp["interaction_to_confirmation_delay"],
            target_family=fp["target_family"], target_tf=fp["target_tf"],
            validity_start_et=validity_start_et, validity_expiry_et=validity_expiry_et,
            reduced_key=_reduced_key(fp),
        ))
    return items


def match_modes(ep, playbook):
    """Return dict of matches per mode for an application-week episode.
    EXACT / REDUCED_FAMILY are categorical; SIMILARITY_DIAGNOSTIC is the
    nearest playbook item by L1 distance over SIM_FIELDS (diagnostic only)."""
    fp = ep.fingerprint
    exact = [pb.item_id for pb in playbook
             if all(fp.get(f) == pb.fingerprint.get(f) for f in EXACT_FIELDS)]
    reduced = [pb.item_id for pb in playbook if _reduced_key(fp) == pb.reduced_key]
    sim = None
    if playbook:
        def dist(pb):
            d = 0.0
            for f in SIM_FIELDS:
                av, bv = fp.get(f), pb.fingerprint.get(f)
                if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                    d += abs(av - bv)
                elif av != bv:
                    d += 1.0
            return d
        nn = min(playbook, key=dist)
        sim = {"nearest_item_id": nn.item_id, "l1_distance": round(dist(nn), 4)}
    return {"EXACT": exact, "REDUCED_FAMILY": reduced, "SIMILARITY_DIAGNOSTIC": sim}

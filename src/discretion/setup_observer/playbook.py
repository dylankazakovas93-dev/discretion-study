"""Recent-validity playbook (spec Part 8). Freeze successful observation-week
entry-variant fingerprints into authorized items, then match application-week
variants under three explicitly separate modes.

Crucially the fingerprint carries BOTH the entry variant and the reaction
state, so a successful strong-displacement setup can never authorize a tap-entry
variant, a successful tap entry can never authorize waiting for displacement,
and a small-rejection setup stays distinct from a strong rejection. Application
data never touches playbook construction or matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# EXACT = every categorical + binned fingerprint field.
EXACT_FIELDS = [
    "lane", "entry_variant", "reaction_state", "direction",
    "context_tf", "interaction_tf", "reaction_tf", "confirmation_tf", "trigger_tf",
    "is_multi_timeframe", "session", "day_of_week", "context_family", "confluence",
    "rb_activation_class", "interaction_to_trigger_delay_bin",
    "target_family", "target_tf", "natural_rr_bin",
]
# REDUCED_FAMILY = provisional family analogue (spec-mandated minimum set).
REDUCED_FIELDS = [
    "lane", "entry_variant", "direction", "context_family", "context_tf", "trigger_tf",
    "session", "reaction_state", "interaction_to_trigger_delay_bin",
    "rb_activation_class", "target_family", "target_tf", "natural_rr_bin",
]
# SIMILARITY_DIAGNOSTIC continuous features (diagnostic only, never actionable).
SIM_FIELDS = ["context_tf", "trigger_tf", "reaction_state"]

# PATTERN = the setup identity WITHOUT the target/RR executability fields. Used
# only to surface non-actionable "near" matches into the rejected ledger; it is
# never an authorization.
PATTERN_FIELDS = [f for f in REDUCED_FIELDS
                  if f not in ("target_family", "target_tf", "natural_rr_bin")]


def pattern_key(fp):
    return tuple(fp.get(k) for k in PATTERN_FIELDS)


@dataclass
class PlaybookItem:
    item_id: str
    fingerprint: dict
    entry_variant: str
    reaction_state: str
    source_variant_ids: list
    source_episode_ids: list
    source_outcomes: list
    rb_activation_requirement: str
    target_family: object
    target_tf: object
    single_observation: bool
    validity_start_et: object
    validity_expiry_et: object
    reduced_key: tuple = field(default_factory=tuple)
    pattern_k: tuple = field(default_factory=tuple)


def _reduced_key(fp):
    return tuple(fp.get(k) for k in REDUCED_FIELDS)


def build_playbook(obs_variants, obs_outcomes, validity_start_et, validity_expiry_et):
    """Authorized playbook = fingerprints of executable observation-week variants
    whose outcome hit TARGET. Deduplicated by exact fingerprint."""
    out_by_v = {o.variant_id: o for o in obs_outcomes}
    successful = [v for v in obs_variants
                  if v.executable and out_by_v.get(v.variant_id) is not None
                  and out_by_v[v.variant_id].success]

    grouped = {}
    for v in successful:
        key = tuple(v.fingerprint.get(f) for f in EXACT_FIELDS)
        grouped.setdefault(key, []).append(v)

    items = []
    for n, (key, vs) in enumerate(sorted(grouped.items(), key=lambda kv: str(kv[0])), start=1):
        fp = vs[0].fingerprint
        acts = {v.fingerprint["rb_activation_class"] for v in vs}
        req = acts.pop() if len(acts) == 1 else "EITHER"
        items.append(PlaybookItem(
            item_id=f"PB-{n:04d}", fingerprint=fp,
            entry_variant=fp["entry_variant"], reaction_state=fp["reaction_state"],
            source_variant_ids=[v.variant_id for v in vs],
            source_episode_ids=sorted({v.episode_id for v in vs}),
            source_outcomes=[{"variant_id": v.variant_id, "exit_type": out_by_v[v.variant_id].exit_type,
                              "r_multiple": out_by_v[v.variant_id].r_multiple,
                              "points": out_by_v[v.variant_id].points} for v in vs],
            rb_activation_requirement=req, target_family=fp["target_family"],
            target_tf=fp["target_tf"], single_observation=(len(vs) == 1),
            validity_start_et=validity_start_et, validity_expiry_et=validity_expiry_et,
            reduced_key=_reduced_key(fp), pattern_k=pattern_key(fp)))
    return items


def match_modes(v, playbook):
    """Return matches per mode for an application-week variant. EXACT and
    REDUCED_FAMILY are categorical (both preserve entry_variant + reaction_state
    so cross-authorization is impossible); SIMILARITY_DIAGNOSTIC is the nearest
    item by L1 distance and is diagnostic only -- never actionable."""
    fp = v.fingerprint
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

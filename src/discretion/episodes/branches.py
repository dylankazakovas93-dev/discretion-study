"""Branching graph: turn episodes into branches and coherent setup candidates.

A ``Branch`` is one interpretation of an episode (CONTINUATION / FADE /
UNRESOLVED / FAILURE / EXPIRY) with a permanent id and an exact causal-node
signature. A coherent candidate's frozen entry/stop/target/RR come from the
canonical setup builders in ``src/discretion/setups`` (the audited, reused
completion logic) — this layer supplies the causal provenance (episode + branch
+ exact path + edge reasons) and never re-derives a stop or target.

Graph control: identical branch signatures are deduplicated; distinct entry modes
stay separate; depth is capped (MAX_BRANCH_DEPTH); branches terminated by depth /
expiry / duplication are recorded, never dropped for poor outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..setups.constructor import build_setups
from ..setups.model import evaluate_outcome
from .state_machine import EpisodeEngine

MAX_BRANCH_DEPTH = 8

# families whose transitions form the causal "spine" of an exact graph
_SPINE_FAMILIES = {"fvg", "ifvg", "rejection_block", "displacement", "structure"}
_SPINE_INVERSIONS = {"SWEEP", "RECLAIM", "FAILURE", "REINVERSION", "BREAK"}


@dataclass
class Branch:
    branch_id: str
    episode_id: str
    state: str                  # CONTINUATION | FADE | UNRESOLVED | FAILURE | EXPIRY
    direction: str
    node_event_ids: tuple
    node_subtypes: tuple
    exact_signature: str
    trigger_event_id: str | None
    depth: int
    terminated_reason: str | None = None


@dataclass
class SetupCandidate:
    setup: object               # discretion.setups.model.Setup (frozen entry/RR)
    episode_id: str
    branch_id: str
    branch_state: str
    exact_graph: str
    edge_reasons: list
    reduced_graph: str = ""     # filled in Phase 5
    features: dict = field(default_factory=dict)   # Phase 5
    evidence: dict = field(default_factory=dict)   # Phase 6
    qualification: str = "UNSCORED"                # Phase 6


def _episode_nodes(ep, eng, log):
    """Ordered (seq, subtype, event_id) for an episode's events."""
    out = []
    for eid in ep.primitive_event_ids:
        ev = log.get(eid)
        out.append((eng.ts_to_seq[ev.timestamp_et], ev.event_subtype, eid, ev))
    out.sort(key=lambda t: t[0])
    return out


def _spine(nodes, origin_eid, trigger_seq):
    """Curated causal spine up to the trigger: origin + spine-family transitions
    + explicit inversions, capped at MAX_BRANCH_DEPTH (keeps origin and tail)."""
    spine = []
    for seq, sub, eid, ev in nodes:
        if seq > trigger_seq:
            break
        keep = (eid == origin_eid
                or ev.event_type in _SPINE_FAMILIES
                or ev.state_after in _SPINE_INVERSIONS)
        if keep:
            spine.append((seq, sub, eid))
    truncated = False
    if len(spine) > MAX_BRANCH_DEPTH:
        spine = [spine[0]] + spine[-(MAX_BRANCH_DEPTH - 1):]
        truncated = True
    return spine, truncated


def _index_episodes(episodes):
    idx = {}
    for ep in episodes:
        for obj in ep.objects:
            idx.setdefault(obj, []).append(ep)
    return idx


def _match_episode(setup, idx):
    """Most recent episode containing the setup's origin object whose span covers
    the entry. Prefer an episode originated by that exact object."""
    cands = [ep for ep in idx.get(setup.origin_id, [])
             if ep.origin_seq <= setup.entry_seq <= ep.episode_expiry
             and ep.segment_id == setup.segment_id]
    if not cands:
        return None
    own = [ep for ep in cands if ep.origin_object_id == setup.origin_id]
    pool = own or cands
    return max(pool, key=lambda ep: ep.origin_seq)


def build_branches_and_candidates(ps):
    """Return (episodes, log, engine, branches, candidates, ledger)."""
    from ..events.adapter import build_event_log
    log = build_event_log(ps)
    eng = EpisodeEngine(ps)
    episodes = eng.run(log)
    idx = _index_episodes(episodes)

    ledger = build_setups(ps)
    branches: list[Branch] = []
    candidates: list[SetupCandidate] = []
    seen_signatures: dict[tuple, str] = {}
    used_episode_ids: set[str] = set()
    n_branch = 0
    n_fallback = 0

    for s in ledger.eligible:
        ep = _match_episode(s, idx)
        if ep is None:
            n_fallback += 1
            episode_id = f"EP-SYNTH-{s.id}"
            exact = f"{s.graph}"
            nodes_e = ()
            nodes_s = tuple(exact.split(" -> "))
            edge_reasons = [("synthetic_origin", s.origin_id)]
            trigger_eid = None
            depth = len(nodes_s)
        else:
            episode_id = ep.episode_id
            used_episode_ids.add(episode_id)
            nodes = _episode_nodes(ep, eng, log)
            spine, truncated = _spine(nodes, ep.origin_event_id, s.entry_seq)
            nodes_e = tuple(n[2] for n in spine)
            nodes_s = tuple(n[1] for n in spine)
            # append trigger token from the setup's entry mode
            trigger_tok = f"{s.entry_mode.upper()}_{('LONG' if s.direction=='long' else 'SHORT')}_TRIGGER"
            exact = " -> ".join(list(nodes_s) + [trigger_tok])
            edge_reasons = list(ep.edges)
            trigger_eid = spine[-1][2] if spine else ep.origin_event_id
            depth = len(nodes_s) + 1

        state = "FADE" if s.continuation_or_fade == "fade" else "CONTINUATION"
        sig = (episode_id, exact, s.direction, s.entry_mode)
        if sig in seen_signatures:
            branch_id = seen_signatures[sig]  # merged into the existing branch
        else:
            n_branch += 1
            branch_id = f"BR-{n_branch:06d}"
            seen_signatures[sig] = branch_id
            branches.append(Branch(
                branch_id=branch_id, episode_id=episode_id, state=state,
                direction=s.direction, node_event_ids=nodes_e, node_subtypes=nodes_s,
                exact_signature=exact, trigger_event_id=trigger_eid, depth=depth,
                terminated_reason=None,
            ))
        candidates.append(SetupCandidate(
            setup=s, episode_id=episode_id, branch_id=branch_id,
            branch_state=state, exact_graph=exact, edge_reasons=edge_reasons,
        ))

    # UNRESOLVED branches: episodes that produced no coherent candidate but carry
    # a weak-response transition (bad displacement / compression) — recorded, not
    # setups. Deterministic, capped path.
    for ep in episodes:
        if ep.episode_id in used_episode_ids:
            continue
        nodes = _episode_nodes(ep, eng, log)
        subs = [n[1] for n in nodes]
        if any("BAD_" in x or x == "COMPRESSION" or "FAILED_CONTINUATION" in x
               for x in subs):
            spine, truncated = _spine(nodes, ep.origin_event_id, nodes[-1][0])
            n_branch += 1
            branches.append(Branch(
                branch_id=f"BR-{n_branch:06d}", episode_id=ep.episode_id,
                state="UNRESOLVED", direction="none",
                node_event_ids=tuple(n[2] for n in spine),
                node_subtypes=tuple(n[1] for n in spine),
                exact_signature=" -> ".join(n[1] for n in spine),
                trigger_event_id=None, depth=len(spine),
                terminated_reason="depth" if truncated else "unresolved",
            ))

    stats = {
        "episodes": len(episodes),
        "branches": len(branches),
        "branches_continuation": sum(b.state == "CONTINUATION" for b in branches),
        "branches_fade": sum(b.state == "FADE" for b in branches),
        "branches_unresolved": sum(b.state == "UNRESOLVED" for b in branches),
        "branches_merged": len(candidates) - sum(
            1 for b in branches if b.state in ("CONTINUATION", "FADE")),
        "coherent_candidates": len(candidates),
        "candidates_synthetic_episode": n_fallback,
        "raw_setup_candidates": ledger.raw_count,
        "rejected_setups": len(ledger.rejected),
    }
    return {
        "episodes": episodes, "log": log, "engine": eng, "branches": branches,
        "candidates": candidates, "ledger": ledger, "stats": stats,
    }

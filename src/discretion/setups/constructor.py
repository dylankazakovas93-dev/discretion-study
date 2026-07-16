"""Setup factory + orchestration: run path builders, apply RR policy, dedup.

The factory freezes every setup's prices and expiry and applies the RR policy
immediately, so no downstream step can move a stop or target. It records both
eligible and rejected candidates (nothing is deleted). Deduplication collapses
cosmetic duplicates of one interaction episode while keeping genuinely distinct
entry modes separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..primitives.engine import PrimitiveSet
from .model import Setup, apply_rr_policy, evaluate_outcome
from ..data.bars import NQ_TICK

EXPIRY_BARS = 120
EPISODE_BARS = 3


class SetupFactory:
    def __init__(self, ps: PrimitiveSet):
        self.ps = ps
        self.bars = ps.bars
        self.levels = ps.all_levels
        self._n = 0
        # last bar index of each segment (bars are contiguous per segment)
        self._seg_last_map: dict[int, int] = {}
        for i, b in enumerate(self.bars):
            self._seg_last_map[b.segment_id] = i

    def _seg_last(self, segment_id: int) -> int:
        return self._seg_last_map[segment_id]

    def make(self, *, direction, path_family, graph, entry_mode, origin_id,
             transition_ids, primitive_ids, context_conditions, entry_seq,
             entry_price, stop, target, cont_or_fade, has_fvg=False,
             has_ifvg=False, has_rb=False, has_sweep=False):
        if stop is None or target is None:
            return None
        if len(context_conditions) > 3:
            raise ValueError(f"too many context conditions: {context_conditions}")
        if entry_seq >= len(self.bars):
            return None
        seg = self.bars[entry_seq].segment_id
        self._n += 1
        expiry_seq = min(entry_seq + EXPIRY_BARS, self._seg_last(seg))
        s = Setup(
            id=f"SETUP-{self._n:06d}",
            direction=direction,
            path_family=path_family,
            graph=graph,
            entry_mode=entry_mode,
            origin_id=origin_id,
            transition_ids=list(transition_ids),
            primitive_ids=list(primitive_ids),
            context_conditions=list(context_conditions),
            entry_seq=entry_seq,
            entry_ts=self.bars[entry_seq].ts_utc,
            entry_price=float(entry_price),
            structural_stop=float(stop),
            structural_target=float(target),
            expiry_seq=expiry_seq,
            expiry_rule=f"{EXPIRY_BARS}_bars_or_segment_end",
            segment_id=seg,
            has_fvg=has_fvg, has_ifvg=has_ifvg, has_rb=has_rb, has_sweep=has_sweep,
            continuation_or_fade=cont_or_fade,
        )
        apply_rr_policy(s)
        s.episode_key = (
            origin_id, direction, entry_mode, entry_seq // EPISODE_BARS,
            round(s.structural_stop / NQ_TICK), round(s.structural_target / NQ_TICK),
        )
        return s


@dataclass
class SetupLedger:
    all_candidates: list = field(default_factory=list)   # every raw candidate
    eligible: list = field(default_factory=list)         # eligible, deduplicated
    rejected: list = field(default_factory=list)         # rejected by RR/other

    @property
    def raw_count(self) -> int:
        return len(self.all_candidates)


def deduplicate(candidates: list[Setup]) -> tuple[list[Setup], int]:
    """Collapse cosmetic duplicates by episode_key; keep first chronologically.

    Distinct entry modes have distinct keys (entry_mode is part of the key), so
    they are never merged. Returns (deduped, n_removed).
    """
    seen: dict = {}
    order = sorted(candidates, key=lambda s: (s.entry_seq, s.id))
    removed = 0
    for s in order:
        if s.episode_key in seen:
            removed += 1
            continue
        seen[s.episode_key] = s
    return list(seen.values()), removed


def build_setups(ps: PrimitiveSet) -> SetupLedger:
    from . import builders  # local import to avoid cycles
    factory = SetupFactory(ps)
    ledger = SetupLedger()

    raw: list[Setup] = []
    for builder in builders.ALL_BUILDERS:
        for s in builder(factory):
            if s is not None:
                raw.append(s)

    ledger.all_candidates = raw
    eligible_raw = [s for s in raw if s.eligible]
    ledger.rejected = [s for s in raw if s.rejected]

    deduped, _ = deduplicate(eligible_raw)
    # evaluate outcomes (diagnostic only) on the deduplicated eligible set
    for s in deduped:
        evaluate_outcome(s, ps.bars)
    ledger.eligible = sorted(deduped, key=lambda s: s.entry_seq)
    return ledger

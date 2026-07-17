"""Run every primitive detector over a bar list in one place.

Returns a :class:`PrimitiveSet` bundling all detected primitives plus the ATR
series, which the setup constructor consumes. Detectors are independent and all
strictly causal, so ordering among them does not matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..data.atr import wilder_atr
from ..data.aggregation import aggregate_all
from ..data.bars import Bar
from .base import IdRegistry
from .displacement import detect_displacements, Displacement
from .fvg import detect_fvgs, FVG
from .htf_fvg import detect_htf_fvgs, HTFFVG, HTFIFVG
from .ifvg import detect_ifvgs, IFVG
from .wick_liquidity import detect_wick_liquidity, ProminentWickLiquidity
from .levels import (
    build_time_anchors, build_session_levels, track_level_interactions, Level,
)
from .rejection_block import detect_rejection_blocks, RejectionBlock
from .structure import (
    detect_swings, detect_equal_levels, detect_compression_expansion, StructureZone,
)
from .vwap import build_vwap_sessions, VWAPSession


@dataclass
class PrimitiveSet:
    bars: list[Bar]
    atr: list
    registry: IdRegistry
    fvgs: list[FVG] = field(default_factory=list)
    ifvgs: list[IFVG] = field(default_factory=list)
    rbs: list[RejectionBlock] = field(default_factory=list)
    displacements: list[Displacement] = field(default_factory=list)
    anchors: list[Level] = field(default_factory=list)
    session_levels: list[Level] = field(default_factory=list)
    swings: list[Level] = field(default_factory=list)
    equal_levels: list[Level] = field(default_factory=list)
    vwaps: list[VWAPSession] = field(default_factory=list)
    structures: list[StructureZone] = field(default_factory=list)
    # multi-timeframe target inventory (5/15/30/60m)
    htf: dict = field(default_factory=dict)
    wicks: list[ProminentWickLiquidity] = field(default_factory=list)
    htf_fvgs: list[HTFFVG] = field(default_factory=list)
    htf_ifvgs: list[HTFIFVG] = field(default_factory=list)

    @property
    def all_levels(self) -> list[Level]:
        return self.anchors + self.session_levels + self.swings + self.equal_levels

    def counts(self) -> dict:
        return {
            "fvg": len(self.fvgs),
            "ifvg": len(self.ifvgs),
            "rejection_block": len(self.rbs),
            "displacement": len(self.displacements),
            "time_anchor": len(self.anchors),
            "session_level": len(self.session_levels),
            "swing": len(self.swings),
            "equal_level": len(self.equal_levels),
            "vwap_session": len(self.vwaps),
            "structure": len(self.structures),
        }


def build_primitives(bars: list[Bar], atr_period: int = 14) -> PrimitiveSet:
    reg = IdRegistry()
    atr = wilder_atr(bars, period=atr_period)

    fvgs = detect_fvgs(bars, reg)
    ifvgs = detect_ifvgs(bars, fvgs, reg)
    rbs = detect_rejection_blocks(bars, atr, reg)
    disps = detect_displacements(bars, atr, reg)

    anchors = build_time_anchors(bars, reg)
    session_levels = build_session_levels(bars, reg)
    swings = detect_swings(bars, reg)
    equals = detect_equal_levels(swings, reg)
    # Track interactions for every horizontal level in one causal pass each.
    track_level_interactions(anchors, bars)
    track_level_interactions(session_levels, bars)
    track_level_interactions(swings, bars)
    track_level_interactions(equals, bars)

    vwaps = build_vwap_sessions(bars, reg)
    structures = detect_compression_expansion(bars, atr, reg)

    # multi-timeframe target inventory (causal 5/15/30/60m aggregation)
    htf = aggregate_all(bars)
    wicks = detect_wick_liquidity(bars, htf, reg)
    htf_fvgs, htf_ifvgs = detect_htf_fvgs(bars, htf, reg)

    return PrimitiveSet(
        bars=bars, atr=atr, registry=reg,
        fvgs=fvgs, ifvgs=ifvgs, rbs=rbs, displacements=disps,
        anchors=anchors, session_levels=session_levels, swings=swings,
        equal_levels=equals, vwaps=vwaps, structures=structures,
        htf=htf, wicks=wicks, htf_fvgs=htf_fvgs, htf_ifvgs=htf_ifvgs,
    )

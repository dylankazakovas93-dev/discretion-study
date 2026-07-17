"""Frozen, machine-readable transition registry (declarative causal grammar).

A causal path is a ``Hypothesis`` = an ordered list of ``Stage`` transitions
opened by an origin event. The last stage emits a graph-native candidate; earlier
stages ``advance`` the branch. A hypothesis whose emit stage is never reached
remains an UNRESOLVED (recorded) branch. Adding a market path = adding a row here,
not editing procedural code — this expresses a general grammar, not named
strategies.

Each stage requires an explicit structural relationship (proximity alone never
qualifies; enforced by the engine via ``has_structural_edge``). Direction is
resolved against the branch hypothesis direction, the event, or the subtype.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stage:
    kind: str                       # "advance" | "emit"
    event_family: str | None = None
    event_state: object = None      # str | set[str] | None
    subtype_contains: str | None = None
    rels: tuple = ()                # required relationship names (ALL)
    direction: str = "ANY"          # SUPPORT | INVERSION | ANY
    min_delay: int = 0
    max_delay: int = 240
    immediate: bool = False         # matches the origin event itself (delay 0)
    updates_focus: bool = True
    entry_mode: str | None = None       # for emit stages
    trigger_family: str | None = None   # for emit stages


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    family: str                     # origin event family
    cont_or_fade: str               # continuation | fade | unresolved
    dir_from_origin: object         # +1 | -1 | "FROM_EVENT" | "FROM_SUBTYPE"
    stages: tuple


def _emit(entry_mode, trigger_family, **kw):
    return Stage(kind="emit", entry_mode=entry_mode, trigger_family=trigger_family, **kw)


def _adv(**kw):
    return Stage(kind="advance", **kw)


# --------------------------------------------------------------------------
# FVG lifecycle — one branch per entry mode (never merged)
# --------------------------------------------------------------------------
_FVG = [
    Hypothesis("H_fvg_formation_close", "fvg", "continuation", +1,
               (_emit("formation_close", "fvg_formation", immediate=True,
                      rels=("SAME_OBJECT",)),)),
    Hypothesis("H_fvg_next_bar", "fvg", "continuation", +1,
               (_emit("next_bar", "fvg_formation", immediate=True,
                      rels=("SAME_OBJECT",)),)),
    Hypothesis("H_fvg_first_touch", "fvg", "continuation", +1,
               (_emit("first_touch", "fvg_fill", event_family="fvg",
                      event_state="FIRST_TOUCH", rels=("SAME_OBJECT", "TOUCHES_ZONE")),)),
    Hypothesis("H_fvg_first_fill", "fvg", "continuation", +1,
               (_emit("first_fill", "fvg_fill", event_family="fvg",
                      event_state="FIRST_FILL", rels=("SAME_OBJECT", "ENTERS_ZONE")),)),
    Hypothesis("H_fvg_midpoint", "fvg", "continuation", +1,
               (_emit("midpoint", "fvg_fill", event_family="fvg",
                      event_state="MIDPOINT", rels=("SAME_OBJECT", "ENTERS_ZONE")),)),
    Hypothesis("H_fvg_full_fill", "fvg", "continuation", +1,
               (_emit("full_fill", "fvg_fill", event_family="fvg",
                      event_state="FULL_FILL", rels=("SAME_OBJECT", "FILLS_ZONE")),)),
]

# --------------------------------------------------------------------------
# iFVG — immediate + retest (fade of the failed FVG); never merged
# --------------------------------------------------------------------------
_IFVG = [
    Hypothesis("H_ifvg_immediate", "ifvg", "fade", +1,
               (_emit("formation_close", "ifvg_activation", immediate=True,
                      rels=("SAME_OBJECT",)),)),
    Hypothesis("H_ifvg_next_bar", "ifvg", "fade", +1,
               (_emit("next_bar", "ifvg_activation", immediate=True,
                      rels=("SAME_OBJECT",)),)),
    Hypothesis("H_ifvg_retest", "ifvg", "fade", +1,
               (_emit("retest", "ifvg_retest", event_family="ifvg",
                      event_state="FIRST_TOUCH", rels=("SAME_OBJECT", "TOUCHES_ZONE")),)),
]

# --------------------------------------------------------------------------
# Rejection block — continuation, FVG-fill continuation, and unresolved->fade
# --------------------------------------------------------------------------
_RB = [
    Hypothesis("H_rb_reaction_continuation", "rejection_block", "continuation", +1,
               (_adv(event_family="rejection_block", event_state="FIRST_TOUCH",
                     rels=("SAME_OBJECT", "TOUCHES_ZONE")),
                _emit("formation_close", "rb_reaction", event_family="displacement",
                      event_state="FORMED", subtype_contains="GOOD",
                      rels=("DISPLACEMENT_ORIGINATES_AT_OBJECT",), direction="SUPPORT"))),
    Hypothesis("H_rb_fvg_fill_continuation", "rejection_block", "continuation", +1,
               (_adv(event_family="rejection_block", event_state="FIRST_TOUCH",
                     rels=("SAME_OBJECT",)),
                _adv(event_family="displacement", event_state="FORMED",
                     subtype_contains="GOOD",
                     rels=("DISPLACEMENT_ORIGINATES_AT_OBJECT",), direction="SUPPORT"),
                _adv(event_family="fvg", event_state="FORMED",
                     rels=("FVG_CREATED_BY_DISPLACEMENT",), direction="SUPPORT"),
                _emit("first_touch", "rb_fvg_fill", event_family="fvg",
                      event_state="FIRST_TOUCH", rels=("SAME_OBJECT", "TOUCHES_ZONE")))),
    Hypothesis("H_rb_unresolved_fade", "rejection_block", "fade", -1,
               (_adv(event_family="rejection_block", event_state="FIRST_TOUCH",
                     rels=("SAME_OBJECT",)),
                _adv(event_family="displacement", event_state="FORMED",
                     subtype_contains="BAD",
                     rels=("DISPLACEMENT_ORIGINATES_AT_OBJECT",)),
                _adv(event_family="structure", event_state="COMPRESSION",
                     rels=("COMPRESSION_FORMS_AROUND_OBJECT",)),
                _emit("formation_close", "rb_failure_fade",
                      event_state={"FAILED_CONTINUATION", "BREAK", "FAILURE",
                                   "REINVERSION", "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW"},
                      rels=(), direction="INVERSION"))),
]

# --------------------------------------------------------------------------
# Liquidity / historical levels
# --------------------------------------------------------------------------
_LEVELS = []
for _fam in ("liquidity", "hist_level", "time_anchor"):
    _LEVELS += [
        Hypothesis(f"H_{_fam}_sweep_reject_fade", _fam, "fade", -1,
                   (_emit("formation_close", "sweep_fade", immediate=True,
                          rels=("SAME_OBJECT",), direction="INVERSION"),)),
        Hypothesis(f"H_{_fam}_sweep_reclaim_fade", _fam, "fade", -1,
                   (_emit("formation_close", "sweep_reclaim_fade",
                          event_state="RECLAIM", rels=("RECLAIMS_BOUNDARY",),
                          direction="INVERSION"),)),
        Hypothesis(f"H_{_fam}_sweep_accept_continuation", _fam, "continuation", +1,
                   (_emit("formation_close", "sweep_accept_cont",
                          event_state={"ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW"},
                          rels=("ACCEPTS_BEYOND_BOUNDARY",), direction="SUPPORT"),)),
    ]
# non-sweep break -> acceptance -> continuation ; break -> failed -> fade
for _fam in ("hist_level", "liquidity", "time_anchor"):
    _LEVELS += [
        Hypothesis(f"H_{_fam}_break_accept_continuation", _fam, "continuation", +1,
                   (_emit("formation_close", "break_accept_cont",
                          event_state={"ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW"},
                          rels=("ACCEPTS_BEYOND_BOUNDARY",), direction="SUPPORT"),)),
        Hypothesis(f"H_{_fam}_break_failed_fade", _fam, "fade", -1,
                   (_emit("formation_close", "break_failed_fade",
                          event_state="RECLAIM", rels=("RECLAIMS_BOUNDARY",),
                          direction="INVERSION"),)),
    ]

# time-anchor reclaim continuation / rejection fade (no FVG required)
_ANCHOR = [
    Hypothesis("H_anchor_reclaim_continuation", "time_anchor", "continuation", "FROM_EVENT",
               (_emit("formation_close", "anchor_reclaim", immediate=True,
                      rels=("SAME_OBJECT",)),)),
]

# --------------------------------------------------------------------------
# VWAP (band fade, bounce continuation, reclaim continuation, break-accept)
# --------------------------------------------------------------------------
_VWAP = [
    Hypothesis("H_vwap_band_fade", "vwap", "fade", "FROM_SUBTYPE",
               (_emit("formation_close", "vwap_band_fade", immediate=True,
                      subtype_contains="BAND_REJECT", rels=("SAME_OBJECT",)),)),
    Hypothesis("H_vwap_bounce_continuation", "vwap", "continuation", "FROM_SUBTYPE",
               (_emit("first_touch", "vwap_bounce", immediate=True,
                      subtype_contains="BOUNCE", rels=("SAME_OBJECT",)),)),
    Hypothesis("H_vwap_reclaim_continuation", "vwap", "continuation", "FROM_SUBTYPE",
               (_emit("formation_close", "vwap_reclaim", immediate=True,
                      subtype_contains="RECLAIM", rels=("SAME_OBJECT",)),)),
    Hypothesis("H_vwap_break_accept_continuation", "vwap", "continuation", "FROM_SUBTYPE",
               (_emit("formation_close", "vwap_break_accept",
                      subtype_contains="ACCEPTANCE", rels=("SAME_OBJECT",)),)),
]

# --------------------------------------------------------------------------
# Compression / expansion
# --------------------------------------------------------------------------
_STRUCT = [
    Hypothesis("H_compression_expansion", "structure", "continuation", "FROM_EVENT",
               (_emit("next_bar", "compression_expansion",
                      event_family="structure", event_state={"EXPANSION", "BREAK"},
                      rels=("EXPANSION_LEAVES_COMPRESSION",)),)),
    Hypothesis("H_compression_false_expansion_fade", "structure", "fade", "FROM_EVENT",
               (_emit("formation_close", "compression_false_expansion",
                      event_family="structure", event_state="FAILED_CONTINUATION",
                      rels=("FAILED_EXPANSION_RETURNS_TO_REGION",), direction="INVERSION"),)),
]

REGISTRY: list[Hypothesis] = (_FVG + _IFVG + _RB + _LEVELS + _ANCHOR + _VWAP + _STRUCT)

BY_FAMILY: dict[str, list[Hypothesis]] = {}
for _h in REGISTRY:
    BY_FAMILY.setdefault(_h.family, []).append(_h)


def hypotheses_for_family(family: str) -> list[Hypothesis]:
    return BY_FAMILY.get(family, [])


def stage_matches(stage: Stage, ev, satisfied: set, delay: int, branch_dir: int) -> bool:
    """True iff the event satisfies this stage (excluding the structural-edge
    check, which the engine enforces separately via has_structural_edge)."""
    if stage.event_family and ev.event_type != stage.event_family:
        return False
    if stage.event_state is not None:
        states = stage.event_state if isinstance(stage.event_state, set) else {stage.event_state}
        if ev.state_after not in states:
            return False
    if stage.subtype_contains and stage.subtype_contains not in ev.event_subtype:
        return False
    if not (stage.min_delay <= delay <= stage.max_delay):
        return False
    for r in stage.rels:
        if r not in satisfied:
            return False
    if stage.direction == "SUPPORT" and "DIRECTIONALLY_SUPPORTS" not in satisfied:
        return False
    if stage.direction == "INVERSION":
        # an explicit inversion/failure transition, or an opposing strong move
        inversion_state = ev.state_after in (
            "FAILURE", "REINVERSION", "RECLAIM", "SWEEP", "FAILED_CONTINUATION",
            "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW", "BREAK")
        if not (inversion_state or "DIRECTIONALLY_INVALIDATES" in satisfied):
            return False
    return True

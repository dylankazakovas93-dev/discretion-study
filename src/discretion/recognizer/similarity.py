"""Deterministic similarity: hard compatibility + prior-only Gower distance.

Level 1 = identical exact graph. Level 2 = identical reduced graph + hard
compatibility. Level 3 = hard compatibility + Gower distance <= threshold. Gower
numeric ranges are computed from the prior pool only (never the current or a
future candidate).
"""

from __future__ import annotations

NN_MAX_DISTANCE = 0.35
NN_MAX_NEIGHBORS = 50

_IMMEDIATE = {"formation_close", "next_bar"}

# Gower feature sets (a subset of the full feature vector).
NUM_KEYS = ["minutes_from_0930", "dist_to_stop_atr", "natural_rr",
            "origin_age_bars", "zone_width_atr", "displacement_body_atr",
            "path_body_ratio", "favorable_close"]
CAT_KEYS = ["session", "target_family", "level_family", "nearest_vwap_band",
            "entry_mode", "has_fvg", "has_ifvg", "has_rb", "has_sweep",
            "vwap_side"]


def entry_mode_class(mode: str) -> str:
    return "immediate" if mode in _IMMEDIATE else "delayed"


def hard_compatible(fa: dict, fb: dict) -> bool:
    """Incompatible comparisons (continuation vs fade, immediate vs delayed,
    different origin family) are forbidden regardless of numeric closeness."""
    return (fa["continuation_or_fade"] == fb["continuation_or_fade"]
            and entry_mode_class(fa["entry_mode"]) == entry_mode_class(fb["entry_mode"])
            and fa["origin_family"] == fb["origin_family"])


def numeric_ranges(pool_features: list[dict]) -> dict:
    """Prior-only min/max per numeric key (None values ignored)."""
    ranges = {}
    for k in NUM_KEYS:
        vals = [f[k] for f in pool_features if f.get(k) is not None]
        if vals:
            ranges[k] = (min(vals), max(vals))
    return ranges


def gower(fa: dict, fb: dict, ranges: dict) -> float:
    """Mean per-feature distance in [0,1] over comparable features."""
    total = 0.0
    n = 0
    for k in NUM_KEYS:
        a, b = fa.get(k), fb.get(k)
        if a is None or b is None or k not in ranges:
            continue
        lo, hi = ranges[k]
        if hi > lo:
            total += abs(a - b) / (hi - lo)
            n += 1
    for k in CAT_KEYS:
        a, b = fa.get(k), fb.get(k)
        if a is None and b is None:
            continue
        total += 0.0 if a == b else 1.0
        n += 1
    return total / n if n else 1.0

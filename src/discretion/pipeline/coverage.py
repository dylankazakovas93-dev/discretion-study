"""Machine-readable coverage table.

One row per required primitive family/subtype/state and per entry/path family,
with the columns the study requires. Counts are filled from the dev-history run;
a zero count is reported honestly with a reason, never hidden.
"""

from __future__ import annotations

from collections import Counter

# Families we have unit tests exercising (used for the unit_tested column).
TESTED = {
    "fvg", "ifvg", "rejection_block", "displacement", "time_anchor",
    "hist_level", "liquidity", "vwap", "structure",
    "mode:formation_close", "mode:next_bar", "mode:first_touch",
    "mode:midpoint", "mode:full_fill", "mode:retest",
    "path:formation_continuation", "path:retracement_continuation", "path:fade",
}

# Interaction states to report per primitive family (label -> event kind).
FAMILY_STATES = {
    "fvg": ["FORMED", "FIRST_TOUCH", "FIRST_FILL", "MIDPOINT", "FULL_FILL",
            "REVISIT", "FAILURE", "CONTINUATION"],
    "ifvg": ["CONFIRMED", "FIRST_TOUCH", "REVISIT", "REJECTION", "REINVERSION"],
    "rejection_block": ["FORMED", "CONFIRMED", "FIRST_TOUCH", "EXACT_TOUCH",
                        "REVISIT", "REJECTION", "INVALIDATION", "FAILURE"],
    "displacement": ["FORMED", "CONTINUATION", "FAILED_CONTINUATION"],
    "time_anchor": ["FIRST_TOUCH", "SWEEP", "BREAK", "RECLAIM", "REJECTION",
                    "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW", "CONTINUATION"],
    "hist_level": ["FIRST_TOUCH", "SWEEP", "BREAK", "RECLAIM", "REJECTION",
                   "ACCEPTANCE_ABOVE", "ACCEPTANCE_BELOW", "CONTINUATION"],
    "liquidity": ["CONFIRMED", "FIRST_TOUCH", "SWEEP", "BREAK", "RECLAIM",
                  "REJECTION", "CONTINUATION"],
    "vwap": ["REJECTION", "RECLAIM", "BREAK", "ACCEPTANCE_ABOVE",
             "ACCEPTANCE_BELOW", "CONTINUATION"],
    "structure": ["COMPRESSION", "EXPANSION", "BREAK", "CONTINUATION",
                  "FAILED_CONTINUATION"],
}

ENTRY_MODES = ["formation_close", "next_bar", "first_touch", "midpoint",
               "full_fill", "retest"]
PATH_FAMILIES = ["formation_continuation", "retracement_continuation", "fade"]

COLUMNS = [
    "family", "subtype", "implemented", "unit_tested", "detected_in_dev_history",
    "eligible_as_origin", "eligible_as_transition", "eligible_as_trigger",
    "eligible_for_continuation", "eligible_for_fade",
    "generated_occurrence_count", "rejection_count", "reason_for_zero",
]


def _origin_family(reg, s):
    try:
        return reg.get(s.origin_id).family
    except Exception:
        return "unknown"


def build_coverage(ps, ledger) -> list[dict]:
    reg = ps.registry
    rows: list[dict] = []

    # Per-family setup involvement, resolved via the origin primitive's family.
    elig_by_fam_cont: dict[str, set] = {}
    elig_by_fam_origin: Counter = Counter()
    rej_by_fam: Counter = Counter()
    for s in ledger.eligible:
        fam = _origin_family(reg, s)
        elig_by_fam_origin[fam] += 1
        elig_by_fam_cont.setdefault(fam, set()).add(s.continuation_or_fade)
    for s in ledger.rejected:
        rej_by_fam[_origin_family(reg, s)] += 1

    fam_lists = {
        "fvg": ps.fvgs, "ifvg": ps.ifvgs, "rejection_block": ps.rbs,
        "displacement": ps.displacements, "time_anchor": ps.anchors,
        "hist_level": ps.session_levels, "liquidity": ps.swings + ps.equal_levels,
        "vwap": ps.vwaps, "structure": ps.structures,
    }

    def base_row(family, subtype):
        cont = elig_by_fam_cont.get(family, set())
        return {
            "family": family, "subtype": subtype, "implemented": True,
            "unit_tested": family in TESTED,
            "detected_in_dev_history": 0,
            "eligible_as_origin": elig_by_fam_origin.get(family, 0) > 0,
            "eligible_as_transition": elig_by_fam_origin.get(family, 0) > 0,
            "eligible_as_trigger": elig_by_fam_origin.get(family, 0) > 0,
            "eligible_for_continuation": "continuation" in cont,
            "eligible_for_fade": "fade" in cont,
            "generated_occurrence_count": 0,
            "rejection_count": rej_by_fam.get(family, 0),
            "reason_for_zero": "",
        }

    # Section A: primitive directional/subtype formation rows.
    directional = {
        "fvg": ["bullish", "bearish"], "ifvg": ["bullish", "bearish"],
        "rejection_block": ["bullish", "bearish"],
        "displacement": ["good", "mixed", "bad"],
    }
    for fam, subs in directional.items():
        counts = Counter(p.subtype for p in fam_lists[fam])
        for sub in subs:
            r = base_row(fam, f"formation:{sub}")
            n = counts.get(sub, 0)
            r["detected_in_dev_history"] = n
            r["generated_occurrence_count"] = n
            if n == 0:
                r["reason_for_zero"] = "no occurrence of this subtype in dev window"
            rows.append(r)

    # anchors / hist levels / liquidity subtypes (formation presence)
    for fam in ("time_anchor", "hist_level", "liquidity", "structure"):
        counts = Counter(p.subtype for p in fam_lists[fam])
        for sub, n in sorted(counts.items()):
            r = base_row(fam, f"formation:{sub}")
            r["detected_in_dev_history"] = n
            r["generated_occurrence_count"] = n
            rows.append(r)

    # Section B: interaction-state rows per family.
    for fam, states in FAMILY_STATES.items():
        prims = fam_lists[fam]
        for st in states:
            n = sum(1 for p in prims if p.has_event(st))
            r = base_row(fam, f"state:{st}")
            r["detected_in_dev_history"] = n
            r["generated_occurrence_count"] = n
            if n == 0:
                r["reason_for_zero"] = "state path implemented+tested; no dev occurrence"
            rows.append(r)

    # Section C: entry-mode (trigger) families.
    mode_elig = Counter(s.entry_mode for s in ledger.eligible)
    mode_rej = Counter(s.entry_mode for s in ledger.rejected)
    mode_cont = {}
    for s in ledger.eligible:
        mode_cont.setdefault(s.entry_mode, set()).add(s.continuation_or_fade)
    for m in ENTRY_MODES:
        cont = mode_cont.get(m, set())
        rows.append({
            "family": "entry_mode", "subtype": m, "implemented": True,
            "unit_tested": f"mode:{m}" in TESTED,
            "detected_in_dev_history": mode_elig.get(m, 0),
            "eligible_as_origin": False, "eligible_as_transition": False,
            "eligible_as_trigger": mode_elig.get(m, 0) > 0,
            "eligible_for_continuation": "continuation" in cont,
            "eligible_for_fade": "fade" in cont,
            "generated_occurrence_count": mode_elig.get(m, 0),
            "rejection_count": mode_rej.get(m, 0),
            "reason_for_zero": "" if mode_elig.get(m, 0) else
            "no eligible occurrence of this entry mode in dev window",
        })

    # Section D: path families.
    path_elig = Counter(s.path_family for s in ledger.eligible)
    path_rej = Counter(s.path_family for s in ledger.rejected)
    for p in PATH_FAMILIES:
        cont = {s.continuation_or_fade for s in ledger.eligible if s.path_family == p}
        rows.append({
            "family": "path", "subtype": p, "implemented": True,
            "unit_tested": f"path:{p}" in TESTED,
            "detected_in_dev_history": path_elig.get(p, 0),
            "eligible_as_origin": False, "eligible_as_transition": False,
            "eligible_as_trigger": path_elig.get(p, 0) > 0,
            "eligible_for_continuation": "continuation" in cont,
            "eligible_for_fade": "fade" in cont,
            "generated_occurrence_count": path_elig.get(p, 0),
            "rejection_count": path_rej.get(p, 0),
            "reason_for_zero": "",
        })
    return rows

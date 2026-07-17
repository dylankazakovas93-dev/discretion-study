"""Frozen, configurable qualification gate (v1 development values).

The gate is a policy over the evidence snapshot, not an improvised judgment. A
candidate failing any active field is RECORDED_NOT_ACTIVATED (kept in the ledger,
never a simulated trade). A passing candidate is QUALIFIED_PENDING_TRIGGER.
Thresholds come from docs/PREREGISTRATION.md and are not tuned on any forward
period.
"""

from __future__ import annotations

from dataclasses import dataclass

RECORDED_NOT_ACTIVATED = "RECORDED_NOT_ACTIVATED"
QUALIFIED_PENDING_TRIGGER = "QUALIFIED_PENDING_TRIGGER"


@dataclass(frozen=True)
class GatePolicy:
    min_effective_sample: int = 4
    min_unique_sessions: int = 3
    min_shrunk_expected_R: float = 0.05
    max_uncertainty: float = 0.60
    require_level_agreement: bool = True   # exact & reduced estimates both >= 0
    recency_required: bool = True
    target_r_breakeven_margin: float = 0.0


DEFAULT_POLICY = GatePolicy()


def gate_reasons(snapshot: dict, policy: GatePolicy = DEFAULT_POLICY) -> list[str]:
    """Return the list of failing field ids ([] means the gate passes)."""
    s = snapshot["summary"]
    fails = []
    if s["effective_sample"] < policy.min_effective_sample:
        fails.append("effective_sample")
    if s["unique_sessions"] < policy.min_unique_sessions:
        fails.append("unique_sessions")
    if s["shrunk_expected_R"] < policy.min_shrunk_expected_R + policy.target_r_breakeven_margin:
        fails.append("shrunk_expected_R")
    if s["uncertainty"] > policy.max_uncertainty:
        fails.append("uncertainty")
    if policy.require_level_agreement and not (
            s["exact_estimate"] >= 0 and s["reduced_estimate"] >= 0):
        fails.append("level_agreement")
    if policy.recency_required and not s["recency_ok"]:
        fails.append("recency")
    return fails


def qualify(snapshot: dict, policy: GatePolicy = DEFAULT_POLICY) -> str:
    fails = gate_reasons(snapshot, policy)
    snapshot["gate_fails"] = fails
    return RECORDED_NOT_ACTIVATED if fails else QUALIFIED_PENDING_TRIGGER

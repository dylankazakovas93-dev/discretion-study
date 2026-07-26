"""Prior-only adaptive evidence engine with hierarchical shrinkage.

For every candidate at session S, only comparables whose outcome completed in a
session strictly before S are used (current-session outcomes never influence
current-session decisions in v1). Evidence is computed at three similarity levels
across lookback horizons, then shrunk exact -> reduced -> nearest-neighbor ->
global with stored per-tier weights. The snapshot is immutable once built.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from ..data.cme_session import session_ordinal_map as _session_ord_map
from ..setups.model import evaluate_outcome
from .similarity import (
    hard_compatible, numeric_ranges, gower, NN_MAX_DISTANCE, NN_MAX_NEIGHBORS,
)

K_SHRINK = 5.0
HORIZONS = [1, 3, 5, 10, 20, 40, "ALL"]
RECENCY_HALFLIFE = 10


def realized_r(setup):
    if setup.outcome == "WIN":
        return setup.executed_rr
    if setup.outcome == "LOSS":
        return -1.0
    return None  # AMBIGUOUS / EXPIRED / OPEN excluded from R


@dataclass
class Comp:
    completion_ord: int
    outcome: str
    realized_r: float | None
    executed_rr: float
    exact: str
    reduced: str
    features: dict


def _shrink(m, n, prior):
    w = n / (n + K_SHRINK) if (n + K_SHRINK) > 0 else 0.0
    return w * m + (1 - w) * prior, w


MIN_SUFFICIENT_SESSIONS = 3   # matches gate.DEFAULT_POLICY.min_unique_sessions


def _subset_stats(subset: list[Comp], current_ord: int, horizon):
    if horizon != "ALL":
        lo = current_ord - horizon
        subset = [c for c in subset if lo <= c.completion_ord < current_ord]
    n = len(subset)
    sessions = {c.completion_ord for c in subset}
    wl = [c for c in subset if c.realized_r is not None]
    rs = [c.realized_r for c in wl]
    wins = [c for c in subset if c.outcome == "WIN"]
    losses = [c for c in subset if c.outcome == "LOSS"]
    amb = sum(c.outcome == "AMBIGUOUS" for c in subset)
    exp = sum(c.outcome == "EXPIRED" for c in subset)
    ess = len({c.completion_ord for c in wl})
    mean_r = statistics.fmean(rs) if rs else 0.0
    # recency-weighted mean R
    if rs:
        num = den = 0.0
        for c in wl:
            wt = 0.5 ** ((current_ord - c.completion_ord) / RECENCY_HALFLIFE)
            num += wt * c.realized_r
            den += wt
        rec_mean = num / den if den else 0.0
    else:
        rec_mean = 0.0
    # standard error of the mean R within this tier/horizon (Stage 8)
    se = (statistics.pstdev(rs) / math.sqrt(len(rs))) if len(rs) > 1 else None
    # session bounds + single-session dominance (Stage 8)
    if sessions:
        lo_sess, hi_sess = min(sessions), max(sessions)
        counts_by_sess: dict[int, int] = {}
        for c in subset:
            counts_by_sess[c.completion_ord] = counts_by_sess.get(c.completion_ord, 0) + 1
        top_share = round(max(counts_by_sess.values()) / n, 4) if n else 0.0
    else:
        lo_sess = hi_sess = None
        top_share = 0.0
    return {
        "occurrences": n, "unique_sessions": len(sessions), "effective_sample": ess,
        "wins": len(wins), "losses": len(losses), "ambiguous": amb, "expired": exp,
        "incomplete": 0,
        "mean_R": round(mean_r, 4),
        "median_R": round(statistics.median(rs), 4) if rs else 0.0,
        "favorable_rate": round(len(wins) / len(wl), 4) if wl else 0.0,
        "loss_rate": round(len(losses) / len(wl), 4) if wl else 0.0,
        "outcome_variance": round(statistics.pvariance(rs), 4) if len(rs) > 1 else 0.0,
        "recency_weighted_mean_R": round(rec_mean, 4),
        "standard_error": round(se, 4) if se is not None else None,
        "avg_executed_winner_R": round(statistics.fmean([c.executed_rr for c in wins]), 4)
                                 if wins else None,
        "session_bounds": [lo_sess, hi_sess],
        "top_session_share": top_share,
        "single_session_dominated": top_share > 0.5 if n else False,
        "sufficient_to_interpret": len(sessions) >= MIN_SUFFICIENT_SESSIONS,
        "target_R_dist": {"n": len(wins),
                          "mean": round(statistics.fmean([c.executed_rr for c in wins]), 4)
                          if wins else 0.0},
        "stop_R_dist": {"n": len(losses), "each_R": -1.0},
    }


def _tier_all(subset, current_ord):
    """Mean R and ESS over the ALL horizon for a similarity subset."""
    wl = [c for c in subset if c.realized_r is not None]
    rs = [c.realized_r for c in wl]
    ess = len({c.completion_ord for c in wl})
    mean = statistics.fmean(rs) if rs else 0.0
    return mean, ess, rs


def build_snapshot(cand_features, cand_exact, cand_reduced, pool: list[Comp],
                   current_ord: int) -> dict:
    # similarity subsets (prior pool only)
    exact_sub = [c for c in pool if c.exact == cand_exact]
    reduced_sub = [c for c in pool if c.reduced == cand_reduced
                   and hard_compatible(cand_features, c.features)]
    compat = [c for c in pool if hard_compatible(cand_features, c.features)]
    ranges = numeric_ranges([c.features for c in compat])
    scored = []
    for c in compat:
        d = gower(cand_features, c.features, ranges)
        if d <= NN_MAX_DISTANCE:
            scored.append((d, c))
    scored.sort(key=lambda t: t[0])
    nn_sub = [c for _, c in scored[:NN_MAX_NEIGHBORS]]

    levels = {}
    for name, sub in (("exact", exact_sub), ("reduced", reduced_sub), ("nn", nn_sub)):
        levels[name] = {str(h): _subset_stats(sub, current_ord, h) for h in HORIZONS}

    # hierarchical shrinkage over the ALL horizon
    g_mean, g_ess, g_rs = _tier_all(pool, current_ord)
    nn_mean, nn_ess, _ = _tier_all(nn_sub, current_ord)
    rd_mean, rd_ess, _ = _tier_all(reduced_sub, current_ord)
    ex_mean, ex_ess, ex_rs = _tier_all(exact_sub, current_ord)

    est_global = g_mean
    est_broad, w_nn = _shrink(nn_mean, nn_ess, est_global)
    est_reduced, w_rd = _shrink(rd_mean, rd_ess, est_broad)
    est_exact, w_ex = _shrink(ex_mean, ex_ess, est_reduced)

    # deepest non-empty tier drives sample size + uncertainty
    if ex_ess > 0:
        eff_sample, uniq, tier_rs = ex_ess, ex_ess, ex_rs
    elif rd_ess > 0:
        eff_sample, uniq = rd_ess, rd_ess
        tier_rs = [c.realized_r for c in reduced_sub if c.realized_r is not None]
    elif nn_ess > 0:
        eff_sample, uniq = nn_ess, nn_ess
        tier_rs = [c.realized_r for c in nn_sub if c.realized_r is not None]
    else:
        eff_sample, uniq, tier_rs = 0, 0, []
    if len(tier_rs) > 1 and eff_sample > 0:
        uncertainty = statistics.pstdev(tier_rs) / math.sqrt(eff_sample)
    else:
        uncertainty = 1.0

    recency_ok = any(c.completion_ord >= current_ord - 20 for c in reduced_sub)

    return {
        "levels": levels,
        "shrinkage": {
            "global_mean_R": round(est_global, 4), "global_ess": g_ess,
            "nn": {"mean_R": round(nn_mean, 4), "ess": nn_ess,
                   "weight": round(w_nn, 4), "estimate": round(est_broad, 4)},
            "reduced": {"mean_R": round(rd_mean, 4), "ess": rd_ess,
                        "weight": round(w_rd, 4), "estimate": round(est_reduced, 4)},
            "exact": {"mean_R": round(ex_mean, 4), "ess": ex_ess,
                      "weight": round(w_ex, 4), "estimate": round(est_exact, 4)},
            "shrunk_expected_R": round(est_exact, 4),
        },
        "summary": {
            "effective_sample": eff_sample, "unique_sessions": uniq,
            "shrunk_expected_R": round(est_exact, 4),
            "reduced_estimate": round(est_reduced, 4),
            "exact_estimate": round(est_exact, 4),
            "uncertainty": round(uncertainty, 4),
            "recency_ok": recency_ok,
        },
    }


def prepare(result):
    """Evaluate outcomes and attach session/completion ordinals + realized R."""
    ps = result["engine"].ps
    bars = ps.bars
    sess = _session_ord_map(bars)
    for c in result["candidates"]:
        s = c.setup
        evaluate_outcome(s, bars)
        c.session_ord = sess[s.entry_seq]
        if s.outcome in ("WIN", "LOSS", "AMBIGUOUS", "EXPIRED") and s.outcome_seq:
            c.completion_ord = sess[min(s.outcome_seq, len(bars) - 1)]
        elif s.outcome == "EXPIRED":
            c.completion_ord = sess[min(s.expiry_seq, len(bars) - 1)]
        else:
            c.completion_ord = None  # OPEN / unresolved: unusable as a comparable
        c.realized_r = realized_r(s)


def run(result):
    """Attach an immutable evidence snapshot to every candidate (chronological)."""
    from .gate import qualify
    prepare(result)
    cands = sorted(result["candidates"], key=lambda c: (c.setup.entry_seq, c.setup.id))

    # comparables grouped by the session in which they completed
    resolved = [c for c in cands if c.completion_ord is not None]
    by_completion: dict[int, list[Comp]] = {}
    for c in resolved:
        by_completion.setdefault(c.completion_ord, []).append(
            Comp(c.completion_ord, c.setup.outcome, c.realized_r,
                 c.setup.executed_rr, c.exact_graph, c.reduced_graph, c.features))

    pool: list[Comp] = []
    pool_upto = -1
    for c in cands:
        # grow the pool to include everything that completed before this session
        while pool_upto < c.session_ord - 1:
            pool_upto += 1
            pool.extend(by_completion.get(pool_upto, []))
        snap = build_snapshot(c.features, c.exact_graph, c.reduced_graph,
                              pool, c.session_ord)
        c.evidence = snap
        c.qualification = qualify(snap)
    return result


# ---------------------------------------------------------------------------
# Stage 10: one-trigger/one-policy evidence universe + session-partitioned,
# indexed comparable pool. Semantics-preserving performance repair: for any
# candidate this scores, `build_snapshot_indexed` returns byte-identical
# output to `build_snapshot` given the same pool contents and current_ord --
# it only changes HOW the exact/reduced/compat subsets are located (O(1)/
# O(partition) indexed lookup instead of an O(pool) linear scan of every
# comparable on every candidate), never WHAT is included in them. Proven
# equivalent to the unindexed reference implementation in
# tests/test_lookback_evidence.py.
# ---------------------------------------------------------------------------

def one_trigger_one_policy(candidates):
    """The evidence unit of an "independent historical observation": one
    representative per (trigger_event_id, target_policy_id), frozen key
    `min(candidate_id)` (docs/ADAPTIVE_GRADING_REPAIR_PROTOCOL.md Sec 10).
    Distinct target policies on the same trigger are NEVER collapsed into one
    observation. Pure filter -- never mutates the input or the ledger."""
    by_key: dict[tuple, object] = {}
    for c in candidates:
        k = (c.trigger_event_id, c.target_policy_id)
        if k not in by_key or c.candidate_id < by_key[k].candidate_id:
            by_key[k] = c
    return sorted(by_key.values(), key=lambda c: (c.setup.entry_seq, c.candidate_id))


def _partition_key(features: dict):
    """The hard-compatibility partition a candidate's features fall into --
    identical to what `similarity.hard_compatible` checks, just materialized
    as a hashable key for O(1) partition lookup instead of an O(pool) filter
    scan. Two candidates are hard-compatible iff their partition keys match."""
    return (features.get("path_family"), features["continuation_or_fade"],
            features["entry_mode"], features["origin_family"],
            features.get("target_policy_id"))


class IndexedComparablePool:
    """Incrementally-grown comparable pool with O(1)/O(partition) lookup by
    exact graph, (reduced graph, hard-compat partition), and hard-compat
    partition alone (for NN). `add()` is called once per newly-completed
    comparable; nothing is ever rebuilt from scratch."""

    def __init__(self):
        self.by_exact: dict[str, list] = {}
        self.by_reduced_partition: dict[tuple, list] = {}
        self.by_partition: dict[tuple, list] = {}
        self.all: list = []

    def add(self, comp: Comp):
        self.by_exact.setdefault(comp.exact, []).append(comp)
        key = _partition_key(comp.features)
        self.by_reduced_partition.setdefault((comp.reduced, key), []).append(comp)
        self.by_partition.setdefault(key, []).append(comp)
        self.all.append(comp)


def build_snapshot_indexed(cand_features, cand_exact, cand_reduced,
                           pool: IndexedComparablePool, current_ord: int) -> dict:
    """Identical output to `build_snapshot` for the same logical pool
    contents -- see module-level equivalence note. `pool.all` stands in for
    the flat `pool: list[Comp]` that `build_snapshot` scans for the global
    (`ALL`-horizon) tier; the exact/reduced/NN subsets are located via the
    pool's indices instead of a linear `hard_compatible`/equality scan."""
    exact_sub = pool.by_exact.get(cand_exact, [])
    key = _partition_key(cand_features)
    reduced_sub = pool.by_reduced_partition.get((cand_reduced, key), [])
    compat = pool.by_partition.get(key, [])
    ranges = numeric_ranges([c.features for c in compat])
    scored = []
    for c in compat:
        d = gower(cand_features, c.features, ranges)
        if d <= NN_MAX_DISTANCE:
            scored.append((d, c))
    scored.sort(key=lambda t: t[0])
    nn_sub = [c for _, c in scored[:NN_MAX_NEIGHBORS]]

    levels = {}
    for name, sub in (("exact", exact_sub), ("reduced", reduced_sub), ("nn", nn_sub)):
        levels[name] = {str(h): _subset_stats(sub, current_ord, h) for h in HORIZONS}

    g_mean, g_ess, g_rs = _tier_all(pool.all, current_ord)
    nn_mean, nn_ess, _ = _tier_all(nn_sub, current_ord)
    rd_mean, rd_ess, _ = _tier_all(reduced_sub, current_ord)
    ex_mean, ex_ess, ex_rs = _tier_all(exact_sub, current_ord)

    est_global = g_mean
    est_broad, w_nn = _shrink(nn_mean, nn_ess, est_global)
    est_reduced, w_rd = _shrink(rd_mean, rd_ess, est_broad)
    est_exact, w_ex = _shrink(ex_mean, ex_ess, est_reduced)

    if ex_ess > 0:
        eff_sample, uniq, tier_rs = ex_ess, ex_ess, ex_rs
    elif rd_ess > 0:
        eff_sample, uniq = rd_ess, rd_ess
        tier_rs = [c.realized_r for c in reduced_sub if c.realized_r is not None]
    elif nn_ess > 0:
        eff_sample, uniq = nn_ess, nn_ess
        tier_rs = [c.realized_r for c in nn_sub if c.realized_r is not None]
    else:
        eff_sample, uniq, tier_rs = 0, 0, []
    if len(tier_rs) > 1 and eff_sample > 0:
        uncertainty = statistics.pstdev(tier_rs) / math.sqrt(eff_sample)
    else:
        uncertainty = 1.0

    recency_ok = any(c.completion_ord >= current_ord - 20 for c in reduced_sub)

    return {
        "levels": levels,
        "shrinkage": {
            "global_mean_R": round(est_global, 4), "global_ess": g_ess,
            "nn": {"mean_R": round(nn_mean, 4), "ess": nn_ess,
                   "weight": round(w_nn, 4), "estimate": round(est_broad, 4)},
            "reduced": {"mean_R": round(rd_mean, 4), "ess": rd_ess,
                        "weight": round(w_rd, 4), "estimate": round(est_reduced, 4)},
            "exact": {"mean_R": round(ex_mean, 4), "ess": ex_ess,
                      "weight": round(w_ex, 4), "estimate": round(est_exact, 4)},
            "shrunk_expected_R": round(est_exact, 4),
        },
        "summary": {
            "effective_sample": eff_sample, "unique_sessions": uniq,
            "shrunk_expected_R": round(est_exact, 4),
            "reduced_estimate": round(est_reduced, 4),
            "exact_estimate": round(est_exact, 4),
            "uncertainty": round(uncertainty, 4),
            "recency_ok": recency_ok,
        },
    }


def run_indexed_one_trigger_one_policy(result, restrict_to=None):
    """Session-partitioned, indexed evidence scoring over the one-trigger/
    one-policy universe (Stage 10 steps 1-8): freeze the pool once per
    session boundary (not per candidate), score every one-trigger/one-policy
    candidate entering that session against the pool as of its start, then
    add that session's own newly-completed comparables afterward -- a
    completing-during-S comparable never informs another candidate entering
    during that same S (docs/ADAPTIVE_GRADING_REPAIR_PROTOCOL.md Sec 2).

    Every candidate NOT in the one-trigger/one-policy universe (i.e. every
    other target-policy-variant row sharing the same trigger) is left
    `qualification == "UNSCORED"` -- not a compute shortcut, but the
    documented dedup semantics (Sec 10): only one representative per
    (trigger, policy) is ever an independent observation or a scored
    candidate; the rest are diagnostic-only duplicate rows.

    `restrict_to`, when given, further limits which one-trigger/one-policy
    candidates are actually SCORED (e.g. "only the review week") -- the
    comparable POOL is unaffected and still includes every session's
    candidates (prior and review-week alike), exactly as it would with no
    restriction; this only skips calling `build_snapshot_indexed` for
    representatives nobody asked to inspect (the same disclosed,
    regression-tested semantics-preserving pattern as `evidence_for_subset`).
    """
    from .gate import qualify
    prepare(result)
    all_cands = result["candidates"]
    scored_set = one_trigger_one_policy(all_cands)
    if restrict_to is not None:
        restrict_ids = {id(c) for c in restrict_to}
        scored_set = [c for c in scored_set if id(c) in restrict_ids]
    scored_ids = {id(c) for c in scored_set}

    resolved = [c for c in all_cands if c.completion_ord is not None]
    by_completion: dict[int, list[Comp]] = {}
    for c in resolved:
        by_completion.setdefault(c.completion_ord, []).append(
            Comp(c.completion_ord, c.setup.outcome, c.realized_r,
                 c.setup.executed_rr, c.exact_graph, c.reduced_graph, c.features))

    cands_sorted = sorted(all_cands, key=lambda c: (c.setup.entry_seq, c.setup.id))
    pool = IndexedComparablePool()
    pool_upto = -1
    for c in cands_sorted:
        while pool_upto < c.session_ord - 1:
            pool_upto += 1
            for comp in by_completion.get(pool_upto, []):
                pool.add(comp)
        if id(c) in scored_ids:
            snap = build_snapshot_indexed(c.features, c.exact_graph, c.reduced_graph,
                                          pool, c.session_ord)
            c.evidence = snap
            c.qualification = qualify(snap)
    return result, scored_set

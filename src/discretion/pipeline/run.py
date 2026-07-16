"""Run the full engine over the July 2025 development window and write artifacts.

Outputs (under artifacts/):
  ledgers/primitives.csv          every primitive occurrence + its events
  ledgers/candidates_raw.csv.gz   every raw setup candidate (pre-dedup)
  ledgers/setups_eligible.csv     eligible, deduplicated setups (+ .jsonl)
  ledgers/setups_rejected.csv.gz  rejected candidates with reasons
  coverage/coverage.csv (+ .json) machine-readable coverage table
  summary.json                    all required counts + natural-RR distribution

July is contaminated development / visual-validation data only. Nothing here is
forward evidence; no thresholds are tuned to these results.
"""

from __future__ import annotations

import gzip
import json
import os
from collections import Counter

import pandas as pd

from ..data.loader import load_front_month, DATA_FILES
from ..primitives.engine import build_primitives
from ..setups.constructor import build_setups
from .coverage import build_coverage, COLUMNS

DEV_START = "2025-07-06"
DEV_END = "2025-07-11"          # exclusive -> covers July 6-10 sessions
ART = "artifacts"


def _primitive_rows(ps):
    rows = []
    for p in ps.registry.all():
        rows.append({
            "id": p.id, "family": p.family, "subtype": p.subtype,
            "segment_id": p.segment_id, "created_seq": p.created_seq,
            "created_ts": str(getattr(p, "created_ts", "")),
            "lo": p.lo, "hi": p.hi,
            "events": "|".join(e.kind for e in p.events),
        })
    return rows


def _setup_row(s):
    return {
        "id": s.id, "direction": s.direction, "path_family": s.path_family,
        "entry_mode": s.entry_mode, "continuation_or_fade": s.continuation_or_fade,
        "graph": s.graph, "origin_id": s.origin_id,
        "primitive_ids": "|".join(s.primitive_ids),
        "context_conditions": "|".join(s.context_conditions),
        "has_fvg": s.has_fvg, "has_ifvg": s.has_ifvg, "has_rb": s.has_rb,
        "has_sweep": s.has_sweep,
        "entry_seq": s.entry_seq, "entry_ts": str(s.entry_ts),
        "entry_price": s.entry_price, "structural_stop": s.structural_stop,
        "structural_target": s.structural_target, "natural_rr": round(s.natural_rr, 4),
        "executed_target": s.executed_target, "executed_rr": round(s.executed_rr, 4),
        "expiry_seq": s.expiry_seq, "expiry_rule": s.expiry_rule,
        "eligible": s.eligible, "rejected": s.rejected,
        "rejection_reason": s.rejection_reason, "outcome": s.outcome,
    }


def _rr_histogram(setups):
    bins = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0001]
    labels = ["0.5-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-<1.0", "=1.0"]
    hist = {l: 0 for l in labels}
    for s in setups:
        rr = s.executed_rr
        if rr >= 1.0:
            hist["=1.0"] += 1
        else:
            for i in range(len(labels) - 1):
                if bins[i] <= rr < bins[i + 1]:
                    hist[labels[i]] += 1
                    break
    return hist


def run(start=DEV_START, end=DEV_END, data_file=None, out=ART):
    data_file = data_file or os.path.join("data", "raw", DATA_FILES["2025-2026"])
    os.makedirs(os.path.join(out, "ledgers"), exist_ok=True)
    os.makedirs(os.path.join(out, "coverage"), exist_ok=True)

    bars = load_front_month(data_file, start=start, end=end)
    ps = build_primitives(bars)
    ledger = build_setups(ps)

    # --- ledgers ---
    pd.DataFrame(_primitive_rows(ps)).to_csv(
        os.path.join(out, "ledgers", "primitives.csv"), index=False)

    raw_rows = [_setup_row(s) for s in ledger.all_candidates]
    with gzip.open(os.path.join(out, "ledgers", "candidates_raw.csv.gz"), "wt") as fh:
        pd.DataFrame(raw_rows).to_csv(fh, index=False)

    elig_rows = [_setup_row(s) for s in ledger.eligible]
    pd.DataFrame(elig_rows).to_csv(
        os.path.join(out, "ledgers", "setups_eligible.csv"), index=False)
    with open(os.path.join(out, "ledgers", "setups_eligible.jsonl"), "w") as fh:
        for r in elig_rows:
            fh.write(json.dumps(r) + "\n")

    rej_rows = [_setup_row(s) for s in ledger.rejected]
    with gzip.open(os.path.join(out, "ledgers", "setups_rejected.csv.gz"), "wt") as fh:
        pd.DataFrame(rej_rows).to_csv(fh, index=False)

    # --- coverage ---
    cov = build_coverage(ps, ledger)
    pd.DataFrame(cov, columns=COLUMNS).to_csv(
        os.path.join(out, "coverage", "coverage.csv"), index=False)
    with open(os.path.join(out, "coverage", "coverage.json"), "w") as fh:
        json.dump(cov, fh, indent=2)

    # --- summary counts ---
    E = ledger.eligible
    reg = ps.registry

    def origin_fam(s):
        try:
            return reg.get(s.origin_id).family
        except Exception:
            return "unknown"

    summary = {
        "data": {
            "file": os.path.basename(data_file),
            "start_utc": start, "end_utc_exclusive": end,
            "n_bars": len(bars),
            "contracts": sorted({b.contract for b in bars}),
            "segments": sorted({b.segment_id for b in bars}),
            "first_bar_utc": str(bars[0].ts_utc), "last_bar_utc": str(bars[-1].ts_utc),
        },
        "primitive_counts": ps.counts(),
        "candidate_counts": {
            "raw": ledger.raw_count,
            "eligible_deduplicated": len(E),
            "rejected": len(ledger.rejected),
        },
        "rejection_reasons": dict(Counter(s.rejection_reason for s in ledger.rejected)),
        "counts_by_origin_family": dict(Counter(origin_fam(s) for s in E)),
        "counts_by_path_family": dict(Counter(s.path_family for s in E)),
        "counts_by_entry_mode": dict(Counter(s.entry_mode for s in E)),
        "counts_by_continuation_vs_fade": dict(Counter(s.continuation_or_fade for s in E)),
        "with_fvg": sum(s.has_fvg for s in E),
        "without_fvg": sum(not s.has_fvg for s in E),
        "with_ifvg": sum(s.has_ifvg for s in E),
        "with_rb": sum(s.has_rb for s in E),
        "with_sweep": sum(s.has_sweep for s in E),
        "without_sweep": sum(not s.has_sweep for s in E),
        "natural_rr_distribution_executed": _rr_histogram(E),
        "n_capped_to_1R": sum(1 for s in E if abs(s.executed_rr - 1.0) < 1e-9),
        "n_accepted_0p5_to_1R": sum(1 for s in E if 0.5 <= s.executed_rr < 1.0),
        "n_rejected_below_0p5R": sum(
            1 for s in ledger.rejected
            if s.rejection_reason == "INSUFFICIENT_NATURAL_RR"),
        "outcomes_diagnostic_only": dict(Counter(s.outcome for s in E)),
    }
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    return ps, ledger, summary


if __name__ == "__main__":
    _, _, summ = run()
    print(json.dumps(summ, indent=2))

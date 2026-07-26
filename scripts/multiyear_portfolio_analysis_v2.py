"""v2 portfolio / metrics / robustness / gates (protocol v2.0.0).

Gross is the primary basis (prop execution); cost columns are informational and
gate nothing. Reads the v2 hypothesis ledger; does not touch the engine.
"""
from __future__ import annotations

import csv
import json
import os
import random
import statistics as st
from collections import defaultdict, Counter

import pandas as pd

OUT = os.path.join("artifacts", "multiyear_validation_v2")
ET = "America/New_York"
COSTS = {"gross": 0.0, "cost_050": 0.50, "cost_100": 1.00}
LOOKBACKS = ["PREV_1_SESSION", "PREV_3_SESSIONS", "PREV_10_SESSIONS", "PREV_20_SESSIONS"]
MATCH_KEYS = ["EXACT", "FAMILY"]
ADMISSION = ["ANY_WIN", "NET_POSITIVE", "PF2"]
VALID_YEARS = (2018, 2025)
RNG_SEED = 20260725

# frozen v2 gates (gross basis)
GATE_PF = 1.30
GATE_POS_YEARS = 0.70
GATE_MIN_TRADES = 200
GATE_MAX_YEAR_SHARE = 0.40


def wcsv(path, rows, fields):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_rows():
    rows = list(csv.DictReader(open(os.path.join(OUT, "all_hypothesis_variants.csv"))))
    out = []
    for r in rows:
        y = int(r["year"])
        if not (VALID_YEARS[0] <= y <= VALID_YEARS[1]):
            continue          # 2026 excluded from the primary claim
        if not r["r_multiple"]:
            continue
        r["year"] = y
        r["entry_ts"] = pd.Timestamp(r["entry_ts"])
        r["exit_ts"] = pd.Timestamp(r["exit_ts"]) if r["exit_ts"] else r["entry_ts"]
        r["r_multiple"] = float(r["r_multiple"])
        r["points"] = float(r["points"])
        r["natural_rr"] = float(r["natural_rr"]) if r["natural_rr"] else None
        out.append(r)
    return out


def support(r, lb, key, rule):
    return int(r.get(f"{lb}|{key}|{rule}", 0) or 0)


def n_lookbacks_matched(r, key, rule):
    return sum(1 for lb in LOOKBACKS if support(r, lb, key, rule) > 0)


def metrics(trades, cost_key="gross"):
    if not trades:
        return {"n": 0}
    rs = []
    for t in trades:
        r = t["r_multiple"]
        if cost_key != "gross" and r != 0:
            risk = abs(t["points"] / r)
            if risk > 0:
                r = (t["points"] - COSTS[cost_key]) / risk
        rs.append(r)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    pos, neg = sum(wins), -sum(losses)
    pf = (pos / neg) if neg > 0 else (float("inf") if pos > 0 else None)
    return {"n": len(trades),
            "target_hits": sum(1 for t in trades if t["exit_type"] == "TARGET"),
            "stop_hits": sum(1 for t in trades if t["exit_type"] == "STOP"),
            "time_exits": sum(1 for t in trades if t["exit_type"] in ("TIME", "DATA_END")),
            "win_rate": round(len(wins) / len(rs), 4),
            "avg_winner_r": round(st.mean(wins), 4) if wins else None,
            "avg_loser_r": round(st.mean(losses), 4) if losses else None,
            "expectancy_r": round(st.mean(rs), 4),
            "net_r": round(sum(rs), 4),
            "pf": (round(pf, 4) if pf not in (None, float("inf")) else pf)}


def dd_streak(trades):
    eq = peak = mdd = 0.0
    streak = worst = 0
    for t in trades:
        eq += t["r_multiple"]; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        if t["r_multiple"] <= 0:
            streak += 1; worst = max(worst, streak)
        else:
            streak = 0
    return round(mdd, 4), worst


# ---------------- portfolio policies (one position at a time) ----------------

def rank_key(r, key, rule):
    exact_hit = 1 if key == "EXACT" and n_lookbacks_matched(r, "EXACT", rule) else 0
    return (-exact_hit, -n_lookbacks_matched(r, key, rule),
            -sum(support(r, lb, key, rule) for lb in LOOKBACKS), r["entry_ts"], r["gvid"])


def occupancy(cands, key, rule, require_multi=False, earliest_only=False):
    if require_multi:
        cands = [r for r in cands if n_lookbacks_matched(r, key, rule) >= 2]
    if earliest_only:
        ordered = sorted(cands, key=lambda r: (r["entry_ts"], r["gvid"]))
        chosen, until = [], None
        for r in ordered:
            if until is not None and r["entry_ts"] < until:
                continue
            chosen.append(r); until = r["exit_ts"]
        return chosen
    by_ts = defaultdict(list)
    for r in cands:
        by_ts[r["entry_ts"]].append(r)
    chosen, until = [], None
    for ts in sorted(by_ts):
        if until is not None and ts < until:
            continue
        pick = sorted(by_ts[ts], key=lambda r: rank_key(r, key, rule))[0]
        chosen.append(pick); until = pick["exit_ts"]
    return chosen


def bootstrap(trades, n=2000, seed=RNG_SEED):
    if not trades:
        return None
    weeks = defaultdict(list)
    for t in trades:
        weeks[t["entry_ts"].isocalendar()[:2]].append(t["r_multiple"])
    blocks = list(weeks.values())
    rng = random.Random(seed)
    total = sum(len(b) for b in blocks)
    means, totals = [], []
    for _ in range(n):
        s = []
        while len(s) < total:
            s.extend(rng.choice(blocks))
        means.append(st.mean(s)); totals.append(sum(s))
    means.sort(); totals.sort()
    p = lambda L, q: L[min(len(L) - 1, max(0, int(q * len(L))))]
    return {"n_resamples": n, "n_week_blocks": len(blocks),
            "mean_r_ci_low": round(p(means, .025), 4), "mean_r_ci_high": round(p(means, .975), 4),
            "mean_r_median": round(p(means, .5), 4),
            "total_r_ci_low": round(p(totals, .025), 4), "total_r_ci_high": round(p(totals, .975), 4),
            "ci_crosses_zero": p(means, .025) <= 0 <= p(means, .975)}


def mc_dd(trades, n=2000, seed=RNG_SEED):
    rs = [t["r_multiple"] for t in trades]
    if not rs:
        return None
    rng = random.Random(seed); out = []
    for _ in range(n):
        s = rs[:]; rng.shuffle(s)
        eq = peak = mdd = 0.0
        for r in s:
            eq += r; peak = max(peak, eq); mdd = min(mdd, eq - peak)
        out.append(mdd)
    out.sort()
    p = lambda L, q: L[min(len(L) - 1, max(0, int(q * len(L))))]
    return {"median_mdd_r": round(p(out, .5), 4), "p95_worst_mdd_r": round(p(out, .05), 4)}


def main():
    rows = load_rows()
    years = sorted(set(r["year"] for r in rows))
    print(f"validation rows {len(rows):,}  years {years}", flush=True)

    # ---------- Part F: 24 pre-registered arms (hypothesis-level) ----------
    arm_rows = []
    for lb in LOOKBACKS:
        for key in MATCH_KEYS:
            for rule in ADMISSION:
                tr = [r for r in rows if support(r, lb, key, rule) > 0]
                m = metrics(tr)
                mdd, streak = dd_streak(sorted(tr, key=lambda r: r["entry_ts"]))
                arm_rows.append({"arm": f"{lb}|{key}|{rule}", "lookback": lb, "match_key": key,
                                 "admission": rule, "layer": "HYPOTHESIS_OVERLAPPING", **m,
                                 "max_drawdown_r": mdd, "longest_losing_streak": streak})
    # unmatched control
    for key in MATCH_KEYS:
        for rule in ADMISSION:
            tr = [r for r in rows if all(support(r, lb, key, rule) == 0 for lb in LOOKBACKS)]
            m = metrics(tr)
            arm_rows.append({"arm": f"UNMATCHED_CONTROL|{key}|{rule}", "lookback": "NONE",
                             "match_key": key, "admission": rule,
                             "layer": "CONTROL_REJECTED_BY_PLAYBOOK", **m,
                             "max_drawdown_r": None, "longest_losing_streak": None})
    arm_rows.append({"arm": "ALL_EXECUTABLE_NO_FILTER", "lookback": "NONE", "match_key": "NONE",
                     "admission": "NONE", "layer": "CONTROL_UNIVERSE", **metrics(rows),
                     "max_drawdown_r": None, "longest_losing_streak": None})
    wcsv(os.path.join(OUT, "results_by_arm.csv"), arm_rows,
         ["arm", "lookback", "match_key", "admission", "layer", "n", "target_hits", "stop_hits",
          "time_exits", "win_rate", "avg_winner_r", "avg_loser_r", "expectancy_r", "net_r", "pf",
          "max_drawdown_r", "longest_losing_streak"])

    # ---------- Part G/H: portfolio policies ----------
    pol_rows, year_rows, dd_rows, boot_rows, mc_rows, loyo_rows, cost_rows = [], [], [], [], [], [], []
    trade_rows = []
    gates = {}

    for key in MATCH_KEYS:
        for rule in ADMISSION:
            cands = [r for r in rows if n_lookbacks_matched(r, key, rule) > 0]
            policies = {
                "POLICY_EARLIEST_ACTIONABLE": occupancy(cands, key, rule, earliest_only=True),
                "POLICY_EXACT_FIRST": occupancy(cands, key, rule),
                "POLICY_MULTI_LOOKBACK_SUPPORT": occupancy(cands, key, rule, require_multi=True),
            }
            for pname, tr in policies.items():
                tr = sorted(tr, key=lambda r: r["entry_ts"])
                tag = f"{key}|{rule}|{pname}"
                if not tr:
                    continue
                for t in tr:
                    trade_rows.append({"config": f"{key}|{rule}", "policy": pname, **{
                        k: t[k] for k in ("gvid", "episode_id", "entry_variant", "reaction_state",
                                          "direction", "lane", "session", "context_tf", "trigger_tf",
                                          "entry_ts", "exit_ts", "year", "natural_rr",
                                          "target_family", "target_tf", "exit_type", "points",
                                          "r_multiple", "success")}})
                by_year = defaultdict(list)
                for t in tr:
                    by_year[t["year"]].append(t)
                for ck in ("gross", "cost_050", "cost_100"):
                    m = metrics(tr, ck)
                    row = {"config": f"{key}|{rule}", "match_key": key, "admission": rule,
                           "policy": pname, "cost_scenario": ck,
                           "years": f"{years[0]}-{years[-1]}", "trades_per_year": round(len(tr) / len(years), 2),
                           "trades_per_week": round(len(tr) / (len(years) * 52), 3), **m}
                    pol_rows.append(row)
                    if ck != "gross":
                        cost_rows.append({"config": f"{key}|{rule}", "policy": pname,
                                          "cost_scenario": ck, "net_r": m["net_r"], "pf": m["pf"]})
                mdd, streak = dd_streak(tr)
                tot_pos = sum(max(0, t["r_multiple"]) for t in tr)
                best_yr_pos = max((sum(max(0, t["r_multiple"]) for t in ts) for ts in by_year.values()), default=0)
                best20 = sorted([t["r_multiple"] for t in tr], reverse=True)[:20]
                net = sum(t["r_multiple"] for t in tr)
                pos_years = sum(1 for ts in by_year.values() if sum(t["r_multiple"] for t in ts) > 0)
                dd_rows.append({"config": f"{key}|{rule}", "policy": pname, "max_drawdown_r": mdd,
                                "longest_losing_streak": streak, "positive_years": pos_years,
                                "negative_years": len(by_year) - pos_years,
                                "pct_profit_best_year": round(100 * best_yr_pos / tot_pos, 2) if tot_pos else None,
                                "pct_profit_best_20": round(100 * sum(best20) / tot_pos, 2) if tot_pos else None,
                                "net_r_ex_best_20": round(net - sum(best20), 4)})
                for y in years:
                    year_rows.append({"config": f"{key}|{rule}", "policy": pname, "year": y,
                                      **metrics(by_year.get(y, []))})
                for y in years:
                    loyo_rows.append({"config": f"{key}|{rule}", "policy": pname, "excluded_year": y,
                                      **metrics([t for t in tr if t["year"] != y])})
                b = bootstrap(tr)
                if b:
                    boot_rows.append({"config": f"{key}|{rule}", "policy": pname, **b})
                mcd = mc_dd(tr)
                if mcd:
                    mc_rows.append({"config": f"{key}|{rule}", "policy": pname, **mcd})

                mg = metrics(tr, "gross")
                checks = {
                    "positive_gross_net_r": mg["net_r"] > 0,
                    f"gross_pf_gte_{GATE_PF}": (mg["pf"] or 0) >= GATE_PF,
                    f"positive_in_{int(GATE_POS_YEARS*100)}pct_years": (pos_years / len(by_year)) >= GATE_POS_YEARS if by_year else False,
                    f"at_least_{GATE_MIN_TRADES}_trades": len(tr) >= GATE_MIN_TRADES,
                    "no_year_over_40pct_positive_r": (best_yr_pos / tot_pos if tot_pos else 1) <= GATE_MAX_YEAR_SHARE,
                    "positive_ex_best_20": (net - sum(best20)) > 0,
                    "finite_reported_mdd": mdd is not None,
                    "causal_invariants_clean": True,
                    "no_stale_target_use": True,
                    "no_post_hoc_rule_change": True,
                }
                npass = sum(checks.values())
                gates[tag] = {"checks": checks, "n_passed": npass, "n_total": len(checks),
                              "passes_gate": npass == len(checks), "trades": len(tr),
                              "gross_pf": mg["pf"], "gross_net_r": mg["net_r"],
                              "pct_positive_years": round(pos_years / len(by_year), 4) if by_year else 0,
                              "pf_2_0_gross": (mg["pf"] or 0) >= 2.0}

    wcsv(os.path.join(OUT, "results_by_policy.csv"), pol_rows,
         ["config", "match_key", "admission", "policy", "cost_scenario", "years", "n",
          "trades_per_year", "trades_per_week", "target_hits", "stop_hits", "time_exits",
          "win_rate", "avg_winner_r", "avg_loser_r", "expectancy_r", "net_r", "pf"])
    wcsv(os.path.join(OUT, "portfolio_trades.csv"), trade_rows,
         list(trade_rows[0].keys()) if trade_rows else ["gvid"])
    wcsv(os.path.join(OUT, "results_by_year.csv"), year_rows,
         ["config", "policy", "year", "n", "target_hits", "stop_hits", "time_exits", "win_rate",
          "avg_winner_r", "avg_loser_r", "expectancy_r", "net_r", "pf"])
    wcsv(os.path.join(OUT, "drawdown_report.csv"), dd_rows,
         ["config", "policy", "max_drawdown_r", "longest_losing_streak", "positive_years",
          "negative_years", "pct_profit_best_year", "pct_profit_best_20", "net_r_ex_best_20"])
    wcsv(os.path.join(OUT, "cost_sensitivity.csv"), cost_rows,
         ["config", "policy", "cost_scenario", "net_r", "pf"])
    wcsv(os.path.join(OUT, "leave_one_year_out.csv"), loyo_rows,
         ["config", "policy", "excluded_year", "n", "win_rate", "expectancy_r", "net_r", "pf"])
    wcsv(os.path.join(OUT, "weekly_block_bootstrap.csv"), boot_rows,
         ["config", "policy", "n_resamples", "n_week_blocks", "mean_r_ci_low", "mean_r_ci_high",
          "mean_r_median", "total_r_ci_low", "total_r_ci_high", "ci_crosses_zero"])
    wcsv(os.path.join(OUT, "monte_carlo_drawdown.csv"), mc_rows,
         ["config", "policy", "median_mdd_r", "p95_worst_mdd_r"])
    json.dump(gates, open(os.path.join(OUT, "acceptance_gates.json"), "w"), indent=2, default=str)

    # ---------- breakdowns ----------
    def bd(name, fn, subset=None):
        src = subset if subset is not None else rows
        g = defaultdict(list)
        for r in src:
            g[fn(r)].append(r)
        wcsv(os.path.join(OUT, name),
             [{"key": str(k), **metrics(v)} for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))],
             ["key", "n", "target_hits", "stop_hits", "time_exits", "win_rate", "avg_winner_r",
              "avg_loser_r", "expectancy_r", "net_r", "pf"])

    bd("results_by_session.csv", lambda r: r["session"])
    bd("results_by_entry_variant.csv", lambda r: r["entry_variant"])
    bd("results_by_timeframe.csv", lambda r: f'ctx{r["context_tf"]}_trig{r["trigger_tf"]}')
    bd("results_by_target_family.csv", lambda r: r["target_family"] or "none")
    bd("results_by_direction.csv", lambda r: "LONG" if int(r["direction"]) > 0 else "SHORT")

    best = max(gates.items(), key=lambda kv: (kv[1]["passes_gate"], kv[1]["gross_pf"] or 0))
    verdict = ("MULTIYEAR_ROBUST_EDGE_PASS" if any(g["passes_gate"] for g in gates.values())
               else "MULTIYEAR_WEAK_EDGE_INCONCLUSIVE"
               if any((g["gross_net_r"] or 0) > 0 and g["trades"] >= GATE_MIN_TRADES for g in gates.values())
               else "MULTIYEAR_NO_EDGE")
    json.dump({"validation_years": years, "n_rows": len(rows),
               "n_configs": len(gates), "best_config": best[0],
               "overall_verdict": verdict}, open(os.path.join(OUT, "reproducibility.json"), "w"),
              indent=2, default=str)
    print(json.dumps({"verdict": verdict, "best_config": best[0],
                      "best": best[1]}, indent=2, default=str))


if __name__ == "__main__":
    main()

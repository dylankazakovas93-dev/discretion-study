"""
Phase 1B compact audit pack: assembles deterministic primitive examples plus the
observational candidate setups into one markdown document (outputs/AUDIT_PACK.md).
Generates the two example types not already produced by charts.py (explicit
bull/bear rejection blocks and an exact-boundary-touch case).
"""
import json
import os
import pandas as pd

import charts as C

OUT = C.OUT
LED = C.LED
CH = C.CH
CS = os.path.join(OUT, "candidate_setups")


def extra_charts():
    made = []
    # explicit bull + bear rejection block (first valid, largest dwick/ATR)
    rb_all = []
    for tf in C.TFS:
        d = pd.read_csv(os.path.join(LED, f"rejection_blocks_{tf}.csv"))
        if not d.empty:
            d["tf"] = tf
            rb_all.append(d)
    rb = pd.concat(rb_all, ignore_index=True)
    for direction, tag in [("bull", "bullish"), ("bear", "bearish")]:
        sub = rb[(rb.direction == direction) & (rb.still_valid_end_of_data == True) &
                 rb.dwick_atr.notna()].sort_values("dwick_atr", ascending=False)
        if not sub.empty:
            r = sub.iloc[0]
            col = "#00838f"
            C.draw(r.tf, r.source_open_et,
                   f"{tag} rejection block ({r.tf})  dwick/ATR={r.dwick_atr:.2f} body/ATR={r.body_atr:.2f}\n"
                   f"zone [{r.zone_lower}, {r.zone_upper}]  valid through end",
                   zones=[(r.zone_lower, r.zone_upper, col, "wick zone")],
                   hlines=[(r.far_boundary, col, "far"), (r.near_boundary, "#555", "near")],
                   fname=f"rejblock_{direction}_example.png")
            made.append((f"{tag} rejection block", f"rejblock_{direction}_example.png", r))
    # exact-boundary-touch case
    et_case = rb[rb.exact_boundary_body_touch_et.notna()].copy()
    if not et_case.empty:
        et_case["t"] = pd.to_datetime(et_case.exact_boundary_body_touch_et, utc=True)
        r = et_case.sort_values("t").iloc[0]
        col = "#5d4037"
        C.draw(r.tf, r.source_open_et,
               f"exact-boundary body touch ({r.tf}, {r.direction})  zone [{r.zone_lower}, {r.zone_upper}]\n"
               f"body touches boundary WITHOUT entering; touch {r.exact_boundary_body_touch_et}",
               zones=[(r.zone_lower, r.zone_upper, col, "wick zone")],
               vlines=[(pd.to_datetime(r.exact_boundary_body_touch_et, utc=True).tz_convert("America/New_York"),
                        "#000", "boundary touch")],
               fname="rejblock_exact_boundary_touch.png")
        made.append(("exact-boundary body touch", "rejblock_exact_boundary_touch.png", r))
    return made


def img(rel_dir, fname):
    return f"![{fname}]({rel_dir}/{fname})"


def main():
    made = extra_charts()
    ex = json.load(open(os.path.join(OUT, "examples", "audit_examples.json")))
    by_kind = {}
    for e in ex:
        by_kind.setdefault(e["kind"], []).append(e)

    L = []
    L.append("# Phase 1B — Compact Audit Pack\n")
    L.append("Deterministic primitive examples + observational candidate setups. "
             "All examples are chosen chronologically or by a structural (ATR-normalized) "
             "metric — never by outcome. Charts are in `charts/` and `candidate_setups/`.\n")

    def section(title, items):
        L.append(f"\n## {title}\n")
        for label, fn in items:
            L.append(f"**{label}** — `{fn}`\n\n{img('charts', fn)}\n")

    # FVG
    fvg_items = []
    for e in by_kind.get("first_bull_fvg", []) + by_kind.get("first_bear_fvg", []):
        fvg_items.append((f"first {e['record']['direction']} FVG {e['tf']} ({e['record']['id']})", e["chart"]))
    section("Fair Value Gaps (bullish & bearish, per timeframe)", fvg_items[:6])

    # iFVG
    section("Inverse FVG conversions (bullish & bearish)",
            [(e["kind"], e["chart"]) for e in by_kind.get("first_ifvg_to_bull", []) + by_kind.get("first_ifvg_to_bear", [])])

    # rejection blocks (explicit bull/bear + top valid + invalidations + exact touch)
    rej_items = [(lbl, fn) for lbl, fn, _ in made if "rejection" in lbl or "boundary" in lbl]
    rej_items += [(f"top valid rejection #{e['rank']} {e['tf']}", e["chart"]) for e in by_kind.get("rejection_block_topvalid", [])]
    rej_items += [("first invalidation by body overlap", e["chart"]) for e in by_kind.get("rejection_block_first_body_overlap", [])]
    rej_items += [("first invalidation by complete wick traversal", e["chart"]) for e in by_kind.get("rejection_block_first_wick_traversal_beyond_far", [])]
    section("Rejection blocks (bull/bear, invalidation & exact-boundary touch)", rej_items)

    # liquidity
    section("Liquidity references (swept & unswept, each source)",
            [(f"{e['kind']} {e['source']}", e["chart"]) for e in by_kind.get("liquidity_swept", []) + by_kind.get("liquidity_unswept", [])])

    # displacement
    section("Displacement (good / mixed / bad, several timeframes)",
            [(e["kind"], e["chart"]) for e in by_kind.get("displacement_high", []) + by_kind.get("displacement_middle", []) + by_kind.get("displacement_low", [])])

    # candidate setups
    L.append("\n## Observational candidate setups (frozen grammar CG-1)\n")
    L.append("_Observational only — not evidence of edge. Selected chronologically, "
             "not by outcome; losers kept; nothing altered after the outcome was seen._\n")
    sp = os.path.join(CS, "candidate_setups.csv")
    if os.path.exists(sp):
        s = pd.read_csv(sp)
        L.append("\n| ID | tf | dir | trigger (ET) | swept | entry | stop | target | outcome |")
        L.append("|---|---|---|---|---|--:|--:|--:|---|")
        for _, r in s.iterrows():
            L.append(f"| {r.candidate_id} | {r.tf} | {r.direction} | {str(r.trigger_ts_et)[:16]} | "
                     f"{r.swept_source} | {r.entry} | {r.structural_stop} | {r.structural_target} | **{r.outcome}** |")
        L.append("")
        for _, r in s.iterrows():
            L.append(f"\n**{r.candidate_id}** [{r.direction}] — trigger {str(r.trigger_ts_et)[:16]}, "
                     f"outcome **{r.outcome}**\n\n"
                     f"- trigger: sweep of `{r.swept_source}` @ {r.swept_extreme}\n"
                     f"- context: {r.context_conditions}\n"
                     f"- entry {r.entry} · structural stop {r.structural_stop} · structural target {r.structural_target} · expiry E={r.expiry_bars_E} bars\n"
                     f"- primitives: {r.primitive_ids}\n\n{img('candidate_setups', r.candidate_id + '.png')}\n")

    with open(os.path.join(OUT, "AUDIT_PACK.md"), "w") as f:
        f.write("\n".join(L))
    print(f"audit pack written; extra charts: {[m[1] for m in made]}")


if __name__ == "__main__":
    main()

"""
Phase 1 deterministic human-audit examples + annotated charts.

Selection is deterministic (chronological / rank-based on STRUCTURAL metrics
only). No example is chosen because it "led to a winning move" -- outcomes are
never consulted. Provisional ranking metrics for rejection blocks and
displacement are declared explicitly and are for display ordering only; they do
NOT freeze any prominence/quality threshold.
"""
import json
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUT = os.path.join(os.path.dirname(__file__), "outputs")
LED = os.path.join(OUT, "ledgers")
CH = os.path.join(OUT, "charts")
EX = os.path.join(OUT, "examples")
os.makedirs(CH, exist_ok=True)
os.makedirs(EX, exist_ok=True)

TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "daily"]


def load_candles(tf):
    df = pd.read_csv(os.path.join(OUT, f"htf_candles_{tf}.csv"))
    df["bucket_open_et"] = pd.to_datetime(df["bucket_open_et"], utc=True).dt.tz_convert("America/New_York")
    return df.sort_values("bucket_open_et").reset_index(drop=True)


def _ts(x):
    return pd.to_datetime(x, utc=True).tz_convert("America/New_York")


def draw(tf, center_ts, title, zones=None, hlines=None, vlines=None,
         markers=None, fname="chart.png", pad=12):
    """Render a candlestick window centered on center_ts with annotations.

    zones:   list of (y_lo, y_hi, color, label)
    hlines:  list of (y, color, label)
    vlines:  list of (ts, color, label)
    markers: list of (ts, y, color, label)
    """
    cd = load_candles(tf)
    center_ts = _ts(center_ts)
    ci = (cd["bucket_open_et"] - center_ts).abs().idxmin()
    lo = max(0, ci - pad)
    hi = min(len(cd), ci + pad + 1)
    w = cd.iloc[lo:hi].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(13, 7))
    x = mdates.date2num(w["bucket_open_et"].dt.tz_localize(None))
    if len(x) > 1:
        width = (x[1] - x[0]) * 0.7
    else:
        width = 0.0005
    for xi, (_, r) in zip(x, w.iterrows()):
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([xi, xi], [r["low"], r["high"]], color=col, lw=0.8, zorder=2)
        ax.add_patch(plt.Rectangle((xi - width / 2, min(r["open"], r["close"])),
                                   width, max(abs(r["close"] - r["open"]), 1e-6),
                                   color=col, zorder=3))
    for z in (zones or []):
        y0, y1, c, lab = z
        ax.axhspan(y0, y1, color=c, alpha=0.20, zorder=1, label=lab)
    for hl in (hlines or []):
        y, c, lab = hl
        ax.axhline(y, color=c, ls="--", lw=1.1, zorder=4, label=lab)
    for vl in (vlines or []):
        ts, c, lab = vl
        xv = mdates.date2num(_ts(ts).tz_localize(None))
        ax.axvline(xv, color=c, ls=":", lw=1.2, zorder=4, label=lab)
    for mk in (markers or []):
        ts, y, c, lab = mk
        xv = mdates.date2num(_ts(ts).tz_localize(None))
        ax.scatter([xv], [y], color=c, s=70, zorder=6, edgecolor="black", label=lab)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    ax.set_title(title, fontsize=11)
    ax.grid(True, alpha=0.25)
    # de-dup legend
    h, l = ax.get_legend_handles_labels()
    seen = dict(zip(l, h))
    if seen:
        ax.legend(seen.values(), seen.keys(), fontsize=8, loc="best")
    fig.tight_layout()
    path = os.path.join(CH, fname)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def rec_to_dict(row):
    d = {}
    for k, v in row.items():
        if isinstance(v, (pd.Timestamp,)):
            d[k] = v.isoformat()
        elif pd.isna(v) if np.isscalar(v) else False:
            d[k] = None
        else:
            d[k] = v.item() if hasattr(v, "item") else v
    return d


def main():
    examples = []

    # ---- 1 & 2. first bullish / bearish FVG per timeframe ----
    for tf in TFS:
        fp = os.path.join(LED, f"fvg_{tf}.csv")
        f = pd.read_csv(fp)
        if f.empty:
            continue
        f["availability_et"] = pd.to_datetime(f["availability_et"], utc=True).dt.tz_convert("America/New_York")
        for direction in ("bull", "bear"):
            sub = f[f.direction == direction].sort_values("C_open_et")
            if sub.empty:
                continue
            r = sub.iloc[0]
            col = "#2e7d32" if direction == "bull" else "#c62828"
            zones = [(r.lower_boundary, r.upper_boundary, col, f"{direction} FVG zone")]
            markers = []
            if pd.notna(r.first_wick_entry_et):
                pass
            fn = f"fvg_{tf}_{direction}.png"
            draw(tf, r.C_open_et,
                 f"First {direction} FVG {tf}  |  {r.id}\navail {r.availability_et}  zone [{r.lower_boundary}, {r.upper_boundary}]",
                 zones=zones,
                 hlines=[(r.lower_boundary, col, "lower"), (r.upper_boundary, col, "upper")],
                 vlines=[(r.C_open_et, "#555", "C (avail)")],
                 fname=fn)
            examples.append({"kind": f"first_{direction}_fvg", "tf": tf,
                             "chart": fn, "record": rec_to_dict(r)})

    # ---- 3. first FVG->iFVG conversion in each direction (across TFs) ----
    frames = []
    for tf in TFS:
        p = os.path.join(LED, f"ifvg_{tf}.csv")
        d = pd.read_csv(p)
        if not d.empty:
            d["tf"] = tf
            frames.append(d)
    if frames:
        allif = pd.concat(frames, ignore_index=True)
        allif["conversion_et"] = pd.to_datetime(allif["conversion_et"], utc=True).dt.tz_convert("America/New_York")
        for ifd in ("bull", "bear"):
            sub = allif[allif.ifvg_direction == ifd].sort_values("conversion_et")
            if sub.empty:
                continue
            r = sub.iloc[0]
            col = "#6a1b9a"
            zones = [(r.source_lower, r.source_upper, col, "source FVG zone")]
            draw(r.tf, r.conversion_et,
                 f"First iFVG->{ifd}  |  {r.ifvg_id}\nsource {r.source_fvg_id}  conv {r.conversion_et}  close {r.conversion_close}",
                 zones=zones,
                 hlines=[(r.source_lower, col, "src lower"), (r.source_upper, col, "src upper")],
                 vlines=[(r.conversion_et, "#000", "conversion close")],
                 fname=f"ifvg_{ifd}.png", pad=14)
            examples.append({"kind": f"first_ifvg_to_{ifd}", "tf": r.tf,
                             "chart": f"ifvg_{ifd}.png", "record": rec_to_dict(r)})

    # ---- 4. liquidity: first swept & first still-unswept per source type ----
    liq = pd.read_csv(os.path.join(LED, "liquidity_references.csv"))
    liq["availability_et"] = pd.to_datetime(liq["availability_et"], utc=True).dt.tz_convert("America/New_York")
    for src, sub in liq.groupby("source"):
        sub = sub.sort_values("availability_et")
        swept = sub[sub.unswept_through_end == False]
        unswept = sub[sub.unswept_through_end == True]
        for tag, chunk in [("swept", swept), ("unswept", unswept)]:
            if chunk.empty:
                continue
            r = chunk.iloc[0]
            col = "#1565c0" if r.side == "high" else "#ef6c00"
            vlines = []
            if tag == "swept" and pd.notna(r.sweep_et):
                vlines = [(pd.to_datetime(r.sweep_et, utc=True).tz_convert("America/New_York"), "#000", "sweep")]
            # choose a fine timeframe to visualise the level
            draw("5m", r.availability_et,
                 f"Liquidity {src} ({r.side}) [{tag}]  extreme={r.extreme}\navail {r.availability_et}  sweep {r.sweep_et}",
                 hlines=[(r.extreme, col, f"{src}")],
                 vlines=vlines,
                 fname=f"liq_{src}_{tag}.png", pad=40)
            examples.append({"kind": f"liquidity_{tag}", "source": src,
                             "chart": f"liq_{src}_{tag}.png", "record": rec_to_dict(r)})

    # ---- 5. three highest-ranked VALID rejection-block candidates, 3 diff TFs ----
    # provisional display rank = dwick_range_ratio, restricted to still-valid.
    rb_frames = []
    for tf in TFS:
        d = pd.read_csv(os.path.join(LED, f"rejection_blocks_{tf}.csv"))
        if not d.empty:
            d["tf"] = tf
            rb_frames.append(d)
    rbc = pd.concat(rb_frames, ignore_index=True)
    valid = rbc[(rbc.still_valid_end_of_data == True) & rbc.dwick_range_ratio.notna()].copy()
    valid["rank_metric"] = valid.dwick_range_ratio
    valid = valid.sort_values("rank_metric", ascending=False)
    picked_tfs = set()
    top3 = []
    for _, r in valid.iterrows():
        if r.tf in picked_tfs:
            continue
        picked_tfs.add(r.tf)
        top3.append(r)
        if len(top3) == 3:
            break
    for k, r in enumerate(top3):
        col = "#00838f"
        draw(r.tf, r.source_open_et,
             f"Rejection-block candidate #{k+1} ({r.direction}) {r.tf}\nzone [{r.zone_lower}, {r.zone_upper}] dwick/range={r.dwick_range_ratio:.3f} p20={r.dwick_pctile_prev20}",
             zones=[(r.zone_lower, r.zone_upper, col, "wick zone")],
             hlines=[(r.far_boundary, col, "far"), (r.near_boundary, "#555", "near")],
             fname=f"rejblock_top{k+1}_{r.tf}.png")
        examples.append({"kind": "rejection_block_topvalid", "rank": k + 1, "tf": r.tf,
                         "rank_metric": "dwick_range_ratio", "chart": f"rejblock_top{k+1}_{r.tf}.png",
                         "record": rec_to_dict(r)})

    # first invalidated by body overlap; first by complete traversal (across TFs)
    rbc["availability_et"] = pd.to_datetime(rbc["availability_et"], utc=True).dt.tz_convert("America/New_York")
    for reason, fn in [("body_overlap", "rejblock_first_bodyoverlap.png"),
                       ("wick_traversal_beyond_far", "rejblock_first_traversal.png")]:
        sub = rbc[rbc.invalidation_reason == reason].copy()
        sub["invalidation_et"] = pd.to_datetime(sub["invalidation_et"], utc=True).dt.tz_convert("America/New_York")
        sub = sub.sort_values("invalidation_et")
        if sub.empty:
            continue
        r = sub.iloc[0]
        col = "#5d4037"
        draw(r.tf, r.source_open_et,
             f"First rejection-block invalidated by {reason} ({r.direction}) {r.tf}\nzone [{r.zone_lower}, {r.zone_upper}] invalid {r.invalidation_et}",
             zones=[(r.zone_lower, r.zone_upper, col, "wick zone")],
             vlines=[(r.invalidation_et, "#000", reason)],
             fname=fn)
        examples.append({"kind": f"rejection_block_first_{reason}", "tf": r.tf,
                         "chart": fn, "record": rec_to_dict(r)})

    # ---- 6. displacement high / middle / low examples ----
    dfr = []
    for tf in TFS:
        d = pd.read_csv(os.path.join(LED, f"displacement_{tf}.csv"))
        if not d.empty:
            d["tf"] = tf
            dfr.append(d)
    disp = pd.concat(dfr, ignore_index=True)
    # provisional display quality score (structural only), len==3 legs w/ full pctile history
    cand = disp[(disp.leg_len == 3) & disp.median_body_pctile_prev20.notna() &
                disp.path_efficiency.notna()].copy()
    cand["qual"] = (cand.path_efficiency * cand.prop_bodies_aligned *
                    (cand.median_body_pctile_prev20 / 100.0))
    cand = cand.sort_values("qual").reset_index(drop=True)
    picks = {"low": cand.iloc[0], "middle": cand.iloc[len(cand) // 2], "high": cand.iloc[-1]}
    for tag, r in picks.items():
        col = "#283593"
        draw(r.tf, r.end_open_et,
             f"Displacement [{tag}] {r.direction} len3 {r.tf}  qual={r.qual:.3f}\nnet={r.net_directional_move:.2f} eff={r.path_efficiency:.3f} p20={r.median_body_pctile_prev20:.1f} FVG={r.created_fvg}",
             vlines=[(r.start_open_et, "#0288d1", "leg start"), (r.end_open_et, "#000", "leg end")],
             fname=f"disp_{tag}.png")
        examples.append({"kind": f"displacement_{tag}", "tf": r.tf,
                         "quality_metric": "path_eff*prop_aligned*p20", "chart": f"disp_{tag}.png",
                         "record": rec_to_dict(r)})

    with open(os.path.join(EX, "audit_examples.json"), "w") as fout:
        json.dump(examples, fout, indent=2, default=str)
    print(f"generated {len(examples)} audit examples")
    for e in examples:
        print(" -", e["kind"], e.get("tf", e.get("source", "")), "->", e["chart"])
    return examples


if __name__ == "__main__":
    main()

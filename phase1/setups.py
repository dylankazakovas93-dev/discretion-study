"""
Phase 1B: observational candidate-setup occurrences under a FROZEN grammar.

These are OBSERVATIONS, not evidence of edge. The grammar, entry, structural
stop, structural target and expiry are all fixed BEFORE any outcome is seen.
Selection is chronological (first N valid triggers) -- never by outcome. Losers
are kept. Nothing is optimized, ranked by profitability, or altered after the
outcome is observed. Outcomes are reported only.

FROZEN GRAMMAR  CG-1  "liquidity sweep -> opposite displacement FVG reversal"
  * TRIGGER: a completed tf candle T strictly sweeps an active frozen liquidity
    level L (first-ever penetration of L occurs within T's interval).
  * REVERSAL: within R=3 completed candles after T, an OPPOSITE-direction FVG F
    forms (bearish after a high sweep -> SHORT; bullish after a low sweep -> LONG).
    The FVG is the displacement signal (a gap requires a displacement leg).
  * ENTRY (retest): SHORT = F.lower_boundary (proximal edge revisited from below);
    LONG = F.upper_boundary. Filled when a later candle trades to it, within
    E=20 candles of F availability, else EXPIRED (no fill -> incomplete).
  * STRUCTURAL STOP: the swept extreme L (beyond the run) -- SHORT above, LONG below.
  * STRUCTURAL TARGET: the nearest active opposite-side frozen liquidity level in
    the profit direction. If none exists -> incomplete.
  * EXPIRY: resolve within H=60 candles after fill; else incomplete.
  * OUTCOME (observed only): first candle to touch target -> win; stop -> loss;
    a candle whose range spans BOTH -> ambiguous (intrabar order unknown); neither
    by horizon/data end -> incomplete.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import primitives as P

TZ = "America/New_York"
DISC_START = pd.Timestamp("2026-07-06 00:00", tz=TZ)
DISC_END = pd.Timestamp("2026-07-11 00:00", tz=TZ)
R_BARS, E_BARS, H_BARS = 5, 20, 60
OUT = os.path.join(os.path.dirname(__file__), "outputs")
CS = os.path.join(OUT, "candidate_setups")
os.makedirs(CS, exist_ok=True)

LIQ_SOURCES = ["prev_rth_high", "prev_rth_low", "overnight_high", "overnight_low",
               "candle_0900_high", "candle_0900_low", "candle_0930_high",
               "candle_0930_low", "candle_1000_high", "candle_1000_low"]


def build_liquidity_pool(et: pd.DataFrame, disc_abs_seg: int) -> pd.DataFrame:
    """Frozen liquidity references for the discovery ABSOLUTE segment (post-roll
    NQU6, incl. pre-July initial state). Each carries extreme, side, availability
    and first-ever sweep timestamp (scanned over the segment's 1m bars)."""
    e = et[et["segment_id"] == disc_abs_seg].sort_values("ts_open_et").reset_index(drop=True)
    hi = e["high"].to_numpy(float); lo = e["low"].to_numpy(float)
    tclose = e["ts_close_et"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()  # datetime64
    rows = []

    def add(extreme, side, avail, source, gday):
        # first strict penetration strictly after availability
        av = np.datetime64(pd.Timestamp(avail).tz_convert("UTC").tz_localize(None))
        start = int(np.searchsorted(tclose, av))
        sweep = None
        for j in range(start, len(hi)):
            if tclose[j] <= av:
                continue
            if (side == "high" and hi[j] > extreme) or (side == "low" and lo[j] < extreme):
                sweep = pd.Timestamp(tclose[j]).tz_localize("UTC").tz_convert(TZ)
                break
        rows.append({"source": source, "side": side, "extreme": float(extreme),
                     "availability_et": pd.Timestamp(avail), "sweep_et": sweep,
                     "session_globex_day": gday})

    for gday, g in e.groupby("globex_day", sort=True):
        rth = g[g["session"] == "rth"]
        if len(rth):
            add(rth["high"].max(), "high", rth["ts_close_et"].max(), "prev_rth_high", gday)
            add(rth["low"].min(), "low", rth["ts_close_et"].max(), "prev_rth_low", gday)
        on = g[g["session"] == "overnight"]
        if len(on):
            add(on["high"].max(), "high", on["ts_close_et"].max(), "overnight_high", gday)
            add(on["low"].min(), "low", on["ts_close_et"].max(), "overnight_low", gday)
        for hhmm, lab in [(540, "0900"), (570, "0930"), (600, "1000")]:
            bar = g[g["minutes_of_day"] == hhmm]
            if len(bar):
                b = bar.iloc[0]
                add(b["high"], "high", b["ts_close_et"], f"candle_{lab}_high", gday)
                add(b["low"], "low", b["ts_close_et"], f"candle_{lab}_low", gday)
    return pd.DataFrame(rows)


def _in_disc(ts):
    ts = pd.Timestamp(ts)
    return DISC_START <= ts < DISC_END


def observe(tf: str, cd: P.Candles, fvgs: pd.DataFrame, liq: pd.DataFrame) -> list:
    """Scan the tf for CG-1 triggers during July; return setup dicts (chrono)."""
    setups = []
    if fvgs.empty:
        return setups
    fv = fvgs.copy()
    fv_by_dir = {d: fv[fv.direction == d].sort_values("C_index") for d in ("bull", "bear")}
    to_open = cd.t_open
    # map C_index -> fvg rows for speed
    for d in ("bull", "bear"):
        fv_by_dir[d] = fv_by_dir[d].set_index("C_index", drop=False)
    liq = liq.copy()
    liq["avail_utc"] = pd.to_datetime(liq["availability_et"], utc=True)
    liq["sweep_utc"] = pd.to_datetime(liq["sweep_et"], utc=True)

    for i in range(cd.n):
        Topen = pd.Timestamp(to_open[i])
        if not _in_disc(cd.t_avail[i]):
            continue
        t0 = pd.Timestamp(cd.t_open_utc[i]).tz_localize("UTC")
        t1 = pd.Timestamp(cd.t_avail_utc[i]).tz_localize("UTC")
        # levels first-swept within this candle's interval, available beforehand
        swept = liq[(liq.avail_utc <= t0) & (liq.sweep_utc > t0) & (liq.sweep_utc <= t1)]
        if swept.empty:
            continue
        for side in ("high", "low"):
            s = swept[swept.side == side]
            if s.empty:
                continue
            # take the level actually reached (max high-side / min low-side)
            L = s.iloc[s.extreme.values.argmax()] if side == "high" else s.iloc[s.extreme.values.argmin()]
            direction = "short" if side == "high" else "long"
            fdir = "bear" if side == "high" else "bull"
            cand_fvgs = fv_by_dir[fdir]
            F = None
            for cidx in range(i + 1, min(i + 1 + R_BARS, cd.n)):
                if cidx in cand_fvgs.index:
                    F = cand_fvgs.loc[cidx]
                    if isinstance(F, pd.DataFrame):
                        F = F.iloc[0]
                    break
            if F is None:
                continue
            Cidx = int(F["C_index"])
            f_avail_idx = Cidx  # F available at end of candle Cidx
            if direction == "short":
                entry = float(F["lower_boundary"]); stop = float(L["extreme"])
                if not (stop > entry):        # coherent geometry: stop above entry
                    continue
                tgts = liq[(liq.side == "low") & (liq.avail_utc <= t1) & (liq.extreme < entry)]
                target = float(tgts.extreme.max()) if not tgts.empty else np.nan
            else:
                entry = float(F["upper_boundary"]); stop = float(L["extreme"])
                if not (stop < entry):        # coherent geometry: stop below entry
                    continue
                tgts = liq[(liq.side == "high") & (liq.avail_utc <= t1) & (liq.extreme > entry)]
                target = float(tgts.extreme.min()) if not tgts.empty else np.nan

            # entry fill scan (within E bars of F availability)
            fill_idx = None
            for j in range(f_avail_idx + 1, min(f_avail_idx + 1 + E_BARS, cd.n)):
                if direction == "short" and cd.h[j] >= entry:
                    fill_idx = j; break
                if direction == "long" and cd.l[j] <= entry:
                    fill_idx = j; break
            outcome, res_idx = "incomplete", None
            if fill_idx is None:
                outcome = "incomplete"  # never filled -> no trade
            elif np.isnan(target):
                outcome = "incomplete"  # no structural target
            else:
                for j in range(fill_idx, min(fill_idx + 1 + H_BARS, cd.n)):
                    hj, lj = cd.h[j], cd.l[j]
                    if direction == "short":
                        hit_t = lj <= target; hit_s = hj >= stop
                    else:
                        hit_t = hj >= target; hit_s = lj <= stop
                    if hit_t and hit_s:
                        outcome, res_idx = "ambiguous", j; break
                    if hit_t:
                        outcome, res_idx = "win", j; break
                    if hit_s:
                        outcome, res_idx = "loss", j; break

            cid = f"CG1-{tf}-{Topen.strftime('%Y%m%dT%H%M')}-{direction[0].upper()}"
            ctx = [f"swept:{L['source']}",
                   f"session:{'RTH' if 9*60+30 <= Topen.hour*60+Topen.minute < 16*60 else 'ONX'}",
                   f"fvg_width_atr:{round(float(F['fvg_width_atr']),3) if pd.notna(F['fvg_width_atr']) else 'na'}"]
            _ = None
            setups.append({
                "candidate_id": cid, "grammar": "CG-1", "tf": tf, "direction": direction,
                "trigger_ts_et": Topen, "trigger_candle_avail_et": pd.Timestamp(cd.t_avail[i]),
                "swept_source": L["source"], "swept_extreme": float(L["extreme"]),
                "swept_sweep_et": L["sweep_et"],
                "fvg_id": F["id"], "fvg_lower": float(F["lower_boundary"]),
                "fvg_upper": float(F["upper_boundary"]), "fvg_avail_et": F["availability_et"],
                "displacement_leg": f"{pd.Timestamp(cd.t_open[Cidx-2])}..{pd.Timestamp(cd.t_open[Cidx])}",
                "entry": entry, "structural_stop": stop, "structural_target": target,
                "entry_fill_et": pd.Timestamp(cd.t_open[fill_idx]) if fill_idx is not None else None,
                "expiry_bars_E": E_BARS, "resolve_horizon_H": H_BARS,
                "resolution_et": pd.Timestamp(cd.t_open[res_idx]) if res_idx is not None else None,
                "outcome": outcome,
                "context_conditions": " | ".join(ctx),
                "primitive_ids": f"LIQ:{L['source']}@{L['extreme']} ; FVG:{F['id']} ; DISP:{fdir}-leg->C{Cidx}",
                "trigger_index": i, "C_index": Cidx,
            })
    return setups


def _load_candles(tf):
    df = pd.read_csv(os.path.join(OUT, f"htf_candles_{tf}.csv"))
    df["bucket_open_et"] = pd.to_datetime(df["bucket_open_et"], utc=True).dt.tz_convert(TZ)
    return df.sort_values("bucket_open_et").reset_index(drop=True)


def chart_all(setups: list):
    for s in setups:
        cd = _load_candles(s["tf"])
        center = pd.Timestamp(s["trigger_ts_et"])
        ci = (cd["bucket_open_et"] - center).abs().idxmin()
        w = cd.iloc[max(0, ci - 10):min(len(cd), ci + 30)].reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(13, 7))
        x = mdates.date2num(w["bucket_open_et"].dt.tz_localize(None))
        width = (x[1] - x[0]) * 0.7 if len(x) > 1 else 5e-4
        for xi, (_, r) in zip(x, w.iterrows()):
            up = r["close"] >= r["open"]
            col = "#26a69a" if up else "#ef5350"
            ax.plot([xi, xi], [r["low"], r["high"]], color=col, lw=0.8, zorder=2)
            ax.add_patch(plt.Rectangle((xi - width / 2, min(r["open"], r["close"])),
                                       width, max(abs(r["close"] - r["open"]), 1e-6), color=col, zorder=3))
        col = "#c62828" if s["direction"] == "short" else "#2e7d32"
        ax.axhspan(s["fvg_lower"], s["fvg_upper"], color=col, alpha=0.18, zorder=1, label="FVG")
        ax.axhline(s["entry"], color="#1565c0", ls="-", lw=1.3, label="entry")
        ax.axhline(s["structural_stop"], color="#b71c1c", ls="--", lw=1.2, label="structural stop")
        if pd.notna(s["structural_target"]):
            ax.axhline(s["structural_target"], color="#1b5e20", ls="--", lw=1.2, label="structural target")
        ax.axhline(s["swept_extreme"], color="#6a1b9a", ls=":", lw=1.4, label=f"swept {s['swept_source']}")
        for key, cc, lab in [("trigger_ts_et", "#555", "trigger"),
                             ("entry_fill_et", "#1565c0", "fill"),
                             ("resolution_et", "#000", "resolve")]:
            if s.get(key) is not None and pd.notna(s.get(key)):
                xv = mdates.date2num(pd.Timestamp(s[key]).tz_convert(TZ).tz_localize(None))
                ax.axvline(xv, color=cc, ls=":", lw=1.1, label=lab)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
        ax.set_title(f"{s['candidate_id']}  [{s['direction']}]  outcome={s['outcome']}\n"
                     f"{s['context_conditions']}", fontsize=10)
        ax.grid(True, alpha=0.25)
        h, l = ax.get_legend_handles_labels()
        ax.legend(dict(zip(l, h)).values(), dict(zip(l, h)).keys(), fontsize=8, loc="best")
        fig.tight_layout()
        fig.savefig(os.path.join(CS, s["candidate_id"] + ".png"), dpi=110)
        plt.close(fig)

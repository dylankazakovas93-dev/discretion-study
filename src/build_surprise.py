"""Standardize surprises across series so they can be pooled.

Series live on incompatible scales: CPI/PPI/PCE in percentage points, EPS in dollars.
Each surprise is divided by the trailing standard deviation of that series' OWN past
surprises, so a "1 sigma CPI miss" and a "1 sigma EPS beat" are comparable magnitudes.

The scaling window is strictly trailing (shift(1)) -- the sigma used for an event is
computed only from surprises already released before it. Nothing about an event informs
its own standardization.

Deadband (per Dylan): macro surprises below 0.1pp are treated as no-surprise; EPS
surprises below 1% of consensus are treated as no-surprise.

Direction convention: the sign of the expected NQ response is a PRIOR, not a fit.
Hot inflation -> higher expected rates -> negative for equities. EPS beat -> positive.
The unsigned relationship is reported alongside so the prior can be falsified.
"""
import pandas as pd, numpy as np

MACRO_FLOOR_PP = 0.1     # percentage points
EPS_FLOOR_REL  = 1.0     # percent of consensus
WIN            = 12      # trailing window for sigma (months / quarters)

LABOUR_FLOOR = {"US_NFP": 25.0, "US_UNEMP_RATE": 0.1}   # 25k jobs, 0.1pp on the rate
# Rates channel, consistent with the inflation prior: strong labour -> hawkish -> bearish equities.
# NOTE this is contested. A growth channel argues the opposite (strong labour -> better earnings).
# Labour "against the print" is therefore a weaker construct than inflation "against the print".
LABOUR_SIGN = {"US_NFP": -1, "US_UNEMP_RATE": +1}

def build():
    m = pd.read_csv("data/macro/events.csv")
    e = pd.read_csv("data/macro/earnings.csv")
    e = e[e.series != "MSFT_EPS"]                       # timestamp unresolved

    m = m[m.surprise_abs.notna()].copy()
    lab = m.series.isin(LABOUR_FLOOR)
    m["family"] = np.where(lab, "labour", "inflation")
    m["deadband_pass"] = np.where(
        lab, m.surprise_abs.abs() >= m.series.map(LABOUR_FLOOR).fillna(np.inf),
        m.surprise_abs.abs() >= MACRO_FLOOR_PP)
    m["prior_sign"] = np.where(lab, m.series.map(LABOUR_SIGN).fillna(-1), -1)

    e = e[e.surprise_abs.notna() & e.consensus.notna() & (e.consensus != 0)].copy()
    e["family"] = "eps"
    e["deadband_pass"] = e.surprise_pct.abs() >= EPS_FLOOR_REL
    e["prior_sign"] = +1                                # beat -> bullish

    cols = ["event_id","series","family","release_ts_utc","release_date_et",
            "surprise_abs","deadband_pass","prior_sign","notes"]
    df = pd.concat([m[cols], e[cols]], ignore_index=True)
    df["release_ts_utc"] = pd.to_datetime(df.release_ts_utc, utc=True, format="ISO8601")
    df = df.sort_values("release_ts_utc").reset_index(drop=True)

    # trailing sigma per series -- shift(1) so an event never scales itself
    g = df.groupby("series", group_keys=False)
    df["sigma"] = g.surprise_abs.apply(
        lambda s: s.rolling(WIN, min_periods=6).std().shift(1))
    df["surprise_z"] = df.surprise_abs / df.sigma
    # signed by the economic prior: positive z == expected NQ tailwind
    df["z_signed"] = df.surprise_z * df.prior_sign
    df.to_csv("data/macro/surprises.csv", index=False)
    return df

if __name__ == "__main__":
    df = build()
    print(f"rows {len(df)} | with z {df.surprise_z.notna().sum()} "
          f"(NaN = first {WIN//2}+ events per series, no trailing history yet)")
    print(f"\ndeadband pass rate: {df.deadband_pass.mean():.1%}")
    print(df.groupby("family").agg(n=("surprise_z","size"), with_z=("surprise_z","count"),
                                   pass_db=("deadband_pass","mean"),
                                   sigma_med=("sigma","median")).round(3).to_string())
    print("\ntrailing sigma by series (median):")
    print(df.groupby("series").sigma.median().round(4).to_string())
    print("\n|z| distribution (events with z, deadband passed):")
    k = df[df.surprise_z.notna() & df.deadband_pass]
    print(k.surprise_z.abs().describe(percentiles=[.5,.75,.9,.95]).round(2).to_string())

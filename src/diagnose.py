"""Where do the events go, and do release time / clustering / company matter?

Dylan asked why 23 companies over 3.5 years yields ~100 tradeable sessions. This walks
the funnel. Then it tests the two features that cost no new data and are causal:
release hour (EDGAR gives the exact minute) and how many companies report that evening.
"""
import pandas as pd, numpy as np, glob, zstandard, io, os
DEV = {2020, 2022, 2024, 2026}
E = pd.read_csv("data/macro/earnings.csv")
E["ts"] = pd.to_datetime(E.release_ts_utc, utc=True, format="ISO8601")
E["et"] = E.ts.dt.tz_convert("America/New_York")
print("=== FUNNEL: why ~100 sessions? ===")
n=len(E); print(f"  all earnings rows collected            {n}")
E=E[E.series!="MSFT_EPS"]; print(f"  minus MSFT (timestamp unresolved)      {len(E)}")
E=E[E.surprise_abs.notna()&E.consensus.notna()]; print(f"  with usable actual+consensus           {len(E)}")
E=E[E.et.dt.hour>=16]; print(f"  post-market only                       {len(E)}")
d=E[E.et.dt.year.isin(DEV)]; print(f"  in DEV years (2020/22/24/26-partial)   {len(d)}")
print(f"  distinct evenings                      {d.et.dt.date.nunique()}   <- one NQ trade each")
print(f"  companies reporting per evening: mean {len(d)/d.et.dt.date.nunique():.1f}")
print(f"\n  the holdout years hold another         {len(E[E.et.dt.year.isin({2021,2023,2025})])} rows")

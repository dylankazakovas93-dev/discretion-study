# DECISIONS

Locked choices. Each entry records what was decided, by whom, and the consequence.

| # | Decision | Set by | Consequence |
|---|---|---|---|
| 1 | Dev years = 2018, 2020, 2022, 2024, 2026(→Jun). 2019/2021/2023/2025 reserved, not opened. | Dylan | Holdout carries ~1/4 the large-repricing days of dev. Confirmatory power on the 2.5%+ bucket will be weak. Holdout split option (a)/(b)/(c) still UNRESOLVED. |
| 2 | Front month = highest-volume outright per session. | Dylan | Uses full-session volume, so contract choice is not causal at session open. Accepted; recorded in KNOWN_LIMITATIONS. |
| 3 | Exit reference = 16:00 ET cash close. | Dylan | Settle (17:00) available as robustness only. |
| 4 | Magnitude buckets in % of price (primary); vol-normalized secondary. | Dylan | 1% in 2020 and 1% in 2024 are different events; regime attribution mandatory. |
| 5 | Decision points tested: Globex open AND 09:30 cash open. | Dylan | Cash open expected noisier (options flow / opening auction). |
| 6 | Oracle null p=0.5 included alongside 0/20/40/60/80. | Claude, agreed | 0/20/40 are sign-symmetry controls, not nulls. |
| 7 | Horizon is a parameter (1/2/3 sessions), not fixed 1 day. | Dylan | Catalysts land while market is closed; repricing may span sessions. |
| 8 | Macro consensus: proceed on actual-vs-previous as the floor test. | Dylan | A NULL result is uninformative about Dylan's consensus-aware read. Only a POSITIVE result is interpretable. Consensus collected anyway where free. |
| 9 | Event set: CPI, Core CPI, PPI, PCE, Core PCE, Mag 7 EPS, plus <=1 discrete shock per 2 months. | Dylan | ~310 events expected across dev years. |
| 10 | Release timestamp = release date + 08:30 ET (BLS/BEA convention). | Claude, stated | Time is NOT in the source table. Shutdown/holiday exceptions must be verified per-year, not assumed. |

## UNRESOLVED

- Holdout split: option (a) 1-2.5% as confirmatory bucket / (b) chronological / (c) accept underpowered.
- Deadband for macro surprise. Dylan's "+-1%" is well-defined for EPS, undefined for macro prints
  (1% of a 3.0% CPI print = 0.03pp, which filters nothing; 1 percentage point filters everything).
  Proposed: +-1% relative for EPS; surprise z-score vs trailing surprise distribution with a 0.1pp
  floor for macro. NOT adopted.
- API keys needed: Alpha Vantage (Mag 7 EPS consensus), BEA (PCE), FRED/ALFRED (as-printed vintages).

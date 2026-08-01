# KNOWN LIMITATIONS

## Data

1. **Front-month selection is not causal.** Highest-volume outright per session, chosen using the
   whole session's volume. Dylan's call. Affects roll-week sessions most.
2. **Holdout peek (disclosed).** Before the dev/holdout split was set, year-by-year counts of
   |RTH move| buckets were computed across all years 2018-2026, including reserved years. Scope:
   marginal |return| counts only. No path, execution, oracle or event results touched the holdout.
3. **Databento GLBX.MDP3 ohlcv-1m**, NQ.FUT parent, 2018-01-01 -> 2026-06-07. Calendar spreads
   (symbols containing "-") excluded. Price data ends 2026-06-07, so any event after that date is
   out of window.

## Macro event data

4. **CPI table covers 2020-06 onward only.** Dev year **2018 is entirely missing**, and 2020 is
   missing Jan-May. Must be back-filled before the 2018 dev year can be used.
5. **Nov + Dec 2025 CPI releases absent** (81-day gap, 2025-10-24 -> 2026-01-13). Consistent with
   the 2025 federal shutdown disrupting BLS publication, but NOT yet independently verified.
6. **Consensus is survey data, not government data.** BLS/BEA/FRED do not publish it and never
   will. Forex Factory (403), Investing.com (403), MarketWatch (401) and Yahoo (401) all block
   automated access from this environment. Consensus arrives either via Dylan's manual export or
   via the Cleveland Fed nowcast (CPI / Core CPI / PCE / Core PCE); **PPI has no free estimate source**.
7. **Cleveland Fed nowcast != street consensus.** It is a model nowcast, not a survey of bank
   economists. More reproducible, but not the number the market was positioned against.
8. **Release times are a convention, not observed data.** 08:30 ET attached from BLS/BEA practice.

## Statistical

9. **~45 exploratory bucket tests were run before RUN_REGISTRY.csv existed.** They are recorded
   retrospectively as run_id EXP-0001..0003 with the specific counts noted. Any DSR computed later
   must treat these as spent trials.
10. All exploratory results to date are **no-stop, no-cost, exit-at-close**. Costs (~1 tick + commission)
    are roughly 10% of the observed per-day means.

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

11. **The event study is power-starved on any single series.** Under the alternating-year split with
    the 2020-06-10 start, usable CPI releases are: DEV 36 (2020:7, 2022:12, 2024:12, 2026:5), of which
    25 carry a non-zero surprise; HOLDOUT 34 (2021:12, 2023:12, 2025:10), 21 non-zero. Thirty-six
    events cannot resolve anything but a very large effect. No single series will be sufficient --
    the design has to pool CPI/PPI/PCE/earnings into one event panel with surprises standardized
    across series so they are commensurable.
12. **2019 reassigned from holdout to engineering use** (decision 11). It contains no in-scope events,
    so confirmatory contamination risk is low, but it is no longer untouched price data.

### Series-specific

13. **PPI / Core PPI / Core PCE `previous` columns are REVISED vintages, not first prints.**
    Chain validation (previous[i] == actual[i+1]) breaks on 34/72 PPI rows, 32 Core PPI, 20 Core PCE
    -- but 0/72 CPI rows. This is not a parse error. Verified against BLS WPSFD4: mean
    |FF first-print - BLS current| = 0.167pp vs |FF later-vintage - BLS current| = 0.126pp, i.e. the
    `previous` column sits systematically closer to today's revised figure. BLS revises PPI monthly
    and BEA revises PCE monthly, whereas CPI seasonal factors are revised only annually -- which is
    exactly the observed pattern. CONSEQUENCE: actual-minus-previous for PPI/PCE conflates the true
    m/m change with the revision to the prior month. Use actual-minus-consensus for these series.
14. **Core CPI and headline PCE were never supplied.** Core CPI paste was a duplicate of CPI.
    For event-DAY purposes this costs nothing (Core CPI prints the same minute as CPI, headline PCE
    the same minute as Core PCE), but the surprise magnitudes for those two series are unavailable.
15. **No free consensus source exists for PPI.** The FF paste is the only estimate we will get.
16. **Shutdown gaps:** CPI 2025-10-24 -> 2026-01-13; PPI 2025-09-10 -> 2025-11-25 -> 2026-01-14;
    Core PCE 2025-09-26 -> 2025-12-05 -> 2026-01-22. Catch-up releases put two reference months on
    one date (PPI and Core PPI on 2026-01-14, Core PCE on 2026-01-22); the second of each pair has
    no consensus. Consistent with the 2025 federal shutdown but NOT independently verified.

### Earnings

17. **194 Item-2.02 8-Ks collected, but not all are earnings.** Per-symbol: AAPL 24, AMZN 24,
    META 24 (all post-market, clean); GOOGL 25 and NVDA 25 (one extra each); **TSLA 48** -- roughly
    half are pre-market vehicle production/delivery reports, which are genuine repricing events but
    are not EPS; **MSFT 24, all classified intraday** (acceptance ~12:00 ET), which contradicts
    MSFT's known post-close reporting. The MSFT timestamps are ANOMALOUS AND UNRESOLVED and must not
    be used until explained. De-duplication requires cross-referencing Alpha Vantage `reportedDate`.
18. **EPS actual and consensus are absent.** Alpha Vantage rejects the demo key for all Mag 7
    symbols; a free API key is required.

### Discrete events

19. **Not auto-derivable.** Federal Register returns 113 'tariff' and 546 'national emergency'
    presidential documents in the window, overwhelmingly routine (aluminium adjustments, emergency
    continuations). Selecting ~27 genuinely market-moving shocks is a curation judgment, not a query.
    Further, FR carries signing and publication DATES, which lag the market-moving announcement
    (speech, social post, wire) by hours to days. No discrete events have been ingested.

## Statistical

9. **~45 exploratory bucket tests were run before RUN_REGISTRY.csv existed.** They are recorded
   retrospectively as run_id EXP-0001..0003 with the specific counts noted. Any DSR computed later
   must treat these as spent trials.
10. All exploratory results to date are **no-stop, no-cost, exit-at-close**. Costs (~1 tick + commission)
    are roughly 10% of the observed per-day means.

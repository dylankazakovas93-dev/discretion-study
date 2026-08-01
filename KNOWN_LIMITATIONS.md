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
14. **Headline PCE unavailable** (Dylan could not retrieve it). Core CPI has since been supplied and
    ingested with 0 chain breaks, matching CPI and confirming the annual-vs-monthly revision pattern
    in limitation 13. Headline PCE prints the same minute as Core PCE, so no event day is lost; only
    that series' surprise magnitude is missing.
15. **No free consensus source exists for PPI.** The FF paste is the only estimate we will get.
16. **Shutdown gaps:** CPI 2025-10-24 -> 2026-01-13; PPI 2025-09-10 -> 2025-11-25 -> 2026-01-14;
    Core PCE 2025-09-26 -> 2025-12-05 -> 2026-01-22. Catch-up releases put two reference months on
    one date (PPI and Core PPI on 2026-01-14, Core PCE on 2026-01-22); the second of each pair has
    no consensus. Consistent with the 2025 federal shutdown but NOT independently verified.

### Earnings

17. **RESOLVED by AV/EDGAR merge.** Matching Alpha Vantage `reportedDate` against Item-2.02 8-Ks
    separates earnings from non-earnings disclosures cleanly: every Mag 7 name matched 24/24 quarters,
    leaving TSLA's 24 vehicle delivery reports and one stray filing each for GOOGL and NVDA as
    unmatched non-earnings 8-Ks. Final panel: **168 earnings rows, all with consensus and an exact
    disclosure timestamp.** Superseded note follows.
17b. *(superseded)* **194 Item-2.02 8-Ks collected, but not all are earnings.** Per-symbol: AAPL 24, AMZN 24,
    META 24 (all post-market, clean); GOOGL 25 and NVDA 25 (one extra each); **TSLA 48** -- roughly
    half are pre-market vehicle production/delivery reports, which are genuine repricing events but
    are not EPS; **MSFT 24, all classified intraday** (acceptance ~12:00 ET), which contradicts
    MSFT's known post-close reporting.
18a. **RESOLVED.** EDGAR's filing index page `Accepted` field is Eastern and authoritative;
    data.sec.gov's `acceptanceDateTime` appends "Z" but for a subset of filers the digits are
    already Eastern. Confirmed against the tape: MSFT earnings 8-K dates show 1.72x NQ volume at
    16:04 ET versus 1.05x at 12:04 ET (control 13:30 ET = 0.84x); LRCX agrees more weakly
    (1.23x vs 1.08x, control 0.71x) as expected for a smaller index weight. Per-filer detection
    across 3 sampled filings each returned unanimous verdicts: **LRCX, MSFT, PEP and SBUX are
    Eastern-mislabelled; the other 20 filers are true UTC.** 96 rows corrected. Post-market count
    rose 465 -> 557, intraday collapsed 71 -> 3. MSFT and LRCX are restored to the panel.
    Residual doubt: only MSFT has strong independent tape confirmation. PEP and SBUX are corrected
    on the index-page test alone, and both are pre-market reporters whose corrected times land
    post-market the prior evening, which is not obviously right. Both sit outside the core cohort.
18b. *(superseded)* **The MSFT timestamp anomaly is NOT unique to MSFT.** With the universe at 23 names, the
    ~12:00 ET acceptance cluster also appears for **LRCX (24 of 24 filings), PEP (22 of 24) and
    SBUX (22 of 24)**. All three are known pre- or post-market reporters, so a midday disclosure
    is implausible for any of them. This strengthens explanation (a): the trailing "Z" is
    unreliable for a subset of filers, likely tied to the submission agent. Practical effects:
    (i) LRCX sits in the tech/semi CORE cohort but contributed ZERO events, since every filing was
    classified intraday and dropped by the post-market filter; (ii) the observed dilution from the
    8-name expansion is therefore driven by roughly five names (COST, GILD, AMGN, BKNG, ISRG),
    not eight. Overall mix across all 23 names: 465 post-market, 71 intraday, 9 pre-market.
18. **MSFT timestamps remain UNRESOLVED and are excluded by default (24 of 168 rows).** Alpha Vantage
    confirms these are the correct earnings dates, so the dates are right; only the time is in doubt.
    EDGAR `acceptanceDateTime` for MSFT clusters at ~16:04 **UTC** (= ~12:04 ET), e.g. 2026-07-29
    accepted 16:04:53Z, whereas AAPL/AMZN/META/GOOGL/NVDA cluster at 20:00-22:55Z (= 16:00-18:55 ET),
    which is correct for post-close releases. Two competing explanations, neither verified:
    (a) the trailing "Z" is spurious for some filers and the value is already Eastern, which would put
    MSFT at 16:04 ET -- exactly right -- but would push AAPL to 20:30 ET, which is wrong; or
    (b) MSFT submits to EDGAR hours before its press release. Until one is established, MSFT is out.
    Excluding it costs 24 of 168 earnings rows and leaves 144 with timestamps consistent across filers.

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

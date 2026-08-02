# SPEC_LOCKED — NQ post-market mega-cap earnings reaction

Frozen 2026-08-01 on development data only (2018, 2020, 2022, 2024, 2026-to-Jun).
Holdout years 2019, 2021, 2023, 2025 have NEVER been read by any analysis in this repo.

## Universe and event selection

- Instrument traded: **NQ front month** (highest-volume outright per session; see limitation 1).
- Event: a company in **Dylan's point-in-time Nasdaq top-10 table** for that calendar year
  releases earnings **post-market** (EDGAR 8-K item 2.02 acceptance >= 16:00 ET).
- Where several companies report the same evening, the **highest-ranked** one defines the event.
- Rank table: `data/macro/raw/nasdaq_top10_by_year.csv` (supplied by Dylan; covers 2020-2026).
  2018 events carry no rank and are OUT of the locked rule.
- EPS actual and consensus are required to exist (Alpha Vantage) but the **surprise is not used**
  — direction comes only from price. Trading the print direction was tested and loses
  (-0.058%, 47% win, n=130; ANA-0008).

## Entry

1. Anchor price `p0` = last completed 1-minute close strictly BEFORE the release timestamp.
2. From the Globex reopen (18:00 ET, or the release itself if later) until the cash open,
   watch 5-minute bars.
3. Enter on the **second consecutive 5-minute close at or beyond +-0.1% from `p0`**.
   Long if above, short if below. Entry price = that bar's close.
4. If no such pair occurs before the cash open, no trade.

## Exit

- **Stop: fixed 1.6%** from entry.
- **No target.** Six separate target constructions were tested and every one destroyed the
  edge (symmetric brackets, fixed TPs 0.3-2.0%, band targets, ATR trails 1x/2x/3x).
- **Time exit: 16:00 ET cash close.**

## One position at a time

One NQ position, one event evening. Overlapping signals are impossible by construction since
the event is defined per evening.

## Development results (NOT a forecast)

| set | n | mean | win | PF | t |
|---|---|---|---|---|---|
| top 10 | 93 | +0.348% | 59% | 1.77 | 2.2 |
| top 10, no stop | 93 | +0.427% | 62% | 2.06 | 2.7 |
| top 3 | 36 | +0.473% | 67% | 2.04 | 1.8 |

~27 events/year. At NQ 25,000 on one MNQ: ~+87 points (~$174) per trade, stop risk 400
points (~$800).

## Deployment objective (Dylan, 2026-08-01)

The objective is NOT risk-adjusted return. On a funded prop account the downside is capped
at losing the account, which is cheap, while the upside is a payout. So the config is chosen
to maximise expected return and win rate, and max drawdown is deliberately NOT minimised.

Under that objective the breakeven variant is rejected: it cuts mean return from +0.348% to
+0.245% and turned 2022 from +$2,970 to -$207, i.e. it suppresses exactly the high-volatility
years that produce a payout. Its lower drawdown buys nothing that this objective values.

Config stands as written above. No target, no breakeven, no early exit.

## Confirmatory test — ONE run, no redesign afterwards

Run this exact rule on **2021, 2023, 2025**. Declared in advance:

- **PASS**: mean return per trade > 0 with t > 1.5 and win rate >= 55%.
- **FAIL**: mean <= 0, or win rate < 50%.
- **INCONCLUSIVE**: anything between.

No parameter may be changed after the holdout is read. Any change creates a new research
generation requiring genuinely fresh data.

## Costs — NOT yet applied

All figures are gross. Round-trip cost on NQ is roughly 1 tick plus commission, about
0.02-0.03% at these levels, so ~7-9% of the mean. Must be applied before deployment.

## Search history

~250 trials across ANA-0001..0018, all recorded in RUN_REGISTRY.csv. The trial count is
large relative to n=93; DSR/PBO have NOT been computed and the t-statistics above are
NOT corrected for selection.

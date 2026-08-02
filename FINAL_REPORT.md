# FINAL REPORT — two research generations, both failed confirmation

## GENERATION 2 — macro-surprise reaction (SPEC_LOCKED_MACRO.md)

```
IMPLEMENTATION_VALID   = YES
STATISTICALLY_CREDIBLE = NO — confirmatory holdout FAILED
ECONOMICALLY_CREDIBLE  = UNCERTAIN
DEPLOYMENT_READY       = NO
```

Rule: CPI/NFP/PPI release days, |z| >= 0.75, enter on the 1-minute close after 08:30 ET in
that bar's direction, stop at 1.5x the 30-minute ATR, no target, hard exit at +30 minutes.

| | development (2021/22/24/26) | **holdout (2023/25)** |
|---|---|---|
| trades | 80 | 43 |
| mean | +0.1253% | **-0.0482%** |
| win rate | 59% | **46.5%** (W20/L23) |
| profit factor | 2.57 | **0.67** |
| RR | 1.80 | **0.77** |
| t | +2.91 | **-1.01** |

Criteria: mean > 0 **FAIL** · t > 1.5 **FAIL** · win >= 55% **FAIL** → **VERDICT: FAIL**

Holdout by year: 2023 +0.018% (56% win, PF 1.16) · 2025 **-0.096%** (40% win, PF 0.43).
By day type, all three negative: CPI -0.071% (33% win) · NFP -0.043% · PPI -0.036%.

**This failure is more informative than generation 1's.** Only ~53 trials were spent here
against ~285 there, so the development result cannot be dismissed as pure search noise --
the rule simply did not generalise. Every development year was positive and the sign
flipped cleanly in the reserved years.

One factual observation, offered as description rather than rescue: the development set
contained 2022, the peak inflation-surprise regime, while the holdout is 2023 (disinflation)
and 2025. Whether that is regime dependence or absence of edge cannot be settled without
data that does not exist yet.

Both holdouts are now spent. Nothing in this repository has a validated forward edge.

---

# GENERATION 1 — NQ post-market mega-cap earnings reaction

## VERDICT

```
IMPLEMENTATION_VALID   = YES (with the front-month caveat below)
STATISTICALLY_CREDIBLE = NO — the confirmatory holdout did not confirm
ECONOMICALLY_CREDIBLE  = UNCERTAIN
DEPLOYMENT_READY       = NO
```

The preregistered confirmatory test returned **INCONCLUSIVE**, failing two of three criteria.

## The rule tested

Top-10 Nasdaq company (Dylan's point-in-time rank table) reports post-market → from the
Globex reopen, wait for two consecutive 5-minute closes at or beyond ±0.1% from the last
pre-release price → enter that direction → 1.6% stop, no target → exit 16:00 ET cash close.

## Development vs holdout

| | development (2018/20/22/24/26) | **holdout (2021/23/25)** |
|---|---|---|
| trades | 93 | 87 |
| mean/trade | +0.348% | **+0.086%** |
| win rate | 59% | **51.7%** |
| profit factor | 1.77 | **1.19** |
| t-statistic | +2.2 | **+0.65** |
| total, 1 MNQ | $8,890 | $1,263 |
| max drawdown | −$1,849 | **−$4,597** |

Preregistered criteria: mean > 0 **PASS** · t > 1.5 **FAIL** · win ≥ 55% **FAIL**.

Holdout by year: 2021 −0.010% (win 50%) · 2023 +0.409% (win 69%) · 2025 −0.185% (win 34%).
The top-3 rank subset did not rescue it: n=28, +0.107%, win 50%, t=0.46.

## Interpretation

The edge shrank by roughly 75% and the win rate fell to a coin flip. Only one of three
holdout years worked. **~285 trials were run against n=93 development events**, and this
is what that much searching produces: the development statistics were substantially
selection rather than signal.

The mean stayed positive and 2023 was genuinely strong, so this is not proof that nothing
is there — it is a failure to demonstrate that something is. Under the declared criteria
that distinction does not matter: the rule is not confirmed.

Note also that holdout max drawdown ($4,597) exceeded total holdout profit ($1,263) by
3.6x, versus development where profit exceeded drawdown by 4.8x.

## What survived scrutiny regardless

1. **Macro transmission is real and fast.** Inflation surprises correlate +0.573 with the
   NQ move in the first 5 minutes (64 independent sessions, 95% CI [+0.494, +0.660]), and
   the relationship is gone by the cash session (−0.158, CI straddling zero).
2. **The EPS number carries no directional information for NQ** — corr(beat, gap) = +0.066,
   corr(|beat|, |gap|) = −0.019, n=130. Trading the print direction loses.
3. **Generic overnight momentum is ~20x smaller** than the earnings effect (negative control).
4. **Targets do not work on this structure** — eight constructions tested, all rejected.

These are measurements, not strategies, and they are unaffected by the holdout outcome.

## Known limitations bearing on the result

- Front-month selection uses whole-session volume and is therefore not causal (Dylan's call).
- Survivorship: all 37 symbols still exist and are still large; names that left the index
  since 2018 are absent and unrecoverable from free sources.
- Costs were never applied (~7-9% of the development mean).
- DSR, PBO and CPCV were never computed.
- Consensus data is a single unverified source (Forex Factory paste) for the macro series.

## What would be legitimate next

The holdout is spent. Re-tuning on it would be worthless. The only clean paths are:

1. **Forward testing** on data after 2026-06-07 as it accrues — genuinely untouched.
2. A **new hypothesis** with a fresh preregistration, treating everything here as a spent
   generation.

Not legitimate: adjusting parameters until the holdout passes, or reporting the
development figures as the strategy's expected performance.

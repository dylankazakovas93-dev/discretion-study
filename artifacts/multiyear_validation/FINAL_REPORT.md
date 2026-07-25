# FINAL REPORT — Locked Multi-Year Validation (Protocol v1.0.0)

**Verdict: `MULTIYEAR_NO_EDGE`**

Frozen at git HEAD `16957e0233cf9056127a051706fdd8bf9cb1091e`; engine combined
hash `17f0b518a2ece9de38cded2644e74dada06100c00270c26ac922f28abe5b1528`.
The protocol (`docs/FROZEN_MULTIYEAR_VALIDATION_PROTOCOL.md`) was written and
committed **before** any multi-year outcome was opened. No rule, threshold,
arm, or gate was changed after seeing results. No amendment was required.

---

## 1. Data coverage

| Year | Sessions | Bars | Status |
|---|---|---|---|
| 2018 | 259 | ~334,730 | Fully covered |
| 2019 | 256 | ~363,014 | Fully covered |
| 2020 | — | — | **DATA UNAVAILABLE** |
| 2021–2022 | — | — | **DATA UNAVAILABLE** |
| 2023–2024 | — | — | **DATA UNAVAILABLE** |
| 2025 | — | — | Not loaded (bundled with 2026 development file) |
| 2026 | (dev only) | — | **Excluded from the edge claim by protocol** |

- **515 CME sessions**, **697,744 front-month bars**, **9 contract-roll segments**
  (NQH8 → NQH0), rolls handled by the project's deterministic highest-daily-volume
  front-month procedure. Spreads, non-front contracts and duplicate rows excluded
  by the loader.
- The 2020/2021-2022/2023-2024 raw files referenced in `data.loader.DATA_FILES`
  are **not present in this environment**. They were **not fabricated or
  substituted**. Only the fully supported years were run.
- **Consequence:** the validation covers **2 years**, not the 8 targeted. Several
  acceptance gates (notably "positive in ≥75% of years") are statistically weak
  on an n=2 year sample. This is the single largest limitation of this run.

## 2. Scale

- **95,704** executable variants passed every frozen structural / lifecycle /
  ATR / RR gate across 515 sessions.
- **7,403** were authorized by at least one recency playbook (EXACT or REDUCED).
- Occupancy-controlled portfolio trades: 2,457 / 2,438 / 1,519 across the three
  frozen policies.

## 3. Executable portfolio results (the only tradable-strategy numbers)

| Policy | Cost | Trades | Win rate | Expectancy R | Net R | PF |
|---|---|---|---|---|---|---|
| EARLIEST_ACTIONABLE | gross | 2457 | 28.8% | +0.098 | **+240.3** | **1.138** |
| EARLIEST_ACTIONABLE | −0.50pt | 2457 | 28.8% | −0.068 | **−166.4** | **0.919** |
| EARLIEST_ACTIONABLE | −1.00pt | 2457 | 28.8% | −0.233 | −573.1 | 0.758 |
| EXACT_FIRST | gross | 2438 | 28.8% | +0.104 | **+254.1** | **1.147** |
| EXACT_FIRST | −0.50pt | 2438 | 28.8% | −0.063 | **−153.0** | **0.925** |
| EXACT_FIRST | −1.00pt | 2438 | 28.8% | −0.230 | −560.1 | 0.762 |
| MULTI_LOOKBACK_SUPPORT | gross | 1519 | 27.3% | +0.009 | +13.0 | 1.012 |
| MULTI_LOOKBACK_SUPPORT | −0.50pt | 1519 | 27.3% | −0.156 | −237.1 | 0.818 |
| MULTI_LOOKBACK_SUPPORT | −1.00pt | 1519 | 27.3% | −0.321 | −487.2 | 0.674 |

**Every policy is marginally positive gross and negative after even a
half-point of cost.** The gross edge (~0.10R/trade) is smaller than the
transaction cost of trading it.

## 4. Year by year (gross)

| Policy | 2018 | 2019 |
|---|---|---|
| EARLIEST_ACTIONABLE | +238.7 R (PF 1.271) | **+1.6 R (PF 1.002)** |
| EXACT_FIRST | +240.8 R (PF 1.273) | **+13.3 R (PF 1.016)** |
| MULTI_LOOKBACK_SUPPORT | +86.3 R (PF 1.151) | **−73.3 R (PF 0.862)** |

The entire gross result is a 2018 phenomenon. 2019 is flat-to-negative for all
three policies. Leave-one-year-out confirms it: excluding 2018 collapses
EARLIEST_ACTIONABLE to PF 1.002 and MULTI_LOOKBACK to PF 0.862.

## 5. PF 2.0 benchmark

**No arm and no policy reaches PF 2.0 at any cost level.**

| | Best gross PF | Best PF after 0.50pt | Best PF after 1.00pt |
|---|---|---|---|
| Portfolio policies | 1.147 | 0.925 | 0.762 |
| Research arms (overlapping) | 1.126 | — | — |

The highest PF of any frozen arm is `ANY_EXACT_PLUS_REDUCED` at **1.126** gross.

## 6. Acceptance gates (Part J)

| Gate | EARLIEST | EXACT_FIRST | MULTI_LOOKBACK |
|---|---|---|---|
| Positive net R after 0.50pt | ✗ | ✗ | ✗ |
| PF after 0.50pt ≥ 1.20 | ✗ | ✗ | ✗ |
| Positive in ≥75% of years | ✓ (2/2) | ✓ (2/2) | ✗ (1/2) |
| ≥200 trades | ✓ (2457) | ✓ (2438) | ✓ (1519) |
| No year >40% of positive R | ✗ (56.3%) | ✗ (56.4%) | ✗ (58.9%) |
| Positive excluding best 20 trades | ✗ (−141.1) | ✗ (−127.4) | ✗ (−240.5) |
| Finite reported max drawdown | ✓ | ✓ | ✓ |
| Causal invariants clean | ✓ | ✓ | ✓ |
| No stale/deactivated target use | ✓ | ✓ | ✓ |
| No post-hoc rule change | ✓ | ✓ | ✓ |
| **Result** | **6/10 — NO_EDGE** | **6/10 — NO_EDGE** | **5/10 — NO_EDGE** |

## 7. Robustness

**Weekly block bootstrap (gross, 2000 resamples):** EARLIEST_ACTIONABLE mean R
CI [+0.009, +0.196] and EXACT_FIRST [+0.016, +0.199] do not cross zero — the
*gross* edge is statistically distinguishable from zero. MULTI_LOOKBACK
[−0.093, +0.104] **does** cross zero. Note the CIs are computed on gross R; the
cost-adjusted means (−0.063 to −0.156) sit at or below the lower bound of every
interval, so no policy has a demonstrable net edge.

**Monte Carlo drawdown (2000 shuffles):** median max DD −70 to −87 R; 95th
percentile worst −109 to −131 R. Realized max DD: −62.5 to −99.2 R.

**Longest losing streak:** 19–20 trades for all policies.

**The matching layer is not additive — this is the key structural finding.**

| Population | n | Win rate | Expectancy R | PF |
|---|---|---|---|---|
| Authorized by ≥1 lookback | 7,403 | 23.9% | +0.096 | 1.126 |
| **Unmatched (no authorization)** | **88,301** | **33.8%** | **+0.117** | **1.177** |

Variants the recency playbook **rejected** outperformed the ones it authorized,
on every metric, over 88k observations. Depth of support made it worse, not
better: one-lookback support PF 1.311 → two 1.002 → three 0.908 → all four
0.927. By lookback age, only PREV_20 was positive (PF 1.311); PREV_1 (0.943)
and PREV_3 (0.895) were negative.

The honest reading: **the recency-fingerprint-matching hypothesis is not
supported.** The gross positive expectancy present in the raw executable-setup
pool is diluted, not concentrated, by the playbook layer.

**By direction:** LONG PF 1.172 (n=50,834), SHORT PF 1.173 (n=44,870) —
symmetric, no directional bias.

## 8. Hypothesis-level arms (overlapping — NOT a tradable portfolio)

| Arm | n | Win rate | Expectancy R | Net R | PF |
|---|---|---|---|---|---|
| ANY_EXACT_PLUS_REDUCED | 7403 | 23.9% | +0.096 | +709.8 | 1.126 |
| L20_EXACT_PLUS_REDUCED | 7367 | 23.9% | +0.095 | +701.1 | 1.125 |
| L20_EXACT | 1463 | 24.1% | +0.060 | +88.2 | 1.080 |
| ANY_EXACT | 1467 | 24.1% | +0.060 | +87.4 | 1.079 |
| MULTI_LOOKBACK_ANY | 3960 | 22.1% | −0.020 | −80.4 | 0.974 |
| L10_EXACT_PLUS_REDUCED | 3975 | 22.2% | −0.019 | −75.4 | 0.976 |
| ALL_LOOKBACKS | 486 | 21.4% | −0.057 | −27.9 | 0.927 |
| L1_EXACT_PLUS_REDUCED | 496 | 21.6% | −0.045 | −22.1 | 0.943 |
| L3_EXACT_PLUS_REDUCED | 1278 | 21.0% | −0.068 | −87.3 | 0.914 |
| MULTI_LOOKBACK_EXACT | 668 | 18.4% | −0.232 | −154.9 | 0.716 |
| L10_EXACT | 671 | 18.5% | −0.231 | −154.7 | 0.717 |
| L1_EXACT / L3_EXACT | 29 | 6.9% | −0.634 | −18.4 | 0.319 |

These overlap (one physical setup contributes to several arms and several entry
variants) and are **research diagnostics only**, never a portfolio.

## 9. Integrity

- **Causal violations: 0.** Every playbook item's source sessions independently
  re-verified as strictly earlier than the session it authorizes (0 violations
  over 515 sessions).
- **Optimized matcher proven byte-equivalent** to the frozen reference
  `playbook.match_modes` scan: 16,048 side-by-side comparisons over the first 25
  sessions, **0 mismatches**. Recorded in `causal_invariants.json`.
- **Stale/deactivated targets:** excluded by construction via the audited
  `deactivation_available_seq` lifecycle field (see limitation 5 below).
- Checkpointed per roll segment; the run survived an interruption and resumed
  from disk with identical per-segment variant counts.

## 10. Limitations

1. **Only 2 of 8 target years.** 2020–2025 data is absent from this environment.
   Two years — one of which (2018) carries the entire gross result — cannot
   support a durable edge claim in either direction. This is a data-availability
   limit, not a finding.
2. **The result is a 2018 artifact.** 56% of positive R comes from one year;
   removing the best 20 trades turns every policy negative. Even the gross edge
   is concentrated, not broad.
3. **Costs dominate.** The gross edge (~0.10R/trade ≈ 2–3 NQ points on typical
   stop distances) is smaller than a realistic round-trip cost. This is a
   structural problem with targeting the *nearest* opposing structure: it caps
   the average winner near the cost threshold.
4. **Bootstrap CIs are gross-only.** They exclude zero for two policies gross,
   but the net (post-cost) means fall below every interval's lower bound.
5. **Stale-target audit is by-construction, not per-trade re-verified.** The
   `stale_target_audit.csv` records 0 based on the tested lifecycle guarantee in
   `targets.resolve_targets`, not an independent re-scan of all 95,704 variants.
6. **Similarity diagnostics were never executed** (non-actionable by protocol),
   so the optimized matcher does not compute them — this cannot affect any
   reported number, as no arm or policy consumes them.

## 11. Conclusion

The engine is mechanically sound: 0 causal violations, byte-equivalent
optimization, clean lifecycle handling, and a fully frozen pre-registered
protocol that required no amendment. **The strategy hypothesis it was built to
test is not supported by the available validation data.**

All three frozen portfolio policies are unprofitable after a half-point of
cost, no arm approaches PF 2.0, the gross result depends on a single year, and
— most decisively — the recency-playbook matching layer selects setups that
perform *worse* than the ones it rejects. That last result is not a
tuning problem; it is evidence against the central premise that recently
successful setup fingerprints predict near-future ones.

**`MULTIYEAR_NO_EDGE`**

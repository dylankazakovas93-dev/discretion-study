# TP/SL Formula Study — RB-K1 (Dev 2018–2025)

## Objective
Find the best mechanically-defined TP and SL using only pre-trade features.
- **TP minimum**: 2× completed 1m ATR(24) = 2R
- **SL minimum**: 1× completed 1m ATR(24) = 1R
- All exits on whole 1m bar closes (entry = open of entry bar)
- Stop-first on same-bar ambiguity

## Method
Bar-by-bar simulation from segcache OHLC. Grid sweep:
- TP multiples: 2.0R, 2.5R, 3.0R, 3.5R, 4.0R
- SL multiples: 1.0R, 1.25R, 1.5R, 2.0R
- Filter sets: ALL (5,347), HIGH_REACT (TAP/MINIMAL_WICK/STRONG), ADX1≥25, EMA alignment, combos

## Core Finding: TP=2R is always optimal, SL width matters

| Config                          | n    | /wk | PF@1   | PF@2   | net@2 | MDD@2  | win%  | green |
|---------------------------------|------|-----|--------|--------|-------|--------|-------|-------|
| ALL  TP=2R  SL=1R  (baseline)   | 1774 | 4.3 | 1.1596 | 1.0765 | +91.6 | -53.6  | 38.5% | 6/8   |
| ALL  TP=2R  SL=1.25R            | 1656 | 4.0 | 1.1780 | 1.1036 | +129  | -39.6  | 44.0% | 8/8   |
| ALL  TP=2R  SL=1.5R             | 1585 | 3.8 | 1.1945 | 1.1259 | +163  | -42.6  | 48.7% | 8/8   |
| ALL  TP=2R  SL=2R               | 1464 | 3.5 | 1.1845 | 1.1244 | +169  | -41.7  | 55.4% | 7/8   |
| **ADX1≥25  TP=2R  SL=2R**       | **808**  | **2.0** | **1.3286** | **1.2613** | **+183** | **-19.9** | **58.0%** | **8/8** |
| HIGH_REACT+ADX25  TP=2R  SL=2R  | 680  | 1.6 | 1.3142 | 1.2456 | +147  | -21.5  | 58.1% | 8/8   |
| HIGH_REACT  TP=2R  SL=2R        | 1263 | 3.1 | 1.2359 | 1.1715 | +197  | -31.3  | 56.6% | 7/8   |
| EMA_WITH  TP=2R  SL=2R          | 790  | 1.9 | 1.1978 | 1.1410 | +101  | -28.1  | 55.4% | 8/8   |

## Star Result: ADX1 ≥ 25 — Year by Year

**Filter**: 1m ADX(14) ≥ 25 at entry bar (trending, not choppy)
**TP**: 2× ATR  **SL**: 2× ATR  **RR ratio**: 1:1 gross

| Year | n   | PF@1   | PF@2   | net@2 |
|------|-----|--------|--------|-------|
| 2018 | 40  | 1.4428 | 1.3558 | +11.7 |
| 2019 | 37  | 1.4425 | 1.3405 | +9.9  |
| 2020 | 103 | 1.3223 | 1.2527 | +22.8 |
| 2021 | 117 | 1.5384 | 1.4552 | +42.6 |
| 2022 | 152 | 1.2059 | 1.1482 | +20.8 |
| 2023 | 71  | 1.3382 | 1.2670 | +16.3 |
| 2024 | 134 | 1.2625 | 1.2013 | +23.9 |
| 2025 | 154 | 1.3173 | 1.2602 | +34.7 |
| **TOTAL** | **808** | **1.3286** | **1.2613** | **+182.7** |

T=462 target / S=331 stop / t=15 time | MDD@2 = -19.9 R

## Why the pre-trade formula works this way

### 1. TP=2R is the minimum and also the best
Every wider target (2.5R, 3R, etc.) performs worse across all filter sets and SL widths.
The median MFE is 3-4R — trades *can* run far — but TP≥2R hit by the stop before reaching
wider targets frequently enough to erode PF.

### 2. Wider SL prevents premature stop-outs
The MFE/MAE diagnostic showed 83.1% of RB-K1 trades eventually hit -1R — but many of them
first moved favorably. A 1R stop gets clipped by normal 1m noise. SL=2R dramatically
reduces premature exits:
- SL=1R: 1087 stops out of 1774 trades (61%)
- SL=1.5R: 807 stops out of 1585 trades (51%)
- SL=2R: 642 stops out of 1464 trades (44%)

### 3. ADX(14) 1m ≥ 25 is the single most powerful pre-trade filter
- ADX_LOW (<20): PF@2 = 0.889 with 1R stop — the setup has NO edge in choppy markets
- ADX_HIGH (≥25): PF@2 = 1.2613 with 2R stop — robust across all 8 dev years
- ADX signal is entirely causal (computed from completed 1m bars before the entry bar)

## Recommended Formula (for next OOS test)

```
if adx_1m >= 25:
    tp = max(2.0 * atr_1m, natural_structure_tp)  # at least 2R
    sl = 2.0 * atr_1m                              # 2R (not structural — wider)
else:
    skip trade  # no edge below ADX=25
```

Alternative without skipping low-ADX trades (still positive but weaker):
```
tp = 2.0 * atr_1m   (always)
sl = 1.5 * atr_1m   (always)
# → PF@2=1.1259, 8/8 green years, MDD=-42.6
```

## What the OLS formula showed
Walk-forward OLS on 17 features (ADX, VWAP z-score, EMA slope/distance, log-ATR, etc.)
predicting log(MFE/R) and log(|MAE|/R) did NOT outperform simple fixed rules:
- OLS PF@2 = 1.0462, green 5/7, MDD = -141.0 (much worse)
- Reason: OLS predicts the *mean* excursion, not the *minimum favorable bar sequence*.
  The stop-vs-target race depends on path, not mean — OLS cannot model that.
- The pre-trade features do NOT reliably predict which trades go up before they go down.
  ADX is the exception: it filters environments where trades frequently reverse before
  getting anywhere near the target.

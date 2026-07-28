# Exit Rule V2 — RB-K1 (Dev 2018–2025)

## Rule

```
TP = 1.5 × ATR(24) 1m  (= 1.5R)
SL = 1.5 × ATR(24) 1m  (= 1.5R)
```

Symmetric 1:1 gross RR. Entry = open of entry bar. Stop-first on same-bar
ambiguity. Bar-by-bar on whole 1m closes only (no intrabar).

## Year-by-Year

| Year | n   | PF@2   | net@2 |
|------|-----|--------|-------|
| 2018 | 77  | 1.3265 | +16.0 |
| 2019 | 58  | 1.3521 | +12.7 |
| 2020 | 188 | 1.1224 | +16.0 |
| 2021 | 240 | 1.1153 | +19.3 |
| 2022 | 351 | 1.1558 | +37.7 |
| 2023 | 205 | 1.2534 | +33.9 |
| 2024 | 262 | 1.1402 | +25.3 |
| 2025 | 339 | 1.1226 | +29.0 |
| **TOTAL** | **1720** | **1.1614** | **+189.9** |

**8/8 dev years profitable. Win rate 57%. MDD@2 = -31.2R. 4.2 trades/week.**

## Comparison vs all tested exit rules

| Rule          | TP  | SL  | n/wk | PF@2   | net@2 | MDD@2  | win%  | green |
|---------------|-----|-----|------|--------|-------|--------|-------|-------|
| Structural 1R | var | 1R  | 4.3  | 1.0765 | +92   | -53.6  | 38.5% | 6/8   |
| Structural 1R | var | 1.5R| 3.8  | 1.1259 | +163  | -42.6  | 48.7% | 8/8   |
| **Fixed 1.5R**| **1.5R**|**1.5R**|**4.2**|**1.1614**|**+190**|**-31.2**|**57.0%**|**8/8**|
| floor-2bar    | ≥1.5R|1.5R| 4.1  | 1.1703 | +201  | -31.2  | 56.5% | 8/8   |
| ADX≥25 2R/2R  | 2R  | 2R  | 2.0  | 1.2613 | +183  | -19.9  | 58.0% | 8/8   |

The "floor-2bar" (TP = max(1.5R, prior 2-bar swing extreme)) adds 0.009 PF vs fixed
1.5R but 90% of trades use the 1.5R floor anyway — the structural component barely
contributes. Prior 2-bar swings for a rejection block entry are almost always within
1.5R.

ADX≥25 has higher PF@2 but 2R/2R RR requires 58% win rate just to break even at 2pt
commission and cuts frequency by 60%. It's a filter not a formula.

## Why 1.5R beats 2R TP

The MFE scope showed median time to +1R = 2 minutes, and 83% of trades eventually
hit -1R (the give-back problem). At 2R TP, the trade has time to reverse. At 1.5R,
it exits before the reversal on the majority of trades. The win rate jump (38.5% → 57%)
more than compensates for the smaller target at 1:1 RR vs 2:1.

Breakeven at @2pt commission with 1.5R TP / 1.5R SL and mean ATR ≈ 20pt:
- each win nets 1.5R - 2/20 = 1.5 - 0.10 = +1.40R
- each loss costs 1.5R + 2/20 = 1.5 + 0.10 = -1.60R
- breakeven win rate = 1.60 / (1.40 + 1.60) = 53.3%
- actual win rate = 57.0% → solidly above breakeven

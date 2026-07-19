# Facts, Assumptions, Hypotheses

## FACTS

- NQ 1-minute OHLCV is available from 2018 through 2026-06-07 in supplied Databento archives.
- The code supplies causal completed-bar primitives, including a 10:00 ET open level and rejection blocks.
- The anchor price is observable at 10:00:00; the 10:00 bar's high, low, close and volume are not complete until 10:01:00.
- Existing development artifacts are contaminated and do not constitute forward evidence.
- The frozen generic RR policy rejects natural RR below 0.5 and caps execution at 1R; it is not a global portfolio executor.

## ASSUMPTIONS

- The front-month selection/roll policy is acceptable for the intended tradable NQ representation.
- A completed 1-minute OHLCV bar is sufficient for the proposed confirmation and conservative execution model.
- The anchor should be a New York wall-clock event across DST, not a fixed UTC time.

## HYPOTHESES

- `H10-CROSS-001`: after a preregistered meaningful first excursion from the 10:00 open, the first valid completed close through that price predicts directional continuation in the crossing direction.
- `H10-RB-001`: a causally valid opposing RB interaction during that excursion improves the post-cross path distribution over comparable no-RB events.
- `H10-PLACEBO-001`: the frozen event is stronger at 10:00 than at preregistered neighboring/deterministic placebo anchors.
- `H10-NEWS-001`: any apparent effect may be concentrated on scheduled 10:00 release sessions; a later calendar is required.
- `H10-RUNAWAY-001`: non-crossing extension may revert; it is separate and must not be combined with the cross rule.

## ALTERNATIVE EXPLANATIONS

- Scheduled macro releases, broader RTH opening dynamics, volatility regime, contract/roll artifacts, OHLC intrabar ambiguity, and multiple testing can produce an apparent clock-time effect.

## FALSIFIERS

- No positive directional continuation under the frozen event definition, no 10:00 strength beyond placebos, RB interaction without incremental path benefit, or an effect confined to scheduled releases would materially weaken the claimed mechanism.

## UNKNOWNS

- Excursion threshold, penetration, deadline, entry mode, horizon/outcome definition, cost model, exact RB availability rule, session cutoff, and clean final holdout remain unselected.

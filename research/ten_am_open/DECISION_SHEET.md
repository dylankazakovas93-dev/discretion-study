# Dylan Decision Sheet

| ID | Question / options | Why it matters and consequence | Default without results | Blocks Stage 1? |
| --- | --- | --- | --- | --- |
| D1 | Confirmation: first completed 1m close vs first completed 5m close through anchor | Separate hypotheses; 5m is available after 10:05, 1m after 10:01; combining them creates selection risk. | Register both as separate variants, not a winner. | Yes |
| D2 | Meaningful excursion: raw points, volatility-normalized, or small preregistered continuous grid | Points vary by regime; ATR/grid increases multiple-testing burden and changes sample size. | One small declared grid only if adequate correction is specified; otherwise normalized threshold. | Yes |
| D3 | Cross: wick, body intersects, completed close, or close by >=1 tick | The claimed model requires completed close; weaker definitions admit intrabar ambiguity. | Completed close by at least one NQ tick. | Yes |
| D4 | Entry: next eligible bar, anchor retest, FVG/iFVG retracement | These are distinct causal/execution hypotheses and must not be collapsed. | Next eligible bar for primary feasibility. | Yes |
| D5 | RB relationship: pre-existing confirmed touch, formed+confirmed in excursion, reaction, failure, no-RB baseline | Current inventory exposes RB at formation, although confirmation is later. Each option has different availability. | Confirmed-only context; preserve no-RB baseline. | Yes |
| D6 | Formation deadline: 10:30, 11:00, or 11:30 ET | Alters sample and session exposure. | 11:00 ET as a neutral operational boundary; do not choose from results. | Yes |
| D7 | Stop: 1 or 2 ticks beyond pre-confirmation excursion extreme vs RB invalidation boundary | Stop governs natural RR; do not tighten it for target eligibility. | Two ticks beyond the excursion extreme for primary; RB boundary as separately declared contextual variant. | Yes |
| D8 | Target policy: BRANCH_SEMANTIC, NEAREST_VALID_STRUCTURE, NEAREST_PROMINENT_WICK, NEAREST_OPPOSING_HTF_FVG | All exist and are frozen generic variants; branch semantic is not yet tied to the 10:00 model. | `NEAREST_VALID_STRUCTURE` primary; others separate registered variants only. | Yes |
| D9 | RR: retain existing 0.5R rejection and 1R cap, or explicitly amend | Existing rule exactly: select natural target first; reject <0.5R; retain 0.5–<1R; cap >=1R. | Reuse unchanged. | Yes |
| D10 | Partitions/final holdout | July 2025 and phase1 2026 exposures contaminate candidate final periods. | Freeze chronological periods in Data Feasibility, preferably acquire fresh contiguous post-exposure holdout. | Yes |
| D11 | Execution policy: order/fill, costs, cutoff, global one-position, simultaneous events | No authoritative portfolio executor exists; without this, executable claims are undefined. | Conservative next-bar fill; one global position; no same-bar re-entry; conservative ambiguity; explicit costs. | Yes |
| D12 | Placebo anchors and news data | Needed to test anchor specificity/alternative explanation but not to define primary raw cross. | Deterministic neighboring anchors and later external scheduled-news calendar. | No for primary Stage 1; yes before those tests |

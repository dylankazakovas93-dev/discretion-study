# Known Limitations

- Stage 0 establishes feasibility only; it validates neither prediction nor profitability.
- Current raw archives are external to the clone and no `data/raw` source was installed, so data-gated existing tests skipped.
- Generic primitives use completed bars. The 10:00 opening price needs an explicit live-availability exception while excluding the rest of that minute's OHLCV until close.
- RB target visibility at formation conflicts with a likely confirmed-RB research interpretation; Stage 1 must choose and implement an as-of rule without altering the primitive.
- No global portfolio/order execution engine, MAE/MFE ledger, session cutoff, NQ multiplier, costs, or fill/queue model is authoritative.
- Intra-minute sequencing cannot be inferred from OHLCV; same-bar stop/target is currently ambiguous.
- No holiday/early-close calendar or scheduled-news calendar is integrated.
- Archive condition files flag nonavailable dates, but a dedicated selected-front-month 10:00 completeness/duplicate ledger has not been built.
- Prior repository development/replay exposure makes July 2025 and phase1-related 2026 unsuitable as presumed untouched evidence.

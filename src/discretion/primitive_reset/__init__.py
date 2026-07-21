"""Primitive-reset package (NQU6 timestamp audit) -- FROZEN.

Dylan has manually verified the FVG, iFVG and rejection-block primitives on
NQU6 and approved them. As of this commit the primitive logic below is
FROZEN: do not change detector geometry, thresholds, lifecycle or timestamps
without an explicit new instruction to unfreeze a named piece.

Frozen contract
---------------
* colour.py       -- close>open bullish / close<open bearish /
                     close==open EXACT_DOJI_COLOUR_UNRESOLVED (never seeds an
                     eligible FVG or iFVG).
* fvg.py          -- exact 3-candle same-colour wick-to-wick geometry, ATR
                     size ratio + 6 bins, 8h intraday lifetime.
* ifvg.py         -- same-timeframe parent inversion (completed close through
                     the parent's distal boundary), inversion-speed grading.
* traversal.py    -- common 0.20W wick tolerance; close-through vs
                     overshoot-limit deactivation.
* timeframes.py   -- 1/3/5/15/30/60m series; unshifted same-timeframe
                     Wilder ATR(14) at candle close; open-time display helper.
* rejection_block.py -- 0.20 dominant-wick floor; dominant-wick direction;
                     equal-wick ambiguity; existing-structure overlap
                     precedence; 1.5x-ATR next-3-candle MFE ACTIVATION as a
                     descriptive status (NOT a usability gate); a rejection
                     block is a live/usable structure from its source-candle
                     close, and every tap carries a causal was_activated flag.

Downstream setup construction may query ``RBCandidateRecord.was_activated_at``
to label a rejection block activated / not-activated at the time a setup is
taken, without look-ahead.
"""

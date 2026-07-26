# FROZEN MULTI-YEAR VALIDATION PROTOCOL — v2.0.0

Supersedes v1.0.0. Written and committed **before any v2 outcome is opened or
calculated**. v1.0.0's results are formally invalidated (see "Why v2 exists").

## Why v2 exists

v1.0.0 ran to completion and returned `MULTIYEAR_NO_EDGE`, but that result was
**not a valid test of the hypothesis**. Two defects were found by inspecting the
v1 diagnostics (not by inspecting the profitability of alternatives):

1. **Playbook admission was too weak.** A fingerprint authorized on **≥1 win**,
   regardless of its losing record. Audit of 55,515 sampled items: **96.4% were
   authorized on a single win**, and **1.4% were authorized despite losing more
   often than they won**. This selects noise, not repeatable patterns.
2. **The fingerprint never generalized.** The 19-field EXACT key produced
   **1.55 variants per fingerprint**, with **78.3% of fingerprints occurring
   exactly once in two years**. The matcher was memorizing individual trades,
   so the recency hypothesis was never actually exercised.

A third v1 observation — that trades were economically tiny at 2018 price
levels — is **explicitly NOT treated as a defect in v2**, per the account
owner's instruction: the relative ATR floors are correct, an absolute
point floor is not wanted, and execution is on a prop account where slippage
and commission are negligible.

## Frozen changes in v2 (only these; everything else is byte-identical to v1)

### Change 1 — playbook admission requires a genuinely winning record

Within the lookback window, a candidate fingerprint's executable, resolved
occurrences are tallied into `wins` / `losses` and a fingerprint-level
`PF = sum(positive R) / |sum(negative R)|`. Three admission rules are
**pre-registered and all reported**; none is selected after seeing results:

| Rule | Condition |
|---|---|
| `ANY_WIN` | `wins >= 1` (the v1 rule, retained as a control) |
| `NET_POSITIVE` | `wins > losses` |
| `PF2` | `wins >= 1` **and** fingerprint `PF >= 2.0` |

### Change 2 — generalized `SETUP_FAMILY` matching key

A new coarse key is introduced **alongside** (not replacing) the v1 EXACT key,
so both are reported:

`SETUP_FAMILY_FIELDS = [lane, direction, context_family, context_tf_bucket,
session, entry_variant, reaction_state]`

where `context_tf_bucket` = `LTF` for context timeframes 1/3/5m and `HTF` for
15/30/60m.

Deliberately **dropped** from the family key: `day_of_week`, exact
`context_tf` / `trigger_tf` / `interaction_tf` / `reaction_tf` /
`confirmation_tf`, `is_multi_timeframe`, `confluence`, `rb_activation_class`,
`interaction_to_trigger_delay_bin`, `target_family`, `target_tf`,
`natural_rr_bin`.

Rationale (account owner's specification): a NY-AM HTF rejection-block tap
entered on good displacement should be authorized by a prior NY-AM HTF
rejection-block tap on displacement — it need not be the same hour, the same
timestamp, or the same higher timeframe. **Entry variant and reaction state
remain distinct**: a tap entry never authorizes a displacement entry, and a
minimal rejection never authorizes a strong rejection.

### Change 3 — costs are informational, not gates

Gross is the primary reporting basis. Cost columns (0.50pt / 1.00pt round-trip)
are still computed and published as sensitivity, but **no acceptance gate
depends on them**, because execution is on a prop account with negligible
commission and no material slippage.

## Explicitly UNCHANGED from v1 (frozen, byte-identical)

Audited FVG/iFVG/RB primitives · repaired iFVG causal deactivation timing ·
setup lanes · all 10 entry variants · all 9 reaction states · session
boundaries and CME session identity · timeframe architecture · raw structural
stop · **effective stop ≥ completed 1m ATR(24)** · **target distance ≥
completed 5m ATR(24)** · nearest genuine opposing structural target · no
synthetic targets · no bypassing a nearer valid opposing blocker · effective
natural RR ≥ 0.5 · next-bar entry · stop-first same-bar resolution ·
`MAX_HOLD_BARS = 480` · session-by-session walk-forward causality.

## Data scope

- **Validation (locked):** 2018–2025, all completed years, full front-month NQ.
- **Excluded from the primary claim:** 2026 (development / visual-audit data).
- Contract roll: project's deterministic daily-volume front-month selection;
  structures never cross a roll boundary.

## Research arms (pre-registered; no arm added after viewing results)

Full grid — 4 lookbacks × 2 match keys × 3 admission rules = **24 arms**:

- lookbacks: `PREV_1_SESSION`, `PREV_3_SESSIONS`, `PREV_10_SESSIONS`, `PREV_20_SESSIONS`
- match keys: `EXACT` (v1 19-field), `FAMILY` (v2 7-field)
- admission: `ANY_WIN`, `NET_POSITIVE`, `PF2`

## Portfolio policies (one position at a time; unchanged from v1)

`POLICY_EARLIEST_ACTIONABLE` · `POLICY_EXACT_FIRST` ·
`POLICY_MULTI_LOOKBACK_SUPPORT`, each with the same deterministic ranking
(exact > family; more supporting lookbacks; higher historical support; earlier
trigger; lexical variant ID as final tie-break).

## Acceptance gates (frozen; gross basis)

A portfolio policy passes the **minimum robust-edge gate** only when all hold:

1. positive gross net R
2. gross PF ≥ 1.30
3. positive in ≥ 70% of fully covered validation years
4. ≥ 200 occupancy-controlled trades overall
5. no single year > 40% of total positive R
6. removing the best 20 trades leaves positive net R
7. finite, fully reported max drawdown
8. 0 causal-invariant violations
9. 0 stale/deactivated target use
10. no rule added after inspecting outcomes

PF ≥ 2.0 remains an aspirational benchmark, reported but never used to select a
configuration.

Verdicts: `ROBUST_EDGE_PASS` / `WEAK_EDGE_INCONCLUSIVE` / `NO_EDGE` /
`INVALID_RUN`.

## Amendment log

- **v2.0.0** — initial. Supersedes v1.0.0 for the reasons above. All v1 result
  artifacts are retained but marked invalidated.

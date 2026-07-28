# RB-K1 — first out-of-sample evaluation on 2026

Rule frozen before ingestion. Thresholds pre-registered:
PASS = PF > 1.10 after 2pt full round trip AND net R > 0.

| Window | Status | Trades | /wk | PF@1pt | PF@2pt | Net@2pt | Win rate | Verdict |
|---|---|---|---|---|---|---|---|---|
| 2018-2025 development | in-sample | 2,150 | 5.16 | 1.3515 | 1.2296 | +239.6R | 48.0% | baseline |
| 2026-01-01 .. 06-02 | CONTAMINATED | 172 | 7.92 | 1.6091 | 1.5103 | +42.6R | 55.2% | PASS |
| 2026-06-10 .. 07-16 | **CLEAN** | 37 | 7.19 | 1.2476 | **1.1903** | **+3.6R** | 51.4% | **PASS** |

## Contamination note

The Jan-Jun 2026 window is NOT pristine: an Option 3 evaluation on it was run
and disclosed earlier in the session, before RB-K1 was discovered. The
Jun 8 - Jul 17 window had never been ingested, scored or inspected by anyone
prior to this run; the observer was warmed from 2026-04-19 so structures
existed before scoring opened, and only sessions on or after 2026-06-08 scored.

## Reading

Both windows clear the pre-registered PASS threshold. The clean window's PF@2pt
of 1.1903 sits BELOW the in-sample 1.2296 but comfortably above 1.00, and trade
frequency held (7.19/wk vs 5.16 in-sample).

37 trades is a very small sample. At this size the result cannot distinguish
"the edge held" from "the edge halved" from "chance". It is directionally
consistent with the development result and is not evidence of collapse; it is
also not confirmation.

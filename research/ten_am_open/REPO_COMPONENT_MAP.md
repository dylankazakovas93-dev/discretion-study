# Repository Component Map

| Future requirement | Component / path | Status | Tests / causality concern |
| --- | --- | --- | --- |
| 10:00 anchor | `primitives/levels.py` `build_time_anchors` | extend availability wrapper | open price set at bar seq though bar completes at +1m |
| excursion state | none | new | must only advance on completed eligible bars |
| 1m confirmation | `Bar`, `levels` | new event rule | close usable at 10:01 |
| 5m confirmation | `data/aggregation.py` | reuse aggregation, new rule | candle usable at `available_seq` (10:05) |
| RB context | `primitives/rejection_block.py` | reuse unchanged; as-of adapter | formation vs confirmation must be explicit |
| FVG/iFVG context | `primitives/fvg.py`, `ifvg.py`, `htf_fvg.py` | reuse unchanged | timestamped availability/freshness |
| target construction | `graph/targets.py` | reuse policies / extend project adapter | structures' mutable `active` needs avoidance/as-of repair |
| stop construction | `graph/anchors.py` | new project stop resolver | excursion extreme not existing anchor |
| RR policy | `setups/model.py` | reuse unchanged | target selected before RR, <0.5 reject, >=1 cap |
| candidate ledger | `graph/materializer.py` | extend/new project ledger | preserve feature as-of timestamps |
| trade ledger/outcomes | `setups/model.py` | new authoritative executor | individual only; same-bar collision ambiguous |
| global position control | none | new | one position, deterministic event order/no re-entry |
| placebo anchors | `levels.py` anchor pattern | new configuration | freeze before results |
| reporting | `pipeline/run.py`, graph ledger | extend/new | do not reuse contaminated outputs as evidence |
| run registry | `research/ten_am_open/RUN_REGISTRY.csv` | reuse initialized schema | all trials recorded |

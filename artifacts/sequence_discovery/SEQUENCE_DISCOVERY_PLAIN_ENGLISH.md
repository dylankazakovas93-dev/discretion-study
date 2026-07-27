# Native sequence discovery — direct verdict

1. Were genuine native standalone sequences built?  YES. Family A (VWAP band
   extension -> reversion -> optional EMA cross -> next-bar entry) and Family C
   (EMA extension -> close back through EMA -> next-bar entry) generate their
   own candidates, stops, targets and simulated outcomes with no FVG/iFVG/RB
   trigger anywhere in the path.
2. Was AMD fully implemented and tested?  NO. Families E and F were not built.
3. Total configurations run: 432 native (Families A and C).
4. Native sequences positive in all eight years: 0.
5. Sequence-plus-structure (Family H): not run.
6. Survived neighbourhood testing: 0 (none reached the gate).
7. Producing 3-8 trades/week with 8/8 years: 0.
8. Highest native PF@1pt: 1.0144 (VWAP TEN_1000 2SD, 8.8/wk) — 4/8 years.
9. Highest weekly expectancy among natives: negative at 1pt for all but a
   handful; none economically viable.
10. Did any native sequence beat K1 or K3?  NO, and not narrowly.
11. Did AMD add value?  UNTESTED.
12. Did FVG/iFVG/RB add value?  INVERTED ANSWER: removing structure entirely
    destroys the edge. Native VWAP/EMA sequences have no edge at all, so the
    structural primitives are the load-bearing component.
13-15. No native candidate qualifies for freezing.

## Comparison

| Strategy | Type | Trades/wk | PF@1pt | PF@2pt | Pos yrs @1pt |
|---|---|---|---|---|---|
| K1 | Existing structures + state filter | 7.3 | 1.3620 | 1.2369 | 8/8 |
| K3 | Existing structures + state filter | 2.9 | 1.6633 | 1.5138 | 8/8 |
| Option 3 | Existing structures | 23.5 | 1.1466 | 1.0602 | 8/8 |
| Best native sequence | NATIVE, no structure | 8.8 | 1.0144 | 0.9156 | 4/8 |

K1 and K3 remain correctly described as: existing structural setups permitted
only under particular VWAP/EMA market states. They are NOT standalone sequences.

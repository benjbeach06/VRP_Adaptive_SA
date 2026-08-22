# Greedy subtree, n=200 -- WRONG INSTANCE

**Same arms as `../2026-08-20_greedy_subtree_n500/`, run on the wrong instance.**

| | |
|---|---|
| instance | n=200, `tune.build_instance(200)` -- **not** the reference instance |
| budget | 180 s, NN start |
| seeds | 25 paired of 30 planned, stopped early |
| solver | `d43c929` |

**All experiments belong on n=500 capacity 400 unless stated otherwise.** This one was launched
without the instance being written into the plan, and ran nine hours before anyone noticed.

## The data is still valid

It answers the same question on a different shape, and it agreed with the n=500 run that followed:
dropping `ReorderShortSpanExactly` gained 0.74% at -4.1 sigma.

Note that this instance is not 47 short routes as the name might suggest. `build_instance(200)`
produces 3 routes of about 67 customers, so route LENGTH is close to the reference instance and only
route COUNT differs.

Plot in `deltas.png`.

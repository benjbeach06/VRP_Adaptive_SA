# Full-roster K sweep

**Question.** What should `EXACT_REORDER_MAX_SPAN` be, with the whole roster present?

**Why it was needed.** An earlier sweep varied K on an exact-only roster, so it compared K values
against each other on a configuration nobody ships. See `../2026-08-20_greedy_subtree_n500/`.

| | |
|---|---|
| instance | n=500, capacity 400, `tune.build_instance(500)` |
| budget | 600 s, NN start |
| arms | control (K=8 shipped default at the time), then K = 4, 5, 6, 7, 8 |
| seeds | 15 paired, breadth-first |
| solver | `953db60` |

Only `max_span` varies. All 24 operators are present in every arm, farthest-insertion included.

**Arm 12 duplicates the control**, because the shipped default was 8 when this ran. It measures
run-to-run variance at identical settings, which is the noise floor the other arms are read against.

## Verdict

**K=4.** 29.70 better than control at -4.7 sigma, winning 14 of 15 seeds. K=5 is statistically tied.
K=6 and K=7 fall inside the noise. The replicate lands at -0.3 sigma.

The default was changed to 4 in `a54710e`.

Full numbers and interpretation in `RESULTS.md`, "Span size, on the FULL roster". Plot in
`deltas.png`.

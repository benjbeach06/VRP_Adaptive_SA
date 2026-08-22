# Greedy subtree, n=500

**Question.** Are the optimizing operators -- the OPTIMIZED subtree -- worth their cost?

| | |
|---|---|
| instance | n=500, capacity 400, `tune.build_instance(500)` |
| budget | 180 s, NN start |
| arms | control; no-greedy; exact-only at K = 7, 8, 9, 10; farthest-only; `reaction_factor = 1` |
| seeds | 20 paired, breadth-first |
| solver | `8ddc893` |

## Verdict

**Dropping `ReorderShortSpanExactly` gained 24.59 at -4.8 sigma, 16 of 20 seeds.** The exact-only K
arms worsen monotonically as K rises, and K=10 lost every seed and never reached a plateau.

**Read as a scoring failure, not an operator failure.** The follow-up sweep in
`../2026-08-21_full_roster_k/` found the span length was the variable: K=4 gains MORE than removing
the operator entirely.

**Limitation.** The K arms here removed the farthest-insertion operators, so they compare K on a
roster nobody ships.

Interpretation in `RESULTS.md`, "The scoring cannot price rarity against cost". Plot in `deltas.png`.

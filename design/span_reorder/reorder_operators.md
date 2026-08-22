# Span reordering

**Code:** `SimAnn_VRP_Operators.py` -- `_SpanReorderBase` and its descendants
**BL operator:** `PermuteChain`

Rebuild a contiguous span of one route. Every other operator edits a route locally -- move a
customer, swap a pair, reverse a run. These discard the ordering of a whole span and reconstruct it,
so a badly ordered neighbourhood is fixed in ONE accepted move rather than a chain of intermediate
states the acceptance test may refuse.

Measured motivation: from a deliberately bad start the solver needed about 13x the time a greedy
start needed to reach the same objective, at n=500 capacity 400.

## The seam: WHERE and HOW are separate

```
_choose_span()                 -> (route, start, stop)      WHERE
_reorder(points, left, right)  -> span-relative order, []   HOW
```

Everything between them is written once in the base: fixed endpoints, the permutation mapping, and
the degenerate cases. A new span rule is one method. A new reordering algorithm is one method. They
compose without touching each other.

Fixed endpoints are the nodes **outside** the span -- the neighbouring visits, or the route's depots
at the ends. That is what makes a whole-route rebuild well posed.

Selection only. `PermuteChain` applies an arbitrary permutation and inverts it to revert, so there is
no new delta math and no new revert path anywhere in this family.

## The tree

```
_SpanReorderBase
├── _FarthestInsertionReorderBase    -> farthest_insertion_ops.md
│   ├── ReorderSpanByFarthestInsertion
│   ├── ReorderRandomRouteByFarthestInsertion
│   └── ReorderLongRouteByFarthestInsertion
└── ReorderShortSpanExactly          -> below
```

**The inheritance is not only code reuse. It marks family boundaries for ablation and, later, for
selection.** Reasoning in
[design/operator_selection/family_selection.md](../operator_selection/family_selection.md).

## `ReorderShortSpanExactly`

A random span of at most `EXACT_REORDER_MAX_SPAN` customers, reordered **optimally**.

Farthest insertion lands ~16% above optimal. On a span this short the optimum is simply affordable,
so it is taken. `exact_span_order` searches by branch and bound between the fixed endpoints, picking
back-to-front and abandoning a branch as soon as its partial cost reaches the best complete answer
found.

Verified against full enumeration on 300 random spans, n in [3,8]: optimal every time, and never
worse than farthest insertion on the same input.

### Why it carries neither `exploit_only` nor a penalty factor

Both omissions are deliberate, and both are the opposite of the farthest-insertion family's needs.

**`exploit_only` has nothing to restrict.** The bound starts at the incumbent's own cost, so the
search returns something strictly better or the identity. A disimprovement is unreachable. The
farthest-insertion operators are heuristics and genuinely can build an ordering worse than the one
already there, which is what that flag exists for.

**A selection penalty would price the wrong thing.** Cost here is O(1) in problem size -- bounded by
K, independent of route length and customer count. The lever is therefore a **ceiling on K**, not a
discount on selection frequency.

| K | permutations |
|---|---|
| 6 | 720 |
| 8 | 40,320 |

That is the general point: **discount selection when cost scales with the problem; cap the scale
when it does not.** See
[../operator_selection/exploitation_governance.md](../operator_selection/exploitation_governance.md)
for the other half.

### Why K! is not the real cost

The bound is seeded from the **incumbent ordering**, which mid-solve the solver has already been
improving. A tight starting bound kills most branches within a few picks.

A distance matrix over the K points plus both anchors -- at most 100 entries -- is computed once per
call, so the search itself is integer lookups rather than `math.dist`.

**In theory the operator gets cheaper as a run converges**, because spans approach optimal and the
bound tightens. That would be a useful property, since late is when exact optimization is most
wanted. **Not measured.** Cost per call early versus late in a solve is the test.

### The farthest-insertion seed, and when it inverts

The bound also considers a farthest-insertion pass, taking whichever of the two is tighter. That
pays when the incumbent is poorly ordered.

**It can cost more than it saves when pruning is already good, or when the span is small.** In both
cases the O(K^2) pass approaches or exceeds the search it is meant to accelerate. Gating it needs a
progress signal the solver does not expose -- adjust the activation rule per
[planning/solver-progress-metric.md](../../planning/solver-progress-metric.md).

### Choosing K

**The lever is a ceiling on K, not a selection discount.** Cost is bounded by K and does not depend
on instance size, so discounting how often the operator is drawn prices the wrong thing. That is the
general rule stated above: discount selection when cost scales with the problem; cap the scale when
it does not.

**`max_span` is per instance, not a module constant.** `EXACT_REORDER_MAX_SPAN` is the default an
operator starts at, and each instance carries its own. That is what lets an ablation vary K without
touching solver code, and it is what
[planning/family-generation.md](../../planning/family-generation.md) needs to generate one operator
per K.

**The value is measured.** See `RESULTS.md`, "Span size, on the FULL roster", and
[planning/ablations.md](../../planning/ablations.md) for what remains open.

## `choose_random_nonempty_route_ordered`

Every operator in this family uses the **ordered** variant of route selection.

`choose_random_nonempty_route` sets empty routes aside with a swap-remove and re-adds them at the
end, which permutes `all_routes`. Operands are drawn **positionally**, so a permuted RouteSet changes
which route a later draw returns. Selection alone would then divert the search while leaving cost,
vehicle chains and depot membership perfectly intact -- correct by every value check and still wrong.

The ordered variant restores positions exactly via `undo_remove`, unwound LIFO. It is a separate
method so operators that do not need the guarantee do not pay for it.

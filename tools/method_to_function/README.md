# method_to_function

Two scripts that move methods off a class and into free functions, mechanically.

    class Route:                              def cost_deltas_if_removed(route: Route):
        def cost_deltas_if_removed(self):  ->     ...
            ...
    route.cost_deltas_if_removed()            cost_deltas_if_removed(route)

They are a pair and they run in order. `extract.py` produces the new bodies plus a manifest;
`rewire.py` reads that manifest and fixes the call sites. Each script's docstring carries its own
arguments and limits.

```bash
python tools/method_to_function/extract.py spec.json manifest.json SimAnn_VRP_Core_Model
python tools/method_to_function/rewire.py  manifest.json SimAnn_VRP_BLOperators.py tests/test_x.py
```

Neither writes the new modules. Assembling the lifted bodies into files, with whatever region
structure and import headers you want, is yours to do. `tools/free_names.py` reports what each
new module still needs imported.

## The two things that make them worth keeping

**Nothing is classified by hand.** `extract.py` reads `@staticmethod` and `@property` off the AST
and records the kind in the manifest. `rewire.py` dispatches on that. The first version of these
scripts kept the classification in a hand-written set, a name was missing from it, and one call was
silently rewritten as the wrong kind. A duplicated table is the defect this design removes.

**Formatting survives.** `extract.py` rewrites `self` through `tokenize`, so string literals are
never touched. `rewire.py` splices on AST node positions, so comments and line breaks inside a
rewritten call are preserved. That is what lets a behaviour-equivalence check afterwards mean
something: if the objective moves, the move is wrong, not the formatting.

## Verified against real input

Replayed on 2026-09-07 against the tree at `5d56b98`, the commit before these tools were used:

- `extract.py` reproduced all **51** lifted functions byte-identically, and derived 43 instance
  methods, 7 staticmethods and 1 property with no hand input.
- `rewire.py` reproduced the committed `SimAnn_VRP_BLOperators.py` at `c9090b6` **exactly**,
  across 12 call sites.

That refactor is recorded in
[planning/implemented/module-structure.md](../../planning/implemented/module-structure.md).

## Limits worth knowing before you trust them

- A method whose name is lifted from two classes with the SAME kind cannot be told apart by syntax.
  `rewire.py` exits rather than guessing. Split the move into two runs.
- `rewire.py` only rewrites what the AST sees. Commented-out code and dynamic dispatch through
  `getattr` are left alone, so grep for the old names afterwards.
- Neither script checks that the move is SAFE. Confirm first that nothing left behind calls what you
  are moving, or you create an import cycle.

# Operator selection

How the solver decides which operator to run next, and how often.

Selection is a two-stage thing. **Weighting** prices an operator from what it has achieved per unit
of time. **Drawing** turns those weights into a choice. The docs here cover the drawing, and the
adjustments applied to a weight before it is drawn on.

| doc | what it covers |
|---|---|
| [family_selection.md](family_selection.md) | The family tree. Operators carry a path; a node's weight is the MAX over its subtree; selection descends one level at a time instead of accumulating over the whole roster. |
| [share_floors.md](share_floors.md) | The guaranteed minimum share per root family, and the projection that enforces it without distorting the ratios between the families that are not clamped. |
| [exploitation_governance.md](exploitation_governance.md) | `exploit_only`, the per-operator selection penalty for operators whose cost scales with the problem, and the `adj_weights` mirror both are applied through. |
| [hierarchical_magnetism.md](hierarchical_magnetism.md) | Pulls an unproposed operator's weight toward its SIBLINGS, not the whole roster, so a rare reversal is not shrunk toward noise from a whole-route rebuild. |
| [dynamic_penalty.md](dynamic_penalty.md) | How an accepted move becomes a score, how weight EMAs that score, and the cost-ratio penalty that prices selection against wall-clock time. Includes the design defect that forced the current shape. |

**Reading order.** `family_selection.md` first -- it is the structure the other two attach to.
`share_floors.md` is a helper it calls. `exploitation_governance.md` predates the tree and describes
per-leaf adjustments, which now feed the family max as well. `hierarchical_magnetism.md` and
`dynamic_penalty.md` cover what actually decides a weight's value, and read well together.

## Everything unbuilt

Open selection work is in
[planning/operator-selection.md](../../planning/operator-selection.md), which frames it as three
related concerns: exploit-only against exploratory operators, expensive against cheap ones, and
running operators the solver has no time for.

**Ablations.** Several decisions here were made structurally and are unmeasured. They are listed in
[planning/ablations.md](../../planning/ablations.md).

## Re-measuring

Counts and shares in these docs carry a roster stamp and drift as operators are added. Regenerate
with:

```bash
.venv1/Scripts/python.exe tools/family_tree.py
```

## References

- [exploitation_governance.md](exploitation_governance.md) -- per-operator penalty and adj_weights mechanism
- [share_floors.md](share_floors.md) -- guaranteed minimum share and projection enforcement
- [family_selection.md](family_selection.md) -- the family tree structure that other mechanisms attach to
- [hierarchical_magnetism.md](hierarchical_magnetism.md) -- weight magnetism toward siblings instead of whole roster
- [planning/ablations.md](../../planning/ablations.md) -- operator ablation experiments and results
- [planning/operator-selection.md](../../planning/operator-selection.md) -- planning frame for the three mechanisms
- [dynamic_penalty.md](dynamic_penalty.md) -- score, weight EMA, cost-ratio penalty, and design defect

## Links to here

- [design/README.md](../README.md) -- parent index to design folder

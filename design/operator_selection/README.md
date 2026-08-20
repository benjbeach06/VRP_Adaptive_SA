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

**Reading order.** `family_selection.md` first -- it is the structure the other two attach to.
`share_floors.md` is a helper it calls. `exploitation_governance.md` predates the tree and describes
per-leaf adjustments, which now feed the family max as well.

## What is not here

**The scoring formula itself.** How an accepted move becomes a number is still undocumented in
`design/`; the formula is quoted for reference in
[planning/operator-selection.md](../../planning/operator-selection.md) until it gets a proper doc.

**Everything unbuilt.** Open selection work is in
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

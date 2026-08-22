"""Ablation arms for the operator roster.

    tools/ablate_param.py --param ablation_arm --configure ablation_arms:apply_arm \
                          --values 0 8 9 10 11 12 --runs 15 --seconds 600 --size 500

Arm definitions live HERE, not in the solver. An experiment must not put its configuration into
solver code -- the solver exposes `remove()` and `max_span`, and this file decides what to use them
for.

One arm always duplicates the control on purpose. Run as a separate arm it measures run-to-run
variance at identical settings, which is the noise floor every other arm is judged against.

**WHICH arm that is depends on the shipped `EXACT_REORDER_MAX_SPAN`.** Arms 0 and 7 do not set
`max_span`, so they take whatever the solver ships. The default was 8 when the K sweep ran, making
arm 12 the replicate. It is now 4, so **arm 8 is the replicate**. Check the default before reading a
replicate result.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from SimAnn_VRP_Operators import Family                              # noqa: E402

OPTIMIZED = (Family.INTRA_ROUTE, Family.REORDER, Family.OPTIMIZED)
FARTHEST = OPTIMIZED + (Family.FARTHEST_INSERTION,)
EXACT = OPTIMIZED + (Family.EXACT,)

# arm -> (name, families to remove, max_span or None, reaction_factor or None)
ARMS = {
    0:  ("control",          (),          None, None),
    1:  ("no-greedy",        (OPTIMIZED,), None, None),
    2:  ("exact-K7",         (FARTHEST,),  7,    None),
    3:  ("exact-K8",         (FARTHEST,),  8,    None),
    4:  ("exact-K9",         (FARTHEST,),  9,    None),
    5:  ("exact-K10",        (FARTHEST,),  10,   None),
    6:  ("farthest-only",    (EXACT,),     None, None),
    7:  ("no-weight-memory", (),           None, 1.0),
    # Full roster, only max_span varies.
    8:  ("full-K4",          (),           4,    None),
    9:  ("full-K5",          (),           5,    None),
    10: ("full-K6",          (),           6,    None),
    11: ("full-K7",          (),           7,    None),
    12: ("full-K8",          (),           8,    None),
}


def apply_arm(solver, value):
    """Configure a freshly built solver for one arm. Called once per run."""
    name, remove_paths, max_span, reaction = ARMS[int(value)]

    for path in remove_paths:
        solver.remove(path)

    if max_span is not None:
        for op in solver.operators:
            if hasattr(op, "max_span"):
                op.max_span = max_span

    if reaction is not None:
        solver.reaction_factor = reaction

    return name

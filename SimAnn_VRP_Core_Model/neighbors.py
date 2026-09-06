"""
Nearest-neighbor tables, and the dense-ID precondition they rest on.

Operand selection is where most of the solver's performance lives: the same move type accepts far
fewer proposals with a randomly chosen destination than with a geometrically chosen one. These
tables are what make the geometric choice O(1).

They are plain numpy arrays keyed by dense zero-based ID, which is why _require_dense_ids runs
over every customer and depot list the solution is handed.
"""
import numpy as np
from numpy import ndarray

from .basics import Num

#region Nearest-neighbor tables
# How many nearest customers each customer remembers. Consumed by the neighbor-guided operators,
# which scan a candidate route testing membership -- so this is "how wide is near", not a budget.
CUSTOMER_NEIGHBORS_K = 20

# How many nearest depots each customer remembers. Instances have very few depots, so this is
# usually all of them.
CUSTOMER_DEPOTS_K = 10


def nearest_indices(sources: ndarray, targets: ndarray, k: int, exclude_self: bool,
                    chunk: int = 512) -> list[tuple[int, ...]]:
    """
    For each row of `sources`, the indices of its `k` nearest rows in `targets`, nearest first.

    Chunked so peak memory is bounded by `chunk * len(targets)` rather than the full pairwise
    matrix -- 20MB per chunk at 5000 targets, against 200MB for the whole thing.

    O(len(sources) * len(targets)) work, but entirely inside numpy. An incremental "keep a sorted
    top-k, insert when closer than the last" loop has the same asymptotic cost with the Python
    interpreter's constant factor on top, which is around 100x worse here. Genuinely sub-quadratic
    needs a k-d tree or grid bucketing; neither is worth it below roughly 50k customers.

    Squared distances are compared, never rooted. sqrt is monotonic, so the ordering is identical
    and the per-pair cost drops.

    TIES BREAK BY INDEX, deterministically. Coordinates here are integers on a small lattice, so
    equal distances are common rather than exotic, and `argmin` -- which callers are replacing with
    these tables -- resolves a tie by taking the lowest index. lexsort reproduces that rule exactly;
    plain argsort would not, since its default quicksort is unstable.
    """
    limit = len(targets) - (1 if exclude_self else 0)
    k = min(k, limit)
    if k <= 0:
        return [() for _ in range(len(sources))]

    out: list[tuple[int, ...]] = []
    for start in range(0, len(sources), chunk):
        block = sources[start:start + chunk]
        squared = ((block[:, None, :] - targets[None, :, :]) ** 2).sum(axis=-1)
        if exclude_self:
            # sources IS targets here, so row i of this block is target start + i.
            for i in range(len(block)):
                squared[i, start + i] = np.inf

        # argpartition puts the k smallest in front, unordered; order just those k.
        candidates = np.argpartition(squared, k - 1, axis=1)[:, :k]
        distances = np.take_along_axis(squared, candidates, axis=1)
        # lexsort's LAST key is primary, so this is "by distance, then by index".
        order = np.lexsort((candidates, distances), axis=1)
        winners = np.take_along_axis(candidates, order, axis=1)
        out.extend(tuple(int(index) for index in row) for row in winners)
    return out


def _locations_array(nodes) -> ndarray:
    return np.asarray([node.location for node in nodes], dtype=float)


def _require_dense_ids(items, id_attr: str, label: str) -> None:
    """
    The tables index by ID directly, with no indirection, because every construction site in this
    repo numbers its nodes 0..n-1. Fail loudly rather than silently mis-associating neighbors.
    """
    for position, item in enumerate(items):
        if getattr(item, id_attr) != position:
            raise ValueError(
                f"{label} IDs must be dense and 0-based for the neighbor tables to index by ID: "
                f"position {position} has {id_attr}={getattr(item, id_attr)}.")
#endregion

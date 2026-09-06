"""
The core VRP data model: nodes, visits, routes, vehicles, and the solution that owns them.

This package was one 4940-line module. Splitting it changed no behaviour -- every class body and
free function below is the same code, in a smaller file. Import it exactly as before:

    from SimAnn_VRP_Core_Model import FullSolution, Depot, Customer, Vehicle
    import SimAnn_VRP_Core_Model as CM
    from SimAnn_VRP_Core_Model import *

WHERE THINGS LIVE
-----------------
    basics      Num, Chain, dist, and free helpers with no model dependency
    randomness  the one owned RNG stream, and the scalar draws from it
    nodes       Customer, Depot, VirtualDepot, and the two depot sentinels
    records     ObjectiveTermDelta, RawDeltaRecord, AccountingRecord
    visits      RouteVisit and its three concrete kinds, plus the union aliases
    routes      VehicleNode, FirstRoute, LastRoute, Route
    route_set   RouteSet
    vehicle     Vehicle
    neighbors   the nearest-neighbor tables and the dense-ID precondition
    solution    FullSolution, and the accounting sink

IMPORT ORDER BELOW IS LOAD-BEARING. `visits` MUST be imported before `routes`.
LastRouteVisit isinstance-tests Route and LastRoute at runtime, and Route builds and
isinstance-tests the visit classes, so the two modules genuinely need each other. `visits` closes
that cycle with an import on its LAST line, which resolves only if `visits` is the module already
being initialized when `routes` starts. Python runs this file before ANY submodule of the package,
whatever the entry point, so the order set here is the order every importer gets. Swap the two
lines and every entry point raises ImportError.
"""

# These are re-exported deliberately, not left over. `from SimAnn_VRP_Core_Model import *` has
# always leaked this header into its consumers -- SimAnn_VRP.py, SimAnn_VRP_BLOperators.py and
# tools/ablate.py all star-import from here, and SimAnn_VRP_Operators.py then SimAnn_VRP_Solver.py
# re-export that star transitively. Keeping the header verbatim keeps that surface identical.
#
# `all_errors`, `bisect_left`, `cumsum` and `dataclass` are unused by this package and were unused
# by the single-file version too. No consumer references them either. They are kept only so that
# this split provably changes nothing, and can be deleted in one commit of their own.
import copy
import random
from bisect import bisect_left
from dataclasses import dataclass
from ftplib import all_errors

from itertools import chain

import numpy as np
from numpy import cumsum, ndarray

from typing import Any, List, DefaultDict, Iterable, Iterator, Mapping, Sequence, Collection
from types import MappingProxyType
from collections import defaultdict
from math import hypot, ceil

from functools import lru_cache
from enum import Enum, auto
from typing import NamedTuple

from abc import ABC

# --------------------------------------------------------------------------------------------
# The package itself. Dependency order, low to high. See the docstring on `visits` before routes.
# --------------------------------------------------------------------------------------------
from .basics import (Chain, Num, append_new_defaultdict_by_value_sum, as_chain_range,
                     combine_defaultdicts_by_value_sum, dist, from_iterable)

# solver_rng is deliberately NOT imported here. See __getattr__ at the bottom of this file.
from .randomness import (rand_choice, rand_distinct_indices, rand_index, rand_int_inclusive,
                         rand_shuffle, rand_unit, seed_solver_rng)

from .nodes import DEFAULT_DEPOT, VIRTUAL_DEPOT, Customer, Depot, Node, VirtualDepot

from .records import (INVERT_STRATEGIES_CHANGE_DICT, INVERT_STRATEGIES_DELTA_DICT, NO_CHANGES,
                      AccountingRecord, ObjectiveTermDelta, RawDeltaRecord, _chained, _summed,
                      invert_change_dict, invert_delta_dict)

# MUST precede `.routes`. See the import-order note in the module docstring.
from .visits import (CustomerLike, CustomerVisit, DepotLike, DepotVisit, FirstRouteVisit,
                     LastRouteVisit, NextRouteKind, NodeLike, RouteVisit, sub_permute_list,
                     sub_permute_path)

from .routes import FirstRoute, LastRoute, Route, VehicleNode

from .route_set import RouteSet

from .vehicle import Vehicle

from .neighbors import (CUSTOMER_DEPOTS_K, CUSTOMER_NEIGHBORS_K, _locations_array,
                        _require_dense_ids, nearest_indices)

from .solution import NO_TIME_LIMIT, FullSolution

from . import basics, neighbors, nodes, randomness, records, route_set, routes, solution, vehicle
from . import visits


def __getattr__(name: str):
    """Forward `solver_rng` to the module that owns it, so the name can never go stale.

    `seed_solver_rng` REBINDS the global in `randomness`. A plain `from .randomness import
    solver_rng` here would take a snapshot at package-import time, and every read of
    `SimAnn_VRP_Core_Model.solver_rng` after a reseed would hand back the OLD generator -- while
    every `rand_*` call drew from the new one. Two streams, silently, in a solver whose runs are
    long random walks. That is a determinism bug, not a tidiness one.

    Leaving the name unbound here routes each read through this hook instead, which reads the
    live global. It costs nothing on the hot path: the `rand_*` functions live in `randomness`
    alongside `solver_rng` and resolve it as an ordinary module global.
    """
    if name == "solver_rng":
        from . import randomness
        return randomness.solver_rng
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

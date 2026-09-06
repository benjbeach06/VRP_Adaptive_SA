"""
Scalar types and free helpers with no model dependency at all.

Everything here is importable by any other module in the package, and this module imports nothing
from it. That is the whole rule for the file: a helper that needs to know what a Route is does not
belong here.
"""
from collections import defaultdict
from functools import lru_cache
from itertools import chain
from math import hypot
from typing import Any

from_iterable = chain.from_iterable

Num = float | int

# A run of consecutive customers within one route, addressed by position. One index is the
# single-customer case, so every chain operation subsumes the single-customer one and there is no
# second code path to keep in agreement.
Chain = int | range


def as_chain_range(customer_chain: Chain) -> range:
    """Normalise a Chain to a half-open range. Call this ONCE at the top of any chain method, so
    the rest of the body never has to ask which form it was handed."""
    return range(customer_chain, customer_chain + 1) if isinstance(customer_chain, int) else customer_chain

def combine_defaultdicts_by_value_sum[T1: Any](dict1: defaultdict[T1, Any], dict2: defaultdict[T1, Any]) -> defaultdict[T1, Any]:
    # Copy-combines and returns new
    result: defaultdict[T1, Any] = defaultdict(dict1.default_factory)

    all_keys = dict1.keys() | dict2.keys()

    for key in all_keys:
        result[key] = dict1[key] + dict2[key]

    return result

def append_new_defaultdict_by_value_sum[T1: Any](dict1: defaultdict[T1, Any], dict2: defaultdict[T1, Any]) -> None:
    for key in dict2.keys():
        dict1[key] += dict2[key]


@lru_cache(maxsize=10000)
def dist(loc1: tuple[Num, Num], loc2: tuple[Num, Num]) -> Num:
    (x1, y1) = loc1
    (x2, y2) = loc2
    return hypot(x2 - x1, y2 - y1)



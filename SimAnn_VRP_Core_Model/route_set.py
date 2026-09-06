"""
RouteSet: a set of Routes that also supports O(1) random choice.

A plain `set` cannot be sampled in constant time, and the solver samples routes constantly. This
keeps a list beside an index map, so add, remove, membership and `choose_random` are all O(1) --
at the cost of not preserving insertion order across removals.

Routes key by object IDENTITY throughout, which is what makes the index map safe under mutation:
identity survives an apply -> revert cycle, because split_at refills the original object rather
than constructing a fresh one.
"""
from typing import Collection, Iterable, Iterator, List

from .randomness import rand_choice, rand_distinct_indices
from .routes import Route

class RouteSet:
    """Class for a set supporting random choice. Expanded and optimized greatly from Gemini-generated version."""
    """A set-like container supporting O(1) add, remove, lookups, and random choice."""
    __slots__ = "_items", "_idx_map"

    def __init__(self, iterable: Iterable[Route] = ()):
        self._items: list[Route] = []
        self._idx_map: dict[Route, int] = {}
        for item in iterable:
            self.add(item)


    # NOTE on ORDER: removal is swap-with-last, so a remove -> add round trip restores membership
    # but NOT position. That matters because the solver picks operands positionally
    # (rand_choice indexes _items), so a permutation of this list silently changes which route a
    # random draw returns -- i.e. an operator's revert can be perfectly value-correct and still
    # divert the whole search. remove() therefore reports where it moved the displaced element,
    # and add() can put a re-added element straight back there; see undo_remove().

    @staticmethod
    def _add_given_fields(item: Route, items: list[Route], idx_map: dict[Route, int], size,
                          post_add_swap_index: int | None = None) -> bool:
        if item in idx_map:
            return False

        idx_map[item] = size
        items.append(item)

        # Only meaningful for a TRUE add (we returned above otherwise): put the newly appended
        # item back at post_add_swap_index and push whatever sits there to the end -- the exact
        # inverse of the swap-with-last that removal performs.
        if post_add_swap_index is not None and post_add_swap_index != size:
            assert post_add_swap_index is not None # Linter is dumb hurr durr
            displaced = items[post_add_swap_index]
            items[post_add_swap_index] = item
            items[size] = displaced
            idx_map[item] = post_add_swap_index
            idx_map[displaced] = size

        return True

    def add(self, item: Route, post_add_swap_index: int | None = None) -> bool:
        return RouteSet._add_given_fields(item, self._items, self._idx_map, self.__len__(),
                                          post_add_swap_index)

    def undo_remove(self, item: Route, swap_index: int | None) -> bool:
        """
        Re-add `item` at the position it occupied before a remove(), restoring this set's ORDER
        and not just its membership. `swap_index` is remove()'s return value.
        """
        return self.add(item, post_add_swap_index=swap_index)

    @staticmethod
    def _remove_existing_item_given_fields(item: Route, idx: int, items: List[Route], idx_map: dict[Route, int]) -> int:
        # Not worth doing this only if needed: cpu instruction flushing is worse than just 3 ops unnecessarily
        last_item = items[-1]

        # Swap target item with the last item in the list
        items[idx] = last_item
        idx_map[last_item] = idx

        # Remove the target item
        items.pop()
        del idx_map[item]

        # Where the removed item sat, so undo_remove() can restore ordering exactly.
        return idx

    def remove(self, item: Route) -> int:
        idx_map = self._idx_map
        if item not in idx_map:
            raise KeyError(item)

        idx = idx_map[item]
        return RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def discard(self, item: Route) -> int | None:
        idx_map = self._idx_map
        if item not in idx_map:
            return None

        idx = idx_map[item]
        return RouteSet._remove_existing_item_given_fields(item, idx, self._items, idx_map)

    def clear(self):
        self._items.clear()
        self._idx_map.clear()

    def choose_random(self) -> Route:
        """Return a random element in O(1) time."""
        if not self._items:
            raise IndexError("Cannot select from an empty RandomSet")
        return rand_choice(self._items)

    def pop_random(self) -> Route:
        """Remove and return a random element in O(1) time."""
        item = self.choose_random()
        self.remove(item)

        return item

    def choose_n(self, n: int) -> list[Route]:
        """Return n distinct random elements without removing them."""
        indices = rand_distinct_indices(len(self._items), n)
        return [self._items[i] for i in indices]

    def pop_n(self, n: int) -> list[Route]:
        """Remove and return n distinct random elements."""
        chosen = self.choose_n(n)
        self.difference_update(chosen)
        return chosen

    def pop_all(self, items: Iterable[Route]) -> list[Route]:
        """Remove and return all given items at once (each must already be present)."""
        items = list(items)
        self.difference_update(items)
        return items

    def update(self, iterable: Iterable[Route]):
        add = self._add_given_fields
        items = self._items
        idx_map = self._idx_map
        size = len(items)

        for item in iterable:
            size+=add(item, items, idx_map, size)

    def difference_update(self, iterable: Iterable[Route]) -> list[tuple[Route, int]]:
        """
        Remove every item of `iterable` that is present.

        Returns (item, swap_index) records in REMOVAL ORDER -- exactly the order and format
        undo_difference_update() expects, so an undoable removal is just:
            removed = routes.difference_update(victims)
            ...
            routes.undo_difference_update(removed)
        """
        items = self._items
        idx_map = self._idx_map
        remove = RouteSet._remove_existing_item_given_fields
        removed: list[tuple[Route, int]] = []
        for item in iterable:
            if item in idx_map:
                idx = idx_map[item]
                remove(item, idx, items, idx_map)
                removed.append((item, idx))
        return removed

    def undo_difference_update(self, removed: list[tuple[Route, int]]) -> None:
        """
        Exact inverse of difference_update: restores membership AND position.

        Replayed in reverse, because each recorded swap_index is only meaningful against the
        state that immediately preceded that particular removal.
        """
        for item, swap_index in reversed(removed):
            self.undo_remove(item, swap_index)

    def difference(self, other: Iterable[Route]) -> RouteSet:
        diff = RouteSet(self)
        diff.difference_update(other)
        return diff

    def union(self, other: Iterable[Route]) -> RouteSet:
        union = RouteSet(self)
        union.update(other)
        return union

    def intersection(self, other: Iterable[Route]) -> RouteSet:
        if isinstance(other, RouteSet|set):
            return self.intersection_with_set(other)

        return RouteSet(item for item in other if item in self)

    def intersection_with_set(self, other: set[Route] | RouteSet):
        if self.__len__() < len(other):
            return RouteSet(item for item in self if item in other)
        else:
            return RouteSet(item for item in other if item in self)

    def intersection_update(self, other: Iterable[Route]):
        other_set = other if isinstance(other, RouteSet|set) else set(other)

        remove = self._remove_existing_item_given_fields
        items = self._items
        idx_map = self._idx_map
        num_items = len(items)

        i = 0
        while i<num_items:
            item = items[i]
            if item not in other_set:
                remove(item, i, items, idx_map)
                num_items -= 1
            else:
                i+=1

    def symmetric_difference(self, other: Iterable[Route]) -> RouteSet:
        if isinstance(other, set | RouteSet) and len(self) < len(other):
            # Special case: dest_route is large and already a set. We can operate without copying dest_route.
            symmetric_difference = RouteSet(self)
            symmetric_difference.symmetric_difference_update_with_set(other)
            return symmetric_difference

        symmetric_difference = RouteSet(other)
        symmetric_difference.symmetric_difference_update_with_set(self)
        return symmetric_difference

    def symmetric_difference_update(self, other: Iterable[Route]):
        other_set = other if isinstance(other, RouteSet|set) else set(other)
        self.symmetric_difference_update_with_set(other_set)

    def symmetric_difference_update_with_set(self, other_set: set | RouteSet):
        remove = RouteSet._remove_existing_item_given_fields
        add = RouteSet._add_given_fields

        items = self._items
        idx_map = self._idx_map

        size = len(self)

        for item in other_set:
            if item in idx_map:
                idx = idx_map[item]
                remove(item, idx, items, idx_map)
                size -= 1
            else:
                size += add(item, items, idx_map, size)

    def issuperset(self, other: Iterable[Route]):
        if isinstance(other, set|RouteSet) and len(self) < len(other):
            return False

        idx_map = self._idx_map
        return all(item in idx_map for item in other)

    def issuperset_of_set(self, other: set[Route]|RouteSet):
        # Can shortcut as soon as we know #unchecked other items > #unmatched self items
        if len(self) < len(other):
            return False

        idx_map = self._idx_map
        return all(item in idx_map for item in other)

    def issubset(self, other: Iterable[Route]):
        if isinstance(other, set):
            return other.issuperset(self)
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)

        # Like intersect but with possible early exit
        idx_map = self._idx_map
        intersect = RouteSet()
        num_matches = 0
        num_items = self.__len__()
        if num_matches == num_items:
            return True

        for item in other:
            if item in idx_map:
                is_new = intersect.add(item)
                num_matches += is_new
                if is_new and num_matches==num_items:
                    return True

        return False

    def issubset_of_set(self, other: set[Route] | RouteSet):
        if len(self) > len(other):
            return False
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)
        return other.issuperset(self)

    def issubset_of_collection(self, other: Collection[Route]):
        if isinstance(other, set):
            return other.issuperset(self)
        if isinstance(other, RouteSet):
            return other.issuperset_of_set(self)

        # You have more information than if other is Iterable: the length
        # But, less information than if other is set-like: can't check if items of self are in other or call other.superset

        # Can shortcut as soon as we know #unchecked other items > #unmatched self items
        idx_map = self._idx_map

        self_remaining = self.__len__()
        other_remaining = other.__len__()
        intersect = RouteSet()

        if self_remaining == 0:
            # Empty set is subset of all
            return True
        elif self_remaining > other_remaining:
            # Too many items in self
            return False

        for item in other:
            in_self = item in idx_map
            self_remaining -= in_self and intersect.add(item)
            other_remaining -= 1
            if self_remaining == 0:
                # All items in self have been seen in other!
                return True
            elif self_remaining > other_remaining:
                # Too many remaining unmatched items in self
                return False

        return False

    @staticmethod
    def _are_disjoint(set1: set[Route]|RouteSet, set2: Iterable[Route]) -> bool:
        for item in set2:
            if item in set1:
                return False

        return True

    def is_disjoint_with_set(self, other: set[Route]|RouteSet):
        if self.__len__() >= len(other):
            return RouteSet._are_disjoint(self, other)

        return RouteSet._are_disjoint(other, self)

    def is_disjoint(self, other: Iterable[Route]):
        return RouteSet._are_disjoint(self, other)

    def copy(self) -> RouteSet:
        return RouteSet(self)


    # Supports single indexing, but not slicing
    def __getitem__(self, idx: int) -> Route:
        return self._items[idx]

    def __contains__(self, item: object) -> bool:
        return item in self._idx_map

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Route]:
        return iter(self._items)

    def __add__(self, other: Iterable[Route]) -> RouteSet:
        return self.union(other)

    def __sub__(self, other: Iterable[Route]) -> RouteSet:
        return self.difference(other)

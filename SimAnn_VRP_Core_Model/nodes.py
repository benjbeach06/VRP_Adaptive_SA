"""
The physical node types -- Customer, Depot, and the virtual-depot placeholder -- plus the two
module-level depot sentinels.

These are the leaves of the model. A Node knows its location and nothing about routes, so this
module sits directly on top of `basics` and below everything else.

VIRTUAL_DEPOT lives here rather than beside Route (where it sat in the single-file version)
because `records` and `visits` both need it at runtime and neither may import the route classes.
Constructing it earlier changes nothing: VirtualDepot.__init__ reaches only Depot.__init__.
"""
from typing import TYPE_CHECKING

from .basics import Num, dist

if TYPE_CHECKING:
    from .visits import NodeLike

#region Core node definitions
class Node:
    __slots__ = "location"
    location: tuple[Num, Num]

    def __init__(self, location: tuple[Num, Num], **kwargs):
        self.location = location

    def distance(self, other: NodeLike | None) -> Num:
        if other is None: return 0 # Trick to help with type safety: distance with None is 0 (e.g. distance with prev visit but prev visit is None)
        return dist(self.location, other.location)

    def __copy__(self):
        cls = self.__class__

        # We bypass constructor since inherited classes may have different constructor arguments
        new_node = cls.__new__(cls)

        # We overwrite _copy_data when we need more data, leaving __copy__ alone
        new_node._copy_data(self)

        return new_node

    def _copy_data(self, source: Node):
        self.location = source.location

    #region  Convenience methods to check if a Node is a specific subclass.
    # Also, a nice reference for Node's subclasses
    @property
    def is_customer(self) -> bool:
        return isinstance(self, Customer)

    @property
    def is_depot(self) -> bool:
        return isinstance(self, Depot)

    @property
    def is_virtual_depot(self) -> bool:
        return isinstance(self, VirtualDepot)
    #endregion

class Depot(Node):
    __slots__ = "dID", "supply_limit", "vehicle_count"
    def __init__(self, dID: int=0, location: tuple[Num, Num]=(0, 0), supply_limit: int=-1, vehicle_count: int=-1, **kwargs):
        super().__init__(location=location, **kwargs)
        self.dID: int = dID
        self.supply_limit: Num = supply_limit
        self.vehicle_count: int = vehicle_count

    def _copy_data(self, source: Node):
        assert isinstance(source, Depot)

        super()._copy_data(source)
        self.dID = source.dID
        self.supply_limit = source.supply_limit
        self.vehicle_count = source.vehicle_count

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"DEP{self.dID}"

# Placeholder end depot for solution builders to pass into Route(...) while a route is still
# under construction and its real end depot hasn't been decided yet (e.g. Solver.make_initial_solution,
# where customers are appended before a real end depot is chosen). Deliberately a real Depot, not a
# VirtualDepot: at that point the route may already have real customers, so it isn't "virtual"/
# unassigned in the sense that skips depot-usage accounting -- it's just end-undecided. Always
# replaced by a real depot via set_end_depot before the route is added to a vehicle. Route itself
# takes end_depot as a required, non-optional argument -- this branching belongs in the builder,
# not in the core data model's hot construction path.
DEFAULT_DEPOT = Depot(dID=-1, location=(0, 0), supply_limit=-1, vehicle_count=-1)


class VirtualDepot(Depot):
    __slots__ = ()
    def __init__(self, **kwargs):
        super().__init__(dID=-1, **kwargs)

    def __eq__(self, other):
        # All virtual depots are treated as equal: just the placeholder depot
        # Result is True if both are virtual; matches object.__eq__ otherwise:
        # Cases are:
        # 1) If self is virtual, and dest_route is too, then this __eq__ is called and True is returned
        # 2) If self is virtual, and dest_route is not, this method is called and returns False (matches object.__eq__)
        # 3) if self is not virtual, object.__eq__ is called
        return isinstance(other, VirtualDepot)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"(ᅲ_ᅲ)"


class Customer(Node):
    __slots__ = "cID", "demand"
    cID: int
    demand: Num

    def __init__(self, cID:int=0, location: tuple[Num, Num]=(0, 0), demand: Num=5, **kwargs):
        super().__init__(location=location, **kwargs)
        self.cID = cID
        self.demand = demand

    def _copy_data(self, source: Node):
        assert isinstance(source, Customer)
        super()._copy_data(source)

        self.cID = source.cID
        self.demand = source.demand

    def __str__(self):
        return f"c{self.cID}"

    def __repr__(self):
        return str(self)

#endregion


# Shared virtual depot sentinel to cut down on object creation.
VIRTUAL_DEPOT = VirtualDepot()

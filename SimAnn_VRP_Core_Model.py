import copy
from collections import defaultdict
from math import sqrt, hypot

from functools import lru_cache
from typing import NamedTuple

class ObjectiveTermDelta(NamedTuple):
    travel_distance: float = 0
    vehicles_activated: int = 0
    depots_activated: int = 0
    routes_overloaded: int = 0

    def __pos__(self):
        return ObjectiveTermDelta(self.travel_distance, self.vehicles_activated, self.depots_activated, self.routes_overloaded)

    def __neg__(self):
        return ObjectiveTermDelta(-self.travel_distance, -self.vehicles_activated, -self.depots_activated, -self.routes_overloaded)

    def __add__(self, other):
        if not isinstance(other, ObjectiveTermDelta):
            raise ValueError("NamedTuples can be added only to other NamedTuples")

        return ObjectiveTermDelta(self.travel_distance + other.travel_distance, self.vehicles_activated + other.vehicles_activated,
                                  self.depots_activated + other.depots_activated, self.routes_overloaded + other.routes_overloaded)

    def __sub__(self, other):
        return self + (-other)

    def get_cost_delta(self, travel_unit_cost = 0.0, vehicle_cost = 0.0, depot_cost = 0.0, overload_penalty = 0.0):
        """
            Returns the change in cost implied by the deltas stored here, given objective coefficients.
        """
        return travel_unit_cost * self.travel_distance + vehicle_cost * self.vehicles_activated +\
            depot_cost * self.depots_activated + overload_penalty * self.routes_overloaded

    def get_cost_improvement(self, travel_unit_cost = 0.0, vehicle_cost = 0.0, depot_cost = 0.0, overload_penalty = 0.0, minimizing = True):
        """
           Returns the improvement value (positive = better) based on cost deltas and weights.
           If minimizing: improvement = -cost_delta (i.e., cost reduction is good).
           If maximizing: improvement = +cost_delta (i.e., increase is good).
        """
        sign = -1 if minimizing else 1
        return sign * self.get_cost_delta(travel_unit_cost, vehicle_cost, depot_cost, overload_penalty)

@lru_cache(maxsize=10000)
def dist(loc1, loc2):
    (x1, y1) = loc1
    (x2, y2) = loc2
    return hypot(x2 - x1, y2 - y1)

class Node:
    def __init__(self, location):
        self.location = location

    def distance(self, other):
        return dist(self.location, other.location)

class Depot(Node):
    def __init__(self, i=0, location=(0, 0), supply_limit=-1, vehicle_count=-1):
        super().__init__(location)
        self.i = i
        self.supply_limit = supply_limit
        self.vehicle_count = vehicle_count
        self.num_routes_starting_here = 0


    def __repr__(self):
        return f"{self.i}"

    @property
    def is_used(self): return self.num_routes_starting_here >= 1

class Customer(Node):
    def __init__(self, i=0, location=(0, 0), demand=5):
        super().__init__(location)
        self.i = i
        self.demand = demand

        self.route: Route = None
        self.prev_node: Node = None
        self.next_node: Node = None

    def __repr__(self):
        return f"{self.i}"

    # We choose not to use full objective deltas here: full related processing done in Route
    @property
    def distance_in(self):
        return self.distance(self.prev_node)

    @property
    def distance_out(self):
        return self.distance(self.next_node)

    @property
    def distance_surrounding(self):
        return self.distance_in + self.distance_out

    @property
    def distance_if_removed(self):
        return self.prev_node.distance(self.next_node)

    def get_removal_travel_delta(self):
        old_length = self.distance_surrounding
        new_length = self.distance_if_removed
        return new_length - old_length

    def is_adjacent_with(self, other):
        return other == self.prev_node or other == self.next_node

    def unlink_from_route(self):
        prev_is_customer = isinstance(self.prev_node, Customer)
        next_is_customer = isinstance(self.next_node, Customer)

        prev_node = self.prev_node
        next_node = self.next_node

        self.route = None
        self.prev_node = None
        self.next_node = None

        if prev_is_customer:
            prev_node.next_node = next_node
        if next_is_customer:
            next_node.prev_node = prev_node

def sub_permute_list(subpermutation, lst):
    # Applies subpermutation of list in place.
    if len(subpermutation) > len(lst):
        raise ValueError("Subpermutation is longer than the lst")
    if len(subpermutation) <= 1:
        return

    subpermutation_set = set(subpermutation)
    if len(subpermutation) != len(subpermutation_set):
        raise ValueError("Entries of Subpermutation.")
    if not subpermutation_set.issubset(set(range(len(lst)))):
        raise ValueError("Subpermutation indices must be in the range from 0 to the given list length - 1.")

    start = lst[subpermutation[0]]
    for i in range(len(subpermutation) - 1):
        lst[subpermutation[i]] = lst[subpermutation[i + 1]]
    lst[subpermutation[-1]] = start

class Route:
        # NOTE: Equality and hashing are identity-based to ensure performance in sets/lists, and to
        #   guarantee stability despite field mutability. Uniqueness is managed externally.

        # NOTE 2: All route-based operators herein assume you don't operate with empty routes - except for removing them from their vehicle!
        #   Thus: If combining with a route, or inserting self in a list, etc: we
        #   assume the moving route is nonempty. This simplifies the logic quite a bit in some places.
        #   HOWEVER: To ensure dynamic initial route building still works: we allow adding customers to an empty route

        def __init__(self, path: list[Customer], end_depot: Depot):
            self.path = path # List of customers
            self.end_depot = end_depot
            self.start_depot: Depot = None
            self.vehicle: Vehicle = None

            self.prev_route: Route = None
            self.next_route: Route = None

            self.current_load = 0
            if len(path) > 0:
                self.current_load = self.capacity_needed()
                #self.populate_derived_data()

            self.populate_derived_data()

            self.__eq__ = object.__eq__
            self.__hash__ = object.__hash__

            # Start_depot and vehicle will be filled out when the route is added to a vehicle.

        def set_values(self, path=None, vehicle=None, start_depot=None, end_depot=None):
            if path is not None:
                self.path = path
                self.populate_derived_data()
            if vehicle is not None:
                self.vehicle = vehicle
            if start_depot is not None:
                # Start depot must be where the vehicle left off.
                # So this is a derived quantity, but useful for reference nonetheless.
                self.set_start_depot(start_depot)
            if end_depot is not None:
                self.set_end_depot(end_depot)

        @property
        def path_len(self): return len(self.path)

        @property
        def path_is_cycle(self): return self.start_depot == self.end_depot

        @property
        def is_empty(self): return self.path_len == 0

        @property
        def is_trivial(self): return self.is_empty and self.path_is_cycle

        def is_adjacent_with(self, other):
            return other == self.prev_route or other == self.next_route

        #### Feasibility- and optimality-related computations
        def capacity_needed(self):
            if not self.path:
                return 0

            return sum(customer.demand for customer in self.path)

        def total_distance(self):
            if self.end_depot is None or self.vehicle is None:
                raise Exception("Route must be assigned to a vehicle to compute total distance")

            return self.first_move_distance() + self.tail_distance()

        def is_overloaded(self):
            return self.current_load > self.vehicle.capacity

        @property
        def amount_overloaded(self):
            return max(0, self.current_load - self.vehicle.capacity)

        ### Important logic to be used on "next route" and "this route" to determine effects of changing start and end depots.
        ### Affects: Insert self, remove self, change end depot of self.

        def get_depot_num_usage_deltas_if_start_depot_changes_to(self, new_start_depot: Depot):
            # Calculates, without considering previous routes: a dictionary of {depot: depot_num_use_delta}

            # Assuming the new start depot is different from the current one:
            # The current start depot loses a usage if it's currently counted (i.e. we're not trivial).
            # The next start depot gains a usage if it will be counted (i.e. we won't be trivial after adding it).

            start_depot = self.start_depot
            end_depot = self.end_depot

            result = defaultdict(int)

            if start_depot == new_start_depot:
                # Then there are no changes! Report this.
                return result

            start_depot_is_counted = not self.is_trivial
            new_start_depot_will_be_counted = not(self.is_empty and new_start_depot == end_depot)

            if start_depot_is_counted:
                result[start_depot] = -1

            if new_start_depot_will_be_counted:
                result[new_start_depot] = 1

            return result

        def get_depot_num_usage_deltas_if_removed(self):
            # Calculates a dictionary of {depot: depot_num_use_delta} that will result if self is removed from its vehicle.
            result = defaultdict(int)

            if self.is_trivial:
                return result

            next_route = self.next_route
            start_depot = self.start_depot

            old_next_start_depot = self.end_depot
            new_next_start_depot = start_depot

            result[start_depot] = -1

            if next_route is not None:
                depot_usage_deltas = next_route.get_depot_num_usage_deltas_if_start_depot_changes_to(new_next_start_depot)

                result[old_next_start_depot] += depot_usage_deltas[old_next_start_depot]
                result[new_next_start_depot] += depot_usage_deltas[new_next_start_depot]

            return result

        def get_depot_num_usage_deltas_if_inserted_at(self, vehicle, index):
            result = defaultdict(int)

            if self.is_empty:
                # We don't allow inserting empty routes anywhere! Report no change.
                return result

            next_route = None

            if index <= vehicle.num_routes - 1:
                next_route = vehicle.routes[index]

            if index == 0:
                start_depot = vehicle.initial_depot
            else:
                start_depot = vehicle.routes[index - 1].end_depot

            new_next_start_depot = self.end_depot

            result[start_depot] = 1

            if next_route is not None:
                old_next_start_depot = next_route.start_depot
                depot_usage_deltas = next_route.get_depot_num_usage_deltas_if_start_depot_changes_to(new_next_start_depot)

                result[old_next_start_depot] += depot_usage_deltas[old_next_start_depot]
                result[new_next_start_depot] += depot_usage_deltas[new_next_start_depot]

            return result

        def get_depot_num_usage_deltas_if_appended_to(self, vehicle):
            # Much simpler: there's no next route, so if we're not empty, we just report that our start depot gains a use.
            result = defaultdict(int)

            if self.is_empty:
                # We don't allow inserting empty routes anywhere! Report no change.
                return result

            start_depot = self.get_start_depot_for_append(vehicle)
            result[start_depot] = 1

            return result

        def get_depot_num_usage_deltas_if_end_depot_changes(self, new_end_depot: Depot):
            next_route = self.next_route
            if self.is_empty or next_route is None:
                # We don't allow changing end depots of empty routes! So if we're empty, report no change
                # If next route is None, then the change doesn't affect depot start counts. Still report no change.
                return defaultdict(int)

            return next_route.get_depot_num_usage_deltas_if_start_depot_changes_to(new_end_depot)

        @staticmethod
        def get_depot_activation_deltas_from_depot_usage_deltas(depot_usage_deltas):
            if not depot_usage_deltas:
                # No-changes case
                return 0

            result = 0
            """ Result will report:
            +1 for each depot that transitions from 0 to some uses,
            -1 for each that transitions from some uses to no uses.
            """
            for (depot, usage_deltas) in depot_usage_deltas.items():
                if usage_deltas > 0: # Depot gained uses - possible activation
                    result += int(depot.num_routes_starting_here == 0)
                elif usage_deltas < 0: # Depot lost uses - possible deactivation: if num uses lost == current routes starting here.
                    if depot.num_routes_starting_here < -usage_deltas:
                        raise ValueError("Usage deltas are incorrect! They exceed the current number of routes. "
                                         "Something went wrong with the bookkeeping for depot uses.")
                    result -= int(depot.num_routes_starting_here == -usage_deltas)

            return result

        @staticmethod
        def apply_depot_usage_deltas_to_depots(depot_usage_deltas):
            if not depot_usage_deltas:
                # No-changes case
                return

            for (depot, usage_deltas) in depot_usage_deltas.items():
                depot.num_routes_starting_here += usage_deltas
                if depot.num_routes_starting_here < 0:
                    raise ValueError("Usage deltas are incorrect! They exceed the current number of routes. "
                                     "Something went wrong with the bookkeeping for depot uses.")

        ### Linkage and internal data maintenance

        def unlink_from_vehicle(self):
            # Call as part of popping from vehicle. Takes care of bookkeeping.
            prev_route = self.prev_route
            next_route = self.next_route

            is_trivial = self.is_trivial

            if not is_trivial:
                # Update usages before mutating self - to prevent broken links from changing things.
                depot_usage_deltas = self.get_depot_num_usage_deltas_if_removed()
                self.apply_depot_usage_deltas_to_depots(depot_usage_deltas)


            start_depot = self.start_depot

            self.vehicle = None
            self.start_depot = None

            self.prev_route = None
            self.next_route = None

            if not self.is_empty:
                # Unlink first customer from start_depot
                self.path[0].prev_node = None

            if not next_route is None:
                # Update next_route's start depot to be this route's start depot
                next_route.set_start_depot(start_depot)

            if not (prev_route is None or next_route is None):
                # Hook them babies up!
                prev_route.next_route = next_route
                next_route.prev_route = prev_route

            if next_route is None and prev_route is not None:
                # Unlink prev_route from self
                prev_route.next_route = None

            if prev_route is None and next_route is not None:
                # Unlink next route from self
                next_route.prev_route = None



        def populate_derived_data(self):
            path = self.path
            path_len = len(path)

            if path_len == 0:
                self.current_load = 0
                return

            self.current_load = sum(c.demand for c in path)

            for (i, c) in enumerate(path):
                c.route = self
                if i == 0:
                    # Link start => c
                    c.prev_node = self.start_depot
                if i == path_len - 1:
                    # Link c => end
                    c.next_node = self.end_depot
                else:
                    # Link c <=> next_node
                    c.next_node = path[i + 1]
                    c.next_node.prev_node = c

        def link_customer(self, i):
            # Called at the end of insert or append or swap operation
            path = self.path
            path_len = self.path_len
            if i >= path_len:
                raise IndexError("Customer index out of range.")

            c = self.path[i]

            c.route = self
            if i == 0:
                # Link start => c
                c.prev_node = self.start_depot
            else:
                # Link prev_node <=> c
                prev_node = path[i - 1]
                c.prev_node = prev_node
                prev_node.next_node = c
            if i == path_len - 1:
                # Link c => end
                c.next_node = self.end_depot
            else:
                # Link c <=> next_node
                next_node = path[i + 1]

                c.next_node = next_node
                next_node.prev_node = c

        @staticmethod
        def unlink_customer(customer):
            # Called at the end of remove operation
            customer.unlink_from_route()

        def unlink_customer_at(self, i):
            # Called at the end of pop operation
            if i >= self.path_len:
                raise IndexError("Customer index out of range.")
            self.unlink_customer(self.path[i])

        def first_visit_node(self):
            return self.end_depot if self.path_len == 0 else self.path[0]

        def last_visit_node(self):
            return self.start_depot if self.path_len == 0 else self.path[-1]


        @staticmethod
        def get_start_depot_for_insertion(vehicle, index):
            num_routes = vehicle.num_routes
            routes = vehicle.routes

            if num_routes == 0 or index == 0:
                return vehicle.initial_depot
            else:
                prev_route = routes[index - 1]
                return prev_route.end_depot


        @staticmethod
        def get_start_depot_for_append(vehicle):
            num_routes = vehicle.num_routes
            routes = vehicle.routes

            if num_routes == 0:
                return vehicle.initial_depot
            else:
                prev_route = routes[-1]
                return prev_route.end_depot

        ### Methods to change start and end depot - while maintaining proper customer linkage.

        def set_end_depot(self, new_end_depot):
            if self.is_empty:
                raise ValueError("Cannot change end depot of an empty route.")

            if new_end_depot == self.end_depot:
                return

            # Handle bookkeeping for depot activation deltas: "My end depot changed".
            #   Must happen before self.end_depot is actually changed.
            num_end_depot_deltas = self.get_depot_num_usage_deltas_if_end_depot_changes(new_end_depot)
            self.apply_depot_usage_deltas_to_depots(num_end_depot_deltas)

            self.end_depot = new_end_depot
            self.path[-1].next_node = new_end_depot

            next_route = self.next_route
            if next_route is not None:
                next_route.set_start_depot(new_end_depot)

        def set_start_depot(self, new_start_depot):
            # New depot is derived from "previous node" information during other operations.
            # Depot bookkeeping is handled elsewhere. So here: we just need to change the start depot and
            # link the first customer to it.

            if new_start_depot == self.start_depot:
                return

            self.start_depot = new_start_depot
            if not self.is_empty:
                self.path[0].prev_node = new_start_depot


        ### Objective term delta computations related to removing, inserting, and appending self to/from a vehicle.
        # Possibilities: Travel distance could change. Vehicle could be activated/deactivated.
        #   Depot could be activated/deactivated. Amount of route overload could change.

        ## Depot-related computations
        def num_depot_activations_if_removed(self):
            if self.is_trivial:
                return 0

            depot_usage_deltas = self.get_depot_num_usage_deltas_if_removed()
            return self.get_depot_activation_deltas_from_depot_usage_deltas(depot_usage_deltas)

        def num_depot_activations_if_inserted_at(self, vehicle, index):
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So report 0 change

            depot_usage_deltas = self.get_depot_num_usage_deltas_if_inserted_at(vehicle, index)
            return self.get_depot_activation_deltas_from_depot_usage_deltas(depot_usage_deltas)

        def num_depot_activations_if_appended_to(self, vehicle):
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So report 0 change

            depot_usage_deltas = self.get_depot_num_usage_deltas_if_appended_to(vehicle)
            return self.get_depot_activation_deltas_from_depot_usage_deltas(depot_usage_deltas)

        ## Vehicle-related computations
        def remove_will_deactivate_vehicle(self):
            # Doubles to determine if destructing will deactivate the vehicle.
            # For deactivation to occur: Route must be nontrivial (implying vehicle activation),
            #   the next route must be trivial after this route is removed, and
            #   all but this route and the next route must be trivial
            # Assume: Caller has not yet concluded that the vehicle is already inactive.

            if self.is_trivial:
                return False

            # If reaching this point: route is nontrivial, thus vehicle is active.

            next_route = self.next_route
            if next_route is not None and not \
                    (next_route.is_empty and next_route.end_depot == self.start_depot):
                # Next route is nontrivial after removal
                return False

            if not all(route.is_trivial for route in self.vehicle.routes if route not in {self, next_route}):
                # Some other route is nontrivial
                return False

            return True

            # Note: a route removal can never activate a vehicle, as a deactivated vehicle
            #   has only trivial routes: the vehicle never move

        def insert_will_activate_vehicle(self, vehicle, already_guaranteed_inactive=False):
            # For activation to occur: Vehicle must be deactivated (any routes trivial), and
            #   the route must be nontrivial.
            # already_guaranteed_inactive - allows performance optimization if vehicle was precomputed as inactive.

            if self.is_empty:
                return False # We don't operate with empty routes except for removal! So return 0 change

            vehicle_is_inactive = already_guaranteed_inactive or not vehicle.is_used
            return vehicle_is_inactive

        def append_will_activate_vehicle(self, vehicle, already_guaranteed_inactive=False):
            # Index irrelevant for determining vehicle activation - so logic same as insert.
            return self.insert_will_activate_vehicle(vehicle, already_guaranteed_inactive)

        ## Travel-related computations
        def travel_delta_if_removed(self):
            if self.is_trivial:
                return 0

            next_route = self.next_route

            # Compute travel delta:
            #   For removal, this comes only from the first move in any next route, and losing the first move in the
            #   current route.
            old_distance = self.first_move_distance()
            new_distance = 0
            if next_route is not None:
                old_distance += next_route.first_move_distance()

                next_node = next_route.first_visit_node()
                new_distance += self.start_depot.distance(next_node)

            return new_distance - old_distance

        def travel_delta_if_inserted_at(self, vehicle, index):
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            routes = vehicle.routes
            num_routes = vehicle.num_routes

            if index > num_routes:
                raise IndexError("Insertion index out of range.")

            next_route = None
            next_visit_node = None

            # Determine new starting depot and next visit node
            new_start_depot = self.get_start_depot_for_insertion(vehicle, index)

            if num_routes > 0 and index <= num_routes - 1:
                next_route = routes[index]
                next_visit_node = next_route.first_visit_node()

            # Compute cost deltas: first visit of this route and the next one (if any)
            old_distance = 0
            new_distance = new_start_depot.distance(self.first_visit_node())
            if next_route is not None:
                old_distance += next_route.first_move_distance()
                new_distance += self.end_depot.distance(next_visit_node)

            return new_distance - old_distance

        def travel_delta_if_appended_to(self, vehicle):
            return self.travel_delta_if_inserted_at(vehicle, len(vehicle.routes))

        ## Aggregated computations
        def cost_deltas_if_removed(self):
            # Also doubles as "travel delta if disposed"
            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            if self.is_trivial:
                return ObjectiveTermDelta() # Delta = 0

            travel_delta = self.travel_delta_if_removed()

            # Compute vehicle activation delta
            # Vehicle is deactivated if all of vehicle's other routes are unused
            vehicle_activation_delta = -int(self.remove_will_deactivate_vehicle())

            # Compute depot activation delta
            # Depot is deactivated if self's start depot has only one route
            depot_activation_delta = self.num_depot_activations_if_removed()

            # Compute overload delta: -(amount route is overloaded for the current vehicle)
            overload_delta = -self.amount_overloaded

            return ObjectiveTermDelta(travel_delta, vehicle_activation_delta, depot_activation_delta, overload_delta)

        def cost_deltas_if_inserted_at(self, vehicle, index):
            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            if self.is_empty:
                return ObjectiveTermDelta() # Delta = 0. (We don't allow inserting empty stuff - so return 0.)

            travel_delta = self.travel_delta_if_inserted_at(vehicle, index)

            # Compute vehicle activation delta
            # Vehicle is activated if all of vehicle's other routes are unused
            vehicle_activation_delta = int(self.insert_will_activate_vehicle(vehicle))

            # Compute depot activation delta
            # Depot is deactivated if self's start depot has no routes
            depot_activation_delta = self.num_depot_activations_if_inserted_at(vehicle, index)

            # Compute overload delta: amount route will be overloaded for the target vehicle
            overload_delta = max(0, self.current_load - vehicle.capacity)

            return ObjectiveTermDelta(travel_delta, vehicle_activation_delta, depot_activation_delta, overload_delta)

        def cost_deltas_if_appended_to(self, vehicle):
            # Returns: travel_delta, depot_used_delta, vehicle_used_delta, overload_delta
            if self.is_empty:
                return ObjectiveTermDelta() # Delta = 0. (We don't allow inserting empty stuff - so return 0.)

            travel_delta = self.travel_delta_if_appended_to(vehicle)

            # Compute vehicle activation delta
            # Vehicle is activated if all of vehicle's other routes are unused
            vehicle_activation_delta = int(self.append_will_activate_vehicle(vehicle))

            # Compute depot activation delta
            # Depot is deactivated if self's start depot has no routes
            depot_activation_delta = self.num_depot_activations_if_appended_to(vehicle)

            # Compute overload delta: amount route will be overloaded for the target vehicle
            overload_delta = max(0, self.current_load - vehicle.capacity)

            return ObjectiveTermDelta(travel_delta, vehicle_activation_delta, depot_activation_delta, overload_delta)

        def cost_deltas_if_split(self, split_index, refill_depot: Depot):
            path = self.path
            path_len = self.path_len

            if split_index < 0 or split_index >= path_len:
                return 0 # Invalid operation

            if split_index == 0 or 1 >= path_len or path_len == split_index:
                return 0 # We only allow splits if both resulting paths are nonempty

            ## Compute each relevant delta

            # Travel
            split_customer_1 = self.path[split_index-1]
            split_customer_2 = self.path[split_index]

            old_distance = split_customer_1.distance_out
            new_distance = split_customer_1.distance(refill_depot) + refill_depot.distance(split_customer_2)
            travel_delta = new_distance - old_distance

            # Depot activation
            depot_activation_delta = int(refill_depot.num_routes_starting_here == 0)


            # Capacity overloading
            old_overload = self.amount_overloaded

            split2_load = sum(customer.demand for customer in path[split_index:])
            split1_load = self.current_load - split2_load

            split1_new_overload = max(0, split1_load - self.vehicle.capacity)
            split2_new_overload = max(0, split2_load - self.vehicle.capacity)

            overload_delta = split1_new_overload + split2_new_overload - old_overload


            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta, routes_overloaded=overload_delta)

        ### Operations: disposal, pop, append, insert.
        def should_dispose(self):
            # Routes should be explicitly disposed of by an SA operator if they don't move
            # This method returns true if the route is trivial: a move from start_depot to start_depot.
            return self.is_trivial

        def can_dispose(self):
            # Routes disposal can only be triggered by an SA operator - and only if they serve no customers.
            # This method returns true if route disposal won't eliminate customers from the working route.
            return self.is_empty

        def dispose(self):
            # Note: this may sometimes be called if the end depot mismatches the start depot. However, the route pop
            #   should take care of all accounting for depot route-starting-counting logic in any case.
            #   In this case, also, travel distances and (possibly) vehicle usage counts will be affected by disposal.
            #   pop_route calls unlink_from_vehicle - which helps with disposal.
            self.vehicle.remove_route(self)

        ### Customer operations
        def insert_customer(self, customer, index):
            # Just inserts the customer. Updates start depot's "num_used" if the route was trivial pre-insert.
            if self.is_trivial:
                self.start_depot.num_routes_starting_here += 1

            self.path.insert(index, customer)
            self.current_load += customer.demand

            self.link_customer(index)

        def append_customer(self, customer):
            # Just appends the customer. Updates start depot's "num_used" if the route was trivial pre-insert.
            if self.is_trivial:
                self.start_depot.num_routes_starting_here += 1

            self.path.append(customer)
            self.current_load += customer.demand

            self.link_customer(self.path_len-1)

        def remove_customer(self, customer):
            # Caution: This is more expensive than pop_customer_at:
            #   It requires an unordered search for customer in path, on top of
            #   the normal list removal cost.
            #   Updates start depot's "num_used" if the route becomes trivial post-remove.
            self.current_load -= customer.demand
            customer.unlink_from_route()
            self.path.remove(customer)

            if self.is_trivial:
                # We've already removed the customer, so it's possible we're trivial post-removal.
                self.start_depot.num_routes_starting_here -= 1

        def pop_customer_at(self, index):
            # Pops the route customer at split_index and returns it.
            #   Updates start depot's "num_used" if the route becomes trivial post-pop.
            self.current_load -= self.path[index].demand
            self.unlink_customer_at(index)
            customer = self.path.pop(index)

            if self.is_trivial:
                # We've already removed the customer, so it's possible we're trivial post-removal.
                self.start_depot.num_routes_starting_here -= 1

            return customer

        def split_at(self, split_index, refill_depot: Depot):
            # Removes the customers at or after the index. Then returns a new route with those customers and
            # the given end depot. Idea is that vehicle will handle the insertion of the new route.
            path = self.path
            path_len = self.path_len

            if split_index < 0 or split_index >= path_len:
                raise IndexError("split_index out of range")

            if split_index == 0 or 1 >= path_len or path_len == split_index:
                return None  # No split to do: one route or the other has all the items!!

            # Update linking for new next node.
            self.path[-1].next_node = refill_depot

            # Update new end depot route count
            refill_depot.num_routes_starting_here += 1

            # Make the new route. Implicitly will update linkage of the new customers.
            new_route = Route(path[split_index:], self.end_depot)

            # Remove the tail of the path from the original route, and update this route's depot and load information
            self.path = path[:split_index]

            # We use change_end_depot to ensure that all depot accounting is correct (and
            # self.end_depot=next_route.start_depot as expected) before we insert the new route after this one.
            self.set_end_depot(refill_depot)
            self.current_load -= new_route.current_load

            return new_route  # Return it for addition to all_routes

        ### Objective term deltas for customer operations
        ## Precomp: will operations activate/deactivate self?
        def customer_remove_will_deactivate(self):
            return self.path_len == 1 and self.path_is_cycle

        def customer_pop_will_deactivate(self):
            return self.customer_remove_will_deactivate()

        def customer_insert_will_activate(self):
            return self.path_len == 0 and self.path_is_cycle

        def customer_append_will_activate(self):
            return self.customer_insert_will_activate()

        ## Travel-related deltas
        @staticmethod
        def get_customer_remove_travel_delta(customer):
            return customer.get_removal_travel_delta()

        def get_customer_pop_travel_delta(self, index):
            if index >= self.path_len:
                raise IndexError("Customer index out of range.")
            return self.get_customer_remove_travel_delta(self.path[index])

        def get_customer_insert_travel_delta(self, customer, index):
            # Returns the travel time cost incurred by inserting a customer
            path = self.path
            path_len = len(path)

            start_depot = self.start_depot
            end_depot = self.end_depot

            if index > path_len:
                raise IndexError("Insertion index out of range")

            # customer is not yet inserted - so must rely on indexing to get costs
            prev_node = start_depot if index == 0 else path[index - 1]
            next_node = end_depot if index == path_len else path[index]

            old_distance = prev_node.distance(next_node)
            new_distance = prev_node.distance(customer) + customer.distance(next_node)

            return new_distance - old_distance

        def get_customer_append_travel_delta(self, customer):
            path = self.path
            path_len = len(path)

            start_depot = self.start_depot
            end_depot = self.end_depot

            # customer is not yet inserted - so must rely on indexing to get costs
            prev_node = start_depot if path_len == 0 else path[-1]
            next_node = end_depot

            old_distance = prev_node.distance(next_node)
            new_distance = prev_node.distance(customer) + customer.distance(next_node)

            return new_distance - old_distance

        ## Vehicle activation deltas
        def customer_remove_will_deactivate_vehicle(self):
            # For a customer removal to deactivate our vehicle:
            #   It must make us trivial, and this must be the only nontrivial route.
            return self.customer_remove_will_deactivate() and \
                all(route.is_trivial for route in self.vehicle.routes if route != self)

        def customer_pop_will_deactivate_vehicle(self):
            return self.customer_remove_will_deactivate_vehicle()

        def customer_insert_will_activate_vehicle(self, already_guaranteed_inactive=False):
            if not self.customer_insert_will_activate():
                return False

            # From here: we've activated the route, so the vehicle activates if and only if it's already inactive
            return already_guaranteed_inactive or not self.vehicle.is_used

        def customer_append_will_activate_vehicle(self, already_guaranteed_inactive=False):
            return self.customer_insert_will_activate_vehicle(already_guaranteed_inactive)


        ## Depot activation deltas
        def customer_remove_will_deactivate_depot(self):
            return self.customer_remove_will_deactivate() and self.start_depot.num_routes_starting_here == 1

        def customer_pop_will_deactivate_depot(self):
            return self.customer_remove_will_deactivate_depot()

        def customer_insert_will_activate_depot(self):
            return self.customer_insert_will_activate() and self.start_depot.num_routes_starting_here == 0

        def customer_append_will_activate_depot(self):
            return self.customer_insert_will_activate_depot()


        ## Overload deltas
        def customer_remove_overload_delta(self, customer):
            return max(0, self.current_load - customer.demand - self.vehicle.capacity) - self.amount_overloaded

        def customer_pop_overload_delta(self, index):
            return self.customer_remove_overload_delta(self.path[index])

        def customer_insert_overload_delta(self, customer):
            return max(0, self.current_load + customer.demand - self.vehicle.capacity) - self.amount_overloaded

        def customer_append_overload_delta(self, customer):
            return self.customer_insert_overload_delta(customer)

        ## Full deltas for customer operations. These report full ObjectiveTermDelta values.
        def get_customer_remove_deltas(self, customer):
            travel_delta = self.get_customer_remove_travel_delta(customer)
            vehicle_delta = -self.customer_remove_will_deactivate_vehicle()
            depot_delta = -self.customer_remove_will_deactivate_depot()
            overload_delta = self.customer_remove_overload_delta(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta)

        def get_customer_pop_deltas(self, index):
            travel_delta = self.get_customer_pop_travel_delta(index)
            vehicle_delta = -self.customer_pop_will_deactivate_vehicle()
            depot_delta = -self.customer_pop_will_deactivate_depot()
            overload_delta = self.customer_pop_overload_delta(index)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta)

        def get_customer_insert_deltas(self, customer, index):
            travel_delta = self.get_customer_insert_travel_delta(customer, index)
            vehicle_delta = self.customer_insert_will_activate_vehicle()
            depot_delta = self.customer_insert_will_activate_depot()
            overload_delta = self.customer_insert_overload_delta(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta)

        def get_customer_append_deltas(self, customer):
            travel_delta = self.get_customer_append_travel_delta(customer)
            vehicle_delta = self.customer_append_will_activate_vehicle()
            depot_delta = self.customer_append_will_activate_depot()
            overload_delta = self.customer_append_overload_delta(customer)

            return ObjectiveTermDelta(travel_delta, vehicle_delta, depot_delta, overload_delta)

        """
        def get_end_depot_change_travel_delta(self, refill_depot):
            path = self.path
            path_len = len(path)
            
            start_depot = self.start_depot
            end_depot = self.end_depot
            
            prev_node = start_depot if (path_len == 0) else path[path_len - 1]
                        
            prev_distance = prev_node.distance(end_depot)
            new_distance = prev_node.distance(refill_depot)
                        
            return new_distance - prev_distance
        """


        #### Miscellaneous path distance computations. Any of these could be useful in computing cost deltas within
        ####    solution operators.
        def first_move_distance(self):
            path = self.path
            path_len = len(path)
            start_depot = self.start_depot
            end_depot = self.end_depot

            if path_len == 0:
                start_dist = start_depot.distance(end_depot)
            else:
                start_dist = start_depot.distance(path[0])

            return start_dist

        def last_move_distance(self):
            path = self.path
            path_len = len(path)
            end_depot = self.end_depot

            if path_len == 0:
                return self.first_move_distance()  # There can be only one (move)

            return end_depot.distance(path[-1])

        def first_and_last_move_distance(self):
            if len(self.path) == 0:
                return self.first_move_distance()  # There can be only one (move)

            return self.first_move_distance() + self.last_move_distance()

        def mid_distance(self):
            path = self.path
            path_len = len(path)

            if path_len == 0:
                return 0 # Nothing to see here!

            return sum(path[i].distance(path[i + 1]) for i in range(path_len - 1))

        def tail_distance(self):
            # Returns total distance, minus first node
            path = self.path
            path_len = len(path)
            end_depot = self.end_depot

            if path_len == 0:
                return 0 # Nothing to see here!

            end_dist = end_depot.distance(path[-1])
            mid_dist = sum(path[i].distance(path[i+1]) for i in range(path_len-1))
            return mid_dist + end_dist

        ### Cost computations for combining, swapping, permuting
        ## Changing end depot
        def end_depot_change_travel_delta(self, new_end_depot: Depot):
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            next_route = self.next_route
            last_visit = self.last_visit_node()

            old_distance = self.last_move_distance()
            new_distance = last_visit.distance(new_end_depot)

            if next_route is not None:
                next_visit = next_route.first_visit_node()

                old_distance += next_route.first_move_distance()
                new_distance += new_end_depot.distance(next_visit)

            return new_distance - old_distance

        # Since we don't allow operations (except removal and customer insertion) for empty routes:
        #   if we're changing the end depot, this route is nonempty, and so our vehicle is active and will remain so.


        def end_depot_change_depot_activation_delta(self, new_end_depot: Depot):
            if self.is_empty:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            depot_num_usage_deltas = self.get_depot_num_usage_deltas_if_end_depot_changes(new_end_depot)
            return self.get_depot_activation_deltas_from_depot_usage_deltas(depot_num_usage_deltas)

        def get_end_depot_change_deltas(self, new_end_depot: Depot):
            travel_delta = self.end_depot_change_travel_delta(new_end_depot)
            depot_activation_delta = self.end_depot_change_depot_activation_delta(new_end_depot)

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta)

        ## Combining another route with this one
        def combine_with_travel_delta(self, other):
            if self.is_empty or other.is_empty or self is other:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            # Travel for other's tail_distance was already accounted for.
            # This delta comes from a few changes:
            # 1) We no longer visit this route's end node
            # 2) We now visit the other route's first customer (the other route already visits its end node)
            # 3) If we have a next route: its first visit starts from a different vehicle
            old_distance = self.last_move_distance()
            new_distance = self.path[-1].distance(other.path[0])

            next_route = self.next_route
            if next_route is not None:
                next_visit = next_route.first_visit_node()

                old_distance += next_route.first_move_distance()
                new_distance += other.end_depot.distance(next_visit)

            return new_distance - old_distance

        # Combining cannot activate self.vehicle: we only allow combining with nonempty routes, so self must be nonempty!

        def combine_depot_activation_delta(self, other):
            if self.is_empty or other.is_empty or self is other:
                return 0 # We don't operate with empty routes except for removal! So return 0 change

            # self.end_depot is about to be replaced with other.end_depot. SO: Depot changes can happen if
            #   we have a next route, and the other's end depot is different from ours
            next_route = self.next_route
            if next_route is None or self.end_depot == other.end_depot:
                return 0

            # Depot changes are exactly as if we're just changing our end depot.
            return self.end_depot_change_depot_activation_delta(other.end_depot)

        def combine_overload_delta(self, other):
            if self.is_empty or other.is_empty or self is other:
                return 0 # We don't operate with empty routes except for removal! So return 0 change
            return max(0, self.current_load + other.current_load - self.vehicle.capacity) - self.amount_overloaded

        def get_combine_deltas(self, other):
            if self is other:
                raise ValueError("Cannot combine a route with itself")

            travel_delta = self.combine_with_travel_delta(other)
            depot_activation_delta = self.combine_depot_activation_delta(other)
            overload_delta = self.combine_overload_delta(other)

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_activation_delta, routes_overloaded=overload_delta)

        ## Swapping customers (can only change travel distance or overload routes)
        @staticmethod
        def get_adjacent_customer_swap_deltas(customer1):
            customer2 = customer1.next_node
            if not isinstance(customer2, Customer):
                raise ValueError("Specified customer is at the end of a route.")

            prev_node = customer1.prev_node
            next_node = customer2.next_node

            old_distance = prev_node.distance(customer1) + customer1.distance(customer2) + customer2.distance(next_node)
            new_distance = prev_node.distance(customer2) + customer2.distance(customer1) + customer1.distance(next_node)

            travel_delta = new_distance - old_distance
            return ObjectiveTermDelta(travel_distance=travel_delta)

        # Adjacent swap
        def get_adjacent_customer_swap_deltas_at(self, index):
            # Get cost for swapping customer at index with the next one.
            if index >= self.path_len - 1:
                if index == self.path_len - 1:
                    raise ValueError("Specified customer has no next customer.")
                else:
                    raise ValueError("Customer index out of range.")

            path = self.path
            customer1 = path[index]

            return self.get_adjacent_customer_swap_deltas(customer1)

        # Nonadjacent swap
        @staticmethod
        def get_nonadjacent_customer_swap_travel_delta(customer1: Customer, customer2: Customer):
            prev_node_1 = customer1.prev_node
            prev_node_2 = customer2.prev_node

            next_node_1 = customer1.next_node
            next_node_2 = customer2.next_node

            old_distance = customer1.distance_surrounding + customer2.distance_surrounding
            new_distance_1 = prev_node_1.distance(customer2) + customer2.distance(next_node_1)
            new_distance_2 = prev_node_2.distance(customer1) + customer1.distance(next_node_2)

            return (new_distance_1 + new_distance_2) - old_distance

        @staticmethod
        def get_nonadjacent_customer_swap_overload_delta(customer1: Customer, customer2: Customer):
            if customer1 == customer2:
                return 0

            route1 = customer1.route
            route2 = customer2.route

            route1_load_delta = customer2.demand - customer1.demand
            route2_load_delta = -route1_load_delta

            route1_new_amount_overloaded = max(0, route1.current_load + route1_load_delta - route1.vehicle.capacity)
            route2_new_amount_overloaded = max(0, route2.current_load + route2_load_delta - route2.vehicle.capacity)

            route1_overload_delta = route1_new_amount_overloaded - route1.amount_overloaded
            route2_overload_delta = route2_new_amount_overloaded - route2.amount_overloaded

            return route1_overload_delta + route2_overload_delta

        @staticmethod
        def get_nonadjacent_customer_swap_deltas(customer1: Customer, customer2: Customer):
            travel_delta = Route.get_nonadjacent_customer_swap_travel_delta(customer1, customer2)
            overload_delta = Route.get_nonadjacent_customer_swap_overload_delta(customer1, customer2)

            return ObjectiveTermDelta(travel_distance=travel_delta, routes_overloaded=overload_delta)

        # Any two customers
        @staticmethod
        def get_customer_swap_deltas(customer1: Customer, customer2: Customer):
            if customer1.is_adjacent_with(customer2):
                if customer1.next_node == customer2:
                    # Customer1 comes first
                    return Route.get_adjacent_customer_swap_deltas(customer1)
                # Customer2 comes first
                return Route.get_adjacent_customer_swap_deltas(customer2)

            # Nonadjacent swap
            return Route.get_nonadjacent_customer_swap_deltas(customer1, customer2)

        def get_customer_swap_deltas_at(self, i, j):
            customer1 = self.path[i]
            customer2 = self.path[j]

            return self.get_customer_swap_deltas(customer1, customer2)

        def get_customer_swap_with_deltas(self, i, other, j):
            customer1 = self.path[i]
            customer2 = other.path[j]

            return self.get_customer_swap_deltas(customer1, customer2)

        ## Permutation and subpermutation (travel distance only)
        def get_permutation_deltas(self, permutation):
            # WARNING: Must permute anyway to get the cost delta. Could be cheaper to apply the operator, compute, then unapply.
            if len(permutation) != len(self.path):
                raise ValueError("Permutation has wrong length")

            if set(permutation) != set(range(len(self.path))):
                raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

            old_distance = self.total_distance()
            new_path = [self.start_depot] + [self.path[i] for i in permutation] + [self.end_depot]
            new_distance = sum(new_path[i].distance(new_path[i+1]) for i in range(len(new_path)-1))

            travel_delta = new_distance - old_distance

            return ObjectiveTermDelta(travel_distance=travel_delta)

        def get_subpermutation_deltas(self, subpermutation):
            # WARNING: Must sub-permute anyway to get the cost delta. Could be cheaper to apply the operator, compute, then unapply.
            old_distance = self.total_distance()

            new_path = self.path
            sub_permute_list(subpermutation, new_path)
            new_path = [self.start_depot] + new_path + [self.end_depot]
            new_distance = sum(new_path[i].distance(new_path[i+1]) for i in range(len(new_path)-1))

            travel_delta = new_distance - old_distance

            return ObjectiveTermDelta(travel_distance=travel_delta)

        ### Nonbasic operators
        def combine_with(self, other):
            # IF we or other are empty, we error out: No using combine operators involving empty routes!
            if other.is_empty or self.is_empty:
                raise ValueError("Cannot combine using empty routes")

            if self is other:
                raise ValueError("Cannot combine a route with itself")

            # Operate before removing other so that the remove operation sees the correct end depot - and thus correctly updates
            #   the end_depot for the next pop.
            #   ("pop" triggers "self.unlink_from_vehicle" - which will set the current start depot as the next route's
            #       start_depot, among other key changes. So we need to ensure data is correct when we pop!)
            self.path += other.path
            self.set_end_depot(other.end_depot)
            self.current_load += other.current_load

            if other.vehicle is not None:
                other.vehicle.remove_route(other)


        def swap_customers(self, i, j):
            path = self.path
            path_len = len(path)

            if i>=path_len or j>=path_len:
                raise IndexError("Path index out of range")
            if i==j:
                return
            self.path[i], self.path[j] = self.path[j], self.path[i]

            # Re-link customers i and j to properly update prev_node and next_node.
            self.link_customer(i)
            self.link_customer(j)

        def swap_customers_with(self, i, other, j):
            if self == other and i == j:
                return # No-op!

            path = self.path
            path_len = len(path)

            path2 = other.path
            path_len2 = len(path2)

            if i>=path_len or j>=path_len2:
                raise IndexError("Path index out of range")


            self.current_load += other.path[j].demand - self.path[i].demand
            other.current_load += self.path[i].demand - other.path[j].demand

            temp = self.path[i]
            self.path[i] = other.path[j]
            other.path[j] = temp

            self.link_customer(i)
            other.link_customer(j)


        def permute(self, permutation):
            if len(permutation) != len(self.path):
                raise ValueError("Permutation has wrong length")

            if set(permutation) != set(range(len(self.path))):
                raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

            # Use set_values to re-link customers
            self.set_values(path = [self.path[i] for i in permutation])


        def sub_permute(self, subpermutation):
            # Like permute, but e.g. if subpermute is 1,3,5, then we move item 1->3->5->1

            if len(subpermutation) > self.path_len:
                raise ValueError("Subpermutation is longer than the path")
            if len(subpermutation) <= 1:
                return

            self.set_values(path=sub_permute_list(subpermutation, self.path))

        # We leave split to the vehicle - as the new route needs to be added to the vehicles' route list at the proper index.



        ### Now, the final one: Cost computations for swapping self with the next route.
        def swap_with_next_route_travel_deltas(self):
            route1 = self
            route2 = self.next_route

            if route2 is None:
                raise ValueError("No next route to swap with.")

            if route1.is_empty or route2.is_empty:
                # Cannot swap with empty routes (soft rule on calculate, hard on operate)
                return 0

            # Original data: etc => sd1 => r1 => ed1=sd2 => r2 => ed2=sd3 => r3 => etc.
            # Swapped data: etc => sd2=old_sd1 => r2 => ed2=sd1 => rd1 => ed1=sd3 => r3 => etc
            # Travel changes:
            #   Old: sd1 => fv1 + sd2 => fv2 + sd3 => fv3
            #   New: sd1 => fv2 + ed2 => fv1 + ed1 => fv3


            route3 = route2.next_route

            old_distance = route1.first_move_distance() + route2.first_move_distance()

            first_visit_1 = route1.first_visit_node()
            first_visit_2 = route2.first_visit_node()

            start_depot_1 = route1.start_depot
            end_depot_2 = route2.end_depot
            end_depot_1 = route1.end_depot

            new_distance = start_depot_1.distance(first_visit_2) + end_depot_2.distance(first_visit_1)

            if route3 is not None:
                old_distance += route3.first_move_distance()
                new_distance += end_depot_1.distance(route3.first_visit_node())

            return new_distance - old_distance

        def swap_with_next_route_depot_activation_deltas(self):
            route1 = self
            route2 = self.next_route

            if route2 is None:
                raise ValueError("No next route to swap with.")

            if route1.is_empty or route2.is_empty:
                # Cannot swap with empty routes (soft rule on calculate, hard on operate)
                return 0

            # Original data: etc => sd1 => r1 => ed1=sd2 => r2 => ed2=sd3 => r3 => etc.
            # Swapped data: etc => sd2=old_sd1 => r2 => ed2=sd1 => rd1 => ed1=sd3 => r3 => etc
            # Travel changes:
            #   Old: sd1 => fv1 + sd2 => fv2 + sd3 => fv3
            #   New: sd1 => fv2 + ed2 => fv1 + ed1 => fv3

            # Note: if there is a nonempty route after the next one: there are no changes - sd1, ed1, ed2 have the
            #   same number of "start counts" in the affected portion as before.
            # Otherwise: ed1 loses a start and ed2 gains a start.
            # NOTE: We calculate to start with as if there's no next route. Then we take itself into account
            #   based on the change in its start depot. (Lots of edge cases around next route being empty/trivial)

            route3 = route2.next_route

            num_use_deltas = defaultdict(int)

            end1 = route1.end_depot
            end2 = route2.end_depot

            num_use_deltas[end1] = -1
            num_use_deltas[end2] = 1
            if route3 is not None:
                next_deltas = route3.get_depot_num_usage_deltas_if_start_depot_changes_to(route1.end_depot)

                num_use_deltas[end1] += next_deltas[end1]
                num_use_deltas[end2] += next_deltas[end2]

            depot_use_delta = self.get_depot_activation_deltas_from_depot_usage_deltas(num_use_deltas)

            return depot_use_delta

        def swap_with_next_route_deltas(self):
            travel_delta = self.swap_with_next_route_travel_deltas()
            depot_delta = self.swap_with_next_route_depot_activation_deltas()

            return ObjectiveTermDelta(travel_distance=travel_delta, depots_activated=depot_delta)

class Vehicle:
    def __init__(self, i=0, initial_depot=None, capacity = -1):
        self.i = i # data
        self.initial_depot = initial_depot # data
        self.capacity = capacity # data
        self.routes = [] # Core decision for the vehicle
        self.final_depot = initial_depot

    @property
    def num_routes(self):
        return len(self.routes)

    def link_route_to_vehicle(self, i):
        # Called at the end of insert or append operation
        routes = self.routes
        num_routes = self.num_routes
        if i < 0 or i >= num_routes:
            raise IndexError("Route index out of range.")


        route = self.routes[i]
        route.vehicle = self

        if i == 0:
            # No previous route
            route.prev_route = None
            route.set_start_depot(self.initial_depot)
        else:
            # Link prev_route <=> route
            prev_route = routes[i - 1]
            route.prev_route = prev_route
            prev_route.next_route = route

            route.set_start_depot(prev_route.end_depot)

        if i == num_routes - 1:
            # No next route
            route.next_route = None
            self.final_depot = route.end_depot
        else:
            # Link route <=> next_route
            next_route = routes[i + 1]

            route.next_route = next_route
            next_route.prev_route = route

            next_route.set_start_depot(route.end_depot)

        # We do not handle depot accounting here. Instead, we allow the append/insert operators to handle it
        #   via a couple of calls to the route's methods.

    def append_route(self, route: Route):
        if route.is_empty:
            raise ValueError("Cannot add empty route to vehicle.")

        # Before linking the new route in: handle depot accounting
        depot_num_usage_deltas = route.get_depot_num_usage_deltas_if_appended_to(self)
        route.apply_depot_usage_deltas_to_depots(depot_num_usage_deltas)

        self.routes.append(route)
        self.link_route_to_vehicle(self.num_routes - 1)

    def insert_route(self, route: Route, index):
        if index >= len(self.routes)+1:
            raise IndexError("index out of range")

        if route.is_empty:
            raise ValueError("Cannot add empty route to vehicle.")

        if index == len(self.routes):
            self.final_depot = route.end_depot

        # Before linking the new route in: handle depot accounting
        depot_num_usage_deltas = route.get_depot_num_usage_deltas_if_inserted_at(self, index)
        route.apply_depot_usage_deltas_to_depots(depot_num_usage_deltas)

        self.routes.insert(index, route)
        self.link_route_to_vehicle(index)

    def remove_route(self, route):
        if route.vehicle is not self:
            raise IndexError(f"route not assigned to vehicle {self.i}")

        if route == self.routes[-1]:
            if self.num_routes == 1:
                self.final_depot = self.initial_depot
            else:
                self.final_depot = route.start_depot

        # No need to handle depot accounting: route.unlink_for_vehicle() handles it.

        # Here, the route is unassigned - but its data still exists.
        route.unlink_from_vehicle()
        self.routes.remove(route)

    def pop_route_at(self, index):
        if index >= len(self.routes):
            raise IndexError("index out of range")


        if index == self.num_routes - 1:
            if self.num_routes == 1:
                self.final_depot = self.initial_depot
            else:
                self.final_depot = self.routes[index].start_depot

        # No need to handle depot accounting: route.unlink_for_vehicle() handles it.

        # Here, the route is unassigned - but its data still exists.
        route = self.routes.pop(index)
        route.unlink_from_vehicle()
        return route

    def split_route(self, index, split_index, refill_depot: Depot):
        # split_index is the first split_index to split into the new route
        if split_index < 0 or split_index >= len(self.routes[index].path):
            raise IndexError("split_index out of range")

        route = self.routes[index]

        new_route = route.split_at(split_index, refill_depot)

        self.insert_route(new_route, index+1)
        return new_route # Return it for addition to all_routes

    def combine_routes_at(self, i, j):
        # No need to update separate "num routes starting at each depot" data: the pop handles this update
        if i >= len(self.routes) or j >= len(self.routes):
            raise IndexError("split_index out of range")
        if i==j:
            return

        dest_route = self.routes[i]
        src_route = self.routes[j]

        if dest_route.is_empty or src_route.is_empty:
            raise ValueError("Cannot combine empty routes.")

        dest_route.combine_with(src_route)

    def get_total_distance(self):
        if self.num_routes == 0:
            return 0

        return sum(route.total_distance() for route in self.routes)

    @property
    def has_overloaded_routes(self):
        return self.num_routes > 0 and any(route.is_overloaded() for route in self.routes)

    @property
    def is_used(self):
        return self.num_routes > 0 and not all(route.should_dispose() for route in self.routes)

    def num_used(self):
        if self.num_routes == 0:
            return len(self.routes)
        return sum(not route.should_dispose() for route in self.routes)

    def route_capacity_valid(self, route):
        return self.capacity >= route.capacity_needed()

    def num_routes_past_capacity(self):
        if self.num_routes == 0:
            return 0
        return sum(1 for route in self.routes if not self.route_capacity_valid(route))

class FullSolution:
    def __init__(self):
        # Solution data
        self.all_routes: list[Route] = []
        self.vehicles: list[Vehicle] = []
        self.routes_to_dispose: set[Route] = set()

        # Objective terms
        self.unit_travel_cost = 0
        self.cost_per_vehicle = 0
        self.cost_per_depot = 0
        self.overload_penalty = 1000 # feasibility penalty for overloading a route. $1000 per unit to replace broken truck should suffice XD

        # Problem data
        self.depots = []
        self.customers = []
        self.capacity_per_vehicle = []

        self.total_customer_capacity = 0
        self.mean_customer_capacity = 0

        self.min_vehicle_capacity = 1e100
        self.max_vehicle_capacity = -1e100
        self.mean_vehicle_capacity = 0
        self.total_vehicle_capacity = 0

        self.num_routes_lb = -1

    # Data setters
    def set_customers(self, customers):
        self.customers = customers
        self.total_customer_capacity = sum(c.demand for c in self.customers)
        self.mean_customer_capacity = self.total_customer_capacity / len(self.customers)

    def set_depots(self, depots):
        self.depots = depots

    def set_objectives(self, unit_travel_cost, cost_per_vehicle, cost_per_depot, overload_penalty = 1000):
        self.unit_travel_cost = unit_travel_cost
        self.cost_per_vehicle = cost_per_vehicle
        self.cost_per_depot = cost_per_depot
        self.overload_penalty = overload_penalty

    def add_vehicle(self, vehicle: Vehicle):
        self.vehicles.append(vehicle)
        vehicle_capacity = vehicle.capacity

        self.total_vehicle_capacity += vehicle_capacity
        self.mean_vehicle_capacity = self.total_vehicle_capacity/len(self.vehicles)
        self.min_vehicle_capacity = min(self.min_vehicle_capacity, vehicle_capacity)
        self.max_vehicle_capacity = max(self.max_vehicle_capacity, vehicle_capacity)

        self.num_routes_lb = self.total_customer_capacity / self.max_vehicle_capacity

    def remove_vehicle(self, vehicle):
        if vehicle.routes:
            raise ValueError("Must reassign a vehicle's routes before removing it.")

        self.vehicles.remove(vehicle)

        vehicle_capacity = vehicle.capacity
        self.total_vehicle_capacity -= vehicle_capacity
        self.mean_vehicle_capacity = self.total_vehicle_capacity/len(self.vehicles)

        # Warning: This update is expensive! Though removing vehicles doesn't help much with solve, so shouldn't be used much.
        if vehicle_capacity == self.min_vehicle_capacity:
            self.min_vehicle_capacity = min(v.capacity for v in self.vehicles)
        if vehicle_capacity == self.max_vehicle_capacity:
            self.max_vehicle_capacity = max(v.capacity for v in self.vehicles)

        self.num_routes_lb = self.total_customer_capacity / self.max_vehicle_capacity

    def remove_routes(self, routes):
        for route in routes:
            route.dispose()
        self.all_routes[:] = [r for r in self.all_routes if r not in set(routes)]


    def remove_routes_to_dispose(self):
        self.remove_routes(self.routes_to_dispose)
        self.routes_to_dispose.clear()

    def add_route_to_vehicle(self, route, vehicle):
        # We assume vehicle is in self.vehicles already.
        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        vehicle.append_route(route)
        self.all_routes.append(route)

    def add_route_to_vehicle_with_id(self, route, vehicle_id):
        if vehicle_id >= len(self.vehicles) or vehicle_id < 0:
            raise ValueError("vehicle_id out of range")

        if route.is_empty:
            raise ValueError("Cannot add empty routes.")

        self.add_route_to_vehicle(route, self.vehicles[vehicle_id])

    # Objective computation
    def vehicles_used(self):
        return sum(vehicle.is_used for vehicle in self.vehicles)

    def depots_used(self):
        return sum(depot.is_used for depot in self.depots)

    def recompute_depots_used(self):
        return sum(any(route.start_depot == depot and not route.is_trivial for route in self.all_routes) for depot in self.depots)

    def depot_usage_breakdown(self):
        return {depot: sum(route.start_depot == depot and not route.is_trivial for route in self.all_routes) for depot in self.depots}

    def total_path_len(self):
        return sum(route.total_distance() for route in self.all_routes)

    def num_overloaded_routes(self):
        return sum(route.is_overloaded() for route in self.all_routes)

    def total_overload(self):
        return sum(route.amount_overloaded for route in self.all_routes)

    def solution_cost(self):
        return (self.cost_per_vehicle * self.vehicles_used() +
                self.cost_per_depot * self.depots_used() +
                self.unit_travel_cost * self.total_path_len() +
                self.overload_penalty * self.total_overload())

    def take_snapshot(self):
        snapshot = copy.deepcopy(self)
        obj = snapshot.solution_cost()
        return obj, snapshot


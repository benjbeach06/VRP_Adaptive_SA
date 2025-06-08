import copy
from math import sqrt, hypot

from functools import lru_cache


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

    def __repr__(self):
        return f"{self.i}"


class Route:
        # NOTE: Equality and hashing are identity-based to ensure performance in sets/lists, and to
        #   guarantee stability despite field mutability. Uniqueness is managed externally.

        def __init__(self, path: list[Customer], end_depot: Depot):
            self.path = path # List of customers
            self.end_depot = end_depot
            self.start_depot: Depot = None
            self.vehicle: Vehicle = None

            if len(path) == 0:
                self.current_load = 0
            else:
                self.current_load = sum(c.demand for c in path)

            self.__eq__ = object.__eq__
            self.__hash__ = object.__hash__

            # Start_depot and vehicle will be filled out when the route is added to a vehicle.

        def set_values(self, path=None, vehicle=None, start_depot=None, end_depot=None):
            if path is not None:
                self.current_load = sum(c.demand for c in path)
                self.path = path
            if vehicle is not None:
                self.vehicle = vehicle
            if start_depot is not None:
                # Start depot must be where the vehicle left off.
                # So this is a derived quantity, but useful for reference nonetheless.
                self.start_depot = start_depot
            if end_depot is not None:
                self.end_depot = end_depot

        def insert_visit(self, customer, index):
            # Just inserts the visit
            self.path.insert(index, customer)
            self.current_load += customer.demand

        def append_visit(self, customer):
            # Just appends the visit
            self.path.append(customer)
            self.current_load += customer.demand

        def should_dispose(self):
            # Routes should only be explicitly disposed of by an SA operator - and only if they serve no customers.
            # This method returns true if the route is trivial: a move from start_depot to start_depot.

            return len(self.path) == 0 and self.start_depot == self.end_depot

        def can_dispose(self):
            # Routes can only be explicitly disposed of by an SA operator - and only if they serve no customers.
            # This method returns true if route disposal won't eliminate customers from the working route.

            return len(self.path) == 0

        def dispose(self):
            # Note: this may sometimes be called if the end depot mismatches the start depot. However, the route pop
            #   should take care of all accounting for depot route-starting-counting logic in any case.
            #   In this case, also, travel distances and (possibly) vehicle usage counts will be affected by disposal.
            self.vehicle.pop_route(self)

        def pop_visit_at(self, index):
            # Pops the route visit at split_index and returns it
            self.current_load -= self.path[index].demand
            return self.path.pop(index)

        def get_visit_insert_travel_delta(self, customer, index):
            # Returns the travel time cost incurred by inserting a visit
            path = self.path
            path_len = len(path)

            start_depot = self.start_depot
            end_depot = self.end_depot

            if index > path_len:
                raise IndexError("Index out of range")

            prev_node = start_depot if (index == 0) else path[index - 1]
            next_node = end_depot if (index == path_len) else path[index]

            old_distance = prev_node.distance(next_node)
            new_distance = prev_node.distance(customer) + customer.distance(next_node)

            return new_distance - old_distance

        def get_visit_append_travel_delta(self, customer):
            path = self.path
            path_len = len(path)

            start_depot = self.start_depot
            end_depot = self.end_depot

            prev_node = start_depot if path_len == 0 else path[path_len - 1]
            next_node = end_depot

            old_distance = prev_node.distance(next_node)
            new_distance = prev_node.distance(customer) + customer.distance(next_node)

            return new_distance - old_distance

        def get_visit_pop_travel_delta(self, index):
            path = self.path
            path_len = len(path)

            start_depot = self.start_depot
            end_depot = self.end_depot

            if index >= path_len:
                raise IndexError("Index out of range")

            prev_node = start_depot if index == 0 else path[index - 1]
            curr_node = path[index]
            next_node = end_depot if index == path_len - 1 else path[index + 1]

            old_distance = prev_node.distance(curr_node) + curr_node.distance(next_node)
            new_distance = prev_node.distance(next_node)

            return new_distance - old_distance
        """
        def get_end_depot_change_travel_delta(self, new_end_depot):
            path = self.path
            path_len = len(path)
            
            start_depot = self.start_depot
            end_depot = self.end_depot
            
            prev_node = start_depot if (path_len == 0) else path[path_len - 1]
                        
            prev_distance = prev_node.distance(end_depot)
            new_distance = prev_node.distance(new_end_depot)
                        
            return new_distance - prev_distance
        """

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

        def combine_with(self, other):
            # No need to update separate "num routes starting at each depot" data: extending a path does change depot visitation
            other.start_depot.num_routes_starting_here -= 1

            # Operate before popping so that the pop operation sees the correct end depot - and thus correctly updates
            #   the end_depot for the next pop
            self.path += other.path
            self.end_depot = other.end_depot
            self.current_load += other.current_load

            if other.vehicle is not None:
                other.vehicle.pop_route(other)


        def swap_visits(self, i, j):
            path = self.path
            path_len = len(path)

            if i>=path_len or j>=path_len:
                raise IndexError("Path index out of range")
            if i==j:
                return
            self.path[i], self.path[j] = self.path[j], self.path[i]

        def swap_visits_with(self, i, other, j):
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


        def permute(self, permutation):
            if len(permutation) != len(self.path):
                raise ValueError("Permutation has wrong length")

            if set(permutation) != set(range(len(self.path))):
                raise ValueError("Permutation indices must be in the range from 0 to the path length - 1.")

            self.path = [self.path[i] for i in permutation]

        def sub_permute(self, subpermutation):
            # Like permute, but e.g. if subpermute is 1,3,5, then we move item 1->3->5->1
            path = self.path

            if len(subpermutation) > len(path):
                raise ValueError("Subpermutation is longer than the path")
            if len(subpermutation) <= 1:
                return

            subpermutation_set = set(subpermutation)
            if len(subpermutation) != len(subpermutation_set):
                raise ValueError("Entries of Subpermutation.")
            if not subpermutation_set.issubset(set(range(len(path)))):
                raise ValueError("Subpermutation indices must be in the range from 0 to the path length - 1.")

            start = path[subpermutation[0]]
            for i in range(len(subpermutation)-1):
                path[subpermutation[i]] = path[subpermutation[i+1]]
            path[subpermutation[-1]] = start

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

    def add_route(self, route: Route):
        if self.routes:
            next_start_depot = self.routes[-1].end_depot
        else:
            next_start_depot = self.initial_depot

        route.vehicle = self
        route.start_depot = next_start_depot

        next_start_depot.num_routes_starting_here += 1

        self.routes.append(route)

        self.final_depot = route.end_depot

    def insert_route(self, route: Route, index):
        if index >= len(self.routes)+1:
            raise IndexError("index out of range")

        if index == 0:
            route.start_depot = self.initial_depot
        else:
            route.start_depot = self.routes[index-1].end_depot

        route.start_depot.num_routes_starting_here += 1
        route.vehicle = self

        if index <= len(self.routes) - 1:
            # Need to adjust route usage count for the next starting depot before/after route insertion
            next_route = self.routes[index]
            next_start_depot = next_route.start_depot

            next_start_depot.num_routes_starting_here -= 1
            route.end_depot.num_routes_starting_here += 1

            self.routes[index].start_depot = route.end_depot

        if index == len(self.routes):
            self.final_depot = route.end_depot

        self.routes.insert(index, route)

    def pop_route(self, route):
        try:
            index = self.routes.index(route)
        except ValueError:
            raise IndexError(f"route not assigned to vehicle {self.i}")

        return self.pop_route_at(index)

    def pop_route_at(self, index):
        if index >= len(self.routes):
            raise IndexError("index out of range")

        route = self.routes[index]

        if index <= len(self.routes) - 2:
            # If there exists something after the pop index

            # Next route no longer starts at current end depot - so decrement usage for it.
            route.end_depot.num_routes_starting_here -= 1

            if index == 0:
                # Second route becomes first => its new start is vehicle initial
                self.routes[1].start_depot = self.initial_depot
                self.initial_depot.num_routes_starting_here += 1
            else:
                # Next route gets start location from previous one
                self.routes[index+1].start_depot = self.routes[index-1].end_depot
                self.routes[index - 1].end_depot.num_routes_starting_here += 1

        if index == len(self.routes) - 1:
            # No additional depot num_routes_starting_here updates: there's no next route.
            if index == 0:
                self.final_depot = self.initial_depot
            else:
                self.final_depot = self.routes[index-1].end_depot

        # Here, the route is unassigned - but its data still exists.
        route = self.routes[index]
        route.start_depot.num_routes_starting_here -= 1

        route.start_depot = None
        route.vehicle = None

        return self.routes.pop(index)

    def split_route(self, index, split_index, refill_depot: Depot):
        # split_index is the first split_index to split into the new route
        if split_index < 0 or split_index >= len(self.routes[index].path):
            raise IndexError("split_index out of range")

        refill_depot.num_routes_starting_here += 1

        route = self.routes[index]
        path = route.path

        if split_index < 0 or split_index >= len(path):
            raise IndexError("split split_index out of range")
        if split_index == 0 or 1 >= len(path) or len(path) == split_index:
            return None # No split to do: one route or the other has all the items!!

        new_route = Route(path[split_index:], route.end_depot)

        # Remove the tail of the path from the original route, then update start/end info
        route.path = route.path[:split_index]
        route.end_depot = refill_depot
        new_route.start_depot = refill_depot

        new_route.current_load = sum(customer.demand for customer in new_route.path)
        route.current_load -= new_route.current_load

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

        # Objective terms
        self.unit_travel_cost = 0
        self.cost_per_vehicle = 0
        self.cost_per_depot = 0
        self.overload_penalty = 1e5 # feasibility penalty for overloading a route. $100 grand to replace broken truck should suffice XD

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

    def set_objectives(self, unit_travel_cost, cost_per_vehicle, cost_per_depot, overload_penalty = 1e5):
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

    def remove_routes(self, routes: list[Route]):
        for route in routes:
            route.dispose()
        self.all_routes[:] = [r for r in self.all_routes if r not in set(routes)]


    def add_route_to_vehicle(self, route, vehicle):
        # We assume vehicle is in self.vehicles already.
        vehicle.add_route(route)
        self.all_routes.append(route)

    def add_route_to_vehicle_with_id(self, route, vehicle_id):
        if vehicle_id >= len(self.vehicles) or vehicle_id < 0:
            raise ValueError("vehicle_id out of range")

        self.add_route_to_vehicle(route, self.vehicles[vehicle_id])

    # Objective computation
    def vehicles_used(self):
        if any(route is None for route in self.all_routes):
            pass
        return sum(vehicle.is_used for vehicle in self.vehicles)

    def depots_used(self):
        return sum(depot.is_used for depot in self.depots)

    def total_path_len(self):
        return sum(route.total_distance() for route in self.all_routes)

    def num_overloaded_routes(self):
        return sum(route.is_overloaded() for route in self.all_routes)

    def solution_cost(self):
        return (self.cost_per_vehicle * self.vehicles_used() +
                self.cost_per_depot * self.depots_used() +
                self.unit_travel_cost * self.total_path_len() +
                self.overload_penalty * self.num_overloaded_routes())

    def take_snapshot(self):
        snapshot = copy.deepcopy(self)
        obj = snapshot.solution_cost()
        return obj, snapshot


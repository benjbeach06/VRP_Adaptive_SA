import sys
from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Solver import *
import numpy as np

def build_vrp_model():
    # Random seed for reproducibility
    np.random.seed(42)

    # Depots
    depots = [
        Depot(location = (10, 10), supply_limit = 35, vehicle_count = 1),
        Depot(location = (50, 50), supply_limit = 35, vehicle_count = 1),
        Depot(location = (90, 10), supply_limit = 35, vehicle_count = 1),
    ]

    # Customers
    num_customers = 200#5000
    generator = np.random.default_rng()

    gen_customer_location = lambda : tuple(generator.uniform(low = 0, high = 2, size=2))
    gen_customer_demand = lambda : int(generator.integers(1, 11))

    customers: list[Customer] = [Customer(cID = i, location = gen_customer_location(),
                                          demand = gen_customer_demand()) for i in range(num_customers)]


    base_supply_limit = 35
    base_vehicles_per_depot = 1
    capacity_per_vehicle = 25

    # For now, we unconstrain the max #routes, as they can be added and removed dynamically.
    cost_per_vehicle = 10
    cost_per_depot = 20
    unit_travel_cost = 1


    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)

    sln.add_vehicle(Vehicle(initial_depot = depots[0], i=0, capacity = capacity_per_vehicle))
    sln.add_vehicle(Vehicle(initial_depot = depots[1], i=1, capacity = capacity_per_vehicle))
    sln.add_vehicle(Vehicle(initial_depot = depots[2], i=2, capacity = capacity_per_vehicle))

    sln.set_objectives(cost_per_depot = cost_per_depot, cost_per_vehicle = cost_per_vehicle, unit_travel_cost = unit_travel_cost)

    solver = SimAnnVRPSolver(sln, max_time=10)

    """
    route1 = Route([customers[cID] for cID in [1, 15, 18, 17, 5]], depots[2])
    route2 = Route([customers[cID] for cID in [3, 9, 10, 11]], depots[1])
    route3 = Route([customers[cID] for cID in [19, 2, 0]], depots[1])
    route4 = Route([customers[cID] for cID in [4, 12, 6, 7]], depots[1])
    route5 = Route([customers[cID] for cID in [13, 8, 16, 14]], depots[0])

    vehicle = sln.vehicles[1]
    sln.add_route_to_vehicle(route1, vehicle)
    sln.add_route_to_vehicle(route2, vehicle)
    sln.add_route_to_vehicle(route3, vehicle)
    sln.add_route_to_vehicle(route4, vehicle)
    sln.add_route_to_vehicle(route5, vehicle)

    print(sln.solution_cost())

    print('\n'.join(f"{customer.location}, {customer.demand}" for customer in customers))

        (np.int32(51), np.int32(92)), 8
        (np.int32(60), np.int32(20)), 7
        (np.int32(82), np.int32(86)), 8
        (np.int32(99), np.int32(23)), 3
        (np.int32(21), np.int32(52)), 2
        (np.int32(87), np.int32(29)), 6
        (np.int32(1), np.int32(63)), 5
        (np.int32(32), np.int32(75)), 10
        (np.int32(21), np.int32(88)), 1
        (np.int32(90), np.int32(58)), 10
        (np.int32(91), np.int32(59)), 3
        (np.int32(54), np.int32(63)), 9
        (np.int32(2), np.int32(50)), 7
        (np.int32(20), np.int32(72)), 7
        (np.int32(17), np.int32(3)), 9
        (np.int32(59), np.int32(13)), 2
        (np.int32(8), np.int32(89)), 5
        (np.int32(1), np.int32(83)), 7
        (np.int32(43), np.int32(7)), 3
        (np.int32(77), np.int32(80)), 4
    """

    solver.make_initial_solution()
    solver.solve(debug_level=3)

    (obj, sln) = solver.get_best_snapshot()

    all_routes = sln.all_routes
    vehicles = sln.vehicles

    best_obj = solver.best_objective
    curr_obj = solver.curr_objective

    print('\n'.join(f"{key}, {value}" for (key,value) in
                    {i: {"Path": ["d" + str(route.start_depot.dID)] +
                                 [customer.cID for customer in route.path] +
                                 ["d" + str(route.end_depot.dID)],
                         "Vehicle": route.vehicle.cID,
                         "Cost": route.total_distance()}
                     for (i,route) in enumerate(all_routes)}.items()
                    )
    )

    print('\n'.join(f"Total distance traveled for vehicle {vehicle.vID}: "
                    f"{vehicle.get_total_distance()}" for vehicle in vehicles))

    print(f"Total cost: "
          f"Vehicle use cost {sln.vehicles_used()*cost_per_vehicle} + "
          f"Depot use cost {sln.depots_used()*cost_per_depot} + "
          f"Travel cost {sln.total_path_len()*unit_travel_cost} = "
          f"{sln.solution_cost()}")

    print(f"Infeasibility routes - {sln.total_overload()} total units:\n" +
          "\n".join("[" +', '.join(["d" + str(route.start_depot.dID)] +
                                   [str(customer.cID) for customer in route.path] +
                                   ["d" + str(route.end_depot.dID)]) + f"], load={route.current_load}, cap={route.vehicle.capacity}" for route in all_routes))


    #print(vehicle_usage_count.value)

    for (i, route) in enumerate(all_routes):
        path = route.path
        path_len = len(path)

        if path_len >= 1:
            start = route.start_depot
            end = route.end_depot

            start_dist = start.distance(path[0])
            end_dist = end.distance(path[-1])
            mid_dist = sum(path[i].distance(path[i+1]) for i in range(path_len - 1))

            print(f"Cost breakdown for src_route {i} : start_dist={start_dist}, end_dist={end_dist}, mid_dist={mid_dist}, capacity={route.recompute_current_load()}")


    print("We dID it!")

build_vrp_model()
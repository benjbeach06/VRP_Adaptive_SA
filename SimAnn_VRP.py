import sys
from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Solver import *
import numpy as np

def build_vrp_model():
    # Random seed for reproducibility
    np.random.seed(42)

    use_pre_refactor_data = True

    num_customers = 500 #200 #500  # 5000
    if use_pre_refactor_data:
        # Depot locations (x, y), and supply limits
        depot_data = [
            {"location": (10, 10), "supply_limit": 35, "vehicle_count": 1},
            {"location": (50, 50), "supply_limit": 35, "vehicle_count": 1},
            {"location": (90, 10), "supply_limit": 35, "vehicle_count": 1},
        ]

        # Customer data: id -> (x, y, demand)
        customer_data = [
            {
                "location": tuple(np.random.randint(0, 100, size=2)),
                "demand": np.random.randint(1, 11)
            }
            for i in range(num_customers)
        ]

        depots = [Depot(i, depot["location"], depot["supply_limit"], depot["vehicle_count"]) for (i, depot) in
                  enumerate(depot_data)]
        customers = [Customer(i, customer["location"], customer["demand"]) for (i, customer) in enumerate(customer_data)]
    else:
        depots = [
            Depot(location=(10, 10), supply_limit=35, vehicle_count=1, dID=0),
            Depot(location=(50, 50), supply_limit=35, vehicle_count=1, dID=1),
            Depot(location=(90, 10), supply_limit=35, vehicle_count=1, dID=2),
        ]

        # Customers
        generator = np.random.default_rng()

        gen_customer_location = lambda: tuple(generator.integers(low=0, high=100, size=2))
        gen_customer_demand = lambda: int(generator.integers(1, 11))

        customers: list[Customer] = [Customer(cID=i, location=gen_customer_location(),
                                              demand=gen_customer_demand()) for i in range(num_customers)]

    base_supply_limit = 35
    base_vehicles_per_depot = 1
    capacity_per_vehicle = 400#400#25

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

    solver = SimAnnVRPSolver(sln, max_time=60)

    solver.make_initial_solution()
    #solver.make_dumb_initial_solution()
    solver.solve(debug_level=2)

    (obj, sln) = solver.get_best_snapshot()

    all_routes = sln.all_routes
    vehicles = sln.vehicles

    best_obj = solver.best_objective
    curr_obj = solver.curr_objective

    print('\n'.join(f"{key}, {value}" for (key,value) in
                    {i: {"Path": ["d" + str(route.start_depot.dID)] +
                                 [customer.cID for customer in route.path] +
                                 ["d" + str(route.end_depot.dID)],
                         "Vehicle": route.vehicle.vID, #type: ignore - invariant: all routes assigned
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
                                   ["d" + str(route.end_depot.dID)]) + f"], load={route.current_load}, cap={route.vehicle.capacity}" for route in all_routes)) #type: ignore - invariant: all routes assigned


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
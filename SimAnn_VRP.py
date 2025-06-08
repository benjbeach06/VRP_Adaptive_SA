import sys
from SimAnn_VRP_Core_Model import *
from SimAnn_VRP_Solver import *
import numpy as np

def build_vrp_model():
    # Random seed for reproducibility
    np.random.seed(42)

    # Depot locations (x, y), and supply limits
    depot_data = [
        {"location": (10, 10), "supply_limit": 35, "vehicle_count": 1},
        {"location": (50, 50), "supply_limit": 35, "vehicle_count": 1},
        {"location": (90, 10), "supply_limit": 35, "vehicle_count": 1},
    ]

    # Customer data: id -> (x, y, demand)
    num_customers = 20#5000
    customer_data = [
        {
            "location": tuple(np.random.randint(0, 100, size=2)),
            "demand": np.random.randint(1, 11)
        }
        for i in range(num_customers)
    ]

    base_supply_limit = 35
    base_vehicles_per_depot = 1
    capacity_per_vehicle = 25

    # For now, we unconstrain the max #routes, as they can be added and removed dynamically.
    cost_per_vehicle = 10
    cost_per_depot = 20
    unit_travel_cost = 1


    depots = [Depot(i, depot["location"], depot["supply_limit"], depot["vehicle_count"]) for (i, depot) in enumerate(depot_data)]
    customers = [Customer(i, customer["location"], customer["demand"]) for (i, customer) in enumerate(customer_data)]


    sln = FullSolution()
    sln.set_customers(customers)
    sln.set_depots(depots)

    sln.add_vehicle(Vehicle(initial_depot = depots[0], i=0, capacity = capacity_per_vehicle))
    sln.add_vehicle(Vehicle(initial_depot = depots[1], i=1, capacity = capacity_per_vehicle))
    sln.add_vehicle(Vehicle(initial_depot = depots[2], i=2, capacity = capacity_per_vehicle))

    sln.set_objectives(cost_per_depot = cost_per_depot, cost_per_vehicle = cost_per_vehicle, unit_travel_cost = unit_travel_cost)

    solver = SimAnnVRPSolver(sln)
    solver.make_initial_solution()
    solver.solve()

    (obj, sln) = solver.get_best_snapshot()

    all_routes = sln.all_routes
    vehicles = sln.vehicles

    best_obj = solver.best_objective
    curr_obj = solver.curr_objective

    print('\n'.join(f"{key}, {value}" for (key,value) in
                    {i: {"Path": ["d"+str(route.start_depot.i)] +
                       [customer.i for customer in route.path] +
                                 ["d"+str(route.end_depot.i)],
                         "Vehicle": route.vehicle.i,
                         "Cost": route.total_distance()}
                     for (i,route) in enumerate(all_routes)}.items()
                    )
    )

    print('\n'.join(f"Total distance traveled for vehicle {vehicle.i}: "
                    f"{vehicle.get_total_distance()}" for vehicle in vehicles))

    print(f"Total cost: "
          f"Vehicle use cost {sln.vehicles_used()*cost_per_vehicle} + "
          f"Depot use cost {sln.depots_used()*cost_per_depot} + "
          f"Travel cost {sln.total_path_len()*unit_travel_cost} = "
          f"{sln.solution_cost()}")

    print(f"Infeasibility routes - {sln.num_overloaded_routes()} total routes:\n" +
          "\n".join("["+', '.join(["d"+str(route.start_depot.i)] +
                       [str(customer.i) for customer in route.path] +
                                 ["d"+str(route.end_depot.i)]) + f"], load={route.current_load}, cap={route.vehicle.capacity}" for route in all_routes))


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

            print(f"Cost breakdown for route {i} : start_dist={start_dist}, end_dist={end_dist}, mid_dist={mid_dist}, capacity={route.capacity_needed()}")


    print("We did it!")

build_vrp_model()
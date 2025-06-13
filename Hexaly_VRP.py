from platform import machine

import hexaly.optimizer
import sys
from math import sqrt, hypot
from BaseMath import *
import numpy as np
from functools import lru_cache

def build_model():
    with (hexaly.optimizer.HexalyOptimizer() as optimizer):
        # Random seed for reproducibility
        np.random.seed(42)

        m = optimizer.model
        # Depot locations (x, y), and supply limits
        depots = [
            {"location": (10, 10), "supply_limit": 35, "vehicle_count": 1},
            {"location": (50, 50), "supply_limit": 35, "vehicle_count": 1},
            {"location": (90, 10), "supply_limit": 35, "vehicle_count": 1},
        ]
        num_depots = len(depots)
        depot_locations_x = m.array(depot["location"][0] for depot in depots)
        depot_locations_y = m.array(depot["location"][1] for depot in depots)
        depot_supply_limits = m.array(depot["supply_limit"] for depot in depots)
        #depot_vehicle_counts = m.array(depot["vehicle_count"] for depot in depots)

        vehicles = range(sum(depot["vehicle_count"] for depot in depots))
        vehicle_starts = sum(([i]*depot["vehicle_count"] for (i, depot) in enumerate(depots)), [])
        depot_vehicles = [m.array(v for v in vehicles if vehicle_starts == i)
                          for i in range(num_depots)]

        num_vehicles = len(vehicles)
        max_routes = 20
        cost_per_vehicle = 10
        cost_per_depot = 20

        capacity_per_vehicle = 25
        max_routes_per_vehicle = 20

        # Customer data: id -> (x, y, demand)
        num_customers = 20
        customers = [
            {
                "location": tuple(np.random.randint(0, 100, size=2)),
                "demand": np.random.randint(1, 11)
            }
            for i in range(num_customers)
        ]
        customer_locations_x = m.array(customer["location"][0] for customer in customers)
        customer_locations_y = m.array(customer["location"][1] for customer in customers)
        customer_demands = m.array(customer["demand"] for customer in customers)

        # @lru_cache(maxsize=None)
        def dist(node1, node2):
            (x1,y1) = node1["location"]
            (x2,y2) = node2["location"]
            return hypot(x2 - x1, y2 - y1)

        dd_dist = m.array(m.array(dist(depot, depot2) for depot2 in depots) for depot in depots)
        dc_dist = m.array(m.array(dist(depot, customer) for customer in customers) for depot in depots)
        cc_dist = m.array(m.array(dist(customer, customer2) for customer2 in customers) for customer in customers)

        # Each route gets a vehicle ID and a depot to end at.
        route_vehicles = m.array(m.int(0, num_vehicles) for i in range(max_routes))
        route_vehicles.name = "route_vehicles"

        routes = {i: {"path": m.list(num_customers), "vehicle": route_vehicles[i], "end": m.int(0, num_depots) } for i in range(max_routes)}
        route_paths = m.array(route["path"] for route in routes.values())
        route_indexes = m.array(i for i in routes)
        for i in range(max_routes):
            routes[i]["path"].name = f"route_{i}_path"

        vehicle_start_locations = [m.array(vehicle_starts)]
        for i in range(max_routes - 1):
            p1 = [vehicle_start_locations[i][j] for j in range(num_vehicles)]
            vehicle_start_locations.append(m.array(m.iif(m.at(route_vehicles,i) == j, routes[i]["end"], m.at(vehicle_start_locations[i],j))
                                                   for j in range(num_vehicles)))

        route_start_locations = m.array(vehicle_start_locations[i][route["vehicle"]] for (i, route) in routes.items())
        route_end_locations = m.array(route["end"] for route in routes.values())

        vehicle_usage_count = m.array(m.sum(route_indexes, m.lambda_function(lambda i: m.iif(m.and_(v == route_vehicles[i],
                                                                                                    m.count(route_paths[i]) > 0),
                                                                                             1, 0)))
                                      for v in vehicles)

        route_partition_def = m.constraint(m.partition(rt["path"] for rt in routes.values()))
        capacity_limit = [m.constraint(m.sum(rt["path"], m.lambda_function(lambda customer : customer_demands[customer])) <= capacity_per_vehicle) for rt in routes.values()]
        #vehicle_usage_limit = [m.constraint(vehicle_usage_count[v] <= max_routes_per_vehicle) for v in vehicles]

        vehicles_used = m.distinct(route_vehicles)
        num_vehicles_used = m.count(vehicles_used)

        route_depots_used = m.union(route_start_locations, route_end_locations)
        num_depots_used = m.count(route_depots_used)

        def route_cost(route, vehicle_start_location):
            subroute = route["path"]
            path_len = m.count(subroute)

            depot_start_dists = dc_dist[vehicle_start_location]
            depot_end_dists = dc_dist[route["end"]]

            customer1_id = subroute[0]
            customer_last_id = subroute[path_len - 1]

            start_dist = depot_start_dists[customer1_id]
            end_dist = depot_end_dists[customer_last_id]
            mid_dist = m.sum(cc_dist[subroute[i]][subroute[i+1]] for i in range(len(route) - 1))

            return start_dist + mid_dist + end_dist

        def empty_route_cost(route, vehicle_start_location):
            return dd_dist[vehicle_start_location][route["end"]]

        vehicle_cost = cost_per_vehicle * num_vehicles_used
        depot_cost = cost_per_depot * num_depots_used
        route_costs = m.array(m.iif(m.count(rt["path"]) >= 1,
                         route_cost(rt, vehicle_start_locations[i][rt["vehicle"]]),
                         empty_route_cost(rt, vehicle_start_locations[i][rt["vehicle"]])) for (i,rt) in routes.items())
        obj = vehicle_cost + depot_cost + m.sum(route_costs)

        m.minimize(obj)

        m.close()

        #
        # Parametrize the optimizer
        #
        optimizer.param.time_limit = 10

        optimizer.solve()

        print('\n'.join(f"{key}, {value}" for (key,value) in
                        {i: {"Path": ["d"+str(vehicle_start_locations[i].value[rt["vehicle"].value])] +
                           [var for var in rt["path"].value] + ["d"+str(rt["end"].value)],
                             "Vehicle": route_vehicles.value[i],
                             "Cost": route_costs.value[i]}
                         for (i, rt) in routes.items()}.items()
                        )
        )
        #print(vehicle_usage_count.value)

        for (i, route) in routes.items():
            subroute = route["path"].value
            path_len = len(subroute)

            if path_len >= 1:
                vehicle_start_location = vehicle_start_locations[i].value[route["vehicle"].value]

                depot_start_dists = dc_dist.value[vehicle_start_location]
                depot_end_dists = dc_dist.value[route["end"].value]

                customer1_id = subroute[0]
                customer_last_id = subroute[path_len - 1]

                start_dist = depot_start_dists[customer1_id]
                end_dist = depot_end_dists[customer_last_id]
                mid_dist = sum(cc_dist.value[subroute[i]][subroute[i + 1]] for i in range(len(route) - 1))

                print(f"Cost breakdown for route {i} : start_dist={start_dist}, end_dist={end_dist}, mid_dist={mid_dist}")



build_model()
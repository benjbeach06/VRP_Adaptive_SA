import unittest
import numpy as np
from SimAnn_VRP_Core_Model import *


class MyTestCase(unittest.TestCase):
    def __init__(self):
        super().__init__()

        self.sln: FullSolution = None

    def customer_linking(self):
        self.assertEqual(True, False)  # add assertion here

    def make_base_data(self):
        capacity_per_vehicle = 25

        # For now, we unconstrain the max #routes, as they can be added and removed dynamically.
        cost_per_vehicle = 10
        cost_per_depot = 20
        unit_travel_cost = 1

        depots = [Depot(i, (2*i, i+1-i%2), 30, 1) for i in range(3)]
        customers = [Customer(i, (i, i - i%4 + 1), i) for i in range(20)]

        sln = FullSolution()
        sln.set_customers(customers)
        sln.set_depots(depots)

        sln.add_vehicle(Vehicle(initial_depot=depots[0], i=0, capacity=capacity_per_vehicle))
        sln.add_vehicle(Vehicle(initial_depot=depots[1], i=1, capacity=capacity_per_vehicle))
        sln.add_vehicle(Vehicle(initial_depot=depots[2], i=2, capacity=capacity_per_vehicle))


        sln.set_objectives(unit_travel_cost, cost_per_vehicle, cost_per_depot)


        route1 = Route(customers[:3], depots[0])
        route2 = Route(customers[3:4], depots[1])
        route3 = Route([], depots[2])
        route4 = Route(customers[4:9], depots[0])
        route5 = Route([], depots[0])



if __name__ == '__main__':
    unittest.main()

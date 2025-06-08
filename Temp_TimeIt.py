import timeit
import random

setup_code = """
from random import sample

class Route:
    def __init__(self, id):
        self.id = id
    def __hash__(self):
        return id(self)  # simulate identity-based hash
    def __eq__(self, other):
        return self is other
    def dispose(self):
        pass

all_routes = [Route(i) for i in range(30000)]
routes_to_remove = sample(all_routes, 100)
"""

stmt_comprehension = """
to_remove = set(routes_to_remove)
all_routes[:] = [r for r in all_routes if r not in to_remove]
"""

stmt_set_diff = """
all_routes = list(set(all_routes) - set(routes_to_remove))
"""

# Time each
t1 = timeit.timeit(stmt=stmt_comprehension, setup=setup_code, number=1000)
t2 = timeit.timeit(stmt=stmt_set_diff, setup=setup_code, number=1000)

print(f"Comprehension: {t1:.6f} seconds")
print(f"Set difference: {t2:.6f} seconds")
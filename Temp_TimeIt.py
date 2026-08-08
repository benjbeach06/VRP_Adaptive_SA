import timeit
import random
import itertools
import bisect

setup_code = """
from random import sample

class Route:
    def __init__(self, cID):
        self.cID = cID
    def __hash__(self):
        return cID(self)  # simulate identity-based hash
    def __eq__(self, dest_route):
        return self is dest_route
    def dispose(self):
        pass

all_routes = [Route(cID) for cID in range(30000)]
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
#t1 = timeit.timeit(stmt=stmt_comprehension, setup=setup_code, number=1000)
#t2 = timeit.timeit(stmt=stmt_set_diff, setup=setup_code, number=1000)

#print(f"Comprehension: {t1:.6f} seconds")
#print(f"Set difference: {t2:.6f} seconds")

num_trials = 1000000
min_required = 1000
max_required = -1000
results = []

sum_required = 0

for _ in range(num_trials):
    num_tries = 0
    count_until_guarantee = 100
    guarantee_wins_1 = 0
    guarantee_wins_2 = 0

    odds_jackpot = 0.01/4
    odds_guarantee_1 = 0.015/4
    odds_guarantee_2 = 0.015/4

    count_until_jackpot = 500

    won = False

    result_lst = [odds_jackpot, odds_guarantee_1, odds_guarantee_2]
    result_cumsum = list(itertools.accumulate(result_lst)) + [1]

    def record_win_1():
        global guarantee_wins_1, odds_jackpot, odds_guarantee_1, odds_guarantee_2, count_until_guarantee, count_until_jackpot, result_lst, result_cumsum

        guarantee_wins_1 += 1
        if guarantee_wins_1 == 2:
            odds_guarantee_1 = 0
            sum_others = odds_jackpot + odds_guarantee_2

            #odds_jackpot = 0.04 * (0.01 / sum_others)
            #odds_guarantee_2 = 0.04 * (odds_guarantee_2 / sum_others)

            result_lst = [odds_jackpot, odds_guarantee_1, odds_guarantee_2]
            result_cumsum = list(itertools.accumulate(result_lst)) + [1]

        count_until_guarantee = 100
        count_until_jackpot = 100*(5-guarantee_wins_1-guarantee_wins_2)


    def record_win_2():
        global guarantee_wins_2, odds_jackpot, odds_guarantee_1, odds_guarantee_2, count_until_guarantee, count_until_jackpot, result_lst, result_cumsum

        guarantee_wins_2 += 1
        if guarantee_wins_2 == 2:
            odds_guarantee_2 = 0
            sum_others = odds_jackpot + odds_guarantee_1

            #odds_jackpot = 0.04 * (odds_jackpot / sum_others)
            #odds_guarantee_2 = 0.04 * (odds_guarantee_2 / sum_others)


            result_lst = [odds_jackpot, odds_guarantee_1, odds_guarantee_2]
            result_cumsum = list(itertools.accumulate(result_lst)) + [1]

        count_until_guarantee = 100
        count_until_jackpot = 100 * (5 - guarantee_wins_1 - guarantee_wins_2)

    while not won:
        num_tries += 1
        if count_until_jackpot == 0:
            won = True
            continue

        if count_until_guarantee == 0:
            odds_1 = odds_guarantee_1 / (odds_guarantee_1 + odds_guarantee_2)
            if random.random() < odds_1:
                record_win_1()
            else:
                record_win_2()

        sample = random.random()
        choice_id = bisect.bisect_left(result_cumsum, sample)

        if count_until_jackpot <= 100:
            pass

        if choice_id == 0:
            won = True

        elif choice_id == 1:
             record_win_1()

        elif choice_id == 2:
            record_win_2()

        else:
            count_until_jackpot -= 1
            count_until_guarantee -= 1

    sum_required += num_tries
    min_required = min(min_required, num_tries)
    max_required = max(max_required, num_tries)
    results.append(num_tries)

print(f"average: {sum_required/num_trials}, min: {min_required}, max: {max_required}")

pct_over_k = {k: sum(result>k for result in results)/num_trials*100 for k in range(0, 501, 10)}

print(pct_over_k)






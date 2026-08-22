"""
Tests for apply_share_floors: the family-share projection used by two-level operator selection.

PROVENANCE
----------
Written and maintained independently by Claude (Anthropic) during development assistance on this
project; not hand-written by the repository author.

The function has an oracle twin here. apply_share_floors decides the clamped set by an iterative
scan; floors_oracle finds it by brute force over all 2^n subsets. The two agree only if the scan
converges to the unique feasible set, which is the property the fast version relies on and cannot
demonstrate about itself.
"""

import itertools
import math
import random
import unittest

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from SimAnn_VRP_Solver import FAMILY_FLOOR, apply_share_floors


def floors_oracle(weights, floors):
    """Brute force over every clamp subset. Feasible set is unique, so the first hit is the answer."""
    n = len(weights)
    for bits in range(1 << n):
        clamped = [bool(bits >> i & 1) for i in range(n)]
        free = 1.0 - math.fsum(f for f, c in zip(floors, clamped) if c)
        pool = math.fsum(w for w, c in zip(weights, clamped) if not c)
        if pool <= 0.0:
            continue
        raw = [w * free / pool for w in weights]
        if all(raw[i] >= floors[i] for i in range(n) if not clamped[i]) and \
           all(raw[i] < floors[i] for i in range(n) if clamped[i]):
            return [floors[i] if clamped[i] else raw[i] for i in range(n)]
    raise AssertionError("no feasible clamp set")


class ShareFloors(unittest.TestCase):

    def _check(self, weights, floors):
        shares = apply_share_floors(weights, floors)
        self.assertAlmostEqual(math.fsum(shares), 1.0, places=12)
        for share, floor in zip(shares, floors):
            self.assertGreaterEqual(share, floor - 1e-12)
        for got, want in zip(shares, floors_oracle(weights, floors)):
            self.assertAlmostEqual(got, want, places=12)
        return shares

    def test_matches_the_oracle_on_random_inputs(self):
        """The iterative clamped set is the unique feasible one, across many weight spreads."""
        rng = random.Random(20260819)
        for _ in range(2000):
            n = rng.randint(1, 8)
            # Orders-of-magnitude spread, which is how real EMA weights are distributed.
            weights = [10.0 ** rng.uniform(-6, 1) for _ in range(n)]
            floors = [rng.uniform(0.0, 0.9 / n) for _ in range(n)]
            self._check(weights, floors)

    def test_no_floor_binding_leaves_weights_proportional(self):
        """With floors far below every natural share, the function only normalizes."""
        weights = [4.0, 3.0, 2.0, 1.0]
        shares = self._check(weights, [0.01] * 4)
        for share, weight in zip(shares, weights):
            self.assertAlmostEqual(share, weight / 10.0, places=12)

    def test_unclamped_families_keep_their_ratios(self):
        """
        The property that separates proportional redistribution from equal-absolute draining.

        Equal-absolute subtracts the same amount from every surplus family, which changes the
        ratios between them. This test fails if the algorithm is ever swapped for that one.
        """
        weights = [40.0, 10.0, 0.001]
        floors = [0.01, 0.01, 0.30]
        shares = apply_share_floors(weights, floors)
        self.assertAlmostEqual(shares[2], 0.30, places=12)          # the small one clamps
        self.assertAlmostEqual(shares[0] / shares[1], 4.0, places=12)   # ratio survives

    def test_a_clamp_can_cascade(self):
        """
        Clamping one family shrinks the pool, which can pull a second under its own floor.

        Natural shares are 0.692, 0.307, 0.001. Only the third is under its floor, so a
        single-pass implementation clamps that one and stops -- leaving the second at 0.221
        against a floor of 0.30. This case is the reason the scan repeats until stable, and it
        was found by search: the obvious hand-built examples all clamp everything on pass one.
        """
        shares = self._check([7.0, 3.1, 0.01], [0.13, 0.30, 0.28])
        self.assertAlmostEqual(shares[1], 0.30, places=12)   # clamped only by the cascade
        self.assertAlmostEqual(shares[0], 0.42, places=12)

    def test_every_family_weight_equal(self):
        """Degenerate but reachable: at a deep plateau the EMA carries all weights together."""
        self._check([1.0] * 5, [0.25, 0.25, 0.01, 0.01, 0.01])

    def test_shipped_floors_leave_room_for_weighting(self):
        """The precondition apply_share_floors relies on, checked against the real table."""
        self.assertLess(math.fsum(FAMILY_FLOOR.values()), 1.0)
        self.assertEqual(len(FAMILY_FLOOR), 5)


if __name__ == "__main__":
    unittest.main()


class FloorInvariants(unittest.TestCase):
    """
    Stage 7. Benjamin flagged a measured INTER_ROUTE share of 0.251 against a 0.25 floor and asked
    whether a clamped family can land above its floor.

    It cannot. The projection returns `floors[i]` for a clamped family, exactly. The 0.251 was
    binomial noise at 300,000 draws, where one standard error is 0.00079. These tests assert the
    exact property directly, and compare any SAMPLED share against a proper bound rather than a
    hand-picked tolerance.
    """

    def test_a_clamped_family_gets_exactly_its_floor(self):
        """Not approximately. The projection assigns the floor value itself."""
        weights = [1e-9, 10.0, 10.0, 10.0, 10.0]
        floors = [0.25, 0.25, 0.02, 0.01, 0.01]
        shares = apply_share_floors(weights, floors)
        self.assertEqual(shares[0], 0.25)
        self.assertEqual(shares[1], 0.25)

    def test_no_family_ever_ends_below_its_floor(self):
        for weights, floors in _floor_cases():
            shares = apply_share_floors(weights, floors)
            for i, (share, floor) in enumerate(zip(shares, floors)):
                self.assertGreaterEqual(share, floor - 1e-12,
                                        f"family {i} landed under its floor: {shares} / {floors}")

    def test_shares_always_sum_to_one(self):
        for weights, floors in _floor_cases():
            self.assertAlmostEqual(math.fsum(apply_share_floors(weights, floors)), 1.0, places=12)

    def test_a_family_above_its_floor_is_never_clamped_down_to_it(self):
        """
        Clamping must only ever RAISE. A family whose proportional share already clears its floor
        keeps that larger share.
        """
        for weights, floors in _floor_cases():
            total = math.fsum(weights)
            if total <= 0:
                continue
            shares = apply_share_floors(weights, floors)
            for i, (w, floor) in enumerate(zip(weights, floors)):
                proportional = w / total
                if proportional > floor:
                    self.assertGreaterEqual(shares[i], floor,
                                            f"family {i} was pushed below its floor")

    def test_unclamped_families_keep_their_weight_ratios_under_fuzz(self):
        for weights, floors in _floor_cases():
            shares = apply_share_floors(weights, floors)
            free = [i for i, (s, f) in enumerate(zip(shares, floors)) if s > f + 1e-12]
            for a, b in zip(free, free[1:]):
                if weights[b] > 0:
                    self.assertAlmostEqual(shares[a] / shares[b], weights[a] / weights[b], places=9,
                                           msg=f"ratio broke between {a} and {b}")

    def test_sampled_shares_match_the_projection_within_a_binomial_bound(self):
        """
        Draw operators and compare each root family's observed share to the projection's OWN output.

        The bound is five standard errors of a binomial proportion, not a chosen tolerance, so it
        scales with the draw count instead of being retuned whenever the count changes.
        """
        import collections, contextlib, io as _io, os as _os, sys as _sys
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from _harness import random_instance
        from SimAnn_VRP_Solver import SimAnnVRPSolver, FAMILY_FLOOR, _FamilyNode
        from SimAnn_VRP_Operators import Family

        sln = random_instance(seed=20260822, n_customers=200, n_vehicles=40, capacity=25)
        solver = SimAnnVRPSolver(sln)
        with contextlib.redirect_stdout(_io.StringIO()):
            solver.make_initial_solution()
        for op in solver.operators:
            starved = op.family[0] is Family.INTRA_ROUTE
            solver.adj_weights[op] = 1e-9 if starved else 10.0
        solver.refresh_family_tree()

        root = solver.family_root
        families: list[Family] = []
        weights: list[float] = []
        floors: list[float] = []
        for child in root.children:
            assert isinstance(child, _FamilyNode) and child.key is not None
            families.append(child.key)
            weights.append(child.weight)
            floors.append(child.floor)
        expected = dict(zip(families, apply_share_floors(weights, floors)))

        draws = 300_000
        counts = collections.Counter(solver.choose_operator().family[0] for _ in range(draws))
        for family, want in expected.items():
            got = counts[family] / draws
            bound = 5.0 * math.sqrt(max(want * (1 - want), 1e-12) / draws)
            self.assertLess(abs(got - want), bound,
                            f"{family.name}: sampled {got:.5f} against projected {want:.5f}, "
                            f"5-sigma bound {bound:.5f}")
            if abs(want - FAMILY_FLOOR.get(family, 0.0)) < 1e-12:
                self.assertEqual(want, FAMILY_FLOOR[family],
                                 f"{family.name} is clamped and must equal its floor exactly")


def _floor_cases():
    """The shipped shape, some hand-built edge cases, and a deterministic fuzz sweep."""
    yield [1e-9, 10.0, 10.0, 10.0, 10.0], [0.25, 0.25, 0.02, 0.01, 0.01]
    yield [1.0, 1.0, 1.0, 1.0, 1.0], [0.25, 0.25, 0.02, 0.01, 0.01]
    yield [1e-30, 1e-30, 1e-30, 1e-30, 1.0], [0.25, 0.25, 0.02, 0.01, 0.01]
    yield [5.0, 1.0], [0.4, 0.1]
    yield [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]

    rng = random.Random(20260822)
    for _ in range(400):
        n = rng.randint(2, 7)
        weights = [rng.choice([rng.random(), rng.random() * 1e-6, rng.random() * 1e3])
                   for _ in range(n)]
        if math.fsum(weights) <= 0:
            continue
        headroom = rng.uniform(0.05, 0.9)          # keep sum(floors) < 1, the stated precondition
        raw = [rng.random() for _ in range(n)]
        scale = headroom / math.fsum(raw)
        yield weights, [r * scale for r in raw]

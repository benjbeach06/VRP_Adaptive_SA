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

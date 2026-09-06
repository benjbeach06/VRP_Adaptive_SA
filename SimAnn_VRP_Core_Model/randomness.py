"""
The solver's single owned random stream, and the scalar draws taken from it.

This is the one piece of global mutable state in the core model, which is why it gets its own
module. A reproducible run depends on nothing else in the process touching this generator. The
comment on `solver_rng` below records why it is a `random.Random` and not a numpy Generator.

NOTE FOR CALLERS: `seed_solver_rng` REBINDS the module global. Read it back through the package
(`SimAnn_VRP_Core_Model.solver_rng`), which forwards here, rather than through a name you imported
earlier -- an imported name is a snapshot and goes stale the moment the stream is reseeded.
"""
import random



#region Randomness
# Single source of randomness for the whole solver: operand selection, RouteSet sampling, and the
# Metropolis coin all draw from here. Owning one explicit generator (rather than the process-wide
# `random` module) means a run is reproducible from one seed and cannot be perturbed by unrelated
# code -- test harnesses, notebooks, library internals -- drawing from the global stream.
#
# Reproducibility matters here beyond tidiness: the solver is a long random walk, so a single
# extra draw anywhere permanently diverges the trajectory. That is what makes an intermittent
# bug non-bisectable, and it is why instrumenting a failing run can make the failure disappear.
#
# WHY random.Random AND NOT np.random.Generator: the guarantee we need is one OWNED, seeded
# stream -- isolated from anything else in the process -- and a Random instance gives exactly
# that. numpy's Generator gives the same isolation but is built for bulk array generation, so
# every scalar draw pays array machinery: measured at ~6-8x the stdlib cost per call
# (rand_index 0.91us vs 0.13us, rand_choice 0.91us vs 0.12us, distinct-pair 4.50us vs 1.02us).
# The solver only ever draws scalars, millions of times, so that overhead is pure loss.
solver_rng: random.Random = random.Random()


def seed_solver_rng(seed) -> random.Random:
    """Reseed the shared generator. Call once before a solve to make it reproducible."""
    global solver_rng
    solver_rng = random.Random(seed)
    return solver_rng


def rand_unit() -> float:
    """Uniform float in [0, 1)."""
    return solver_rng.random()


def rand_index(num_options: int) -> int:
    """Uniform index in [0, num_options)."""
    return solver_rng.randrange(num_options)


def rand_int_inclusive(low: int, high: int) -> int:
    """Uniform int in [low, high] -- INCLUSIVE upper bound, as randint defines it."""
    return solver_rng.randint(low, high)


def rand_choice(sequence):
    """Uniform element of a sequence supporting len() and indexing (including RouteSet)."""
    return solver_rng.choice(sequence)


def rand_distinct_indices(num_options: int, count: int) -> list[int]:
    """`count` distinct indices from [0, num_options)."""
    return solver_rng.sample(range(num_options), count)


def rand_shuffle(items: list) -> None:
    """In-place shuffle."""
    solver_rng.shuffle(items)
#endregion

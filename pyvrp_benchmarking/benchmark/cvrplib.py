"""
Shared CVRPLIB helpers: a TSPLIB CVRP reader, the EUC_2D distance convention,
and an independent solution verifier.

Nothing here imports the solver, so it can be used to check any solver's output.
"""
from __future__ import annotations

import math
from pathlib import Path


def euc_2d(a: tuple[float, float], b: tuple[float, float]) -> int:
    """TSPLIB EUC_2D: nint(euclidean), rounding half away from zero.

    This is the convention the published best-known solutions are defined on.
    Comparing a float-distance objective against those values is meaningless,
    so every distance on both sides of this benchmark goes through here.
    """
    return int(math.hypot(b[0] - a[0], b[1] - a[1]) + 0.5)


def read_instance(path: str | Path) -> dict:
    """Minimal TSPLIB CVRP reader.

    Returns {name, coords: {id: (x, y)}, demands: {id: int}, depot: id,
             capacity: int, n_customers: int}.
    Raises on anything that is not a single-depot EUC_2D CVRP, rather than
    silently producing a different problem.
    """
    coords: dict[int, tuple[float, float]] = {}
    demands: dict[int, int] = {}
    depots: list[int] = []
    capacity: int | None = None
    name = Path(path).stem
    section = None

    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line == "EOF":
            continue

        if line.endswith("_SECTION"):
            section = line.split("_")[0]
            continue

        if ":" in line and not line[0].isdigit():
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key == "CAPACITY":
                capacity = int(val)
            elif key == "EDGE_WEIGHT_TYPE" and val != "EUC_2D":
                raise ValueError(f"{name}: EDGE_WEIGHT_TYPE {val!r}; only EUC_2D supported")
            elif key == "TYPE" and val != "CVRP":
                raise ValueError(f"{name}: TYPE {val!r}; only CVRP supported")
            continue

        parts = line.split()
        if section == "NODE":
            coords[int(parts[0])] = (float(parts[1]), float(parts[2]))
        elif section == "DEMAND":
            demands[int(parts[0])] = int(parts[1])
        elif section == "DEPOT":
            if int(parts[0]) != -1:
                depots.append(int(parts[0]))

    if capacity is None:
        raise ValueError(f"{name}: no CAPACITY")
    if len(depots) != 1:
        raise ValueError(f"{name}: {len(depots)} depots; this harness is single-depot CVRP only")

    return {
        "name": name,
        "coords": coords,
        "demands": demands,
        "depot": depots[0],
        "capacity": capacity,
        "n_customers": len(coords) - 1,
    }


def read_bks(path: str | Path) -> float | None:
    """Read the objective from a CVRPLIB .sol file ('Cost <value>' on the last line)."""
    p = Path(path)
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        if line.lower().startswith("cost"):
            return float(line.split()[-1])
    return None


def verify_routes(routes: list[list[int]], inst: dict) -> tuple[int, list[str]]:
    """Re-verify a solution from raw geometry, independent of any solver's bookkeeping.

    `routes` is a list of routes, each a list of *instance node ids* (not indices),
    excluding the depot. Returns (total_distance, problems).
    """
    coords, demands = inst["coords"], inst["demands"]
    depot, cap = inst["depot"], inst["capacity"]
    problems: list[str] = []
    seen: set[int] = set()
    total = 0

    for r_i, route in enumerate(routes):
        if not route:
            continue
        load = sum(demands[node] for node in route)
        if load > cap:
            problems.append(f"route {r_i} overloaded: load {load} > capacity {cap}")
        pts = [coords[depot]] + [coords[node] for node in route] + [coords[depot]]
        total += sum(euc_2d(a, b) for a, b in zip(pts, pts[1:]))
        for node in route:
            if node in seen:
                problems.append(f"node {node} visited more than once")
            seen.add(node)

    missing = inst["n_customers"] - len(seen)
    if missing:
        problems.append(f"{missing} customer(s) not visited "
                        f"({len(seen)} of {inst['n_customers']})")
    return total, problems

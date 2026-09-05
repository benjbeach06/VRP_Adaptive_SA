"""
The Crevier / Cordeau / Laporte MDVRPI benchmark — instances and evaluator.

Reference: B. Crevier, J.-F. Cordeau, G. Laporte, "The multi-depot vehicle routing
problem with inter-depot routes", European Journal of Operational Research
176(2):756-773, 2007.

WHY THIS FILE EXISTS
--------------------
This repository's model *is* the MDVRPI: routes may run between different depots,
and a vehicle performs a chained sequence of routes (Crevier et al. call it a
"rotation"). The problem is not new, and it has a published benchmark. `RESULTS.md`
claims no external benchmark exists for this combination; that claim is wrong and
this file is the correction.

INSTANCE IDENTIFICATION
-----------------------
The paper says the 10 adapted instances were built from the Cordeau/Gendreau/Laporte
MDVRP set by adding "a central depot at the centroid of the other depots", giving
5- or 7-depot instances, with D and Q "determined experimentally". It does not name
the source instances. They are identifiable without ambiguity from the dimensions in
its Table 7, which match the `pr` series exactly on BOTH customer count and depot
count:

    a2 (n=48,  r=5) <- pr01 (n=48,  4 depots)      g2 (n=72,  r=7) <- pr07 (n=72,  6)
    b2 (n=96,  r=5) <- pr02 (n=96,  4)             h2 (n=144, r=7) <- pr08 (n=144, 6)
    c2 (n=144, r=5) <- pr03 (n=144, 4)             i2 (n=216, r=7) <- pr09 (n=216, 6)
    d2 (n=192, r=5) <- pr04 (n=192, 4)             j2 (n=288, r=7) <- pr10 (n=288, 6)
    e2 (n=240, r=5) <- pr05 (n=240, 4)
    f2 (n=288, r=5) <- pr06 (n=288, 4)

Customer coordinates, demands and service durations therefore come from the original
files and are exact. D and Q are taken from Table 7. This reconstruction is
deterministic; the 12 *randomly generated* instances (a1-l1) are not reproducible,
because the paper gives the generating distribution but no seed.

WHAT THE PROBLEM REQUIRES
-------------------------
    minimise  total travel duration
    s.t.      load of each route          <= Q
              duration of each rotation   <= D
              at most m vehicles used

where a rotation's duration counts travel + per-customer service time + a docking
time tau = 15 at each intermediate depot.

The duration constraint is the part this repository's model does not implement --
see `planning/vehicle-time-limits.md`, "Status: not started". `evaluate` below
therefore reports duration feasibility separately from cost, so a relaxed run can be
scored honestly rather than compared as though it were feasible.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

TAU = 15.0          # docking time at an intermediate depot (paper, section 5)

# Table 7: source instance -> (name, num_depots_after_centroid, m, D, Q)
ADAPTED = {
    "pr01": ("a2", 5, 4,  600, 150),
    "pr02": ("b2", 5, 4, 1150, 200),
    "pr03": ("c2", 5, 4, 1700, 250),
    "pr04": ("d2", 5, 3, 2250, 300),
    "pr05": ("e2", 5, 3, 2800, 350),
    "pr06": ("f2", 5, 3, 3350, 400),
    "pr07": ("g2", 7, 4,  950, 175),
    "pr08": ("h2", 7, 4, 1800, 250),
    "pr09": ("i2", 7, 3, 2650, 325),
    "pr10": ("j2", 7, 3, 3500, 400),
}

# Table 8, column c(s^b): best value reported by Crevier et al.
PUBLISHED_BEST = {
    "a2":  997.94, "b2": 1307.28, "c2": 1747.61, "d2": 1871.42, "e2": 1942.85,
    "f2": 2284.35, "g2": 1162.58, "h2": 1587.37, "i2": 1972.00, "j2": 2294.06,
}


def dist(a, b) -> float:
    """Euclidean, unrounded. The Cordeau/Crevier convention is real-valued distance."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def read_cordeau(path: str | Path) -> dict:
    """Read a Cordeau MDVRP file (type 2). Returns depots, customers, D, Q."""
    lines = [l for l in Path(path).read_text().splitlines() if l.strip()]
    typ, m, n, t = (int(float(x)) for x in lines[0].split()[:4])
    if typ != 2:
        raise ValueError(f"{path}: type {typ}, expected 2 (MDVRP)")

    dq = [tuple(float(x) for x in lines[1 + i].split()[:2]) for i in range(t)]
    body = lines[1 + t:]

    customers = []
    for row in body[:n]:
        f = row.split()
        customers.append({"id": int(f[0]), "loc": (float(f[1]), float(f[2])),
                          "service": float(f[3]), "demand": float(f[4])})
    depots = []
    for row in body[n:n + t]:
        f = row.split()
        depots.append((float(f[1]), float(f[2])))

    return {"m_per_depot": m, "n": n, "num_depots": t,
            "orig_D": dq[0][0], "orig_Q": dq[0][1],
            "customers": customers, "depots": depots}


def build_adapted(src_path: str | Path) -> dict:
    """Build one MDVRPI instance: original depots + a centroid depot, Table 7 D/Q."""
    src = Path(src_path)
    if src.stem not in ADAPTED:
        raise ValueError(f"{src.stem} is not one of the adapted sources")
    name, expect_r, m, D, Q = ADAPTED[src.stem]

    raw = read_cordeau(src)
    cx = sum(d[0] for d in raw["depots"]) / len(raw["depots"])
    cy = sum(d[1] for d in raw["depots"]) / len(raw["depots"])
    depots = raw["depots"] + [(cx, cy)]          # centroid depot appended last

    if len(depots) != expect_r:
        raise ValueError(f"{name}: built {len(depots)} depots, Table 7 says {expect_r}")
    if raw["n"] != {"a2": 48, "b2": 96, "c2": 144, "d2": 192, "e2": 240,
                    "f2": 288, "g2": 72, "h2": 144, "i2": 216, "j2": 288}[name]:
        raise ValueError(f"{name}: n={raw['n']} does not match Table 7")

    return {
        "name": name, "source": src.stem,
        "depots": [list(d) for d in depots],
        "customers": [{"loc": list(c["loc"]), "demand": c["demand"],
                       "service": c["service"]} for c in raw["customers"]],
        "capacity": Q, "max_rotation_duration": D, "num_vehicles": m,
        "docking_time": TAU,
        "published_best": PUBLISHED_BEST[name],
    }


def evaluate(itineraries: list[list[dict]], inst: dict) -> dict:
    """Score an MDVRPI solution from raw geometry.

    `itineraries` uses the same format as mdvrp.py: a list of vehicles, each a list
    of trips {"start", "end", "visits"}.

    Cost is total travel duration -- the paper's objective. Capacity and rotation
    duration are checked and reported SEPARATELY, so a solver that does not
    implement the duration constraint can still be scored on the objective while the
    violation is stated rather than hidden.
    """
    depots = [tuple(d) for d in inst["depots"]]
    custs = [tuple(c["loc"]) for c in inst["customers"]]
    dem = [c["demand"] for c in inst["customers"]]
    svc = [c["service"] for c in inst["customers"]]
    Q, D, tau = inst["capacity"], inst["max_rotation_duration"], inst["docking_time"]

    problems, dur_violations = [], []
    seen: set[int] = set()
    travel = 0.0
    used = 0

    for v, itin in enumerate(itineraries):
        trips = [t for t in itin if t["visits"]]
        if not trips:
            continue
        used += 1

        for a, b in zip(itin, itin[1:]):
            if a["end"] != b["start"]:
                problems.append(f"vehicle {v}: chain break {a['end']} -> {b['start']}")

        rotation = 0.0
        for k, t in enumerate(trips):
            load = sum(dem[c] for c in t["visits"])
            if load > Q + 1e-9:
                problems.append(f"vehicle {v} trip {k}: load {load:g} > Q={Q:g}")
            pts = ([depots[t["start"]]] + [custs[c] for c in t["visits"]]
                   + [depots[t["end"]]])
            leg = sum(dist(p, q) for p, q in zip(pts, pts[1:]))
            travel += leg
            rotation += leg + sum(svc[c] for c in t["visits"])
            if k < len(trips) - 1:
                rotation += tau                     # docking at the intermediate depot
            for c in t["visits"]:
                if c in seen:
                    problems.append(f"customer {c} visited more than once")
                seen.add(c)

        if rotation > D + 1e-9:
            dur_violations.append({"vehicle": v, "duration": round(rotation, 2),
                                   "limit": D, "over_pct": round(100 * (rotation - D) / D, 1)})

    if len(seen) != len(custs):
        problems.append(f"covered {len(seen)} of {len(custs)} customers")
    if used > inst["num_vehicles"]:
        problems.append(f"used {used} vehicles, m={inst['num_vehicles']}")

    return {
        "cost": travel,
        "vehicles_used": used,
        "capacity_and_coverage_ok": not problems,
        "problems": problems,
        "duration_ok": not dur_violations,
        "duration_violations": dur_violations,
        "worst_over_pct": max((d["over_pct"] for d in dur_violations), default=0.0),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="build the 10 adapted MDVRPI instances")
    ap.add_argument("--cordeau", required=True, help="dir holding pr01..pr10")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "instances" / "MDVRPI"))
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    print(f"{'name':<5}{'src':>6}{'n':>6}{'r':>4}{'m':>4}{'D':>7}{'Q':>6}"
          f"{'demand':>9}{'published':>11}")
    for src in sorted(ADAPTED):
        inst = build_adapted(Path(args.cordeau) / src)
        (out / f"{inst['name']}.json").write_text(json.dumps(inst, indent=1))
        tot = sum(c["demand"] for c in inst["customers"])
        print(f"{inst['name']:<5}{src:>6}{len(inst['customers']):>6}"
              f"{len(inst['depots']):>4}{inst['num_vehicles']:>4}"
              f"{inst['max_rotation_duration']:>7g}{inst['capacity']:>6g}"
              f"{tot:>9g}{inst['published_best']:>11.2f}")

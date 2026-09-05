# Instances

- `MDVRPI/` — the 10 Crevier et al. (2007) adapted instances, rebuilt from Cordeau `pr01`-`pr10`
  by `../mdvrpi.py`. Deterministic; regenerate with
  `python benchmark/mdvrpi.py --cordeau <dir with pr01..pr10>`.
- `MDVRP/` — the generated multi-depot chaining instances, from `../mdvrp.py`. Regenerate with
  `python benchmark/mdvrp.py`.
- `CVRP/` — **not included.** The CVRPLIB X-series is ~57 MB; `../setup.sh` clones it from
  https://github.com/PyVRP/Instances on first run.

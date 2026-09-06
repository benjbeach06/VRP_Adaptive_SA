# Experiment logs

Raw results of every full experiment. Each file carries a `HOW RUN` header, or a `_how_run` key in
JSON, so it can be read or discarded on its own without this index.

**Every result here is valid. Several are DATED.** A measurement describes the solver that produced
it, and the solver has changed. The `solver state` column says which one, so a reader can tell
whether a number still applies. Retracted measurements are separate, in [`withdrawn/`](#withdrawn).

**The discipline that makes this work: run experiments from a CLEAN SOLVER COMMIT.** The four
modules `SimAnn_VRP_Core_Model.py`, `SimAnn_VRP_BLOperators.py`, `SimAnn_VRP_Operators.py` and
`SimAnn_VRP_Solver.py` must be committed before a run starts. Docs, planning and tooling may be
dirty -- they do not change what a solve does.

Without that, the recorded SHA does not describe the code that ran, and nobody can recover what did.
`tools/preflight.py` fails on a dirty solver; `--allow-dirty` overrides it and marks the result
throwaway. Harnesses stamp `_solver` into their output, so the state is recorded rather than
reconstructed.

Milestones the states refer to:

## Ablations live in `ablations/`

One folder per ablation, named `<date>_<slug>`, holding its own `README.md`, `results.json`,
`run.log` and `deltas.png`. Each folder is readable on its own. Regenerate a plot with
`tools/plot_ablation.py <folder>`.

Files outside that folder predate the convention.

## Benchmarks live in `benchmarks/`

Same shape as `ablations/`: one folder per benchmark, named `<date>_<slug>`, readable on its own.
A benchmark measures this solver against an EXTERNAL reference -- a published best-known value or
another solver -- rather than against a variant of itself.

The harness for the PyVRP comparisons is `pyvrp_benchmarking/`, not `tools/`, and the raw JSON
lines stay there beside it. A benchmark folder here carries the analysis and points at them.

Ablation and tuning folders have not been moved yet.

| commit | date | what changed |
|---|---|---|
| `58ae053` | 08-16 | 20-operator roster, neighbor-guided operators present |
| `b5167e0` | 08-16 | `explore_reward` floor added |
| `fed10e8` | 08-16 | improvement counter fixed, so plateau reheating works |
| `2fb9857` | 08-18 | 23 operators: the farthest-insertion family, `PermuteChain` |
| *uncommitted* | 08-19 | `exploit_only`, selection penalty factors, `adj_weights` mirror |
| `f14b82b` | 08-19 | 24 operators; family-level selection with a tree, MAX weights and root floors |
| `a54710e` | 08-21 | `EXACT_REORDER_MAX_SPAN` 8 -> 4, after the full-roster K sweep |
| `97718ad` | 09-04 | vehicle duration objective, off by default |
| `d4fdfbd` | 09-04 | `start_time` moved before setup; `ChangeRandomEndDepot` removed when there is one depot |

## Results

| file | solver state | how it was run |
|---|---|---|
| `tune_results.json` | 08-11, **pre-neighbor roster**, no `explore_reward` | `tools/tune.py` -- 704-trial Optuna/TPE search over the ANNEALING SCHEDULE constants. Landscape flat; hand defaults won. |
| `tuning_report.txt` | as above | Report for the 704-trial schedule search. |
| `tune_log.txt` | as above | stdout of the schedule search. |
| `validate_results.json` | as above | `tools/validate.py` -- paired re-measurement of that search's top configs at 240s on unseen seeds. Defaults won. |
| `profile_cold.json` | 08-15, **pre-neighbor roster** | `tools/profile_operators.py` -- per-operator cost across sizes 10/100/1000/5000, cold. |
| `profile_warm.json` | as above | Same, warm. |
| `profile_cold_log.txt` | as above | stdout of the cold profiling run. |
| `profile_warm_log.txt` | as above | stdout of the warm profiling run. |
| `profile_bestofk.txt` | as above | pyinstrument tree for `CustomerBestOfkSwapInRandomRoute`. Absolute times inflated ~2.65x by instrumentation; compare proportions. |
| `profile_CustomerBestOfkSwapInRandomRoute.txt` | as above | Single-operator profile, same driver. |
| `ablation_results.json` | **`58ae053`, 20 operators, no `explore_reward` floor** | `tools/ablate_operators.py` -- one-factor-at-a-time ablation. 10h, sizes 50/500/5000, capacity 400, 1641 runs over 21 seed-rounds, paired on seed, breadth-first. |
| `ablation_report.txt` | as above | Report rendered from `ablation_results.json`. |
| `ablation_log.txt` | as above | stdout of the ablation run. |
| `tune_selection_v2.json` | **post-`fed10e8`, 20 operators**, counter fixed | `tools/tune.py --sizes 200 --capacity 25 --seconds-per-run 60 --runs-per-size 4 --budget-seconds 36000`. 149 trials, 10h. Found nothing: best 0.9889 was less extreme than pure noise predicts. |
| `tune_v2_log.txt` | as above | stdout of the v2 selection search. |
| `Robustness_Smoke_Test.txt` | **20 operators** (confirmed from its own stats block) | `SimAnn_VRP.py` by hand: 600s, n=500, capacity 400, DUMB initial solution. Robustness case study. Digest with `tools/digest_run_log.py`. |
| `JIT_Smoke_Test.txt` | `a54710e`, 24 operators, K=4 | CPython 3.14.6 experimental JIT, `PYTHON_JIT=1` against unset. n=500 capacity 400, 20s, deterministic weighting so both arms share a trajectory. **Verdict: do not enable, 5.4% slower.** Per-operator data in `jit_smoke_ops_off.json` and `jit_smoke_ops_on.json`. |
| [`benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/`](benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/README.md) | `d4fdfbd` (CVRP arms), `97718ad` (MDVRP) | First external benchmark. 8 CVRPLIB X-series against published best-known, 6 generated multi-depot against PyVRP 0.14, 60 s and 3 seeds. **5.6% off best-known on CVRP where PyVRP is 0.6%.** Multi-depot mean beats PyVRP by 1.56%, but travel is worse on all six and the win is fleet consolidation; PyVRP itself certifies the solution feasible. Fleet size of 1 vs `ceil(demand/capacity)+2` is below the noise floor. |
| [`benchmarks/2026-09-05_pyvrp_600s/`](benchmarks/2026-09-05_pyvrp_600s/README.md) | `cbcbb4f`, both arms | The 2026-09-04 benchmark repeated at **600 s**, same 14 instances, 3 seeds and 1 PyVRP seed, 56 runs. **CVRP 4.35% off best-known where PyVRP is 0.38%**; both sides improve and the ratio barely moves. Multi-depot **travel** gap halves, +3.90% to +1.82%, and stops agreeing with the CVRP gap -- unexplained. Corroborates the unprovenanced 2026-08-24 600 s table in RESULTS.md. |
| [`benchmarks/2026-09-05_rrr_removal_60s/`](benchmarks/2026-09-05_rrr_removal_60s/README.md) | `ab16365` (baseline) vs `c5eda54` (treatment) | Paired A/B on the `RandomRouteReassignment` removal. 8 CVRPLIB X-series, 60 s, 5 seeds, 80 runs, baseline and treatment INTERLEAVED per (instance, seed). **No effect on quality: paired mean -0.11%, sd 0.60%, 19 wins to 19 losses, sign test p = 1.00.** Mean gap to best-known 5.47% against 5.36%. The arms were proved to differ by exactly that one operator, in both trees. Says nothing about the efficiency claim -- no iteration count is recorded. |
| `ablate_explore_reward.json` | **post-`2fb9857`, 23 operators**, before `exploit_only` | `tools/ablate_param.py` -- paired ablation of `explore_reward` over 0 / 1e-2 / 1e-5 / 1e-8. 30 seeds x 5min x 4 arms, n=500 capacity 400, dumb start, 9.9h. |
| `ablate_explore_reward_log.txt` | as above | stdout of that ablation. |
| `run_comparison.png` | **23 operators WITH `exploit_only` and penalty factors** | `tools/compare_runs.py` -- Hexaly against two SimAnn configurations, same instance. |

**What "dated" costs, concretely.** The ablation ranked a 20-operator roster. Three operators have
been added since, and the selection mechanism now prices them differently. Its ranking of the
operators it covered still holds; its claim to rank *the roster* does not.

## Withdrawn

`withdrawn/` holds measurements that are **invalid**, not merely dated. A result lands here when it
was produced under a significant core algorithmic defect, or by poor methodology. The distinction
matters: a dated result still measures something real.

They are kept rather than deleted. A discarded result is evidence about the method, and removing it
hides that the method once failed.

Every file here is void for the same reason. The `explore_reward` floor (`b5167e0`) removed the sign
that `OperatorStats.record_accept` used to detect an improvement, which silently disabled plateau
reheating. Each of these ran between that commit and the fix at `fed10e8`, so each measured a solver
whose reheat mechanism could not fire.

The valid rerun is `tune_selection_v2.json`. Reasoning in [RESULTS.md](../RESULTS.md).

| file | how it was run |
|---|---|
| `withdrawn/tune_selection_results.json` | `tools/tune.py` over OPERATOR SELECTION params (`one_minus_K`, `segment_length`, `explore_reward`), 4.5h, n=500 capacity 400. |
| `withdrawn/tune_selection_log.txt` | stdout of the void selection search. |
| `withdrawn/validate_selection.json` | `tools/validate.py` -- paired validation of the void selection search. |
| `withdrawn/validate_selection_log.txt` | stdout of the void validation. |
| `withdrawn/confirm_L_log.txt` | Scratch isolation run: does `segment_length` alone explain the selection result? 4 configs x 12 seeds x 60s at n=500. |

## References

- [RESULTS.md](../RESULTS.md) -- reasoning for why the withdrawn reheat-affected reruns are invalid
- [experiment_logs/benchmarks/2026-09-05_pyvrp_600s/README.md](benchmarks/2026-09-05_pyvrp_600s/README.md) -- the 600 s repeat indexed above -- full tables, the driver, and the raw jsonl behind that row
- [experiment_logs/benchmarks/2026-09-05_rrr_removal_60s/README.md](benchmarks/2026-09-05_rrr_removal_60s/README.md) -- the paired operator-removal A/B indexed above -- the per-instance table, the two-way detector check, and why the design is paired rather than two blocks
- [experiment_logs/benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/README.md](benchmarks/2026-09-04_pyvrp_cvrp_mdvrp/README.md) -- the 60 s original indexed above -- full tables, the four harness defects fixed first, and the PyVRP feasibility certificate

## Links to here

*(none yet)*

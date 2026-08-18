# Experiment logs

Raw results of every full experiment. Each file carries a `HOW RUN` header (`_how_run` key in JSON) so it can be reproduced or discarded on its own.

**VOID entries are kept on purpose.** A discarded result is evidence about the method, and deleting it hides that the method once failed. See `RESULTS.md`.

| file | status | how it was run |
|---|---|---|
| `Robustness_Smoke_Test.txt` | VALID | SimAnn_VRP.py run by hand: 600s, n=500, capacity 400, DUMB initial solution (make_dumb_initial_solution). Robustness case study. Digest with tools/digest_run_log.py. |
| `ablation_log.txt` | VALID | stdout of the ablation run above. |
| `ablation_report.txt` | VALID | Report rendered from ablation_results.json by tools/ablate_operators.py. |
| `ablation_results.json` | VALID | tools/ablate_operators.py -- one-factor-at-a-time operator ablation, 10h budget, sizes 50/500/5000, capacity 400, 1641 runs over 21 seed-rounds, paired on seed, breadth-first over seeds. Commit 58ae053. |
| `confirm_L_log.txt` | VOID | Scratch isolation run: does segment_length alone explain the selection result? 4 configs x 12 seeds x 60s at n=500. |
| `profile_CustomerBestOfkSwapInRandomRoute.txt` | VALID | Single-operator profile, same driver. |
| `profile_bestofk.txt` | VALID | pyinstrument tree for CustomerBestOfkSwapInRandomRoute, via tools/profile_one_operator.py. Absolute times inflated ~2.65x by instrumentation; compare proportions. |
| `profile_cold.json` | VALID | tools/profile_operators.py -- per-operator cost across instance sizes 10/100/1000/5000, cold. |
| `profile_cold_log.txt` | VALID | stdout of the cold profiling run. |
| `profile_warm.json` | VALID | tools/profile_operators.py -- same, warm. |
| `profile_warm_log.txt` | VALID | stdout of the warm profiling run. |
| `tune_log.txt` | VALID | stdout of the schedule search above. |
| `tune_results.json` | VALID | tools/tune.py -- 704-trial Optuna/TPE search over the ANNEALING SCHEDULE constants, 2026-08-11. Landscape flat; hand defaults won. |
| `tune_selection_log.txt` | VOID | stdout of the void selection search above. |
| `tune_selection_results.json` | VOID | tools/tune.py over OPERATOR SELECTION params (one_minus_K, segment_length, explore_reward), 4.5h, n=500 capacity 400. |
| `tune_selection_v2.json` | VALID | tools/tune.py --sizes 200 --capacity 25 --seconds-per-run 60 --runs-per-size 4 --budget-seconds 36000 -- the RERUN against the fixed counter. 149 trials, 10h. Found nothing: best 0.9889 was less extreme than pure noise predicts. |
| `tune_v2_log.txt` | VALID | stdout of the v2 selection search above. |
| `tuning_report.txt` | VALID | Report for the 704-trial schedule search. |
| `validate_results.json` | VALID | tools/validate.py -- paired re-measurement of the schedule search's top configs at 240s on unseen seeds. Defaults won. |
| `validate_selection.json` | VOID | tools/validate.py -- paired validation of the void selection search. |
| `validate_selection_log.txt` | VOID | stdout of the void validation above. |

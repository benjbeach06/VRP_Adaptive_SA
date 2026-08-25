# The schedule clock

Cooling and plateau-reheat detection both read ONE clock, `self.schedule_now`, set once per
iteration in `solve()`. Sharing a clock is what keeps them from disagreeing about what a unit of
progress is.

```python
schedule_now = elapsed_time if time_based_schedule else iterations
cooling_rate = cooling_rate_per_second if time_based_schedule else -log_cooling_factor
```

## Two modes, and why both exist

**Time mode is production.** The solver terminates on wall clock, so a schedule denominated in
seconds is the one that matches the budget it is spending.

**Iteration mode exists to enable determinism.** Temperature drives every accept decision, so a
clock-driven schedule makes a run irreproducible from its seed. `set_deterministic_weighting()`
selects iteration mode alongside `weight_by_time = False` and the weight EMA's own decay clock
([../operator_selection/dynamic_penalty.md](../operator_selection/dynamic_penalty.md)), which
together close every wall-clock path into selection and acceptance. Without an iteration clock
there would be no reproducible configuration at all, and no bisectable bug report.

The consequence is worth stating: **deterministic mode is a different configuration, not production
with a frozen clock.** A green determinism test exercises the iteration path and says nothing about
the time-based one.

Each mode owns its own parameters, so neither is ever silently inactive:

| mode | cooling | plateau |
|---|---|---|
| time | `cooling_rate_per_second` | `max_plateau_seconds` |
| iterations | `cooling_factor` | `max_plateau_size` (× `segment_length`) |

## `segment_length` is a pure sampling rate

It controls how often weights are recomputed, and nothing else. In iteration mode it also
multiplies into the plateau length; in time mode `max_plateau_seconds` is read directly, so the
coupling is gone.

## The reheat equilibrium is unit-invariant

`gap = C × S × R` holds in either mode. `C` is cooling per unit of the schedule clock and `S` is
clock-units per reheat, so changing the unit scales `C` by `1/k` and `S` by `k`. The product is
unchanged, and `R` is dimensionless. Switching units therefore needs no re-derivation and no
re-measurement.

## Calibration

Either mode can be derived from the other, given a throughput `T` in iterations per second. The
relations are what matter; the numbers depend on the machine and the roster.

```
cooling_rate_per_second = |log2(cooling_factor)| × T
max_plateau_seconds     = max_plateau_size × segment_length / T
```

Read the other way, they say what a time-mode value means in iteration terms. Both hold only at the
`T` used, and `T` moves with the operator mix, which is the reason the schedule is denominated in
seconds in the first place.

A derivation like this gives a neutral starting point, not a good one. The shipped defaults come
from the search below.

## Related experiments

- [experiment_logs/tuning/2026-08-23_six_param_time_based.json](../../experiment_logs/tuning/2026-08-23_six_param_time_based.json)
  -- search over six schedule and selection parameters together. Informed the shipped defaults for
  `cooling_rate_per_second`, `max_plateau_seconds` and `segment_length`.
- [experiment_logs/ablations/2026-08-23_tuned_vs_stage1/](../../experiment_logs/ablations/2026-08-23_tuned_vs_stage1/README.md)
  -- the tuned schedule against the scoring rework's stage-1 commit. Informed accepting those
  defaults.

## References

- [../operator_selection/dynamic_penalty.md](../operator_selection/dynamic_penalty.md) —
  `segment_time` and `weight_time_constant`, the weight EMA's own decay clock, which
  `set_deterministic_weighting()` disables alongside this one.

## Links to here

- [../operator_selection/dynamic_penalty.md](../operator_selection/dynamic_penalty.md) — cites this
  for the weight EMA's decay rate.
- [../../planning/implemented/scoring-rework.md](../../planning/implemented/scoring-rework.md) —
  names this as one of the two changes that followed from the same diagnosis.
- [../README.md](../README.md) — summarises this doc in the top-level index.

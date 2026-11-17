# Webster fixed-time baseline

Controller identifier: `webster_fixed_time`. real_signals network only.

## Why

`static_fixed_time` gives every phase 30 s, a naive plan. Published adaptive systems
(SCOOT, SCATS) are measured against fixed-time plans a traffic engineer optimised from
counts, so comparing only against 30 s greens overstates any gain. This baseline is that
optimised fixed-time plan.

## How

`scripts/setup/make_webster_plans.py` runs SUMO's `tlsCycleAdaptation.py` (Webster's
method) on each scenario's seed-42 demand, the "historical counts":

- 3 s yellow
- greens at least 7 s, the same minimum as actuated control and the rl agents
- cycle 30-120 s

It keeps only the eight agent lights and writes
`sumo/skopje/network/webster_real_signals/<scenario>.add.xml`. The same plan runs
unchanged on every seed.

At the start of each run, `WebsterFixedTimeController` installs the plan on the agent
lights through TraCI. Every other light keeps its imported program, as in
`imported_actuated`.

```powershell
$env:SKOPJE_NETWORK="real_signals"
python scripts/setup/make_webster_plans.py
python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42 --webster
```

Cycles came out at 33-41 s on `low` and 34-45 s on `medium`. On `high` they ran 35-65 s.
On `peak` they hit the 120 s cap at the busiest lights.

The plans are from Webster's formula, not Skopje's real timings, which the TMCC holds.
Rerun the script after changing the network or the demand.

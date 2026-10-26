# Imported SUMO Actuated Baseline

The imported actuated baseline evaluates the traffic-light programs
contained in the imported SUMO network without issuing manual
phase-control actions. These programs are used as a simulation baseline
and are not claimed to reproduce the official operational traffic-control
system of the City of Skopje.

We have not verified the imported programs against official City of
Skopje signal plans, detector logic, offsets, or time-of-day schedules.
The controller identifier for this baseline is always `imported_actuated`.
It is never labeled `skopje_official`, `official_skopje`, or
`original_skopje_controller` -- `src/baselines/imported_actuated.py`
actively rejects those names.

## Purpose

This baseline establishes a responsive, non-learning benchmark that
future Q-learning and coordinated MARL controllers must beat. It sits
between the two simpler and more advanced controllers in the project's
comparison path:

```
static_fixed_time -> imported_actuated -> independent_q_learning -> coordinated_marl
```

Unlike `static_fixed_time` (which assigns a deterministic duration to
every green phase through the safe KEEP/NEXT_GREEN action wrapper), this
baseline never requests a phase change. It leaves the imported SUMO
actuated programs already attached to all eight selected traffic lights
fully in control.

## Scope

The controller configures all eight selected traffic-light agents: A9,
A18, A19, A20, A24, A25, A26, A29 (`SELECTED_CORRIDOR.agent_ids`). The
complete Skopje SUMO network stays active. No reinforcement-learning code
or action is used, and no manual traffic-light action of any kind
(`KEEP` or `NEXT_GREEN`) is ever issued.

## How zero-action control is enforced

`ImportedActuatedController` (`src/baselines/imported_actuated.py`) wraps
a `MultiAgentTrafficEnvironment` (`src/environment/multi_agent_environment.py`)
and always advances it with `environment.step(None)`. The environment's own
`step()` implementation already treats `actions=None` as an
observation-only decision round: `_validate_actions` is never called and no
`TrafficSignal.apply_action` request is ever sent
(`MultiAgentTrafficEnvironment.step`, `_validate_actions`). The controller
also refuses to run against anything other than the full eight-agent
selected corridor, so this baseline can never silently narrow which
traffic lights stay under the imported program's control.

This baseline deliberately reuses existing components instead of
duplicating them: `MultiAgentEnvironmentConfig`, `MultiAgentTrafficEnvironment`,
`MultiAgentStepResult`, the shared `src/evaluation/` metrics package, the
existing low/medium/high demand scenarios, and the selected corridor are
all used unchanged. No environment lifecycle, observation, reward, or
metrics logic is reimplemented.

## Experiment timing

Each run has two windows, matching the static fixed-time baseline:

- `0` to `demand_seconds` (default 3600 s): scheduled vehicles continue
  departing, per the scenario's own generated demand window.
- `demand_seconds` to `demand_seconds + cooldown_seconds` (default 600 s):
  cooldown -- no new planned demand, active vehicles continue travelling.

Default total simulated duration: 4200 s. Traffic files are not
regenerated for the cooldown period; the existing scenario files are used
unchanged.

`--demand-seconds` must match the scenario's own generated duration
(`TrafficDemandScenario.duration_seconds`, currently 3600 s for low,
medium, and high), reusing the same validation
(`_resolve_demand_seconds`) as the static fixed-time runner.

## Metrics

Every run uses the shared `src/evaluation/` package (`MetricsCollector`,
`EpisodeMetrics`, `append_result`), so results stay directly comparable
with `static_fixed_time` and every other controller. Results are appended
to `results/experiments.csv` with `controller=imported_actuated`.

Recorded fields: controller, scenario, seed, demand duration, cooldown
duration, total simulation duration, average waiting time, average queue
length, maximum queue length, average speed, throughput / arrived
vehicles, departed vehicles, active vehicles remaining, stopped vehicles,
teleport count, and total reward when supported by the shared schema.
`total_reward` and `fixed_green_seconds` stay `None` for this baseline,
since it issues no reinforcement-learning actions and has no fixed-timing
policy.

Per-agent diagnostics (controlled incoming-lane count, average queue,
maximum queue, average waiting time, observed vehicle count, final phase)
are collected for all eight selected agents and printed to the console at
the end of each run. `phase_change_count` is always `0` for every agent,
since this baseline never requests a phase change -- the imported SUMO
actuated programs make every phase decision on their own. Per-agent
diagnostics are not written to `experiments.csv`, matching the existing
shared-metrics design.

## Running experiments

Single experiment:

```powershell
python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600
```

Options: `--scenario {low,medium,high}`, `--seed`, `--demand-seconds`,
`--cooldown-seconds`, `--report-interval`, `--gui`, `--output`.

Canonical seed-42 suite (all three scenarios):

```powershell
python scripts/experiments/run_imported_actuated_suite.py --seed 42
```

Direct reference runs:

```powershell
python scripts/experiments/run_imported_actuated_experiment.py --scenario low --seed 42
python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42
python scripts/experiments/run_imported_actuated_experiment.py --scenario high --seed 42
```

Then summarize:

```powershell
python scripts/analysis/summarize_experiments.py
```

## Validation performed

- `python -m pytest` -- includes `tests/test_imported_actuated_baseline.py`,
  which uses only fake TraCI domains and fake TrafficSignal wrappers (no
  SUMO/SUMO-GUI) and checks: the controller identifier and forbidden-name
  guard; that the environment config always configures all eight selected
  agents in deterministic corridor order and cannot be narrowed; that
  scenario, seed, demand duration, and cooldown duration are forwarded
  correctly; that `environment.step(None)` is used and zero actions are
  ever issued, across repeated decision intervals; that metrics are
  collected through the shared package with `controller=imported_actuated`
  and `phase_change_count=0` for every agent; that TraCI is closed after
  both a successful run and a mid-run exception; that invalid scenarios and
  missing seed files are rejected before SUMO starts; and that no
  reinforcement-learning module is imported.
- `ruff check .`
- `python scripts/experiments/run_imported_actuated_experiment.py --scenario low --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/experiments/run_imported_actuated_experiment.py --scenario high --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/analysis/summarize_experiments.py`

During each real SUMO run, confirm from the console output that:

- all eight selected traffic lights initialize and every environment step
  is observation-only;
- zero manual traffic-light action requests are issued;
- the imported SUMO controllers remain active for the full network;
- the result was appended to `results/experiments.csv` with
  `controller=imported_actuated`;
- the original SUMO network, demand, polygon, and traffic-light files
  remain unchanged;
- no reinforcement-learning code is used.

## Out of scope

This baseline does not change the static fixed-time baseline, does not
use Q-learning, PPO, or neural networks, does not perform coordinated
MARL, does not train or tune hyperparameters, does not regenerate traffic
demand, and does not claim to reproduce official Skopje signal plans.

## Metrics sampling granularity

`build_environment_config()` sets `decision_interval_seconds` to
`DEFAULT_DECISION_INTERVAL_SECONDS` (one raw SUMO second), matching
`sumo_step_length_seconds`. This is required, not just a tuning choice:
`MetricsCollector.record_step()` and the per-agent diagnostics accumulator
both read TraCI's "since the last `simulationStep()` call" snapshot
methods (`simulation.getDepartedIDList`, `getArrivedIDList`,
`lane.getLastStepVehicleIDs`, ...). The runner calls `collector.record_step()`
exactly once per `environment.step(None)` call, so if
`decision_interval_seconds` were larger than `sumo_step_length_seconds`,
`MultiAgentTrafficEnvironment._advance_simulation` would silently advance
several raw SUMO steps per call while metrics were sampled only once,
undercounting departures and arrivals on the skipped intermediate steps.
(An earlier version of this baseline had exactly that bug -- a 5-second
decision interval against 1-second SUMO steps produced
`EpisodeMetrics` validation failures such as `arrived_vehicles cannot
exceed departed_vehicles` on real SUMO runs, since only roughly one in
five departures was ever recorded.) Do not raise
`decision_interval_seconds` above `sumo_step_length_seconds` for this
baseline without also sampling metrics once per raw SUMO step.

## Limitations

- The imported actuated programs' internal detector logic and timing
  parameters are read from the imported SUMO network as-is; this project
  does not audit or recalibrate them.
- This baseline is not a reproduction of any real-world Skopje signal
  timing plan.

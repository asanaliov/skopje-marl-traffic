# Static Fixed-Time Baseline

The static fixed-time controller is an experimental baseline created for
this project. It preserves the imported SUMO phase order and transition
states while assigning deterministic durations to green phases. It is not
claimed to reproduce the official traffic-light timings used by the City of
Skopje.

We do not have verified official Skopje signal timings, detector logic,
offsets, or time-of-day plans. The controller identifier for this baseline
is always `static_fixed_time`. It is never labeled `skopje_official`,
`official_skopje`, or `original_skopje_controller` -- `src/baselines/static_fixed_time.py`
actively rejects those names.

The currently imported SUMO traffic-light programs for the full network are
**actuated** programs. They are not touched by this baseline and must not be
described as the official City of Skopje traffic-light system either.

## Scope

The controller operates only the eight selected traffic lights: A9, A18,
A19, A20, A24, A25, A26, A29 (`SELECTED_CORRIDOR.agent_ids`). Every other
traffic light in the complete Skopje network keeps its original imported
program untouched. No reinforcement-learning code or action is used.

## How fixed timing is enforced

`static_fixed_time` reuses `TrafficSignal`, the same safe KEEP/NEXT_GREEN
action wrapper already built for the (future) learning agents
(`src/environment/traffic_signal.py`, see
`traffic_agent_interface.md`). That wrapper already guarantees, for every
selected agent:

- the original phase order is preserved -- it only ever advances to the
  immediate next phase in the active program;
- original phase-state strings are preserved -- phases are read from SUMO,
  never invented;
- a requested switch away from green is rejected until the configured
  minimum green time has elapsed;
- the immediate next phase must be a yellow or all-red transition state, or
  the switch is refused, so it can never jump directly from one green phase
  to another;
- a forced transition uses the transition phase's own original SUMO
  duration (read from the active program logic), not any value chosen by
  the calling controller.

`StaticFixedTimeConfig.action_policy()` sets `minimum_green_seconds ==
maximum_green_seconds == fixed_green_seconds` on that same wrapper. That is
the only change needed to turn the general-purpose safe wrapper into a
deterministic fixed-time controller: every original green phase runs for
exactly `fixed_green_seconds` before the wrapper enters the next original
transition phase, and that transition keeps its own original duration.
`StaticFixedTimeController` never calls `TrafficAction.KEEP` and never sets
a green phase's duration directly -- it only requests `NEXT_GREEN` on a
fixed polling schedule (`decision_interval_seconds`, default 5 s, capped to
`fixed_green_seconds`) and lets the safe wrapper enforce the actual timing.

Intersections with more than two green phases are handled the same way:
every original green phase receives the same configured fixed duration,
while the complete original phase order (including any intermediate
transition phases) is unchanged.

## Configuration

`fixed_green_seconds` is the only timing value the controller logic reads
(`StaticFixedTimeConfig`, default 30 s). It can be changed via the
`--fixed-green-seconds` command-line option on both runner scripts without
editing any controller code.

## Experiment timing

Each run has two windows:

- `0` to `demand_seconds` (default 3600 s): generated traffic continues
  departing, per the scenario's own generated demand window.
- `demand_seconds` to `demand_seconds + cooldown_seconds` (default 600 s):
  cooldown -- no new planned demand, existing vehicles continue moving.

Default total simulated duration: 4200 s.

`--demand-seconds` must match the scenario's own generated duration
(`TrafficDemandScenario.duration_seconds`, currently 3600 s for low,
medium, and high). The generated trips file spreads vehicle departures
evenly across that exact window, so running with a different value would
silently break that assumption; the runner fails fast with a clear error
instead of accepting a mismatched value. To use a different demand window,
regenerate demand with `scripts/generate_traffic_demand.py --duration`
first.

## Metrics

Every run uses the shared `src/evaluation/` package
(`MetricsCollector`, `EpisodeMetrics`, `append_result`), so results stay
directly comparable with every other controller. Results are appended to
`results/experiments.csv` with `controller=static_fixed_time`.

Three optional columns were added to `EpisodeMetrics` and
`results_writer.COLUMNS` for this baseline: `fixed_green_seconds`,
`demand_seconds`, and `cooldown_seconds`. They were appended at the end of
the existing column order, per `results_writer.py`'s own documented
migration policy ("if new fields are ever added, append them at the end so
old CSVs stay readable"). They are `None` (blank in the CSV) for any
controller that does not set them.

`total_reward` stays `None` for this baseline, since it issues no
reinforcement-learning actions and has no reward signal.

Per-agent diagnostics (controlled incoming-lane count, average queue,
maximum queue, average waiting time, observed vehicle count, final phase,
and phase-change count) are collected for all eight selected agents and
printed to the console at the end of each run. They are not written to
`experiments.csv`, matching the existing shared-metrics design: `per_agent`
is deliberately excluded from `EpisodeMetrics.as_flat_dict()` because its
width varies by controller.

## Running experiments

Single experiment:

```powershell
python scripts/run_static_fixed_time_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600
```

Options: `--scenario {low,medium,high}`, `--seed`, `--fixed-green-seconds`,
`--demand-seconds`, `--cooldown-seconds`, `--report-interval`, `--gui`,
`--output`.

All three canonical scenarios in one command:

```powershell
python scripts/run_static_fixed_time_suite.py --seeds 42
```

Then summarize:

```powershell
python scripts/summarize_experiments.py
```

## Validation performed

- `python -m pytest` -- includes `tests/test_static_fixed_time_baseline.py`,
  which uses only fake TraCI domains (no SUMO/SUMO-GUI) and checks: the
  controller identifier and forbidden-name guard; `StaticFixedTimeConfig`
  timing validation; that green is held (no TraCI mutation) before
  `fixed_green_seconds` elapses; that the wrapper switches to the immediate
  next phase (never skipping to another green) at exactly
  `fixed_green_seconds`; that the forced transition's duration is the
  original program duration, not `fixed_green_seconds`; and
  `final_phase_by_agent()` / `phase_change_counts` bookkeeping.
- `ruff check .`
- `python scripts/run_static_fixed_time_experiment.py --scenario low --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/run_static_fixed_time_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/run_static_fixed_time_experiment.py --scenario high --seed 42 --demand-seconds 3600 --cooldown-seconds 600`
- `python scripts/summarize_experiments.py`

During each real SUMO run, confirm from the console output that:

- all eight selected traffic lights use the static timing policy and every
  other traffic light is unaffected;
- original yellow and all-red transitions remain intact (their durations
  are unchanged from the imported program);
- no direct green-to-green jump occurs;
- no reinforcement-learning code is used;
- the scenario files and original SUMO network files remain unchanged;
- the experiment result was appended to `results/experiments.csv` with
  `controller=static_fixed_time`.

## Limitations

- `fixed_green_seconds` is a single global value applied to every selected
  agent and every green phase within an agent; it is not tuned per
  intersection or per direction.
- The polling interval (`decision_interval_seconds`) means an actual switch
  can occur up to that many seconds after `fixed_green_seconds` is reached,
  not at the exact instant -- the same resolution already accepted
  elsewhere in this project's agent-interface design.
- This baseline is not a reproduction of any real-world Skopje signal
  timing plan.

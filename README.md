# Multi-Agent Reinforcement Learning for Adaptive Traffic Light Control in Skopje

This project will study adaptive traffic-signal control in Skopje with SUMO and multi-agent reinforcement learning, with the goal of comparing traffic efficiency under progressively more coordinated control strategies.

## Planned comparison

- Fixed-time control
- Independent reinforcement learning
- Coordinated multi-agent reinforcement learning

## Windows setup

Open the project in PyCharm and select the existing `.venv` as the project interpreter.
SUMO must be installed separately on Windows.
Set `SUMO_HOME` to the SUMO installation directory and add its `bin` directory to `PATH`.

Run these commands in PowerShell from the project root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Check the interpreter, SUMO tools, and Python dependencies:

```powershell
python scripts/check_setup.py
```

## Random-agent smoke test

Place the grid4x4 benchmark files at `sumo\benchmark\grid4x4\grid4x4.net.xml` and `sumo\benchmark\grid4x4\grid4x4_1.rou.xml`.
If the downloaded files use different names, edit the two filename constants near the top of `scripts\run_random_agents.py`.

Run a short headless simulation:

```powershell
python scripts/run_random_agents.py --seconds 300
```

Add `--gui` to view the simulation:

```powershell
python scripts/run_random_agents.py --gui --seconds 300
```

## Skopje OSM Scenario

The complete original SUMO OSM Web Wizard output is preserved under `sumo/skopje/source/wizard_initial/`.
The organized scenario is split across `sumo/skopje/network/`, `sumo/skopje/demand/`, `sumo/skopje/config/`, `sumo/skopje/polygons/`, and `sumo/skopje/additional/`.

The road geometry and map shapes come from OpenStreetMap.
The initial passenger demand was generated synthetically by the wizard and does not represent measured Skopje traffic volumes.

Inspect the imported network without starting SUMO:

```powershell
python scripts/inspect_skopje_network.py
```

Run a 10-minute visual smoke test with the original SUMO traffic-light programs:

```powershell
python scripts/run_skopje_simulation.py --gui --seconds 600
```

Omit `--gui` for a headless run.
This is only the first imported Skopje network.
Traffic-light cleanup, measured-demand calibration, baseline evaluation, and multi-agent reinforcement learning are still pending.

## Traffic-Light Network Audit

The traffic-light audit computes directed network paths between controllers without changing the imported SUMO network.
It records signal phases, controlled edges, lane and speed information, network-path neighbors, and conservative named-road corridor relationships.

Regenerate the audit CSV files and corridor recommendations:

```powershell
python scripts/audit_traffic_lights.py
```

Print the generated directed agent adjacency list:

```powershell
python scripts/show_agent_graph.py
```

Inspect the wider network statistics and traffic-light connected components:

```powershell
python scripts/inspect_skopje_network.py
```

The audit prepares connected subsets of 6 to 10 intersections for the first multi-agent reinforcement-learning experiment.
Candidate groups remain recommendations until their roads, turns, lanes, and signal programs are checked manually in netedit.

## Candidate Corridor Review

The candidate review tools compare the three audited 8-controller subsets without modifying the complete imported network, its demand, or its original traffic-light programs.
The generated Netedit selections highlight each candidate's controlled junctions, controlled passenger edges, and passenger-compatible paths between candidate neighbors.

Regenerate deterministic selection files and candidate review sheets:

```powershell
python scripts/generate_candidate_selections.py
```

Generate POI labels from the audited agent coordinates:

```powershell
python scripts/generate_agent_labels.py
```

Print the computed candidate comparison table:

```powershell
python scripts/summarize_candidates.py
```

Open Candidate 1 with its selection in Netedit:

```powershell
python scripts/open_candidate_in_netedit.py --candidate 1
```

After Netedit opens, press F9 and open the POI visualization settings.
Enable Show ID and constant text size, then increase the text size if labels such as A9 and A18 are too small.

Observe Candidate 1 under the original demand and signal programs in SUMO-GUI:

```powershell
python scripts/run_candidate_review.py --candidate 1 --seconds 600 --gui
```

Replace `1` with `2` or `3` to review the other candidates.

## Selected Experimental Corridor

Candidate 1 was manually reviewed and selected as the official experimental corridor.
Its selected agents are A9, A18, A19, A20, A24, A25, A26, and A29.
The full Skopje network remains active, and only these eight traffic lights are future learning agents.
All other traffic lights retain their original fixed SUMO programs.

Inspect the selected mappings and graph:

```powershell
python scripts/show_selected_corridor.py
```

Run the complete scenario headlessly without learning actions:

```powershell
python scripts/run_selected_corridor.py --seconds 600
```

Run the same fixed-program smoke test in SUMO-GUI:

```powershell
python scripts/run_selected_corridor.py --gui --seconds 600
```

See `sumo/skopje/documentation/selected_corridor.md` for the audited controller mappings, directed neighbor distances, review evidence, warnings, and limitations.

## Synthetic Traffic-Demand Scenarios

Low, medium, and high synthetic demand scenarios use the same complete Skopje network with different passenger-vehicle volumes.
Most generated trips traverse the selected corridor, while background trips retain wider-network traffic.
These scenarios are synthetic experimental loads and are not official or measured Skopje traffic data.
Seed 42 is the canonical committed example.

Generate all canonical scenarios:

```powershell
python scripts/generate_traffic_demand.py --all --seed 42
```

Validate the generated files and run each scenario headlessly:

```powershell
python scripts/validate_traffic_demand.py --all --seed 42
```

Review the medium scenario visually:

```powershell
python scripts/run_traffic_scenario.py --scenario medium --seed 42 --gui
```

The synthetic demand sets provide reproducible benchmarks for evaluating both baseline and learning controllers.
See `sumo/skopje/documentation/traffic_demand.md` for generation details, validation results, limitations, and reproducibility guarantees.

## Traffic-Agent Interface

The selected agents can observe queue lengths, vehicle counts, mean accumulated waiting times, and mean speeds for their controlled incoming lanes.
Their only actions are `KEEP` and `NEXT_GREEN`.
The safe action wrapper preserves the immediate yellow and all-red phases from each original SUMO program and never jumps directly between conflicting greens.
Pure local rewards and neighbor-aware and global corridor reward helpers are defined separately from experiment metrics.
Single-agent and multi-agent reinforcement learning runners build directly on top of this interface.

Inspect A19 in the canonical medium scenario:

```powershell
python scripts/inspect_traffic_agent.py --scenario medium --seed 42 --agent A19
```

Inspect all eight selected agents:

```powershell
python scripts/inspect_traffic_agent.py --scenario medium --seed 42 --all
```

Inspect the high-demand scenario in SUMO-GUI:

```powershell
python scripts/inspect_traffic_agent.py --scenario high --seed 42 --all --gui
```

See `sumo/skopje/documentation/traffic_agent_interface.md` for the feature ordering, phase structures, timing policy, safe-transition rules, reward formulas, and limitations.

## Multi-Agent SUMO Environment

`MultiAgentTrafficEnvironment` owns the SUMO and TraCI lifecycle and coordinates any ordered subset of the eight selected `TrafficSignal` wrappers.
Pass `None` to `step()` to observe the original imported controllers, or pass a complete mapping of agent IDs to `TrafficAction` values for safe controlled operation.
Configuring only `A19` uses the same class as a single-agent environment.

```python
from src.environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentTrafficEnvironment,
    TrafficAction,
)

config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
with MultiAgentTrafficEnvironment(config) as environment:
    observations = environment.reset()
    result = environment.step(
        {"A19": TrafficAction.KEEP, "A26": TrafficAction.NEXT_GREEN}
    )
```

Run a short headless inspection without a learning algorithm:

```powershell
python scripts/inspect_multi_agent_environment.py --scenario low --seed 42 --seconds 120 --agents A19,A26 --policy cycle
```

## Experiment Metrics

Every controller (fixed-time, independent RL, coordinated MARL) reports results
through the same shared package in `src/evaluation/`, so runs stay directly
comparable.

`EpisodeMetrics` is a typed, validated result record (non-negative counts and durations, arrived ≤ departed, etc).
`MetricsCollector` isolates all TraCI calls needed to build one during a run; it does not start or close SUMO itself - the calling script owns that lifecycle.
Results are appended to `results/experiments.csv` with a stable column order and a header written once.

Average waiting time is the mean, over vehicles that departed during the run, of each vehicle's accumulated waiting time, read once per vehicle rather than summed across steps.
Average speed excludes steps with zero active vehicles rather than counting them as speed 0.
`total_reward` is left unset (not zero) for non-learning controllers such as fixed-time.

Summaries and plots group by controller, scenario, **and episode length**.
Episode length changes what a metric means -- a 600-second evaluation releases a sixth of the traffic a 3600-second one does -- so runs of different lengths are never averaged into one number, and the plot legend names the demand period as soon as a results file holds more than one.
Compare controllers only within one episode length; `--episode-seconds 3600` matches the baselines.

Print a summary grouped by controller, scenario, and episode length:

```powershell
python scripts/summarize_experiments.py
```

Render comparison plots across scenarios and controllers:

```powershell
python scripts/visualize_results.py
```

This saves high-resolution comparison charts in `results/plots/` for average waiting time, average speed versus traffic density, average queue length, and throughput.
Series labels automatically distinguish between different demand periods (such as 600-second and 3600-second runs) to ensure fair comparisons.

Run the metrics tests, which do not require SUMO or SUMO-GUI:

```powershell
python -m pytest tests/test_metrics.py
```

## Static Fixed-Time Baseline

The static fixed-time controller (`static_fixed_time`) is an experimental baseline created for this project.
It reuses the safe KEEP/NEXT_GREEN traffic-agent wrapper so it preserves each selected traffic light's original phase order, phase-state strings, and yellow/all-red transition durations, and only assigns a deterministic duration to green phases.
It is not claimed to reproduce the official traffic-light timings used by the City of Skopje; we do not have verified official Skopje signal timings, detector logic, offsets, or time-of-day plans.
The currently imported SUMO traffic-light programs for the full network are actuated programs and are a separate, later comparison (`imported_actuated`).

Run one experiment:

```powershell
python scripts/run_static_fixed_time_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600
```

Run all three canonical scenarios in one command:

```powershell
python scripts/run_static_fixed_time_suite.py --seeds 42
```

Summarize saved results:

```powershell
python scripts/summarize_experiments.py
```

Run the baseline's unit tests, which do not require SUMO or SUMO-GUI:

```powershell
python -m pytest tests/test_static_fixed_time_baseline.py
```

See `sumo/skopje/documentation/static_fixed_time_baseline.md` for the timing-policy design, configuration, experiment-timing windows, and validation checklist.

## Imported SUMO Actuated Baseline

The imported actuated baseline (`imported_actuated`) evaluates the traffic-light programs already contained in the imported SUMO network, without issuing any manual phase-control actions.
It reuses `MultiAgentTrafficEnvironment` and always advances with `environment.step(None)`, so the imported SUMO actuated programs stay fully in control of all eight selected traffic lights.
It is not claimed to reproduce the official operational traffic-control system of the City of Skopje; we have not verified the imported programs against official Skopje signal plans, detector logic, offsets, or time-of-day schedules.
This baseline establishes a responsive, non-learning benchmark that future Q-learning and coordinated MARL controllers must beat.

Run one experiment:

```powershell
python scripts/run_imported_actuated_experiment.py --scenario medium --seed 42 --demand-seconds 3600 --cooldown-seconds 600
```

Run all three canonical scenarios in one command:

```powershell
python scripts/run_imported_actuated_suite.py --seed 42
```

Summarize saved results:

```powershell
python scripts/summarize_experiments.py
```

Run the baseline's unit tests, which do not require SUMO or SUMO-GUI:

```powershell
python -m pytest tests/test_imported_actuated_baseline.py
```

See `sumo/skopje/documentation/imported_actuated_baseline.md` for the zero-action design, experiment-timing windows, and validation checklist.

## Single-Agent Independent Q-Learning

The single-agent trainer (`independent_rl`) trains one corridor agent (default `A19`) with tabular Q-learning while all other traffic lights follow their imported SUMO programs.
Each discrete state encodes controlled incoming queue buckets, vehicle counts, waiting times, and active phase.
Only evaluation runs append their final performance metrics to `results/experiments.csv`.

Train a single agent:

```powershell
python scripts/run_q_learning.py train --agent A19 --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/a19_medium.json
```

Continue an interrupted run with `--resume`:

```powershell
python scripts/run_q_learning.py train --agent A19 --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/a19_medium.json --resume
```

Evaluate a trained model greedily on the training scenario and seed:

```powershell
python scripts/run_q_learning.py evaluate --agent A19 --scenario medium --seed 42 --checkpoint checkpoints/a19_medium.json
```

Evaluate on an unseen random traffic seed to test policy generalization across traffic distributions:

```powershell
python scripts/run_q_learning.py evaluate --agent A19 --scenario medium --seed 43 --checkpoint checkpoints/a19_medium.json --allow-cross-seed
```

Checkpoints strictly enforce that scenario, seed, and agent IDs match to prevent accidental parameter drift during training and resume.
Passing `--allow-cross-seed` during evaluation permits testing policy robustness across different random traffic realizations.

Run the unit tests, which do not require SUMO:

```powershell
python -m pytest tests/test_q_learning_agent.py tests/test_q_learning_training.py
```

## Multi-Agent Independent Q-Learning

The multi-agent independent RL controller (`multi_agent_independent_rl`) runs all eight selected corridor agents (`A9, A18, A19, A20, A24, A25, A26, A29`) as learners in the *same* SUMO episode.
Each agent keeps its own tabular Q-table and learns only from its own local reward, so there is no shared value function, no communication, and no joint action space -- this is the "independent reinforcement learning" row of the planned comparison, and the benchmark that coordinated MARL has to beat.
Every agent gets its own RNG stream, so the eight learners explore independently rather than in lockstep.

Contrast this with `scripts/run_q_learning.py`, which trains one corridor agent at a time while the other seven traffic lights stay on their imported SUMO programs.

Train all eight agents:

```powershell
python scripts/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/multi_agent_medium.json
```

Training writes an inspectable JSON checkpoint holding all eight Q-tables plus each agent's exploration state.
Continue an interrupted run with `--resume`:

```powershell
python scripts/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/multi_agent_medium.json --resume
```

Evaluate a trained checkpoint with exploration switched off.
Only evaluation episodes are appended to `results/experiments.csv`, under the controller label `multi_agent_independent_rl`, with `total_reward` recorded as the combined reward across all eight agents:

```powershell
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --checkpoint checkpoints/multi_agent_medium.json
```

Evaluate on an unseen random traffic seed with `--allow-cross-seed` to test multi-agent generalization:

```powershell
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 43 --checkpoint checkpoints/multi_agent_medium.json --allow-cross-seed
```

Use `--agents A19 A20` to control a subset of the corridor.
A checkpoint records the agent set it was trained on and refuses to load into a run configured with a different one, and likewise refuses a mismatched scenario or seed unless `--allow-cross-seed` is explicitly passed during evaluation.

### Spatial observation sharing between neighbor nodes

By default every agent sees only its own junction.
`--spatial-observations` adds the corridor's one communication channel: each agent additionally observes a single congestion flag per neighbor -- `1` once that neighbor holds four or more queued vehicles, `0` below that -- so it can react to a platoon before the platoon reaches its own stop line.
Rewards stay purely local; this changes what an agent *sees*, not what it is paid for.

```powershell
python scripts/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 30 --checkpoint checkpoints/multi_agent_medium_spatial.json --spatial-observations
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --checkpoint checkpoints/multi_agent_medium_spatial.json --spatial-observations
```

Evaluate the spatial checkpoint on an unseen traffic seed:

```powershell
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 43 --checkpoint checkpoints/multi_agent_medium_spatial.json --spatial-observations --allow-cross-seed
```

Neighbors come from the audited `SELECTED_CORRIDOR.neighbor_map`, ordered by network distance, and `--neighbor-limit` (default 2) keeps only the closest ones.
That bound is the whole design constraint: each observed neighbor is one extra bit of a tabular state, so it doubles the reachable Q-table, and A26 alone has six audited neighbors.
A subset run only observes agents it actually controls, so `--agents A19` falls back to purely local states.

Spatial runs are written to `results/experiments.csv` under the controller label `multi_agent_spatial_rl`, next to the local `multi_agent_independent_rl` rows, which is what makes the two directly comparable.
Their checkpoints are not interchangeable -- a spatial Q-table is keyed by states a local agent cannot even represent -- and a checkpoint also refuses to load into a run using a different `--neighbor-limit`.

See `sumo/skopje/documentation/spatial_observation_sharing.md` for the state design, the per-agent neighborhoods, and the measured 30-episode comparison against purely local agents.
That comparison is not yet a win for spatial observations: the larger state space is under-trained at 30 episodes, and purely local rewards give an agent no reason to spend a neighbor flag on the corridor rather than on itself.

### Coordinated MARL via neighbor-aware and global reward mixing

Independent multi-agent Q-learning rewards each agent strictly based on its own local incoming lanes.
This can encourage selfish behavior where an agent clears its own queue by dumping a bottleneck onto adjacent intersections.
The `--reward-mode` setting coordinates the corridor through reward shaping:

- `local` (default): Pure local junction reward. Recorded under controller label `multi_agent_independent_rl`.
- `neighbor_aware`: Blends 75% of an agent's local reward with 25% of the average reward of its topological neighbors. Recorded under controller label `marl_neighbor_reward`.
- `global`: Every agent receives the corridor-wide average reward across all controlled intersections. Recorded under controller label `marl_global_reward`.

Train all eight agents with neighbor-aware reward coordination:

```powershell
python scripts/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 30 --reward-mode neighbor_aware --checkpoint checkpoints/marl_neighbor.json
```

Evaluate the neighbor-aware checkpoint:

```powershell
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --reward-mode neighbor_aware --checkpoint checkpoints/marl_neighbor.json
```

Evaluate on an unseen seed with cross-seed evaluation:

```powershell
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 43 --reward-mode neighbor_aware --checkpoint checkpoints/marl_neighbor.json --allow-cross-seed
```

Train and evaluate with global corridor-wide reward sharing:

```powershell
python scripts/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 30 --reward-mode global --checkpoint checkpoints/marl_global.json
python scripts/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --reward-mode global --checkpoint checkpoints/marl_global.json
```

Summarize saved results:

```powershell
python scripts/summarize_experiments.py
```

Run the multi-agent runner's unit tests, which do not require SUMO or SUMO-GUI:

```powershell
python -m pytest tests/test_multi_agent_q_learning.py
```

## Gymnasium and PettingZoo Wrappers for Deep RL

Tabular Q-learning discretizes observations into buckets, which stops scaling once the state space grows. `src/environment/gym_wrapper.py` exposes the same SUMO environment through the two standard reinforcement-learning APIs, so deep RL libraries (Stable-Baselines3, Ray/RLlib, MAPPO implementations) can train on it unchanged. The wrapper is an adapter only: no learning, no reward shaping, and no state beyond what `MultiAgentTrafficEnvironment` already produces.

* `CorridorParallelEnv` is the PettingZoo **parallel** API. Every corridor agent observes, acts, and is rewarded in the same decision interval, which is how the SUMO environment already works.
* `SingleAgentTrafficEnv` is the Gymnasium API for exactly one corridor agent while the other traffic lights keep their imported SUMO programs -- the same setup as `scripts/run_q_learning.py`, so a deep RL run stays comparable with those results.

Observations are `TrafficObservation.normalized_features()` as a `float32` `Box` bounded to `[0.0, 1.0]`: per controlled lane the queue length, vehicle count, mean waiting time, and mean speed, then the normalized phase elapsed time, then a one-hot vector over the program's phases. Actions are `Discrete(2)`: `0` is `KEEP`, `1` is `NEXT_GREEN`, applied through the same minimum-green, maximum-green, and yellow-transition safety rules as every other controller.

An observation's length therefore depends on the junction, and libraries need the spaces before SUMO is running. The spaces are sized from the audited `controlled_lane_count` and `phase_count` in `sumo/skopje/documentation/traffic_light_audit.csv`, then verified against the live program on every `reset()`, so a stale audit becomes a readable error instead of a shape mismatch inside a training loop:

| Agent | Lanes | Phases | Observation features |
| --- | --- | --- | --- |
| A9 | 7 | 4 | 33 |
| A18 | 7 | 4 | 33 |
| A19 | 14 | 9 | 66 |
| A20 | 11 | 8 | 53 |
| A24 | 13 | 8 | 61 |
| A25 | 10 | 4 | 45 |
| A26 | 9 | 9 | 46 |
| A29 | 4 | 4 | 21 |

```python
from src.environment import CorridorParallelEnv, SingleAgentTrafficEnv
from src.environment.multi_agent_environment import MultiAgentEnvironmentConfig

config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"), demand_seconds=600.0)
with CorridorParallelEnv(config) as environment:
    observations, infos = environment.reset()
    actions = {agent: environment.action_space(agent).sample() for agent in environment.agents}
    observations, rewards, terminations, truncations, infos = environment.step(actions)
```

`reset(seed=...)` seeds SUMO's own randomness -- driver imperfection, lane choices -- for that episode, through the environment's optional `sumo_seed`. The traffic load itself stays the generated scenario the configuration names, because `seed` elsewhere in the project selects a *generated demand file* and only generated scenarios exist as episodes. Splitting the two means every seed a library invents is a real episode, and no training loop can silently swap the demand a run is being measured on. Use `MultiAgentEnvironmentConfig(seed=...)` to choose the demand scenario, as every other runner does.

Termination is a property of the SUMO episode rather than of one junction, so all agents finish together: `terminated` when no vehicle is left to simulate, `truncated` when the episode duration -- or the optional `max_cycles` -- runs out. `info` reports each agent's action status (`applied`, `rejected_minimum_green`, `forced_maximum_green`, ...), so a training loop can see when the safety layer overruled the policy.

Verify both API contracts against a live SUMO simulation:

```powershell
python scripts/check_gym_wrapper.py --scenario low --episode-seconds 120 --cycles 4
```

That runs PettingZoo's `parallel_api_test` over all eight agents and Gymnasium's `check_env` on A19. Both suites also run in `tests/test_gym_wrapper.py` against a fake environment, where they need no SUMO installation:

```powershell
python -m pytest tests/test_gym_wrapper.py
```

Run a short Stable-Baselines3 training loop through the wrapper (optional dependency; `pip install stable-baselines3`):

```powershell
python scripts/run_deep_rl_demo.py --algorithm ppo --scenario medium --timesteps 128 --episode-seconds 600
```

Stable-Baselines3 builds the policy network from the wrapper's spaces and runs its own loop end to end -- 128 PPO timesteps over 600-second episodes produced ten gradient updates and an `ep_rew_mean` of about -1.2e3 on the medium scenario. That is a compatibility demonstration, not a benchmark: a few hundred timesteps train nothing worth comparing, so the demo writes no row to `results/experiments.csv` and the comparison table stays reserved for controllers that were trained to convergence. Training a competitive deep policy is separate work.

## Current status

The initial package structure, shared configuration, setup checker, random-agent integration smoke test, first imported Skopje scenario, shared experiment-metrics package, static fixed-time baseline, and imported actuated baseline are in place.
Single-agent and multi-agent tabular Q-learning runners support training, resuming, strict checkpoint validation, and cross-seed evaluation.
Coordinated MARL is supported through spatial observation sharing (neighbor congestion flags) and reward coordination (neighbor-aware and global reward mixing).
Results can be summarized across episode durations and visualized as publication-quality comparison charts.
Gymnasium and PettingZoo parallel environment wrappers are validated and ready for deep reinforcement learning libraries, with a single-agent Stable-Baselines3 demo included.
Full multi-seed 3600-second benchmark runs for the multi-agent models, multi-agent deep RL training across all eight agents, real-world calibrated demand, and netedit junction geometry cleanup are future work.
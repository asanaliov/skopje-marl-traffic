# Adaptive Traffic Lights in Skopje with Multi-Agent RL

Compares traffic-light controllers on a real Skopje road network in SUMO:
fixed-time baselines, independent Q-learning, and coordinated multi-agent RL
(shared PPO, PPO with self-attention, and DQN).

**Final results are on the `real_signals` network:** see [Results](#results-real_signals).

Eight traffic lights on one corridor are learning agents:
`A9, A18, A19, A20, A24, A25, A26` plus `A29` on the original network, or `A21` on
the `real_signals` network (see [Networks](#networks)). Every other light in the network
keeps its original SUMO program.

> The road network comes from OpenStreetMap. Traffic demand is synthetic, not
> measured Skopje data, and the signal timings are not the city's official ones.

## Controllers

| Label in results | What it is |
| --- | --- |
| `static_fixed_time` | Fixed green durations, original phase order |
| `webster_fixed_time` | Fixed-time plans optimised with Webster's method (`real_signals` only) |
| `imported_actuated` | The actuated programs from the imported SUMO network |
| `independent_rl` | Q-learning on one agent, others on SUMO programs |
| `multi_agent_independent_rl` | All 8 agents learn, each with its own local reward |
| `multi_agent_spatial_rl` | Same, plus each agent sees its neighbors' congestion |
| `marl_neighbor_reward` | Reward = 70% own + 30% neighbors' average |
| `marl_global_reward` | Every agent gets the corridor-wide average reward |
| `marl_deep_ppo` | One shared PPO network for all 8 agents, local reward |
| `marl_attention_ppo` | Same, plus self-attention across junctions |
| `marl_deep_dqn` | Shared-parameter Double DQN, same network size, reward and budget as `marl_deep_ppo` |

## Results (real_signals)

Final network (`SKOPJE_NETWORK=real_signals`, after #78). Every learned controller trains for 300 episodes on demand
seed 42 and is evaluated greedily on seeds 42, 43 and 44 (two of them never seen in training). Values are means over
the three seeds; where two numbers are given, the controller was trained twice with different torch seeds.
Low and peak are being trained on a second machine.

| Controller | Medium wait (s) | High wait (s) | High: vehicles left |
| --- | ---: | ---: | ---: |
| `static_fixed_time` | 14.49 | 19.04 | 4–20 |
| `webster_fixed_time` | 8.78 | 14.01 | 17–43 |
| `imported_actuated` | **7.44** | **12.32** | 0–2 |
| `marl_deep_ppo` | 8.10 / 7.95 | 15.95 | 165–174 |
| `marl_attention_ppo` | 8.66 / 8.74 | 16.53 | 98–103 |
| `marl_deep_dqn`, SB3 default settings | 8.23 / 8.52 | 16.34 | 153–159 |
| `marl_deep_dqn`, tuned (current defaults) | 7.78 / 7.80 | 13.46 | 1–7 |

**Metric.** "Wait" is the mean over all vehicles of SUMO's accumulated waiting time, which SUMO counts over a
100 s window (`--waiting-time-memory` default). Stuck vehicles are included but contribute at most 100 s each, so
the mean understates a jam. That is why vehicles still in the network at the end (after 3600 s of demand plus
600 s without new vehicles) are reported next to it.

- RL clearly beats fixed-time control: tuned DQN is 46% better than static and 11% better than Webster on medium.
- Actuated control is still best. Tuned DQN is 0.35 s (4.7%) behind on medium and 9% behind on high.
- Self-attention does not help: it is about 0.7 s worse than the same PPO without attention, in both training runs.
- On high, both PPO controllers jam at A26 (Kuzman): one queue on Mitropolit Teodosij Gologanov grows past the 150 m
  the agent observes, so neither its observation nor its local reward sees it grow. Tuned DQN, with the same
  150 m observation, serves that approach like actuated does and leaves 1–7 vehicles.
- 500 episodes instead of 300 did not help attention PPO on high (16.75 s); its training reward peaks around episode 60.

Sources: `results/real_signals/experiments.csv` (baselines, PPO, attention, default DQN),
`results/real_signals/torchseed1.csv` (second training runs), `results/real_signals/test_ep500.csv`,
`results/real_signals/tuning_dqn/` (tuned DQN and its tuning runs).

### How the settings were chosen

The same protocol for every controller: change **one setting at a time** from the current best, train on seed 42,
evaluate on seeds 42–44, tune on medium first and confirm the winner on high. Promising changes get a second
training run with another torch seed, because two runs of the same settings can differ by up to 0.3 s.

**PPO** (tuned on `marl_attention_ppo`, 150 episodes per run; `marl_deep_ppo` shares the same defaults). Runs a–p
were on the network before #78, F on the fixed one. Raw rows: `results/real_signals/tuning/`.

| Run | Change from the previous best | Medium wait (s) | Kept? |
| --- | --- | ---: | --- |
| a | linear learning-rate decay | 8.64 | yes |
| b | + 10 instead of 4 update epochs | 8.48 | yes (reference) |
| c | decide every 2 s instead of 5 s | 9.05 | no |
| e | neighbor-aware reward | 8.99 | no |
| h | count vehicles up to 150 m before the stop line | 9.04 | not on its own |
| j | 150 m + minimum green 7 s instead of 10 s | 8.11 | yes |
| p | pressure instead of local reward | 8.06 | no (same as j) |
| F | j settings on the fixed network | 8.04 | final defaults |

**DQN** (300 episodes per run; started from the Stable-Baselines3 values). One episode gives 6,720 decisions
(840 per junction); they go into a replay buffer of the last 200,000, and after each episode the network takes a
number of gradient steps on random batches of 256. Raw rows: `results/real_signals/tuning_dqn/`.

| Change | Concretely | Medium wait (s) |
| --- | --- | ---: |
| none (SB3 default) | lr 1e-4, 840 gradient steps per episode | 8.23 / 8.52 |
| bigger learning rate | lr 3e-4 | 8.12 |
| more gradient steps | 1680 per episode | 8.12 |
| smaller replay buffer | 50,000 instead of 200,000 | 8.31 |
| slower target network | synced every 5000 instead of 1000 steps | 8.39 |
| less exploration | random actions only in the first 10% of episodes | 8.56 |
| **lr 3e-4 + 1680 steps** | both together (current defaults) | **7.78 / 7.80** |
| lr 1e-3 + 1680 steps | even bigger learning rate | 7.50 (one run) |
| lr 3e-4 + 3360 steps | 4x the default steps | 7.49 (one run) |
| bigger network | 2x256 instead of 2x128 | 7.84 |

No single change beat the run-to-run noise; the combination did, in both training runs, and the same settings
applied unchanged to high removed the A26 jam. Learning more from each sample is what helped; buffer size, target
speed and network size did not.

**Caveat:** tuning and evaluation used the same seeds (42–44). A final evaluation on fresh seeds 45–47 is planned.

## Setup

### Linux

Python 3.11 is required (`check_setup.py` checks it). The `eclipse-sumo` pip package provides
the SUMO binaries, so no system install is needed:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # optional: CPU-only torch
pip install -r requirements.txt -r requirements-dev.txt eclipse-sumo==1.27.1
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"
python scripts/setup/check_setup.py
```

Add the `SUMO_HOME` export to `.venv/bin/activate` so it is set every time.
The commands below use PowerShell syntax; on Linux set variables with `export NAME=value`.

### Windows

1. Install [SUMO](https://sumo.dlr.de/docs/Downloads.php), set `SUMO_HOME`, and add its `bin` folder to `PATH`.
2. Install dependencies and check the setup:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python scripts/setup/check_setup.py
```

## Quick start

```powershell
# Generate low / medium / high demand scenarios
python scripts/demand/generate_traffic_demand.py --all --seed 42

# Watch the corridor with its original signal programs
python scripts/experiments/run_traffic_scenario.py --scenario medium --seed 42 --gui
```

## Running experiments

Every run that evaluates a controller appends one row to `results/experiments.csv`.

**Baselines**

```powershell
python scripts/experiments/run_static_fixed_time_suite.py --seeds 42
python scripts/experiments/run_imported_actuated_suite.py --seed 42
```

**Single-agent Q-learning**

```powershell
python scripts/experiments/run_q_learning.py train    --agent-id A19 --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/a19_medium.json
python scripts/experiments/run_q_learning.py evaluate --agent-id A19 --scenario medium --seed 42 --checkpoint checkpoints/a19_medium.json
```

**Multi-agent Q-learning**

```powershell
python scripts/experiments/run_multi_agent_q_learning.py train    --scenario medium --seed 42 --episodes 50 --checkpoint checkpoints/marl_medium.json
python scripts/experiments/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --checkpoint checkpoints/marl_medium.json
```

### Watch a trained controller

Replay a saved controller in the SUMO traffic GUI without starting another training run:

```powershell
python scripts/sumo_visualization/watch_trained_controller.py --controller single-agent --scenario medium --agent-id A19
python scripts/sumo_visualization/watch_trained_controller.py --controller multi-agent --scenario medium --reward-mode local
python scripts/sumo_visualization/watch_trained_controller.py --controller deep-marl --scenario medium
```

The script loads the matching checkpoint from `checkpoints/` by default and does not append a row to `results/experiments.csv`.

Pass `--checkpoint` to replay another saved model, or `--help` to change the scenario, seed, agents, or playback duration.

Useful flags for both runners:

| Flag | Effect |
| --- | --- |
| `--resume` | Continue an interrupted training run |
| `--allow-cross-seed` | Evaluate on a different traffic seed than training |
| `--reward-mode local\|neighbor_aware\|global` | Reward coordination (multi-agent only) |
| `--spatial-observations` | Agents see neighbor congestion flags (multi-agent only) |
| `--agents A19 A20` | Train only a subset of the corridor (multi-agent only) |

`neighbor_aware` averages over all of an agent's audited neighbors that are in the run
(up to six for A26). `--neighbor-limit` only applies to `--spatial-observations`.

Use the same `--reward-mode` / `--spatial-observations` for train and evaluate.
Checkpoints refuse to load if the scenario, seed, agents, or settings don't match.

## Looking at results

```powershell
python scripts/analysis/summarize_experiments.py                       # table by controller, scenario, episode length
python scripts/analysis/visualize_results.py                           # plots in results/plots/
python scripts/analysis/generate_waiting_time_chart.py                  # refresh the README SVG from experiments.csv
python scripts/analysis/experiment_matrix.py results/experiments.csv   # which runs are still missing
python scripts/analysis/experiment_matrix.py results/real_signals      # also takes folders of per-run csvs
python scripts/analysis/training_curve.py logs/<run>.log --csv out.csv # reward curve from a training log
python scripts/analysis/merge_results.py other_machine.csv             # merge results from another machine
```

Only compare runs with the same episode length. Baselines use 3600 seconds.

### Original network results (for the record)

These are from the **original** network, before `real_signals`; see [Results](#results-real_signals) for the final ones.

Mean average waiting time in seconds across full 3600-second-demand evaluations for every controller label in the results CSV.
Lower is better.
The results use synthetic demand and a limited set of seeds; the comparison is descriptive, not evidence of statistical significance.

![Line chart comparing mean average waiting time across traffic scenarios](results/waiting-time-comparison.svg)

| Controller | Low | Medium | High |
| --- | ---: | ---: | ---: |
| `static_fixed_time` | 7.65 | 10.33 | 15.17 |
| `imported_actuated` | 4.31 | 6.01 | 10.44 |
| `independent_rl` | 4.46 | 6.89 | 11.44 |
| `multi_agent_independent_rl` | 5.53 | 7.68 | 13.60 |
| `multi_agent_spatial_rl` | 5.84 | 7.24 | 14.01 |
| `marl_neighbor_reward` | 5.27 | 8.00 | 17.25 |
| `marl_global_reward` | 5.91 | 7.57 | 14.31 |
| `marl_deep_ppo` | 5.28 | 7.42 | 12.68 |

Values are calculated from `results/experiments.csv` using only rows with 3600 seconds of demand, grouped by controller and scenario. Short trials are excluded.
Run `python scripts/analysis/generate_waiting_time_chart.py` to refresh the chart after adding experiment rows.
If a controller/scenario has repeated full-length rows for a seed, the chart averages those rows rather than silently choosing one result.
Use `python scripts/analysis/summarize_experiments.py` to inspect run counts and standard deviations.
The imported actuated baseline has the lowest mean wait in all three scenarios in the current results table.
The learned controllers do not consistently improve on that baseline, and their relative performance changes with demand level.
These results do not establish a novel or generally superior controller.

## Deep RL wrappers

`src/environment/gym_wrapper.py` exposes the environment as:

- `CorridorParallelEnv`: PettingZoo parallel API, all agents
- `SingleAgentTrafficEnv`: Gymnasium API, one agent

```python
from src.environment import CorridorParallelEnv
from src.environment.multi_agent_environment import MultiAgentEnvironmentConfig

config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"), demand_seconds=600.0)
with CorridorParallelEnv(config) as env:
    observations, infos = env.reset()
    actions = {agent: env.action_space(agent).sample() for agent in env.agents}
    observations, rewards, terminations, truncations, infos = env.step(actions)
```

Actions are `0 = KEEP`, `1 = NEXT_GREEN`. A safety layer enforces minimum/maximum
green and yellow transitions. A short PPO demo (`stable-baselines3` and `torch` are in `requirements-dev.txt`):

```powershell
python scripts/experiments/run_deep_rl_demo.py --algorithm ppo --scenario medium --timesteps 128 --episode-seconds 600
```

## Deep MARL (shared-parameter PPO)

`src/training/deep_marl.py` trains one PyTorch PPO network shared by all eight agents
(independent PPO: actor and critic see only the agent's own observation). Observations are
zero-padded to the widest junction and tagged with a one-hot agent ID.

- **Why shared:** SUMO is the bottleneck, and sharing gives the network 8x the samples per episode.
- **Why `local` reward:** no coordinated tabular reward won consistently, so this is the direct
  deep counterpart of `multi_agent_independent_rl`. Same budget: 300 episodes on seed 42.
- Rewards are scaled by a running return std and clipped to ±10 (like SB3's `VecNormalize`).

```powershell
python scripts/experiments/run_deep_marl.py train    --scenario medium --seed 42 *>&1 | Tee-Object logs/deep_marl_local_medium_seed42.log
python scripts/experiments/run_deep_marl.py evaluate --scenario medium --seed 42
python scripts/experiments/run_deep_marl.py evaluate --scenario medium --seed 43 --allow-cross-seed --checkpoint checkpoints/deep_marl_local_medium_seed42.pt
```

Other reward modes are recorded as `marl_deep_ppo_neighbor` / `marl_deep_ppo_global`.
Checkpoints are saved as `checkpoints/deep_marl_<reward>_<scenario>_seed<seed>.pt`.

**Results on the original network** (mean over seeds 42/43/44; for `real_signals` see [Results](#results-real_signals)):

| Scenario | Controller | Avg wait (s) | Avg queue | Vehicles left | Teleports |
|---|---|---|---|---|---|
| low | `marl_deep_ppo` | 5.28 | 1.97 | 0.67 | 0.00 |
| low | `multi_agent_independent_rl` | 5.53 | 2.31 | 0.33 | 0.00 |
| medium | `marl_deep_ppo` | 7.42 | 5.77 | 1.00 | 0.00 |
| medium | `multi_agent_independent_rl` | 7.68 | 6.98 | 1.67 | 0.00 |
| high | `marl_deep_ppo` | 12.68 | 13.02 | 15.00 | 0.33 |
| high | `multi_agent_independent_rl` | 13.60 | 21.11 | 36.33 | 7.33 |

Across the three recorded seeds, deep PPO has lower mean waiting time than the tabular multi-agent controller in all three scenarios. In low and medium demand the gap is comparable to the seed-to-seed spread.
The imported actuated and single-agent RL baselines have lower mean waiting time than deep PPO in every scenario.

Caveats: high seed 43 leaves 41 vehicles in the network (vs 3 and 1 on seeds 42/44).
Medium training reward peaked around episodes 200–225 and dropped about 8% by the end; the final
checkpoint is the one evaluated, as for every tabular run.

## Self-attention PPO

`src/training/deep_marl_attention.py` is a separate controller that adds one self-attention layer to the shared PPO network, so
each junction can use the state of the other seven. Everything else matches `marl_deep_ppo`:
observations, local reward, PPO settings, gradient steps per episode and the 300-episode budget.

Attention needs all 8 observations at execution time and also makes the critic centralized, so the
comparison measures shared information as a whole, and the controller is not decentralized.

```powershell
python scripts/experiments/run_attention_ppo.py train    --scenario medium --seed 42 *>&1 | Tee-Object logs/deep_marl_attention_local_medium_seed42.log
python scripts/experiments/run_attention_ppo.py evaluate --scenario medium --seed 42
python scripts/experiments/run_attention_ppo.py evaluate --scenario medium --seed 43 --allow-cross-seed --checkpoint checkpoints/deep_marl_attention_local_medium_seed42.pt
```

Checkpoints are saved as `checkpoints/deep_marl_attention_<reward>_<scenario>_seed<seed>.pt`.

### Training settings

Both PPO trainers default to the settings that won the November 2026 tuning on real_signals (medium and
high, seeds 42-44, 150-episode runs):

| Flag | Default | Why |
| --- | --- | --- |
| `--approach-range` | 150 m | most stop-line lanes are ~18 m (three cars), so longer queues were invisible; each lane now counts vehicles up to 150 m upstream, stopping at the next agent |
| `--min-green` | 7 s | was 10 s; the actuated programs use the same 7 s, so both controllers work within identical limits |
| `--lr-decay` / `--no-lr-decay` | on | linear decay to zero over `--episodes`; keep `--episodes` unchanged when resuming |
| `--update-epochs` | 10 | was 4; learns faster per simulated episode |

Tried and kept off by default: `--reward-mode pressure` (exits counted 150 m downstream; tied with the local
reward on high, behind on medium), `--switch-penalty`, `--waiting-weight` above 0.1, `--entropy-coefficient`
above 0.01, `--decision-interval 2` and `--reward-mode neighbor_aware`. Checkpoints written before these flags
existed load with their old values (no approach range, 10 s minimum green, no decay), so pass those flags to
resume or evaluate them.

Limit PyTorch to one thread before training. On medium demand, 2 episodes with updates took 55 s instead of 162 s at the default 14 threads, with identical logged rewards and losses. Plain PPO and parallel runs have not been timed with this setting.

```powershell
$env:OMP_NUM_THREADS=1; $env:MKL_NUM_THREADS=1
```

### Faster runs with libsumo

`SKOPJE_LIBSUMO=1` runs SUMO inside the Python process through libsumo instead of over a TraCI socket. Results are identical: the `high` deep MARL evaluation row and two attention-PPO training episodes on medium matched TraCI value for value. It took 21 s instead of 55 s for those two episodes and 26 s instead of 63 s for the evaluation. libsumo has no GUI, so `--gui` refuses it.

```powershell
$env:SKOPJE_LIBSUMO=1; $env:OMP_NUM_THREADS=1; $env:MKL_NUM_THREADS=1
```

It applies to everything built on `MultiAgentTrafficEnvironment` (deep MARL, attention PPO, the imported actuated baseline); the static fixed-time runner keeps TraCI. The SUMO Python packages are pinned to the installed SUMO version (1.27.1) in `requirements.txt`. On Windows libsumo bundles a newer `sqlite3.dll` than Python, so `src/__init__.py` imports it first when the switch is on.

## Deep MARL (shared DQN)

`src/training/deep_marl_dqn.py` is the value-based counterpart of `marl_deep_ppo`: the same observations,
local reward, network size (2x128) and 300-episode budget, but with one Q-value head, epsilon-greedy
exploration (1.0 to 0.05 over the first 30% of episodes), a shared replay buffer of every agent's steps,
and Double-DQN updates against a target network.

Defaults are the tuned settings: learning rate 3e-4 and 1680 gradient steps per episode. On medium
(seeds 42-44) they beat the Stable-Baselines3 defaults (1e-4, 840 steps) in two training runs each.

```powershell
python scripts/experiments/run_dqn.py train    --scenario medium --seed 42
python scripts/experiments/run_dqn.py evaluate --scenario medium --seed 43 --allow-cross-seed --checkpoint checkpoints/deep_marl_dqn_local_medium_seed42.pt
```

The replay buffer is not stored in checkpoints, so `--resume` continues with an empty buffer.

## Tests

```powershell
python -m pytest
```

## Project layout

```
src/
  agents/        Q-learning agent and state encoder
  baselines/     fixed-time and actuated controllers
  demand/        synthetic traffic generation
  environment/   SUMO environment, signals, rewards, Gym/PettingZoo wrappers
  evaluation/    metrics collection and results CSV
  training/      tabular and deep MARL training loops
scripts/
  analysis/      result summaries and charts
  demand/        synthetic demand generation and validation
  experiments/   SUMO runs and controller training/evaluation
  environment_inspection/ Gym wrapper and traffic-agent inspection
  network_inspection/     traffic-light audits and corridor reviews
  setup/                  local Python and SUMO checks
  sumo_visualization/     replay trained controllers in SUMO GUI
sumo/skopje/     network, demand, configs, and documentation
results/         experiments.csv, plots, training curves
checkpoints/     saved Q-tables and PPO networks
```

## More detail

See [scripts.md](scripts.md) for descriptions and example commands for every runnable script.

In Windows PowerShell, run `.\helpme.bat` from the repository root to list the available script commands.

On Linux or macOS, run `./helpme` from the repository root.

Add `--full` to either command to open the detailed usage manual.

Design notes live in `sumo/skopje/documentation/`:

- `selected_corridor.md`: why these 8 lights, neighbor distances
- `traffic_demand.md`: how scenarios are generated
- `traffic_agent_interface.md`: observations, actions, rewards, safety rules
- `static_fixed_time_baseline.md`, `imported_actuated_baseline.md`, `webster_fixed_time_baseline.md`: baselines
- `real_signals_network.md`: the `real_signals` network variant
- `spatial_observation_sharing.md`: neighbor-observation design and results

## Status

Done: baselines (static, Webster, actuated), single/multi-agent Q-learning, coordinated MARL (spatial,
neighbor-aware, global), deep MARL (shared PPO, self-attention PPO, DQN), PPO and DQN tuning, the `real_signals`
network, final medium and high results on `real_signals`, metrics and plots, Gym/PettingZoo wrappers.

In progress: low and peak on `real_signals` (second machine), evaluation on fresh seeds 45–47.

Not done: calibrated real-world demand.

## Networks

There are two network variants, chosen with the `SKOPJE_NETWORK` environment variable:

| Variant | Agents | Use |
| --- | --- | --- |
| `original` (default) | the 7 shared + A29 | the results above; kept for the record |
| `real_signals` | the 7 shared + A21 | final results; signals recoded to real Skopje behaviour |

`real_signals` also joins the stub junctions at Kuzman (A26) into one signalized junction, gives the
actuated programs and the agents the same green limits (7 s minimum), and adds two heavier scenarios:
`peak` (4600 vehicles, 50% rerouting) and `stress` (5400). Its results, checkpoints and audit are kept
apart from the original ones (`results/real_signals/`, `checkpoints/real_signals/`), and both folders
are gitignored.

```powershell
$env:SKOPJE_NETWORK="real_signals"
python scripts/experiments/run_imported_actuated_suite.py --scenarios low medium high peak --seed 42
python scripts/experiments/run_imported_actuated_experiment.py --scenario peak --seed 42 --webster
python scripts/experiments/run_attention_ppo.py train --scenario high --seed 42
```

Changing the network changes the number of lanes each agent observes, so a checkpoint only loads on
the network version it was trained on. Retrain after any network change.

See [`real_signals_network.md`](sumo/skopje/documentation/real_signals_network.md) and
[`webster_fixed_time_baseline.md`](sumo/skopje/documentation/webster_fixed_time_baseline.md).

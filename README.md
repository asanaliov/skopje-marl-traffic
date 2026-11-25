# Adaptive Traffic Lights in Skopje with Multi-Agent RL

Eight traffic lights on one Skopje corridor are controlled by reinforcement-learning agents in SUMO and compared
with fixed-time and actuated control. The learned controllers are a shared PPO, PPO with self-attention across
the junctions, and a shared DQN; tabular Q-learning variants were compared earlier on the original network.

> The road network comes from OpenStreetMap. Traffic demand is synthetic, not measured Skopje data, and the
> signal timings are not the city's official ones.

## Results (real_signals)

Final network (`SKOPJE_NETWORK=real_signals`). Learned controllers train for 300 episodes on demand seed 42 and are
evaluated on seeds 42, 43 and 44. Values are means over the three seeds; two numbers mean two training runs with
different torch seeds. Low and peak were trained once, with the current (tuned) defaults.

| Controller | Low wait (s) | Medium wait (s) | High wait (s) | High: vehicles left | Peak wait (s) | Peak: vehicles left |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `static_fixed_time` | 10.60 | 14.49 | 19.04 | 4–20 | 21.82 | 206–315 |
| `webster_fixed_time` | 6.20 | 8.78 | 14.01 | 17–43 | 17.27 | 131–700 |
| `imported_actuated` | 5.68 | **7.44** | **12.32** | 0–2 | **11.91** | 5–13 |
| `marl_deep_ppo` | 5.42 | 8.10 / 7.95 | 15.95 | 165–174 | 19.74 | 388–463 |
| `marl_attention_ppo` | 5.70 | 8.66 / 8.74 | 16.53 | 98–103 | 16.50 | 198–299 |
| `marl_deep_dqn`, SB3 default settings | – | 8.23 / 8.52 | 16.34 | 153–159 | – | – |
| `marl_deep_dqn`, tuned (current defaults) | **5.20** | 7.78 / 7.80 | 13.46 | 1–7 | 14.30 | 135–229 |

- RL beats fixed-time control: tuned DQN is 46% better than static and 11% better than Webster on medium.
- Actuated control is still best on medium, high and peak: tuned DQN is 4.7%, 9% and 20% behind. On low, tuned DQN
  (8% better) and plain PPO beat it.
- On peak, the seed-42 Webster plan gridlocks on seed 43 (21.67 s, 700 vehicles left) but not on 42 and 44
  (14.49 s, 15.64 s): the known weakness of a fixed plan under different demand.
- Self-attention does not help: about 0.7 s worse than the same PPO without attention, in both training runs.
- On high, both PPOs jam at A26 (Kuzman): a queue grows past the 150 m the agent observes, so neither its
  observation nor its reward sees it. Tuned DQN, with the same observation, serves that approach and leaves 1–7 vehicles.
- 500 episodes instead of 300 did not help (attention PPO on high: 16.75 s).

**Metric.** "Wait" is the mean over all vehicles of SUMO's accumulated waiting time, counted over a 100 s window
(SUMO's `--waiting-time-memory` default). Stuck vehicles count at most 100 s each, so vehicles still in the network
at the end (3600 s of demand plus 600 s without new vehicles) are reported next to it.

Raw rows: `results/real_signals/experiments.csv`, `torchseed1.csv` (second training runs), `test_ep500.csv`,
`tuning/` (PPO tuning) and `tuning_dqn/` (DQN tuning and the tuned DQN; `*_lr3e-4_grad1680.csv` per scenario).

## How the settings were chosen

Change one setting at a time from the current best, train on seed 42, evaluate on seeds 42–44; tune on medium,
then confirm on high. Promising changes get a second training run, because two runs of the same settings can differ
by up to 0.3 s. Caveat: tuning and evaluation used the same seeds; a final evaluation on seeds 45–47 is planned.

**PPO** (tuned on attention PPO, 150 episodes per run; plain PPO shares the defaults). Runs a–p were on the network
before #78 (the Kuzman fix), F on the fixed one.

| Run | Change from the previous best | Medium (s) | Kept? |
| --- | --- | ---: | --- |
| a | linear learning-rate decay | 8.64 | yes |
| b | + 10 instead of 4 update epochs | 8.48 | yes |
| c | decide every 2 s instead of 5 s | 9.05 | no |
| e | neighbor-aware reward | 8.99 | no |
| h | count vehicles up to 150 m before the stop line | 9.04 | not alone |
| j | 150 m + minimum green 7 s instead of 10 s | 8.11 | yes |
| p | pressure instead of local reward | 8.06 | no (same as j) |
| F | j on the fixed network | 8.04 | final |

**DQN** (300 episodes per run, starting from Stable-Baselines3 values). An episode gives 6,720 decisions; they go
into a replay buffer of the last 200,000, and after each episode the network takes gradient steps on random batches of 256.

| Change | Concretely | Medium (s) |
| --- | --- | ---: |
| none (SB3 default) | lr 1e-4, 840 gradient steps per episode | 8.23 / 8.52 |
| bigger learning rate | lr 3e-4 | 8.12 |
| more gradient steps | 1680 per episode | 8.12 |
| smaller replay buffer | 50,000 | 8.31 |
| slower target network | synced every 5000 steps | 8.39 |
| less exploration | random actions in the first 10% of episodes | 8.56 |
| **lr 3e-4 + 1680 steps** | both (current defaults) | **7.78 / 7.80** |
| lr 1e-3 + 1680 steps | even bigger learning rate | 7.50 (one run) |
| lr 3e-4 + 3360 steps | 4x the default steps | 7.49 (one run) |
| bigger network | 2x256 | 7.84 |

No single change beat the run-to-run noise; the combination did, in both runs, and the same settings removed the
A26 jam on high. Learning more from each sample helped; buffer size, target speed and network size did not.

## Controllers

| Label | What it is |
| --- | --- |
| `static_fixed_time` | fixed 30 s greens, original phase order |
| `webster_fixed_time` | fixed plans optimised with Webster's method (`real_signals` only) |
| `imported_actuated` | SUMO actuated programs: extend green while detectors see traffic, 7–60 s |
| `marl_deep_ppo` | one PPO network shared by all 8 agents; local observation and reward |
| `marl_attention_ppo` | the same, plus one self-attention layer across the junctions (needs all 8 observations at run time) |
| `marl_deep_dqn` | shared Double DQN with replay buffer and target network; same observation, reward and network size |
| `independent_rl`, `multi_agent_*`, `marl_neighbor_reward`, `marl_global_reward` | tabular Q-learning variants (original network) |

Agents choose `KEEP` or `NEXT_GREEN` every 5 s; a safety layer enforces minimum/maximum green and yellow.
Observations per incoming lane (up to 150 m upstream): queue, vehicle count, mean waiting time, mean speed, plus the
current phase. Local reward: −(queue) − 0.1 × (lane waiting time).

## Setup

Python 3.11. **Linux** (SUMO comes from the `eclipse-sumo` pip package):

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # optional: CPU-only torch
pip install -r requirements.txt -r requirements-dev.txt eclipse-sumo==1.27.1
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"   # add this line to .venv/bin/activate
python scripts/setup/check_setup.py
```

**Windows:** install [SUMO](https://sumo.dlr.de/docs/Downloads.php), set `SUMO_HOME`, add its `bin` to `PATH`, then
`pip install -r requirements.txt -r requirements-dev.txt` and `python scripts/setup/check_setup.py`.

## Running

Set these first (PowerShell: `$env:NAME="value"`):

```bash
export SKOPJE_NETWORK=real_signals                 # final network; default is the original one
export SKOPJE_LIBSUMO=1                            # SUMO in-process: ~2.5x faster, identical results, no GUI
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1         # one torch thread: ~3x faster for these small networks
```

Baselines (no training):

```bash
python scripts/experiments/run_static_fixed_time_suite.py --scenarios medium high --seeds 42 43 44
python scripts/experiments/run_imported_actuated_suite.py --scenarios medium high --seed 42
python scripts/experiments/run_imported_actuated_experiment.py --scenario medium --seed 42 --webster
```

Learned controllers: the same pattern for `run_deep_marl.py` (PPO), `run_attention_ppo.py` and `run_dqn.py`:

```bash
python scripts/experiments/run_dqn.py train    --scenario medium --seed 42
python scripts/experiments/run_dqn.py evaluate --scenario medium --seed 42
python scripts/experiments/run_dqn.py evaluate --scenario medium --seed 43 --allow-cross-seed \
    --checkpoint checkpoints/real_signals/deep_marl_dqn_local_medium_seed42.pt
```

Each evaluation appends one row to `results/real_signals/experiments.csv` (or `results/experiments.csv` on the
original network). Checkpoints refuse to load if the network, scenario, agents or settings don't match. `--resume`
continues an interrupted run (keep `--episodes` unchanged; DQN restarts with an empty replay buffer).

Seed 42 demand ships with the repo. For other seeds run `generate_traffic_demand.py --scenario <s> --seed <n>`
(without `SKOPJE_NETWORK`), then `scripts/setup/make_real_signals_configs.py`.

Results and analysis:

```bash
python scripts/analysis/summarize_experiments.py --results results/real_signals/experiments.csv
python scripts/analysis/experiment_matrix.py results/real_signals          # which runs are done or missing
python scripts/analysis/merge_results.py other_machine.csv                 # merge rows from another machine
python scripts/sumo_visualization/watch_trained_controller.py --controller deep-marl --scenario medium   # GUI replay
python -m pytest                                                           # tests
```

Every script is described in [scripts.md](scripts.md) (`./helpme` or `.\helpme.bat` lists them).

## Networks

| Variant | Agents | Use |
| --- | --- | --- |
| `original` (default) | A9, A18, A19, A20, A24, A25, A26, A29 | earlier results, kept for the record |
| `real_signals` | the same, with A21 instead of A29 | final results |

`real_signals` recodes the signals to real Skopje behaviour after a site check (including A19), joins the stub
junctions at Kuzman (A26) into one signalised junction, gives actuated control and the agents the same 7 s minimum
green, and adds two heavier scenarios: `peak` (4,600 vehicles, 50% choose the fastest route when they depart) and
`stress` (5,400). A network change changes what agents observe, so retrain after any network change.

| Scenario | Vehicles / hour | Rerouting |
| --- | ---: | ---: |
| low / medium / high | 900 / 1,800 / 3,000 | none |
| peak / stress | 4,600 / 5,400 | 50% |

## Original network results (for the record)

Mean waiting time (s), seeds 42–44, before `real_signals`:

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

Actuated was best in every scenario; deep PPO beat the independent tabular multi-agent controller in all three. Source: `results/experiments.csv`.

## Project layout

```
src/            agents, baselines, demand, environment (SUMO + Gym/PettingZoo wrappers), evaluation, training
scripts/        experiments, analysis, demand, setup, network and environment inspection, visualization
sumo/skopje/    network, demand, configs and design notes (documentation/)
results/        result CSVs; checkpoints/ holds trained models
```

Design notes in `sumo/skopje/documentation/`: `selected_corridor.md`, `traffic_demand.md`,
`traffic_agent_interface.md`, `real_signals_network.md`, and one file per baseline.

**Status.** Done: baselines, tabular and deep MARL, PPO and DQN tuning, `real_signals`, low, medium, high and peak results.
In progress: evaluation on seeds 45–47. Not done: demand calibrated to measured counts.

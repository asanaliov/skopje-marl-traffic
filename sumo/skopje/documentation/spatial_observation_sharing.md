# Spatial Observation Sharing Between Neighbor Nodes

Independent multi-agent Q-learning (`multi_agent_independent_rl`) lets
every corridor agent see only its own junction. A platoon released by an
upstream neighbor is therefore invisible until it is already queued at
the agent's own stop line.

Spatial observation sharing (`multi_agent_spatial_rl`) adds the one
communication channel the tabular runner supports: each agent also
observes a coarse congestion flag for its nearest neighbors. Rewards stay
purely local -- this changes what an agent *sees*, not what it is paid
for. Neighbor-aware and global reward mixing is separate work.

## State representation

`DiscreteTrafficState` gains one field, `neighbor_queue_flags`: a tuple
holding one value per observed neighbor, in the encoder's `neighbor_ids`
order.

| Neighbor total queue | Flag |
| --- | --- |
| 0-3 queued vehicles | `0` |
| 4 or more queued vehicles | `1` |

The threshold is `StateEncoderConfig.neighbor_total_queue_threshold`
(default `4`, the second `total_queue_thresholds` boundary). One bit per
neighbor is deliberate: a full bucket per neighbor would multiply the
tabular Q-table by five instead of two.

For purely local agents the field stays `()`, so a local state encoded
today is still equal to one encoded before spatial sharing existed, and
existing local checkpoints keep loading.

## Choosing the neighborhood

Neighbors come from the audited `SELECTED_CORRIDOR.neighbor_map` and are
ordered by `neighbor_distances_m` through
`nearest_neighbor_ids()`, nearest first. `--neighbor-limit` (default `2`)
keeps only the closest ones.

That bound is the central design constraint. Each observed neighbor is
one extra state bit, so it doubles the reachable Q-table:

| Agent | Audited neighbors | Observed at limit 2 |
| --- | --- | --- |
| A9 | A18, A19, A20, A26 | A18, A26 |
| A18 | A9, A19, A20, A26 | A19, A9 |
| A19 | A9, A18, A26 | A18, A26 |
| A20 | A26 | A26 |
| A24 | A25 | A25 |
| A25 | A20, A24, A26, A29 | A24, A29 |
| A26 | A9, A18, A19, A20, A25, A29 | A20, A9 |
| A29 | A19, A20, A25, A26 | A19, A26 |

A26 alone has six audited neighbors; observing all of them would multiply
its Q-table by 64. Two nearest neighbors caps the growth at four times
the local state space.

A run only observes agents it actually controls, so `--agents A19` falls
back to purely local states rather than reading a junction nobody is
stepping.

## Checkpoint compatibility

A spatial Q-table is keyed by states a local agent cannot represent, so
the two are not interchangeable. Checkpoints carry both the controller
label and the exact `spatial_neighbor_ids` mapping they were trained
with, and a load refuses a mismatch -- including a run that changed
`--neighbor-limit`.

## Measured comparison

Both controllers were trained with identical settings and then evaluated
greedily on the same seed. The rows are in `results/experiments.csv`.

Training: `--scenario medium --seed 42 --episodes 30`, 600 s demand plus
600 s cooldown per episode, default hyperparameters.

| Metric | `multi_agent_independent_rl` | `multi_agent_spatial_rl` |
| --- | --- | --- |
| Distinct Q-table states (all 8 agents) | 716 | 1307 |
| Mean training combined reward | -8096.20 | -8223.56 |
| Best training combined reward | -6883.86 | -6789.54 |
| Evaluation combined reward | -15139.19 | -14785.73 |
| Evaluation average waiting time (s) | 13.18 | 20.71 |
| Evaluation average queue length | 15.69 | 20.07 |
| Evaluation maximum queue length | 39 | 54 |
| Evaluation average speed (m/s) | 8.22 | 7.70 |
| Evaluation throughput (arrived) | 398 | 367 |

Reading these numbers honestly: spatial observations reached a slightly
better evaluation reward (+2.3%) and a better best-episode training
reward, but *worse* corridor traffic metrics -- longer waits, longer
queues, lower throughput. Two things drive that, and neither is settled
by this run:

1. The spatial agents carry 1.8x the states on the same 30 episodes, so
   each state is visited far less often. Exploration is still wide open
   at the end of training (mean epsilon 0.86 with the default 0.995
   per-episode decay), which is the well-known cost of a larger tabular
   state space.
2. Combined reward is a sum of purely local rewards. A neighbor flag can
   only help an agent choose better for itself; with local rewards there
   is nothing pushing agents to use that information to help the
   corridor. That is exactly what neighbor-aware and global reward mixing
   is for.

The conclusion this run supports is a mechanical one -- spatial states
are constructed correctly, training runs end to end, and the results are
separately labeled and comparable. It does *not* yet support a claim that
spatial observations improve corridor performance. A longer training
budget (enough episodes for epsilon to actually decay) and a pairing with
coordinated rewards are the obvious next steps.

## Reproducing

```powershell
python scripts/experiments/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 30 --checkpoint checkpoints/multi_agent_medium_local.json
python scripts/experiments/run_multi_agent_q_learning.py train --scenario medium --seed 42 --episodes 30 --checkpoint checkpoints/multi_agent_medium_spatial.json --spatial-observations
python scripts/experiments/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --checkpoint checkpoints/multi_agent_medium_local.json
python scripts/experiments/run_multi_agent_q_learning.py evaluate --scenario medium --seed 42 --checkpoint checkpoints/multi_agent_medium_spatial.json --spatial-observations
```

Unit tests, which need neither SUMO nor SUMO-GUI:

```powershell
python -m pytest tests/test_state_encoder.py tests/test_multi_agent_q_learning.py tests/test_selected_corridor.py
```

# Peak improvement experiments and next steps (real_signals, Nov 2026)

After the low and peak results (PR #87), five experiments tried to close the gap to actuated control on
**peak**, where it is largest. Each trains on seed 42 with the current defaults plus one change and is
evaluated on seeds 42, 43 and 44 (`SKOPJE_NETWORK=real_signals`). Rows: `results/real_signals/improve/`.

| Experiment | Change from the current defaults |
| --- | --- |
| `dqn_peak_ep600` | 600 episodes instead of 300 (resumed once at episode 339, with `--resume-warmup 5`) |
| `dqn_peak_lr1e-3_grad3360` | learning rate 1e-3 and 3,360 gradient steps (each gave ~7.5 s on medium, now combined) |
| `dqn_peak_range300` | observe 300 m before the stop line instead of 150 m |
| `ppo_peak_range300` | the same for plain PPO |
| `attention_peak_range300` | the same for attention PPO |

## Results — peak, mean of seeds 42–44

| Controller / experiment | Wait (s) | Queue | Throughput | Teleports | Left | Wait 42/43/44 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `imported_actuated` | **11.91** | 38.4 | 4592 | 9 | 8 | 11.60 / 11.97 / 12.16 |
| `dqn_peak_lr1e-3_grad3360` | 13.76 | 39.9 | 4488 | 13 | 112 | 12.74 / 12.88 / 15.68 |
| `dqn_peak_ep600` | 13.95 | 43.9 | 4409 | 28 | 189 | 13.81 / 12.55 / 15.50 |
| tuned DQN (300 ep) | 14.30 | 39.3 | 4424 | 22 | 173 | 13.04 / 13.96 / 15.90 |
| `dqn_peak_range300` | 14.40 | 42.2 | 4470 | 16 | 128 | 13.49 / 12.71 / 17.01 |
| attention PPO | 16.50 | 46.5 | 4350 | 34 | 245 | 15.73 / 16.44 / 17.33 |
| `attention_peak_range300` | 16.59 | 45.0 | 4372 | 29 | 226 | 15.28 / 17.59 / 16.90 |
| `webster_fixed_time` | 17.27 | 91.3 | 4251 | 44 | 336 | 14.49 / 21.67 / 15.64 |
| `ppo_peak_range300` | 18.68 | 40.3 | 4222 | 76 | 371 | 18.23 / 18.26 / 19.55 |
| PPO | 19.74 | 46.0 | 4159 | 75 | 432 | 19.75 / 18.71 / 20.75 |
| `static_fixed_time` | 21.82 | 73.1 | 4334 | 28 | 262 | 20.62 / 20.94 / 23.91 |

"Left" is vehicles still in the network at the end, "teleports" vehicles SUMO removed after being stuck;
lower is better for both. Queue and throughput are means of `average_queue_length` and `throughput`.

## Analysis

- **Best: DQN with lr 1e-3 and 3,360 gradient steps.** Best RL agent on wait, throughput, teleports and
  vehicles left. The only candidate worth considering as a new DQN default. Still 1.85 s behind actuated.
- **600 episodes did not help.** 0.35 s less wait, but queue, teleports, vehicles left and throughput were
  slightly worse. The training reward had flattened by about episode 350.
- **300 m observation range** made no clear difference for DQN or attention, and helped plain PPO by about
  1 s, which is still the weakest RL agent. So not seeing the queue explains only part of the PPO jam.
- **Seed 44 is the hardest** for every DQN variant (15.5–17 s), where the gap to actuated is widest.
- **Webster** gridlocks on seed 43 with the seed-42 plan (700 vehicles left): the known weakness of fixed
  plans under different demand, not a bug.
- **Why actuated is hard to beat:** it ends green as soon as the queue clears (gap-out), reacts every
  second (the agents decide every 5 s), uses SUMO's own perfect detectors and has nothing to overfit.
- **Attention already shares regional information** and does not help, so plain neighbour observation
  sharing is not worth trying separately: a queue past 150 m is invisible to the neighbours as well.

### From the literature (abstract level)

- Kwesiga et al. 2026 (arXiv 2603.15283): RL trained on **many varied demand patterns** reported 11–32%
  less delay than optimised actuated control, also on unseen demand.
- Semi-centralised MARL 2025 (arXiv 2512.04653): regional observation pooling beat actuated under heavy
  flows.
- arXiv 2412.03925, 2311.15920, 2502.16608 describe the A26 failure: once a queue grows past the sensing
  range the agent cannot learn that more green helps, and spillback corrupts neighbours' state.

## Caveats

- These experiments were compared on seeds 42–44, so those seeds are no longer a clean test for picking
  a winner. Final numbers should come from seeds 45–47.
- The main table uses 300 episodes and the current defaults everywhere. A new setting has to be applied to
  all four scenarios before it replaces a main-table row.

## Next steps

1. **Decide whether lr 1e-3 + 3,360 gradient steps becomes the DQN default.** If yes, retrain DQN on low,
   medium, high and peak (300 episodes).
2. **Final evaluation on seeds 45–47** for every controller and scenario.
3. **Spillback-aware observation:** a per-lane flag for "queue reaches the end of the observed range" plus
   occupancy of the outgoing lanes. Test on peak first.
4. **Train on varied demand:** a different demand seed each episode, from seeds outside 42–47.
5. **Max-pressure baseline:** pressure is already computed for the reward. A fairer adaptive bar than
   Webster, and it shows whether actuated wins because it adapts or because it is SUMO-native.
6. Drop longer training and a larger range on their own; neither paid off.

## Reproducing

```
$env:SKOPJE_NETWORK = "real_signals"; $env:SKOPJE_LIBSUMO = 1
python scripts/experiments/run_dqn.py train --scenario peak --seed 42 --learning-rate 1e-3 --gradient-steps 3360 --checkpoint checkpoints/real_signals/improve/dqn_peak_lr1e-3_grad3360.pt
python scripts/experiments/run_dqn.py evaluate --scenario peak --seed 43 --allow-cross-seed --checkpoint checkpoints/real_signals/improve/dqn_peak_lr1e-3_grad3360.pt
```

The other runs swap in `--episodes 600` or `--approach-range 300` (`run_deep_marl.py`, `run_attention_ppo.py`
for the PPOs; for the range runs pass `--approach-range 300` to `evaluate` too).

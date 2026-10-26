# Traffic-Agent Interface

## Purpose

The traffic-agent interface defines what each selected traffic-light agent observes, which actions it may request, how its learning reward is calculated, and how those requests reach SUMO safely.
No learning algorithm is implemented in this module.
The interface is intended to support future independent reinforcement learning and coordinated multi-agent reinforcement learning without coupling either approach to SUMO process management.

The full Skopje network remains active.
Only A9, A18, A19, A20, A24, A25, A26, and A29 are wrapped for future control.
Every other traffic light retains its original SUMO program.
The official agent-to-controller mapping comes from `SELECTED_CORRIDOR` in `src/environment/selected_corridor.py`.

## Data and control flow

```text
SUMO traffic state
    -> TrafficSignal.observe()
    -> TrafficObservation
    -> future learning algorithm
    -> TrafficAction
    -> TrafficSignal.apply_action()
    -> safe SUMO phase transition
    -> RewardBreakdown
```

SUMO owns the microscopic traffic simulation and the original traffic-light programs.
TraCI exposes the current simulation state and accepts narrowly constrained signal commands.
One `TrafficSignal` wrapper represents one selected agent and receives an injected TraCI connection.
The wrapper does not start or stop SUMO.
The future simulation environment will own the SUMO process and call each wrapper.

## Detected selected-controller programs

All eight selected controllers use actuated program `0` in the committed Skopje network.
The lane counts below are deduplicated controlled incoming lanes in first-occurrence TraCI order.
The durations are the original default phase durations in the network.
Actuated green phases have original minimum and maximum values of 5 and 50 seconds.

| Agent | Incoming lanes | Original phase structure |
| --- | ---: | --- |
| A9 | 7 | green 0 (42 s) -> yellow 1 (3 s) -> green 2 (42 s) -> yellow 3 (3 s) |
| A18 | 7 | green 0 (42 s) -> yellow 1 (3 s) -> green 2 (42 s) -> yellow 3 (3 s) |
| A19 | 14 | green 0 (33 s) -> yellow 1 (3 s) -> green 2 (6 s) -> yellow 3 (3 s) -> all-red 4 (1 s) -> green 5 (32 s) -> yellow 6 (3 s) -> green 7 (6 s) -> yellow 8 (3 s) |
| A20 | 11 | green 0 (24 s) -> yellow 1 (3 s) -> green 2 (6 s) -> yellow 3 (3 s) -> green 4 (24 s) -> yellow 5 (3 s) -> green 6 (24 s) -> yellow 7 (3 s) |
| A24 | 13 | green 0 (33 s) -> yellow 1 (3 s) -> green 2 (6 s) -> yellow 3 (3 s) -> green 4 (33 s) -> yellow 5 (3 s) -> green 6 (6 s) -> yellow 7 (3 s) |
| A25 | 10 | green 0 (42 s) -> yellow 1 (3 s) -> green 2 (42 s) -> yellow 3 (3 s) |
| A26 | 9 | green 0 (33 s) -> yellow 1 (3 s) -> green 2 (6 s) -> yellow 3 (3 s) -> all-red 4 (1 s) -> green 5 (32 s) -> yellow 6 (3 s) -> green 7 (6 s) -> yellow 8 (3 s) |
| A29 | 4 | green 0 (42 s) -> yellow 1 (3 s) -> green 2 (42 s) -> yellow 3 (3 s) |

The interface reads these structures from the active TraCI program logic.
It does not copy controller IDs into the action code and does not assume a common phase count.

## Observation definition

`TrafficSignal.observe()` returns one immutable `TrafficObservation`.
It contains the agent ID, traffic-light ID, simulation time, incoming lane IDs, queue lengths, vehicle counts, lane mean accumulated waiting times, lane mean speeds, current phase index, current red/yellow/green state, elapsed phase time, and green/transition flags.

A vehicle is queued when its speed is strictly below 0.1 metres per second.
A vehicle moving at exactly 0.1 metres per second is not queued.
A lane with no vehicles has queue length 0, vehicle count 0, mean waiting time 0.0, and mean speed 0.0.
The interface never represents an empty lane with NaN.

Vehicle IDs are read from each controlled incoming lane.
Speed and accumulated waiting time are then read for each vehicle.
A vehicle that disappears between those two TraCI snapshots is skipped.
Unknown lanes, unknown traffic lights, invalid program structures, and other structural errors still fail clearly.

SUMO 1.27.1 exposes the current phase's spent duration directly through TraCI.
The wrapper uses that value when available.
For a smaller TraCI-like implementation without that operation, the wrapper detects phase-index changes and tracks the phase start time locally.

## Lane ordering

TraCI may repeat one incoming lane because several controlled links originate from it.
`TrafficSignal` removes duplicates while preserving the first occurrence returned by TraCI.
That tuple becomes the stable lane order for raw metrics and normalized features for the lifetime of the wrapper.
An optional expected-lane tuple may validate the detected set and define an explicit stable order.

## Normalized observation

`TrafficObservation.normalized_features()` produces an immutable tuple whose values are clipped to the interval from 0.0 to 1.0.
The default caps are 20 queued vehicles per lane, 30 vehicles per lane, 300 seconds of lane mean waiting time, 13.89 metres per second for speed, and 60 seconds for phase elapsed time.
The 13.89 metres-per-second speed cap is a documented 50 km/h fallback.
`TrafficSignal.normalization_config()` replaces that fallback with each detected lane's SUMO speed limit when the injected lane API exposes it.
It also uses the configured maximum green as the phase-elapsed cap.

For every lane in `incoming_lane_ids` order, the tuple contains these four features:

1. Clipped queue length divided by the queue cap.
2. Clipped vehicle count divided by the vehicle-count cap.
3. Clipped mean accumulated waiting time divided by the waiting-time cap.
4. Clipped mean speed divided by that lane's speed cap or the documented fallback.

After all lane-major features, the tuple contains:

1. Clipped current phase elapsed time divided by the phase-elapsed cap.
2. A deterministic one-hot vector whose length equals the active program's phase count.

The one-hot phase representation avoids treating phase numbers as a continuous measurement.
Different intersections may have different feature lengths because they have different lane counts and phase counts.

## Action definitions

`TrafficAction.KEEP` has integer value 0.
`TrafficAction.NEXT_GREEN` has integer value 1.
An agent cannot request a yellow phase, an all-red phase, or an arbitrary phase index.

The initial action policy uses:

- Minimum green: 10 seconds.
- Maximum green: 60 seconds.
- Decision interval: 5 seconds.

These timings are initial experimental parameters, not official traffic-engineering settings.
They require calibration and safety review before any real-world interpretation.

During a green phase, `KEEP` retains the current green and extends its remaining duration only when needed to reach the next decision point.
The wrapper also prevents a retained phase from exceeding the configured maximum.
If the maximum green has been reached, `KEEP` initiates the same safe immediate transition used by an accepted `NEXT_GREEN`.

`NEXT_GREEN` is rejected before the minimum green has elapsed.
After the minimum green, it sets only the immediate next phase index in the original program.
It applies that transition phase's original duration to the current occurrence because changing a phase through TraCI can otherwise inherit an unsuitable remaining switch time.
SUMO then continues through the original phase sequence.

During a yellow or all-red phase, both actions return `TRANSITION_IN_PROGRESS` and issue no new phase command.
The wrapper synchronizes after automatic or external changes so it recognizes when the transition has completed.

## Safe phase transitions

The wrapper preserves original cyclic program order.
A typical change is:

```text
current green
    -> original yellow
    -> original all-red, if present
    -> next original green
```

The yellow and all-red phases come from the original SUMO programs.
The wrapper does not invent signal states, rewrite program definitions, or jump directly to a later green.
Setting one current transition occurrence to its original duration does not change the stored program definition or later cycles.
If an active program would place another green immediately after the current green, the wrapper reports an invalid action instead of issuing an unsafe direct green-to-green command.

Only a selected wrapper may receive these commands.
Traffic lights outside the selected eight are never passed to `TrafficSignal` and retain their original behavior.
Read-only inspection mode does not call `apply_action()` at all.

## Local learning reward

The local reward is:

```text
local_reward = -(
    queue_weight * total_queue
    + waiting_weight * total_waiting_time
    + switch_penalty_weight * phase_switch_value
)
```

`total_queue` is the sum of lane queue lengths.
`total_waiting_time` is the sum of lane mean accumulated waiting times.
`phase_switch_value` is 1 when a phase switch was initiated and 0 otherwise.
The initial weights are 1.0 for queue, 0.1 for waiting time, and 0.0 for the optional switch penalty.
`RewardBreakdown` reports the negative queue, waiting, and switch components plus their sum.

No congestion and no switch penalty produce a reward of 0.
Larger queues and waiting times make the reward more negative.

## Future coordinated rewards

Neighbor-aware reward is defined as:

```text
combined_reward = (
    local_weight * local_reward
    + neighbor_weight * mean_neighbor_reward
)
```

The initial weights are 0.7 local and 0.3 neighbor.
They must be non-negative and sum to 1.
If no neighbor rewards are available, the helper returns the local reward.
Neighbor-aware reward is available as a pure helper but is not activated automatically.

Global corridor reward is the arithmetic mean of all supplied local agent rewards:

```text
global_reward = sum(local_rewards) / number_of_local_rewards
```

An empty global input is rejected because its arithmetic mean is undefined.
Global reward is available as a pure helper but is not activated automatically.

These rewards are learning feedback.
They are not final experiment metrics and do not import or replace the teammate-owned evaluation package.

## Inspection commands

Inspect A19 in the canonical medium scenario:

```powershell
python scripts/inspection/inspect_traffic_agent.py --scenario medium --seed 42 --agent A19
```

Inspect all selected agents:

```powershell
python scripts/inspection/inspect_traffic_agent.py --scenario medium --seed 42 --all
```

Inspect all selected agents for 600 seconds under high demand:

```powershell
python scripts/inspection/inspect_traffic_agent.py --scenario high --seed 42 --all --seconds 600
```

Open the high-demand inspection in SUMO-GUI:

```powershell
python scripts/inspection/inspect_traffic_agent.py --scenario high --seed 42 --all --gui
```

Run the deterministic action demonstration only after read-only inspection succeeds:

```powershell
python scripts/inspection/inspect_traffic_agent.py --scenario low --seed 42 --agent A19 --seconds 120 --demo-actions
```

The script prints: `This is an agent-interface inspection run. No learning algorithm is active.`
Default mode observes only and leaves every original program in control.
Demonstration mode uses a slow deterministic schedule of safe `KEEP` and `NEXT_GREEN` requests.
It is not reinforcement learning and it writes no experiment results or scenario files.

## Future integration

An independent reinforcement-learning environment can give each agent only its own normalized observation, request one of the two actions, and use its local `RewardBreakdown`.
A coordinated multi-agent environment can additionally exchange selected neighbor information from `SELECTED_CORRIDOR.neighbor_map` and combine already-calculated local rewards with the pure neighbor-aware helper.
The same safe `TrafficSignal.apply_action()` boundary should remain in both designs.

## Limitations

- The observations use current lane snapshots and do not include downstream occupancy, turning intention, pedestrian demand, or transit priority.
- Different lane and phase counts produce different raw feature lengths across agents.
- The waiting aggregation sums lane means rather than summing every vehicle's waiting time.
- The queue, vehicle, waiting, speed, and phase-duration caps are initial feature-scaling choices.
- The action policy does not certify traffic-engineering safety beyond preserving the imported SUMO phase order.
- The imported actuated programs and synthetic demand are experimental simulation inputs rather than calibrated real-world control plans.
- A future environment must call actions on the configured decision schedule and continue synchronizing every wrapper.
- No learning algorithm, training loop, replay buffer, model persistence, experiment CSV writer, or baseline experiment is implemented here.

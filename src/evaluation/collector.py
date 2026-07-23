"""TraCI-based metric collection for a single simulation run.

This module isolates every TraCI-specific call behind `MetricsCollector`.
It does NOT start or close SUMO itself -- the calling script (fixed-time
runner, RL runner, ...) owns the `traci.start(...)` / `traci.close()`
lifecycle (typically in a try/finally block). The collector only reads
state through an already-connected TraCI-like object, which is exactly why
its tests can pass a small fake/stub instead of a real SUMO connection.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from src.evaluation.metrics import EpisodeMetrics, PerAgentDiagnostics


@dataclass
class _RunningStats:
    step_count: int = 0
    queue_sum: float = 0.0
    queue_max: float = 0.0
    speed_sum: float = 0.0
    speed_sample_steps: int = 0
    stopped_vehicle_ids: set[str] = field(default_factory=set)
    waiting_time_by_vehicle: dict[str, float] = field(default_factory=dict)
    departed_ids: set[str] = field(default_factory=set)
    arrived_ids: set[str] = field(default_factory=set)
    teleport_count: int = 0


class MetricsCollector:
    """Accumulates episode-level metrics one simulation step at a time.

    Usage (inside a runner that already called traci.start(...)):

        collector = MetricsCollector(
            controller="static_fixed_time",
            scenario="medium",
            seed=42,
            monitored_lanes=selected_corridor_incoming_lanes,
        )
        try:
            while <simulation should continue>:
                traci.simulationStep()
                collector.record_step(traci)
        finally:
            metrics = collector.finalize(simulation_seconds=4200)
            traci.close()
    """

    def __init__(
        self,
        controller: str,
        scenario: str,
        seed: int,
        monitored_lanes: Iterable[str] | None = None,
        stopped_speed_threshold: float = 0.1,
    ) -> None:
        self.controller = controller
        self.scenario = scenario
        self.seed = seed
        # If no monitored lanes are given, queue/stopped-vehicle stats fall
        # back to "every vehicle in the network" -- still safe, just wider
        # than the eight-agent corridor.
        self.monitored_lanes = list(monitored_lanes) if monitored_lanes else None
        self.stopped_speed_threshold = stopped_speed_threshold
        self._stats = _RunningStats()
        self._reward_total: float | None = None

    def record_step(self, traci_conn) -> None:
        """Read state for the step that was just advanced.

        Safe to call on steps with zero active vehicles: every aggregate
        below either skips the empty step (average_speed) or naturally
        contributes zero (queue sums, stopped-vehicle set).
        """
        self._stats.step_count += 1

        vehicle_ids: list[str] = list(traci_conn.vehicle.getIDList())

        if self.monitored_lanes is not None:
            step_queue = sum(
                traci_conn.lane.getLastStepHaltingNumber(lane_id)
                for lane_id in self.monitored_lanes
            )
        else:
            step_queue = sum(
                1
                for vid in vehicle_ids
                if traci_conn.vehicle.getSpeed(vid) < self.stopped_speed_threshold
            )
        self._stats.queue_sum += step_queue
        self._stats.queue_max = max(self._stats.queue_max, step_queue)

        if vehicle_ids:
            speeds = [traci_conn.vehicle.getSpeed(vid) for vid in vehicle_ids]
            self._stats.speed_sum += sum(speeds) / len(speeds)
            self._stats.speed_sample_steps += 1

        for vid in vehicle_ids:
            if traci_conn.vehicle.getSpeed(vid) < self.stopped_speed_threshold:
                self._stats.stopped_vehicle_ids.add(vid)
            # Overwrite with the latest cumulative value each step, so the
            # final value kept per vehicle is its own last observation
            # (on arrival, or at the end of the run) -- never summed
            # across steps, which would double count.
            self._stats.waiting_time_by_vehicle[vid] = (
                traci_conn.vehicle.getAccumulatedWaitingTime(vid)
            )

        for vid in traci_conn.simulation.getDepartedIDList():
            self._stats.departed_ids.add(vid)
        for vid in traci_conn.simulation.getArrivedIDList():
            self._stats.arrived_ids.add(vid)

        self._stats.teleport_count += len(
            traci_conn.simulation.getStartingTeleportIDList()
        )

    def add_reward(self, reward: float) -> None:
        """Let future RL runners accumulate a reward signal.

        Non-RL controllers (fixed_time, static_fixed_time) simply never
        call this, so `total_reward` stays None for them rather than 0.
        """
        self._reward_total = (self._reward_total or 0.0) + reward

    def finalize(
        self,
        simulation_seconds: float,
        per_agent: Iterable[PerAgentDiagnostics] = (),
    ) -> EpisodeMetrics:
        """Build the final EpisodeMetrics for the run so far.

        Does not close TraCI or reset internal state -- call this once,
        after the simulation loop ends, still inside the runner's
        try/finally so traci.close() runs afterward regardless of errors.
        """
        stats = self._stats
        departed = len(stats.departed_ids)
        arrived = len(stats.arrived_ids)

        average_queue_length = (
            stats.queue_sum / stats.step_count if stats.step_count else 0.0
        )
        average_speed = (
            stats.speed_sum / stats.speed_sample_steps
            if stats.speed_sample_steps
            else 0.0
        )
        waiting_times = list(stats.waiting_time_by_vehicle.values())
        average_waiting_time = (
            sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
        )

        active_remaining = max(departed - arrived, 0)

        return EpisodeMetrics(
            controller=self.controller,
            scenario=self.scenario,
            seed=self.seed,
            simulation_seconds=simulation_seconds,
            average_waiting_time=average_waiting_time,
            average_queue_length=average_queue_length,
            max_queue_length=stats.queue_max,
            average_speed=average_speed,
            throughput=arrived,
            departed_vehicles=departed,
            arrived_vehicles=arrived,
            total_stopped_vehicles=len(stats.stopped_vehicle_ids),
            active_vehicles_remaining=active_remaining,
            teleport_count=stats.teleport_count,
            total_reward=self._reward_total,
            per_agent=tuple(per_agent),
        )

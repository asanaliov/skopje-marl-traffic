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

from traci import constants as tc

from src.evaluation.metrics import EpisodeMetrics, PerAgentDiagnostics

# Every TraCI getter is a socket round-trip to the SUMO process, and this
# collector runs once per simulation step. Reading speed and waiting time
# with per-vehicle getters costs several round-trips per active vehicle per
# step -- millions per full-length episode -- and the runner ends up bound
# on socket latency with the CPU mostly idle. Subscriptions replace that with
# one batched read per domain per step; SUMO pushes the requested variables
# for every subscribed object after each step.
_VEHICLE_VARS = (tc.VAR_SPEED, tc.VAR_ACCUMULATED_WAITING_TIME)
_LANE_VARS = (tc.LAST_STEP_VEHICLE_HALTING_NUMBER,)


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
        self._subscribed_vehicles: set[str] = set()
        self._lanes_subscribed = False

    def _read_vehicles(
        self, traci_conn, vehicle_ids: list[str]
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Return this step's speed and accumulated waiting time per vehicle.

        A subscription only starts delivering after the *next* simulation
        step, so a vehicle seen for the first time here has no batched
        result yet. Those are read directly for this one step, which keeps
        every vehicle's first observation in the aggregates exactly as the
        per-vehicle getters did -- the batching changes how values are
        fetched, never which values are counted.
        """
        subscribe = getattr(traci_conn.vehicle, "subscribe", None)
        batched: dict = {}
        if subscribe is not None:
            for vid in vehicle_ids:
                if vid not in self._subscribed_vehicles:
                    subscribe(vid, _VEHICLE_VARS)
                    self._subscribed_vehicles.add(vid)
            batched = traci_conn.vehicle.getAllSubscriptionResults() or {}

        speeds: dict[str, float] = {}
        waits: dict[str, float] = {}
        for vid in vehicle_ids:
            row = batched.get(vid)
            if row is not None and tc.VAR_SPEED in row:
                speeds[vid] = row[tc.VAR_SPEED]
                waits[vid] = row[tc.VAR_ACCUMULATED_WAITING_TIME]
            else:
                speeds[vid] = traci_conn.vehicle.getSpeed(vid)
                waits[vid] = traci_conn.vehicle.getAccumulatedWaitingTime(vid)
        return speeds, waits

    def _read_lane_queue(self, traci_conn) -> int:
        """Return this step's summed halting count over the monitored lanes."""
        subscribe = getattr(traci_conn.lane, "subscribe", None)
        batched: dict = {}
        if subscribe is not None:
            if not self._lanes_subscribed:
                for lane_id in self.monitored_lanes:
                    subscribe(lane_id, _LANE_VARS)
                self._lanes_subscribed = True
            batched = traci_conn.lane.getAllSubscriptionResults() or {}

        # Halting counts are integers and the recorded max_queue_length is
        # written as one; an int seed keeps the sum an int like sum() did.
        total = 0
        for lane_id in self.monitored_lanes:
            row = batched.get(lane_id)
            if row is not None and tc.LAST_STEP_VEHICLE_HALTING_NUMBER in row:
                total += row[tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
            else:
                total += traci_conn.lane.getLastStepHaltingNumber(lane_id)
        return total

    def record_step(self, traci_conn) -> None:
        """Read state for the step that was just advanced.

        Safe to call on steps with zero active vehicles: every aggregate
        below either skips the empty step (average_speed) or naturally
        contributes zero (queue sums, stopped-vehicle set).
        """
        self._stats.step_count += 1

        vehicle_ids: list[str] = list(traci_conn.vehicle.getIDList())
        speeds, waits = self._read_vehicles(traci_conn, vehicle_ids)

        if self.monitored_lanes is not None:
            step_queue = self._read_lane_queue(traci_conn)
        else:
            step_queue = sum(
                1
                for vid in vehicle_ids
                if speeds[vid] < self.stopped_speed_threshold
            )
        self._stats.queue_sum += step_queue
        self._stats.queue_max = max(self._stats.queue_max, step_queue)

        if vehicle_ids:
            # Summed in getIDList order, as before: float addition is not
            # associative, and the run must reproduce its recorded metrics.
            step_speed_sum = sum(speeds[vid] for vid in vehicle_ids)
            self._stats.speed_sum += step_speed_sum / len(vehicle_ids)
            self._stats.speed_sample_steps += 1

        for vid in vehicle_ids:
            if speeds[vid] < self.stopped_speed_threshold:
                self._stats.stopped_vehicle_ids.add(vid)
            # Overwrite with the latest cumulative value each step, so the
            # final value kept per vehicle is its own last observation
            # (on arrival, or at the end of the run) -- never summed
            # across steps, which would double count.
            self._stats.waiting_time_by_vehicle[vid] = waits[vid]

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

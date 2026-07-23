"""Typed data models for a single experiment episode's results.

An "episode" here means one complete run of a controller (fixed_time,
static_fixed_time, independent_q, coordinated_marl, ...) against one
traffic scenario and one random seed, for a fixed simulated duration
(including any cooldown period).

This module has ZERO SUMO/TraCI imports. It only describes the shape of a
result and validates it, so it stays usable from the metrics collector,
any controller runner, and the results writer / summary script without
pulling in a running simulation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


class MetricsValidationError(ValueError):
    """Raised when an EpisodeMetrics or PerAgentDiagnostics value is invalid."""


def _require_non_negative(name: str, value) -> None:
    if value is None:
        return
    if value < 0:
        raise MetricsValidationError(f"{name} must be >= 0, got {value!r}")


@dataclass(frozen=True)
class PerAgentDiagnostics:
    """Optional per-traffic-light diagnostics for one controlled agent.

    Shape is fixed here so every controller (fixed-time, RL, ...) reports
    the same fields whenever it does report per-agent diagnostics.
    """

    agent_id: str
    controlled_lane_count: int
    average_queue: float
    max_queue: float
    average_waiting_time: float
    observed_vehicle_count: int
    final_phase: str | None = None
    phase_change_count: int = 0

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise MetricsValidationError("agent_id must be a non-empty string")
        _require_non_negative("controlled_lane_count", self.controlled_lane_count)
        _require_non_negative("average_queue", self.average_queue)
        _require_non_negative("max_queue", self.max_queue)
        _require_non_negative("average_waiting_time", self.average_waiting_time)
        _require_non_negative("observed_vehicle_count", self.observed_vehicle_count)
        _require_non_negative("phase_change_count", self.phase_change_count)


@dataclass(frozen=True)
class EpisodeMetrics:
    """Result of a single (controller, scenario, seed) experiment run.

    Metric definitions (the collector implementation must match these
    exactly):

    - average_waiting_time: mean, over every vehicle that departed during
      the run, of that vehicle's *accumulated* waiting time (SUMO's own
      notion of time spent below the halting-speed threshold), read once
      per vehicle -- on arrival, or at the end of the run for vehicles
      still active. We read the latest cumulative value rather than
      summing per-step samples, so a vehicle is never double counted.
    - average_queue_length: mean, across simulation steps, of the number
      of halted vehicles on the monitored incoming lanes at that step.
    - max_queue_length: the single highest per-step queue value observed
      on the monitored lanes during the whole run.
    - average_speed: mean, across simulation steps, of the mean speed of
      all vehicles active in the network at that step. Steps with zero
      active vehicles are excluded from the average entirely (they do not
      count as a speed-0 sample).
    - throughput: number of vehicles that completed their route (arrived)
      during the run. Equal to arrived_vehicles by definition.
    - total_stopped_vehicles: count of *distinct* vehicles observed with
      speed below the stopped-speed threshold at least once during the
      run (not a per-step sum), so it never exceeds departed_vehicles.
    - total_reward: optional; only meaningful for RL controllers. Left as
      None (not 0) for controllers such as fixed-time / static-fixed-time
      that have no reward signal, so it's clearly distinguishable in the
      CSV from "a controller that earned zero reward".
    """

    controller: str
    scenario: str
    seed: int
    simulation_seconds: float

    average_waiting_time: float
    average_queue_length: float
    max_queue_length: float
    average_speed: float
    throughput: int
    departed_vehicles: int
    arrived_vehicles: int
    total_stopped_vehicles: int

    active_vehicles_remaining: int = 0
    teleport_count: int = 0
    total_reward: float | None = None

    per_agent: tuple[PerAgentDiagnostics, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.controller:
            raise MetricsValidationError("controller must be a non-empty string")
        if not self.scenario:
            raise MetricsValidationError("scenario must be a non-empty string")

        _require_non_negative("seed", self.seed)
        _require_non_negative("simulation_seconds", self.simulation_seconds)
        _require_non_negative("average_waiting_time", self.average_waiting_time)
        _require_non_negative("average_queue_length", self.average_queue_length)
        _require_non_negative("max_queue_length", self.max_queue_length)
        _require_non_negative("average_speed", self.average_speed)
        _require_non_negative("throughput", self.throughput)
        _require_non_negative("departed_vehicles", self.departed_vehicles)
        _require_non_negative("arrived_vehicles", self.arrived_vehicles)
        _require_non_negative("total_stopped_vehicles", self.total_stopped_vehicles)
        _require_non_negative(
            "active_vehicles_remaining", self.active_vehicles_remaining
        )
        _require_non_negative("teleport_count", self.teleport_count)

        if self.total_reward is not None and self.total_reward != self.total_reward:
            # NaN check (NaN is the only float that isn't equal to itself).
            raise MetricsValidationError("total_reward must not be NaN")

        if self.arrived_vehicles > self.departed_vehicles:
            raise MetricsValidationError(
                "arrived_vehicles cannot exceed departed_vehicles "
                f"({self.arrived_vehicles} > {self.departed_vehicles})"
            )
        if self.throughput > self.departed_vehicles:
            raise MetricsValidationError(
                "throughput cannot exceed departed_vehicles "
                f"({self.throughput} > {self.departed_vehicles})"
            )
        if self.total_stopped_vehicles > self.departed_vehicles:
            raise MetricsValidationError(
                "total_stopped_vehicles cannot exceed departed_vehicles "
                f"({self.total_stopped_vehicles} > {self.departed_vehicles})"
            )

    def as_flat_dict(self) -> dict:
        """Flatten to a single dict suitable for one CSV row.

        `per_agent` is deliberately excluded: the task spec has it printed
        to the console by the runner (not stored in the CSV), and it's
        variable-width across controllers, which doesn't fit a fixed
        experiments.csv schema.
        """
        data = asdict(self)
        data.pop("per_agent", None)
        return data

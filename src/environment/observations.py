"""Immutable traffic-signal observations and deterministic normalization."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


QUEUE_SPEED_THRESHOLD_MPS = 0.1
"""A vehicle is queued only when its speed is below 0.1 metres per second."""


def _validated_nonnegative_values(
    values: Iterable[float],
    metric_name: str,
) -> tuple[float, ...]:
    """Return finite non-negative values or raise a readable validation error."""
    normalized = tuple(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0.0 for value in normalized):
        raise ValueError(f"{metric_name} must contain only finite non-negative values.")
    return normalized


def count_queued_vehicles(
    speeds_mps: Iterable[float],
    threshold_mps: float = QUEUE_SPEED_THRESHOLD_MPS,
) -> int:
    """Count vehicles moving strictly below the queue-speed threshold.

    The project queue definition is speed < 0.1 metres per second.
    A vehicle moving at exactly 0.1 metres per second is not queued.
    """
    if not math.isfinite(threshold_mps) or threshold_mps <= 0.0:
        raise ValueError("Queue-speed threshold must be a finite positive value.")
    speeds = _validated_nonnegative_values(speeds_mps, "Vehicle speeds")
    return sum(speed < threshold_mps for speed in speeds)


def count_vehicles_on_lane(vehicle_ids: Iterable[str]) -> int:
    """Count vehicle IDs returned for one lane."""
    return len(tuple(vehicle_ids))


def calculate_mean_waiting_time(waiting_times_seconds: Iterable[float]) -> float:
    """Return the arithmetic mean waiting time, or 0.0 for an empty lane."""
    waiting_times = _validated_nonnegative_values(
        waiting_times_seconds,
        "Vehicle waiting times",
    )
    return sum(waiting_times) / len(waiting_times) if waiting_times else 0.0


def calculate_mean_speed(speeds_mps: Iterable[float]) -> float:
    """Return the arithmetic mean speed, or 0.0 for an empty lane."""
    speeds = _validated_nonnegative_values(speeds_mps, "Vehicle speeds")
    return sum(speeds) / len(speeds) if speeds else 0.0


def validate_lane_metric_tuple_sizes(
    incoming_lane_ids: Sequence[str],
    queue_lengths: Sequence[int],
    vehicle_counts: Sequence[int],
    mean_waiting_times: Sequence[float],
    mean_speeds: Sequence[float],
) -> None:
    """Require every lane-based metric tuple to match the lane-ID tuple."""
    expected_size = len(incoming_lane_ids)
    actual_sizes = {
        "queue_lengths": len(queue_lengths),
        "vehicle_counts": len(vehicle_counts),
        "mean_waiting_times": len(mean_waiting_times),
        "mean_speeds": len(mean_speeds),
    }
    mismatches = {
        name: size for name, size in actual_sizes.items() if size != expected_size
    }
    if mismatches:
        details = ", ".join(
            f"{name}={size}" for name, size in sorted(mismatches.items())
        )
        raise ValueError(
            "Lane-based observation tuples must have the same length as "
            f"incoming_lane_ids={expected_size}; got {details}."
        )


def _validate_positive_cap(value: float, field_name: str) -> None:
    """Require one normalization cap to be finite and positive."""
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{field_name} must be a finite positive value.")


@dataclass(frozen=True, slots=True)
class ObservationNormalizationConfig:
    """Immutable caps used to create stable numeric observation features.

    ``speed_cap`` is the documented 50 km/h fallback, expressed as 13.89 m/s.
    Callers may provide one positive ``lane_speed_caps`` entry per observed lane
    when the running SUMO network's lane speed limits should be used instead.
    """

    queue_cap: float = 20.0
    vehicle_count_cap: float = 30.0
    waiting_time_cap: float = 300.0
    speed_cap: float = 13.89
    phase_elapsed_cap: float = 60.0
    lane_speed_caps: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        """Validate every configured cap."""
        for field_name in (
            "queue_cap",
            "vehicle_count_cap",
            "waiting_time_cap",
            "speed_cap",
            "phase_elapsed_cap",
        ):
            _validate_positive_cap(float(getattr(self, field_name)), field_name)
        if self.lane_speed_caps is not None:
            for cap in self.lane_speed_caps:
                _validate_positive_cap(float(cap), "lane_speed_caps entry")


def _clip_ratio(value: float, cap: float) -> float:
    """Normalize a non-negative value to [0.0, 1.0] using clipping."""
    return min(max(float(value) / float(cap), 0.0), 1.0)


@dataclass(frozen=True, slots=True)
class TrafficObservation:
    """Observation of one selected traffic-light agent at one simulation step."""

    agent_id: str
    traffic_light_id: str
    simulation_time: float
    incoming_lane_ids: tuple[str, ...]
    queue_lengths: tuple[int, ...]
    vehicle_counts: tuple[int, ...]
    mean_waiting_times: tuple[float, ...]
    mean_speeds: tuple[float, ...]
    current_phase_index: int
    current_phase_state: str
    current_phase_elapsed_seconds: float
    is_green_phase: bool
    is_transition_phase: bool

    def __post_init__(self) -> None:
        """Reject malformed or physically invalid observation values."""
        if not self.agent_id.strip():
            raise ValueError("agent_id must not be empty.")
        if not self.traffic_light_id.strip():
            raise ValueError("traffic_light_id must not be empty.")
        if any(not lane_id.strip() for lane_id in self.incoming_lane_ids):
            raise ValueError("incoming_lane_ids must not contain empty lane IDs.")
        validate_lane_metric_tuple_sizes(
            self.incoming_lane_ids,
            self.queue_lengths,
            self.vehicle_counts,
            self.mean_waiting_times,
            self.mean_speeds,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.queue_lengths
        ):
            raise ValueError("queue_lengths must contain non-negative integers.")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.vehicle_counts
        ):
            raise ValueError("vehicle_counts must contain non-negative integers.")
        _validated_nonnegative_values(
            self.mean_waiting_times,
            "mean_waiting_times",
        )
        _validated_nonnegative_values(self.mean_speeds, "mean_speeds")
        if (
            not math.isfinite(self.simulation_time)
            or self.simulation_time < 0.0
        ):
            raise ValueError("simulation_time must be finite and non-negative.")
        if (
            not isinstance(self.current_phase_index, int)
            or isinstance(self.current_phase_index, bool)
            or self.current_phase_index < 0
        ):
            raise ValueError("current_phase_index must be a non-negative integer.")
        if (
            not math.isfinite(self.current_phase_elapsed_seconds)
            or self.current_phase_elapsed_seconds < 0.0
        ):
            raise ValueError(
                "current_phase_elapsed_seconds must be finite and non-negative."
            )

    def normalized_features(
        self,
        phase_count: int,
        config: ObservationNormalizationConfig | None = None,
    ) -> tuple[float, ...]:
        """Return deterministic lane-major features followed by phase features.

        Each lane contributes queue length, vehicle count, mean waiting time,
        and mean speed in ``incoming_lane_ids`` order.
        The lane features are followed by normalized phase elapsed time and a
        one-hot vector of length ``phase_count`` for the current phase index.
        """
        if (
            not isinstance(phase_count, int)
            or isinstance(phase_count, bool)
            or phase_count <= 0
        ):
            raise ValueError("phase_count must be a positive integer.")
        if self.current_phase_index >= phase_count:
            raise ValueError(
                f"Current phase index {self.current_phase_index} is outside "
                f"phase_count={phase_count}."
            )

        normalization = config or ObservationNormalizationConfig()
        if normalization.lane_speed_caps is None:
            speed_caps = (normalization.speed_cap,) * len(self.incoming_lane_ids)
        else:
            speed_caps = normalization.lane_speed_caps
            if len(speed_caps) != len(self.incoming_lane_ids):
                raise ValueError(
                    "lane_speed_caps must contain exactly one cap per incoming lane."
                )

        features: list[float] = []
        for queue, count, waiting_time, speed, speed_cap in zip(
            self.queue_lengths,
            self.vehicle_counts,
            self.mean_waiting_times,
            self.mean_speeds,
            speed_caps,
            strict=True,
        ):
            features.extend(
                (
                    _clip_ratio(queue, normalization.queue_cap),
                    _clip_ratio(count, normalization.vehicle_count_cap),
                    _clip_ratio(waiting_time, normalization.waiting_time_cap),
                    _clip_ratio(speed, speed_cap),
                )
            )

        features.append(
            _clip_ratio(
                self.current_phase_elapsed_seconds,
                normalization.phase_elapsed_cap,
            )
        )
        features.extend(
            1.0 if index == self.current_phase_index else 0.0
            for index in range(phase_count)
        )
        return tuple(features)


__all__ = [
    "QUEUE_SPEED_THRESHOLD_MPS",
    "ObservationNormalizationConfig",
    "TrafficObservation",
    "calculate_mean_speed",
    "calculate_mean_waiting_time",
    "count_queued_vehicles",
    "count_vehicles_on_lane",
    "validate_lane_metric_tuple_sizes",
]

"""Deterministic discrete state encoding for tabular traffic-light agents."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from src.environment.observations import TrafficObservation


def _validated_integer_thresholds(
    values: Sequence[int],
    field_name: str,
) -> tuple[int, ...]:
    """Return strictly increasing positive integer thresholds."""
    thresholds = tuple(values)
    if not thresholds:
        raise ValueError(f"{field_name} must contain at least one threshold.")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in thresholds
    ):
        raise ValueError(f"{field_name} must contain positive integers.")
    if any(
        current >= following
        for current, following in zip(thresholds, thresholds[1:])
    ):
        raise ValueError(f"{field_name} must be strictly increasing.")
    return thresholds


def _validated_float_thresholds(
    values: Sequence[float],
    field_name: str,
) -> tuple[float, ...]:
    """Return strictly increasing positive finite thresholds."""
    thresholds = tuple(float(value) for value in values)
    if not thresholds:
        raise ValueError(f"{field_name} must contain at least one threshold.")
    if any(
        not math.isfinite(value) or value <= 0.0
        for value in thresholds
    ):
        raise ValueError(
            f"{field_name} must contain finite positive values."
        )
    if any(
        current >= following
        for current, following in zip(thresholds, thresholds[1:])
    ):
        raise ValueError(f"{field_name} must be strictly increasing.")
    return thresholds


@dataclass(frozen=True, slots=True)
class StateEncoderConfig:
    """Immutable lower boundaries for each discrete traffic-state bucket."""

    total_queue_thresholds: tuple[int, ...] = (1, 4, 8, 16)
    maximum_lane_queue_thresholds: tuple[int, ...] = (1, 3, 6, 11)
    mean_waiting_time_thresholds_seconds: tuple[float, ...] = (
        5.0,
        15.0,
        30.0,
        60.0,
    )
    phase_elapsed_thresholds_seconds: tuple[float, ...] = (
        10.0,
        20.0,
        40.0,
        60.0,
    )

    def __post_init__(self) -> None:
        """Validate and normalize all threshold sequences."""
        object.__setattr__(
            self,
            "total_queue_thresholds",
            _validated_integer_thresholds(
                self.total_queue_thresholds,
                "total_queue_thresholds",
            ),
        )
        object.__setattr__(
            self,
            "maximum_lane_queue_thresholds",
            _validated_integer_thresholds(
                self.maximum_lane_queue_thresholds,
                "maximum_lane_queue_thresholds",
            ),
        )
        object.__setattr__(
            self,
            "mean_waiting_time_thresholds_seconds",
            _validated_float_thresholds(
                self.mean_waiting_time_thresholds_seconds,
                "mean_waiting_time_thresholds_seconds",
            ),
        )
        object.__setattr__(
            self,
            "phase_elapsed_thresholds_seconds",
            _validated_float_thresholds(
                self.phase_elapsed_thresholds_seconds,
                "phase_elapsed_thresholds_seconds",
            ),
        )


@dataclass(frozen=True, slots=True)
class DiscreteTrafficState:
    """Compact hashable traffic state used as a tabular Q-learning key."""

    total_queue_bucket: int
    maximum_lane_queue_bucket: int
    mean_lane_waiting_time_bucket: int
    green_phase_position: int
    phase_elapsed_bucket: int
    is_transition_phase: bool


class TrafficStateEncoder:
    """Convert TrafficObservation values into deterministic discrete states.

    When ``green_phase_indices`` is supplied from ``TrafficSignal``, a green
    phase is represented by its position in that sequence.
    Without that controller metadata, the encoder uses the current phase index.
    Transition phases use position ``-1`` and remain explicitly identifiable
    through ``is_transition_phase``.
    """

    def __init__(
        self,
        config: StateEncoderConfig | None = None,
        *,
        green_phase_indices: Sequence[int] | None = None,
    ) -> None:
        """Store validated bucket settings and optional green-phase metadata."""
        self.config = config or StateEncoderConfig()
        if not isinstance(self.config, StateEncoderConfig):
            raise TypeError("config must be a StateEncoderConfig.")
        self._green_phase_indices = self._validate_green_phase_indices(
            green_phase_indices
        )

    @staticmethod
    def _validate_green_phase_indices(
        green_phase_indices: Sequence[int] | None,
    ) -> tuple[int, ...] | None:
        """Validate optional controller green phases while preserving order."""
        if green_phase_indices is None:
            return None
        if isinstance(green_phase_indices, str):
            raise ValueError("green_phase_indices must be a sequence of integers.")
        indices = tuple(green_phase_indices)
        if not indices:
            raise ValueError("green_phase_indices must not be empty.")
        if any(
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            for index in indices
        ):
            raise ValueError(
                "green_phase_indices must contain non-negative integers."
            )
        if len(indices) != len(set(indices)):
            raise ValueError("green_phase_indices must not contain duplicates.")
        return indices

    @property
    def green_phase_indices(self) -> tuple[int, ...] | None:
        """Return the optional known green-phase sequence."""
        return self._green_phase_indices

    @staticmethod
    def _bucket(value: float, thresholds: Sequence[float]) -> int:
        """Map a non-negative value using inclusive lower boundaries."""
        return bisect_right(thresholds, value)

    def _phase_position(self, observation: TrafficObservation) -> int:
        """Return a transition sentinel, green position, or raw phase index."""
        if observation.is_transition_phase:
            return -1
        if (
            self._green_phase_indices is not None
            and observation.is_green_phase
        ):
            try:
                return self._green_phase_indices.index(
                    observation.current_phase_index
                )
            except ValueError as error:
                raise ValueError(
                    "The observation's green phase index is absent from the "
                    "configured green_phase_indices."
                ) from error
        return observation.current_phase_index

    def encode(self, observation: TrafficObservation) -> DiscreteTrafficState:
        """Return a compact state without identifiers or absolute time."""
        if not isinstance(observation, TrafficObservation):
            raise TypeError("observation must be a TrafficObservation.")

        total_queue = sum(observation.queue_lengths)
        maximum_lane_queue = max(observation.queue_lengths, default=0)
        mean_lane_waiting_time = (
            sum(observation.mean_waiting_times)
            / len(observation.mean_waiting_times)
            if observation.mean_waiting_times
            else 0.0
        )
        return DiscreteTrafficState(
            total_queue_bucket=self._bucket(
                total_queue,
                self.config.total_queue_thresholds,
            ),
            maximum_lane_queue_bucket=self._bucket(
                maximum_lane_queue,
                self.config.maximum_lane_queue_thresholds,
            ),
            mean_lane_waiting_time_bucket=self._bucket(
                mean_lane_waiting_time,
                self.config.mean_waiting_time_thresholds_seconds,
            ),
            green_phase_position=self._phase_position(observation),
            phase_elapsed_bucket=self._bucket(
                observation.current_phase_elapsed_seconds,
                self.config.phase_elapsed_thresholds_seconds,
            ),
            is_transition_phase=observation.is_transition_phase,
        )


__all__ = [
    "DiscreteTrafficState",
    "StateEncoderConfig",
    "TrafficStateEncoder",
]

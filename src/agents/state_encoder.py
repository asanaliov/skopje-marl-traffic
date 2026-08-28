"""Deterministic discrete state encoding for tabular traffic-light agents."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
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
    neighbor_total_queue_threshold: int = 4
    """Total queued vehicles at which a neighbor counts as congested.

    Neighbor status is deliberately a single two-valued flag instead of a
    full bucket. A neighbor observed with four or more queued vehicles --
    the second ``total_queue_thresholds`` boundary -- is reported as ``1``,
    everything below it as ``0``. Every extra bit here multiplies the
    tabular Q-table, so the shared signal stays as coarse as it can be
    while still announcing an incoming wave.
    """

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
        if (
            not isinstance(self.neighbor_total_queue_threshold, int)
            or isinstance(self.neighbor_total_queue_threshold, bool)
            or self.neighbor_total_queue_threshold <= 0
        ):
            raise ValueError(
                "neighbor_total_queue_threshold must be a positive integer."
            )


@dataclass(frozen=True, slots=True)
class DiscreteTrafficState:
    """Compact hashable traffic state used as a tabular Q-learning key.

    ``neighbor_queue_flags`` carries the optional spatial part of the state:
    one ``0``/``1`` congestion flag per configured neighbor, in the encoder's
    ``neighbor_ids`` order. It stays empty for purely local agents, so a
    local state encoded before spatial observations existed still equals the
    one encoded now.
    """

    total_queue_bucket: int
    maximum_lane_queue_bucket: int
    mean_lane_waiting_time_bucket: int
    green_phase_position: int
    phase_elapsed_bucket: int
    is_transition_phase: bool
    neighbor_queue_flags: tuple[int, ...] = ()


class TrafficStateEncoder:
    """Convert TrafficObservation values into deterministic discrete states.

    When ``green_phase_indices`` is supplied from ``TrafficSignal``, a green
    phase is represented by its position in that sequence.
    Without that controller metadata, the encoder uses the current phase index.
    Transition phases use position ``-1`` and remain explicitly identifiable
    through ``is_transition_phase``.

    Supplying ``neighbor_ids`` turns the encoder into a *spatial* one: every
    encoded state then also carries one congestion flag per named neighbor,
    letting an agent see an incoming wave before it reaches its own stop
    line. Such an encoder belongs to exactly one agent, because
    ``neighbor_ids`` is that agent's own adjacency.
    """

    def __init__(
        self,
        config: StateEncoderConfig | None = None,
        *,
        green_phase_indices: Sequence[int] | None = None,
        neighbor_ids: Sequence[str] | None = None,
    ) -> None:
        """Store validated bucket settings and optional agent metadata."""
        self.config = config or StateEncoderConfig()
        if not isinstance(self.config, StateEncoderConfig):
            raise TypeError("config must be a StateEncoderConfig.")
        self._green_phase_indices = self._validate_green_phase_indices(
            green_phase_indices
        )
        self._neighbor_ids = self._validate_neighbor_ids(neighbor_ids)

    @staticmethod
    def _validate_neighbor_ids(
        neighbor_ids: Sequence[str] | None,
    ) -> tuple[str, ...] | None:
        """Validate the observed neighbors while preserving their order."""
        if neighbor_ids is None:
            return None
        if isinstance(neighbor_ids, str):
            raise ValueError("neighbor_ids must be a sequence of agent IDs.")
        identifiers = tuple(neighbor_ids)
        if not identifiers:
            raise ValueError(
                "neighbor_ids must not be empty. Use None for an agent that "
                "observes only its own junction."
            )
        if any(
            not isinstance(neighbor_id, str) or not neighbor_id.strip()
            for neighbor_id in identifiers
        ):
            raise ValueError("neighbor_ids must contain non-empty strings.")
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("neighbor_ids must not contain duplicates.")
        return identifiers

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

    @property
    def neighbor_ids(self) -> tuple[str, ...] | None:
        """Return the observed neighbors, or None for a local-only encoder."""
        return self._neighbor_ids

    def neighbor_queue_flag(self, observation: TrafficObservation) -> int:
        """Return 1 when a neighbor's total queue is congested, otherwise 0."""
        if not isinstance(observation, TrafficObservation):
            raise TypeError("observation must be a TrafficObservation.")
        total_queue = sum(observation.queue_lengths)
        return int(total_queue >= self.config.neighbor_total_queue_threshold)

    def _neighbor_queue_flags(
        self,
        neighbor_observations: Mapping[str, TrafficObservation] | None,
    ) -> tuple[int, ...]:
        """Return one flag per configured neighbor, in ``neighbor_ids`` order."""
        if self._neighbor_ids is None:
            if neighbor_observations:
                raise ValueError(
                    "neighbor_observations were supplied to an encoder that "
                    "was not configured with neighbor_ids."
                )
            return ()
        if neighbor_observations is None:
            raise ValueError(
                "This encoder observes neighbors "
                f"({', '.join(self._neighbor_ids)}) and requires "
                "neighbor_observations."
            )
        if not isinstance(neighbor_observations, Mapping):
            raise TypeError("neighbor_observations must be a mapping.")
        missing = [
            neighbor_id
            for neighbor_id in self._neighbor_ids
            if neighbor_id not in neighbor_observations
        ]
        if missing:
            raise ValueError(
                "neighbor_observations is missing configured neighbors: "
                f"{', '.join(missing)}."
            )
        return tuple(
            self.neighbor_queue_flag(neighbor_observations[neighbor_id])
            for neighbor_id in self._neighbor_ids
        )

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

    def encode(
        self,
        observation: TrafficObservation,
        neighbor_observations: Mapping[str, TrafficObservation] | None = None,
    ) -> DiscreteTrafficState:
        """Return a compact state without identifiers or absolute time.

        ``neighbor_observations`` is required exactly when the encoder was
        built with ``neighbor_ids``, and must contain every one of them.
        A silently dropped neighbor would change what a Q-table key means
        mid-run, so a missing one is an error rather than a zero flag.
        """
        if not isinstance(observation, TrafficObservation):
            raise TypeError("observation must be a TrafficObservation.")
        neighbor_queue_flags = self._neighbor_queue_flags(neighbor_observations)

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
            neighbor_queue_flags=neighbor_queue_flags,
        )


__all__ = [
    "DiscreteTrafficState",
    "StateEncoderConfig",
    "TrafficStateEncoder",
]

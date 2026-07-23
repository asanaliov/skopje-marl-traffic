"""Safe high-level traffic-signal actions and phase analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, IntEnum


class TrafficAction(IntEnum):
    """Actions available to a future traffic-signal learning agent."""

    KEEP = 0
    NEXT_GREEN = 1


@dataclass(frozen=True, slots=True)
class ActionPolicyConfig:
    """Immutable timing rules for safe action application."""

    minimum_green_seconds: float = 10.0
    maximum_green_seconds: float = 60.0
    decision_interval_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Reject unusable timing settings."""
        values = (
            self.minimum_green_seconds,
            self.maximum_green_seconds,
            self.decision_interval_seconds,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("Action-policy timing values must be finite.")
        if self.minimum_green_seconds <= 0.0:
            raise ValueError("minimum_green_seconds must be greater than zero.")
        if self.maximum_green_seconds < self.minimum_green_seconds:
            raise ValueError(
                "maximum_green_seconds must be at least minimum_green_seconds."
            )
        if self.decision_interval_seconds <= 0.0:
            raise ValueError("decision_interval_seconds must be greater than zero.")
        if self.decision_interval_seconds > self.maximum_green_seconds:
            raise ValueError(
                "decision_interval_seconds must not exceed maximum_green_seconds."
            )


class ActionStatus(Enum):
    """Outcome of one requested traffic-signal action."""

    APPLIED = "applied"
    KEPT = "kept"
    REJECTED_MINIMUM_GREEN = "rejected_minimum_green"
    FORCED_MAXIMUM_GREEN = "forced_maximum_green"
    TRANSITION_IN_PROGRESS = "transition_in_progress"
    INVALID_ACTION = "invalid_action"


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Immutable description of an action request and its outcome."""

    requested_action: object
    status: ActionStatus
    previous_phase_index: int
    resulting_phase_index: int
    phase_changed: bool
    message: str


def is_green_phase_state(state: str) -> bool:
    """Return whether a state contains green and contains no yellow."""
    return any(signal in "Gg" for signal in state) and not any(
        signal in "Yy" for signal in state
    )


def is_transition_phase_state(state: str) -> bool:
    """Return whether a state contains yellow or is entirely red."""
    if any(signal in "Yy" for signal in state):
        return True
    return bool(state) and all(signal in "Rr" for signal in state)


def find_green_phase_indices(phase_states: tuple[str, ...]) -> tuple[int, ...]:
    """Return green phase indices in original program order."""
    return tuple(
        index
        for index, state in enumerate(phase_states)
        if is_green_phase_state(state)
    )


def find_immediate_next_phase_index(current_index: int, phase_count: int) -> int:
    """Return the next original program index using cyclic ordering."""
    if phase_count <= 0:
        raise ValueError("phase_count must be greater than zero.")
    if current_index < 0 or current_index >= phase_count:
        raise ValueError(
            f"current_index={current_index} is outside phase_count={phase_count}."
        )
    return (current_index + 1) % phase_count


def find_next_green_phase_index(
    current_index: int,
    phase_states: tuple[str, ...],
) -> int:
    """Return the next green index while scanning cyclic program order."""
    phase_count = len(phase_states)
    if phase_count == 0:
        raise ValueError("phase_states must not be empty.")
    if current_index < 0 or current_index >= phase_count:
        raise ValueError(
            f"current_index={current_index} is outside phase_count={phase_count}."
        )
    for offset in range(1, phase_count + 1):
        candidate = (current_index + offset) % phase_count
        if is_green_phase_state(phase_states[candidate]):
            return candidate
    raise ValueError("phase_states does not contain a green phase.")


__all__ = [
    "ActionPolicyConfig",
    "ActionResult",
    "ActionStatus",
    "TrafficAction",
    "find_green_phase_indices",
    "find_immediate_next_phase_index",
    "find_next_green_phase_index",
    "is_green_phase_state",
    "is_transition_phase_state",
]

"""Pure traffic-signal reward calculations for future learning agents."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from src.environment.observations import TrafficObservation


@dataclass(frozen=True, slots=True)
class RewardWeights:
    """Non-negative weights for the local traffic-signal reward."""

    queue_weight: float = 1.0
    waiting_weight: float = 0.1
    switch_penalty_weight: float = 0.0

    def __post_init__(self) -> None:
        """Reject negative or non-finite reward weights."""
        for field_name in (
            "queue_weight",
            "waiting_weight",
            "switch_penalty_weight",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"{field_name} must be a finite non-negative value."
                )


@dataclass(frozen=True, slots=True)
class RewardBreakdown:
    """Negative reward components and their deterministic total."""

    queue_component: float
    waiting_component: float
    switch_component: float
    total_reward: float


def calculate_local_reward(
    observation: TrafficObservation,
    phase_switched: bool = False,
    weights: RewardWeights | None = None,
) -> RewardBreakdown:
    """Calculate queue, lane-mean waiting, and optional switch penalties.

    Waiting time is aggregated as the sum of lane mean waiting times.
    This keeps every lane represented once regardless of its current vehicle
    count and matches the lane-level observation supplied to the agent.
    """
    reward_weights = weights or RewardWeights()
    queue_component = -reward_weights.queue_weight * sum(observation.queue_lengths)
    waiting_component = -reward_weights.waiting_weight * sum(
        observation.mean_waiting_times
    )
    switch_component = -reward_weights.switch_penalty_weight * int(phase_switched)
    total_reward = queue_component + waiting_component + switch_component
    return RewardBreakdown(
        queue_component=queue_component,
        waiting_component=waiting_component,
        switch_component=switch_component,
        total_reward=total_reward,
    )


def neighbor_aware_reward(
    local_reward: float,
    neighbor_rewards: Iterable[float],
    local_weight: float = 0.7,
    neighbor_weight: float = 0.3,
) -> float:
    """Combine one local reward with the mean of available neighbor rewards."""
    weights = (float(local_weight), float(neighbor_weight))
    if any(not math.isfinite(weight) or weight < 0.0 for weight in weights):
        raise ValueError(
            "Neighbor-aware reward weights must be finite and non-negative."
        )
    if not math.isclose(
        local_weight + neighbor_weight,
        1.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ValueError("Neighbor-aware reward weights must sum to 1.0.")
    if not math.isfinite(local_reward):
        raise ValueError("local_reward must be finite.")

    neighbors = tuple(float(reward) for reward in neighbor_rewards)
    if any(not math.isfinite(reward) for reward in neighbors):
        raise ValueError("neighbor_rewards must contain only finite values.")
    if not neighbors:
        return float(local_reward)

    mean_neighbor_reward = sum(neighbors) / len(neighbors)
    return local_weight * local_reward + neighbor_weight * mean_neighbor_reward


def global_corridor_reward(local_rewards: Iterable[float]) -> float:
    """Return the arithmetic mean of all supplied local agent rewards."""
    rewards = tuple(float(reward) for reward in local_rewards)
    if not rewards:
        raise ValueError("At least one local reward is required.")
    if any(not math.isfinite(reward) for reward in rewards):
        raise ValueError("local_rewards must contain only finite values.")
    return sum(rewards) / len(rewards)


__all__ = [
    "RewardBreakdown",
    "RewardWeights",
    "calculate_local_reward",
    "global_corridor_reward",
    "neighbor_aware_reward",
]

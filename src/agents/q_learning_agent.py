"""Independent tabular Q-learning over safe traffic-light actions."""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.environment.actions import TrafficAction


_ACTIONS = (TrafficAction.KEEP, TrafficAction.NEXT_GREEN)


def _validated_probability(
    value: float,
    field_name: str,
    *,
    positive: bool = False,
) -> float:
    """Return one finite learning parameter in its valid unit interval."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a numeric value.")
    numeric_value = float(value)
    minimum_is_valid = numeric_value > 0.0 if positive else numeric_value >= 0.0
    if (
        not math.isfinite(numeric_value)
        or not minimum_is_valid
        or numeric_value > 1.0
    ):
        interval = "(0.0, 1.0]" if positive else "[0.0, 1.0]"
        raise ValueError(f"{field_name} must be in {interval}.")
    return numeric_value


@dataclass(frozen=True, slots=True)
class QLearningConfig:
    """Immutable hyperparameters for one independent tabular learner."""

    alpha: float = 0.1
    gamma: float = 0.95
    epsilon: float = 1.0
    minimum_epsilon: float = 0.05
    epsilon_decay: float = 0.995
    random_seed: int = 42

    def __post_init__(self) -> None:
        """Validate and normalize all learning parameters."""
        alpha = _validated_probability(self.alpha, "alpha", positive=True)
        gamma = _validated_probability(self.gamma, "gamma")
        epsilon = _validated_probability(self.epsilon, "epsilon")
        minimum_epsilon = _validated_probability(
            self.minimum_epsilon,
            "minimum_epsilon",
        )
        epsilon_decay = _validated_probability(
            self.epsilon_decay,
            "epsilon_decay",
        )
        if minimum_epsilon > epsilon:
            raise ValueError(
                "minimum_epsilon must not exceed the initial epsilon."
            )
        if (
            not isinstance(self.random_seed, int)
            or isinstance(self.random_seed, bool)
            or self.random_seed < 0
        ):
            raise ValueError("random_seed must be a non-negative integer.")

        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "gamma", gamma)
        object.__setattr__(self, "epsilon", epsilon)
        object.__setattr__(self, "minimum_epsilon", minimum_epsilon)
        object.__setattr__(self, "epsilon_decay", epsilon_decay)


class QLearningAgent:
    """Independent epsilon-greedy tabular Q-learning agent."""

    def __init__(self, config: QLearningConfig | None = None) -> None:
        """Create an empty Q-table and a reproducible random generator."""
        self.config = config or QLearningConfig()
        if not isinstance(self.config, QLearningConfig):
            raise TypeError("config must be a QLearningConfig.")
        self._epsilon = self.config.epsilon
        self._random = random.Random(self.config.random_seed)
        self._q_table: dict[tuple[Hashable, TrafficAction], float] = {}
        self._training_episode_count = 0

    @property
    def actions(self) -> tuple[TrafficAction, TrafficAction]:
        """Return the only actions this learner can select."""
        return _ACTIONS

    @property
    def epsilon(self) -> float:
        """Return the current exploration probability."""
        return self._epsilon

    @property
    def training_episode_count(self) -> int:
        """Return the number of completed training episodes."""
        return self._training_episode_count

    @property
    def q_table(
        self,
    ) -> Mapping[tuple[Hashable, TrafficAction], float]:
        """Return a read-only snapshot of all learned Q-values."""
        return MappingProxyType(dict(self._q_table))

    @staticmethod
    def _validate_state(state: Hashable | None, field_name: str) -> Hashable:
        """Require a non-null hashable state key."""
        if state is None:
            raise ValueError(f"{field_name} must not be None.")
        try:
            hash(state)
        except TypeError as error:
            raise TypeError(f"{field_name} must be hashable.") from error
        return state

    @staticmethod
    def _validate_action(action: TrafficAction) -> TrafficAction:
        """Require one of the two supported TrafficAction values."""
        if not isinstance(action, TrafficAction) or action not in _ACTIONS:
            raise ValueError(
                "action must be TrafficAction.KEEP or "
                "TrafficAction.NEXT_GREEN."
            )
        return action

    def q_value(self, state: Hashable, action: TrafficAction) -> float:
        """Return one learned value, defaulting to zero without insertion."""
        state_key = self._validate_state(state, "state")
        valid_action = self._validate_action(action)
        return self._q_table.get((state_key, valid_action), 0.0)

    def q_values(self, state: Hashable) -> Mapping[TrafficAction, float]:
        """Return both action values for one state as a read-only mapping."""
        state_key = self._validate_state(state, "state")
        return MappingProxyType(
            {
                action: self._q_table.get((state_key, action), 0.0)
                for action in _ACTIONS
            }
        )

    def select_action(
        self,
        state: Hashable,
        *,
        training: bool = True,
    ) -> TrafficAction:
        """Select an action using exploration only when training is enabled."""
        state_key = self._validate_state(state, "state")
        if not isinstance(training, bool):
            raise ValueError("training must be a boolean.")
        if (
            training
            and self._epsilon > 0.0
            and self._random.random() < self._epsilon
        ):
            return self._random.choice(_ACTIONS)

        return max(
            _ACTIONS,
            key=lambda action: self._q_table.get((state_key, action), 0.0),
        )

    def update(
        self,
        state: Hashable,
        action: TrafficAction,
        reward: float,
        next_state: Hashable | None,
        *,
        terminated: bool = False,
    ) -> float:
        """Apply one standard Q-learning update and return the new value."""
        state_key = self._validate_state(state, "state")
        valid_action = self._validate_action(action)
        if isinstance(reward, bool):
            raise ValueError("reward must be a finite numeric value.")
        numeric_reward = float(reward)
        if not math.isfinite(numeric_reward):
            raise ValueError("reward must be a finite numeric value.")
        if not isinstance(terminated, bool):
            raise ValueError("terminated must be a boolean.")

        current_value = self._q_table.get((state_key, valid_action), 0.0)
        target = numeric_reward
        if not terminated:
            next_state_key = self._validate_state(next_state, "next_state")
            target += self.config.gamma * max(
                self._q_table.get((next_state_key, next_action), 0.0)
                for next_action in _ACTIONS
            )
        updated_value = current_value + self.config.alpha * (
            target - current_value
        )
        self._q_table[(state_key, valid_action)] = updated_value
        return updated_value

    def end_episode(self) -> float:
        """Decay epsilon once and return the bounded new value."""
        self._training_episode_count += 1
        self._epsilon = max(
            self.config.minimum_epsilon,
            self._epsilon * self.config.epsilon_decay,
        )
        return self._epsilon

    def load_q_table(
        self,
        entries: Mapping[tuple[Hashable, TrafficAction], float],
        *,
        epsilon: float | None = None,
        training_episode_count: int | None = None,
    ) -> None:
        """Replace learned values and optional episode metadata."""
        if not isinstance(entries, Mapping):
            raise TypeError("entries must be a mapping.")
        loaded: dict[tuple[Hashable, TrafficAction], float] = {}
        for (state, action), value in entries.items():
            state_key = self._validate_state(state, "state")
            valid_action = self._validate_action(action)
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError("Q-values must be finite numeric values.")
            loaded[(state_key, valid_action)] = float(value)
        if epsilon is not None:
            epsilon_value = _validated_probability(epsilon, "epsilon")
            self._epsilon = epsilon_value
        if training_episode_count is not None:
            if (
                not isinstance(training_episode_count, int)
                or isinstance(training_episode_count, bool)
                or training_episode_count < 0
            ):
                raise ValueError("training_episode_count must be non-negative.")
            self._training_episode_count = training_episode_count
        self._q_table = loaded

    def clear_q_table(self) -> None:
        """Remove all learned values without changing epsilon or RNG state."""
        self._q_table.clear()


__all__ = ["QLearningAgent", "QLearningConfig"]

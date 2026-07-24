"""Unit tests for the independent tabular Q-learning agent."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.agents.q_learning_agent import QLearningAgent, QLearningConfig
from src.environment.actions import TrafficAction


STATE = ("state", 1)
NEXT_STATE = ("next", 2)


def test_unseen_q_values_are_zero_without_table_insertion() -> None:
    """Inspection of an unseen state does not mutate the table."""
    agent = QLearningAgent()

    assert agent.q_value(STATE, TrafficAction.KEEP) == 0.0
    assert agent.q_value(STATE, TrafficAction.NEXT_GREEN) == 0.0
    assert agent.q_values(STATE) == {
        TrafficAction.KEEP: 0.0,
        TrafficAction.NEXT_GREEN: 0.0,
    }
    assert agent.q_table == {}


def test_evaluation_selects_highest_value_without_exploration() -> None:
    """training=False ignores epsilon and selects the learned maximum."""
    agent = QLearningAgent(
        QLearningConfig(alpha=1.0, epsilon=1.0, minimum_epsilon=0.0)
    )
    agent.update(
        STATE,
        TrafficAction.KEEP,
        1.0,
        None,
        terminated=True,
    )
    agent.update(
        STATE,
        TrafficAction.NEXT_GREEN,
        3.0,
        None,
        terminated=True,
    )

    assert (
        agent.select_action(STATE, training=False)
        is TrafficAction.NEXT_GREEN
    )


def test_evaluation_tie_breaks_deterministically_to_keep() -> None:
    """Action declaration order makes KEEP the stable tie choice."""
    agent = QLearningAgent()

    choices = {
        agent.select_action(STATE, training=False) for _ in range(20)
    }

    assert choices == {TrafficAction.KEEP}


def test_full_exploration_uses_reproducible_seeded_randomness() -> None:
    """Equal seeds produce equal exploratory action sequences."""
    config = QLearningConfig(
        epsilon=1.0,
        minimum_epsilon=0.0,
        random_seed=17,
    )
    first_agent = QLearningAgent(config)
    second_agent = QLearningAgent(config)

    first_actions = [
        first_agent.select_action(STATE, training=True) for _ in range(20)
    ]
    second_actions = [
        second_agent.select_action(STATE, training=True) for _ in range(20)
    ]

    assert first_actions == second_actions
    assert set(first_actions) == {
        TrafficAction.KEEP,
        TrafficAction.NEXT_GREEN,
    }


def test_zero_epsilon_exploits_during_training() -> None:
    """An epsilon of zero uses the highest Q-value in training mode."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        STATE,
        TrafficAction.NEXT_GREEN,
        2.0,
        None,
        terminated=True,
    )

    assert (
        agent.select_action(STATE, training=True)
        is TrafficAction.NEXT_GREEN
    )


def test_agent_can_only_return_supported_traffic_actions() -> None:
    """Exploration never invents actions outside KEEP and NEXT_GREEN."""
    agent = QLearningAgent(
        QLearningConfig(
            epsilon=1.0,
            minimum_epsilon=0.0,
            random_seed=9,
        )
    )

    selected = {
        agent.select_action(("state", index), training=True)
        for index in range(50)
    }

    assert agent.actions == (
        TrafficAction.KEEP,
        TrafficAction.NEXT_GREEN,
    )
    assert selected <= set(agent.actions)


def test_nonterminal_update_uses_next_state_maximum() -> None:
    """The standard target includes gamma times the best next Q-value."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            gamma=0.95,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        NEXT_STATE,
        TrafficAction.NEXT_GREEN,
        4.0,
        None,
        terminated=True,
    )

    updated = agent.update(
        STATE,
        TrafficAction.KEEP,
        2.0,
        NEXT_STATE,
    )

    assert updated == pytest.approx(2.0 + 0.95 * 4.0)


def test_terminal_update_omits_next_state_value() -> None:
    """A terminal target is exactly the immediate reward."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            gamma=0.95,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        NEXT_STATE,
        TrafficAction.NEXT_GREEN,
        100.0,
        None,
        terminated=True,
    )

    updated = agent.update(
        STATE,
        TrafficAction.KEEP,
        3.0,
        NEXT_STATE,
        terminated=True,
    )

    assert updated == pytest.approx(3.0)


def test_alpha_controls_partial_update_size() -> None:
    """Alpha interpolates between the old value and target."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=0.1,
            gamma=0.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )

    updated = agent.update(
        STATE,
        TrafficAction.KEEP,
        10.0,
        NEXT_STATE,
    )

    assert updated == pytest.approx(1.0)


def test_gamma_controls_discounted_next_value() -> None:
    """Gamma scales only the non-terminal next-state maximum."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            gamma=0.5,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        NEXT_STATE,
        TrafficAction.KEEP,
        4.0,
        None,
        terminated=True,
    )

    updated = agent.update(
        STATE,
        TrafficAction.NEXT_GREEN,
        2.0,
        NEXT_STATE,
    )

    assert updated == pytest.approx(4.0)


def test_negative_reward_is_learned() -> None:
    """Traffic penalties remain negative in the Q-table."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )

    updated = agent.update(
        STATE,
        TrafficAction.KEEP,
        -7.5,
        None,
        terminated=True,
    )

    assert updated == pytest.approx(-7.5)
    assert agent.q_value(STATE, TrafficAction.KEEP) == pytest.approx(-7.5)


def test_epsilon_decays_only_at_episode_boundary() -> None:
    """Action selection leaves epsilon unchanged until end_episode()."""
    agent = QLearningAgent(
        QLearningConfig(
            epsilon=1.0,
            minimum_epsilon=0.05,
            epsilon_decay=0.5,
        )
    )

    for _ in range(10):
        agent.select_action(STATE)

    assert agent.epsilon == 1.0
    assert agent.end_episode() == pytest.approx(0.5)
    assert agent.epsilon == pytest.approx(0.5)


def test_epsilon_never_decays_below_minimum() -> None:
    """Repeated episode boundaries stop at the configured floor."""
    agent = QLearningAgent(
        QLearningConfig(
            epsilon=0.4,
            minimum_epsilon=0.1,
            epsilon_decay=0.5,
        )
    )

    values = [agent.end_episode() for _ in range(10)]

    assert values[-1] == pytest.approx(0.1)
    assert all(value >= 0.1 for value in values)


def test_selecting_actions_does_not_mutate_q_values() -> None:
    """Evaluation and exploration are both read-only table operations."""
    agent = QLearningAgent(
        QLearningConfig(
            epsilon=1.0,
            minimum_epsilon=0.0,
            random_seed=3,
        )
    )

    for _ in range(10):
        agent.select_action(STATE, training=True)
        agent.select_action(STATE, training=False)

    assert agent.q_table == {}


def test_different_states_keep_separate_q_values() -> None:
    """Learning one state never overwrites another state entry."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        STATE,
        TrafficAction.KEEP,
        1.0,
        None,
        terminated=True,
    )
    agent.update(
        NEXT_STATE,
        TrafficAction.KEEP,
        5.0,
        None,
        terminated=True,
    )

    assert agent.q_value(STATE, TrafficAction.KEEP) == 1.0
    assert agent.q_value(NEXT_STATE, TrafficAction.KEEP) == 5.0


def test_clear_q_table_removes_learned_values() -> None:
    """Explicit clearing restores unseen zero values."""
    agent = QLearningAgent(
        QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )
    agent.update(
        STATE,
        TrafficAction.KEEP,
        8.0,
        None,
        terminated=True,
    )

    agent.clear_q_table()

    assert agent.q_table == {}
    assert agent.q_value(STATE, TrafficAction.KEEP) == 0.0


@pytest.mark.parametrize(
    "overrides",
    (
        {"alpha": 0.0},
        {"alpha": 1.1},
        {"gamma": -0.1},
        {"gamma": 1.1},
        {"epsilon": -0.1},
        {"epsilon": 1.1},
        {"minimum_epsilon": -0.1},
        {"minimum_epsilon": 1.1},
        {"epsilon": 0.1, "minimum_epsilon": 0.2},
        {"epsilon_decay": -0.1},
        {"epsilon_decay": 1.1},
        {"random_seed": -1},
        {"random_seed": True},
    ),
)
def test_invalid_configuration_values_are_rejected(
    overrides: dict[str, object],
) -> None:
    """Invalid learning parameters fail before an agent is created."""
    with pytest.raises(ValueError):
        QLearningConfig(**overrides)  # type: ignore[arg-type]


def test_configuration_is_immutable() -> None:
    """Learning hyperparameters cannot change behind a running agent."""
    config = QLearningConfig()
    with pytest.raises(FrozenInstanceError):
        config.alpha = 0.5  # type: ignore[misc]

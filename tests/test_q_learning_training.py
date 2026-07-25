"""Focused tests for the A19 SUMO Q-learning runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.q_learning_agent import QLearningAgent, QLearningConfig
from src.environment.actions import ActionResult, ActionStatus, TrafficAction
from src.environment.multi_agent_environment import MultiAgentStepResult
from src.environment.observations import TrafficObservation
from src.training.independent_q_learning import (
    IndependentQLearningTrainer,
    QLearningTrainingConfig,
)


def observation(time: float, queue: int = 0) -> TrafficObservation:
    return TrafficObservation(
        agent_id="A19",
        traffic_light_id="cluster_A19",
        simulation_time=time,
        incoming_lane_ids=("lane",),
        queue_lengths=(queue,),
        vehicle_counts=(queue,),
        mean_waiting_times=(float(queue),),
        mean_speeds=(1.0,),
        current_phase_index=0,
        current_phase_state="GG",
        current_phase_elapsed_seconds=time,
        is_green_phase=True,
        is_transition_phase=False,
    )


class FakeEnvironment:
    def __init__(self, config, results):
        self.config = config
        self.results = list(results)
        self.reset_count = 0
        self.step_count = 0
        self.closed = False
        self.actions = []

    def reset(self):
        self.reset_count += 1
        return {"A19": observation(0.0)}

    def step(self, actions):
        self.actions.append(actions)
        result = self.results[self.step_count]
        self.step_count += 1
        return result

    def close(self):
        self.closed = True


class RecordingAgent(QLearningAgent):
    def __init__(self, config):
        super().__init__(config)
        self.termination_flags = []

    def update(self, state, action, reward, next_state, *, terminated=False):
        self.termination_flags.append(terminated)
        return super().update(
            state,
            action,
            reward,
            next_state,
            terminated=terminated,
        )


def result(time: float, reward: float, *, terminated=False, truncated=False):
    return MultiAgentStepResult(
        observations={"A19": observation(time, int(time))},
        rewards={"A19": reward},
        terminated=terminated,
        truncated=truncated,
        info={
            "simulation_time": time,
            "action_results": {
                "A19": ActionResult(
                    requested_action=TrafficAction.KEEP,
                    status=ActionStatus.KEPT,
                    previous_phase_index=0,
                    resulting_phase_index=0,
                    phase_changed=False,
                    message="kept",
                )
            },
        },
    )


def make_trainer(
    tmp_path: Path,
    results,
    *,
    mode="train",
    agent=None,
    episodes=None,
):
    environments = []

    def factory(config):
        environment = FakeEnvironment(config, results)
        environments.append(environment)
        return environment

    if episodes is None:
        episodes = 2 if mode == "train" else 1

    config = QLearningTrainingConfig(
        scenario="low",
        episodes=episodes,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode=mode,
    )

    trainer = IndependentQLearningTrainer(
        config,
        agent=agent,
        environment_factory=factory,
    )

    return trainer, environments

def test_training_loop_configures_a19_and_closes_each_episode(tmp_path):
    trainer, environments = make_trainer(
        tmp_path,
        [result(5, 1.0), result(10, 2.0, truncated=True)],
    )

    summaries = trainer.train()

    assert len(summaries) == 2
    assert all(
        environment.config.agent_ids == ("A19",)
        for environment in environments
    )
    assert all(
        environment.config.reward_mode == "local"
        for environment in environments
    )
    assert all(
        environment.reset_count == 1 and environment.closed
        for environment in environments
    )
    assert all(
        list(environment.actions[0]) == ["A19"]
        for environment in environments
    )
    assert summaries[0].total_reward == pytest.approx(3.0)
    assert summaries[0].decision_steps == 2
    assert summaries[0].action_status_counts["kept"] == 2
    assert trainer.agent.training_episode_count == 2


def test_terminated_update_does_not_bootstrap_and_truncated_does(tmp_path):
    terminated_agent = RecordingAgent(
        QLearningConfig(
            alpha=1.0,
            gamma=0.5,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )

    terminated_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2.0, terminated=True)],
        agent=terminated_agent,
        episodes=1,
    )

    terminated_trainer.train()

    assert sum(terminated_agent.q_table.values()) == pytest.approx(2.0)
    assert terminated_agent.termination_flags == [True]

    truncated_agent = RecordingAgent(
        QLearningConfig(
            alpha=1.0,
            gamma=0.5,
            epsilon=0.0,
            minimum_epsilon=0.0,
        )
    )

    truncated_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2.0, truncated=True)],
        agent=truncated_agent,
        episodes=1,
    )

    truncated_trainer.train()

    assert sum(truncated_agent.q_table.values()) == pytest.approx(2.0)
    assert truncated_agent.termination_flags == [False]


def test_checkpoint_round_trip_preserves_values_epsilon_and_episode_count(tmp_path):
    agent = QLearningAgent(
        QLearningConfig(alpha=1.0, epsilon=0.8, minimum_epsilon=0.0)
    )
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 3.0, terminated=True)],
        agent=agent,
    )
    trainer.train()
    expected = dict(agent.q_table)

    restored = IndependentQLearningTrainer(
        QLearningTrainingConfig(
            scenario="low",
            episodes=1,
            episode_seconds=5,
            checkpoint_path=tmp_path / "checkpoint.json",
            mode="evaluate",
        ),
        environment_factory=lambda config: FakeEnvironment(
            config,
            [result(5, 0, truncated=True)],
        ),
    )
    restored.load_checkpoint()
    assert dict(restored.agent.q_table) == expected
    assert restored.agent.epsilon == agent.epsilon
    assert restored.agent.training_episode_count == agent.training_episode_count
    assert json.loads((tmp_path / "checkpoint.json").read_text())["schema_version"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"agent_id": "A26"},
        {"episodes": 0},
        {"episode_seconds": 0},
        {"decision_interval_seconds": 0},
    ],
)
def test_invalid_training_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        QLearningTrainingConfig(**kwargs)


def test_evaluation_does_not_update_or_decay(tmp_path):
    agent = QLearningAgent(
        QLearningConfig(epsilon=0.4, minimum_epsilon=0.0)
    )
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2, terminated=True)],
        agent=agent,
    )
    trainer.train()
    before = (dict(agent.q_table), agent.epsilon)

    evaluator, environments = make_trainer(
        tmp_path,
        [result(5, 2, terminated=True)],
        mode="evaluate",
    )
    evaluator.evaluate()
    assert dict(evaluator.agent.q_table) == dict(agent.q_table)
    assert evaluator.agent.epsilon == agent.epsilon
    assert evaluator.agent.training_episode_count == agent.training_episode_count
    assert environments[0].closed
    assert before[1] != 0.4


def test_malformed_and_unsupported_checkpoints_are_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}")
    trainer = IndependentQLearningTrainer(
        QLearningTrainingConfig(mode="evaluate", checkpoint_path=path)
    )
    with pytest.raises(ValueError, match="schema"):
        trainer.load_checkpoint()
    path.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError, match="Unsupported"):
        trainer.load_checkpoint()

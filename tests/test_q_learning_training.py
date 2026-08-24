"""Focused tests for the independent Q-learning runner (any corridor agent)."""

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

@pytest.fixture(autouse=True)
def _no_real_results_writes(monkeypatch):
    """Prevent evaluate() calls in tests from writing to the real
    results/experiments.csv -- tests use FakeEnvironment, so any
    written row would be meaningless noise in real experiment data."""
    monkeypatch.setattr(
        "src.training.independent_q_learning.append_result",
        lambda *args, **kwargs: None,
    )
    
def observation(time: float, queue: int = 0, agent_id: str = "A19") -> TrafficObservation:
    return TrafficObservation(
        agent_id=agent_id,
        traffic_light_id=f"cluster_{agent_id}",
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
        # Derive the single agent ID from the environment config.
        self._agent_id = config.agent_ids[0] if config.agent_ids else "A19"

    def reset(self):
        self.reset_count += 1
        return {self._agent_id: observation(0.0, agent_id=self._agent_id)}

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


def result(time: float, reward: float, *, terminated=False, truncated=False, agent_id: str = "A19"):
    return MultiAgentStepResult(
        observations={agent_id: observation(time, int(time), agent_id=agent_id)},
        rewards={agent_id: reward},
        terminated=terminated,
        truncated=truncated,
        info={
            "simulation_time": time,
            "action_results": {
                agent_id: ActionResult(
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
    agent_id="A19",
):
    environments = []

    def factory(config, on_raw_step=None):
        environment = FakeEnvironment(config, results)
        environments.append(environment)
        return environment

    if episodes is None:
        episodes = 2 if mode == "train" else 1

    config = QLearningTrainingConfig(
        agent_id=agent_id,
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

def test_training_loop_configures_agent_and_closes_each_episode(tmp_path):
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
        {"agent_id": "UNKNOWN_AGENT"},
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


def test_resume_continues_episode_count_epsilon_and_q_table(tmp_path):
    agent = QLearningAgent(
        QLearningConfig(alpha=1.0, epsilon=0.8, minimum_epsilon=0.0)
    )
    first_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True), result(5, 2.0, terminated=True)],
        agent=agent,
        episodes=2,
    )
    first_trainer.train()
    assert first_trainer.agent.training_episode_count == 2
    epsilon_after_two = first_trainer.agent.epsilon

    config = QLearningTrainingConfig(
        scenario="low",
        episodes=4,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    resumed_trainer = IndependentQLearningTrainer(
        config,
        environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(
            cfg,
            [result(5, 3.0, terminated=True), result(5, 4.0, terminated=True)],
        ),
    )
    summaries = resumed_trainer.train()

    # Only the two remaining episodes (3 and 4) should have run, numbered
    # to continue from where the first run left off.
    assert len(summaries) == 2
    assert [summary.episode for summary in summaries] == [3, 4]
    assert resumed_trainer.agent.training_episode_count == 4
    assert resumed_trainer.agent.epsilon != epsilon_after_two
    assert dict(resumed_trainer.agent.q_table) != {}


def test_resume_with_no_existing_checkpoint_starts_fresh(tmp_path):
    config = QLearningTrainingConfig(
        scenario="low",
        episodes=2,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    trainer = IndependentQLearningTrainer(
        config,
        environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(
            cfg,
            [result(5, 1.0, terminated=True), result(5, 2.0, terminated=True)],
        ),
    )
    summaries = trainer.train()
    assert len(summaries) == 2
    assert trainer.agent.training_episode_count == 2


def test_resume_already_complete_is_a_noop(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True), result(5, 2.0, terminated=True)],
        episodes=2,
    )
    trainer.train()

    config = QLearningTrainingConfig(
        scenario="low",
        episodes=2,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    resumed_trainer = IndependentQLearningTrainer(
        config,
        environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(cfg, []),
    )
    summaries = resumed_trainer.train()
    assert summaries == ()
    assert resumed_trainer.agent.training_episode_count == 2


def test_resume_rejects_mismatched_scenario_or_seed(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    trainer.train()

    mismatched_scenario = QLearningTrainingConfig(
        scenario="high",
        episodes=2,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    with pytest.raises(ValueError, match="scenario"):
        IndependentQLearningTrainer(
            mismatched_scenario,
            environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(cfg, []),
        ).train()

    mismatched_seed = QLearningTrainingConfig(
        scenario="low",
        seed=7,
        episodes=2,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    with pytest.raises(ValueError, match="seed"):
        IndependentQLearningTrainer(
            mismatched_seed,
            environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(cfg, []),
        ).train()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resume": True, "mode": "evaluate", "checkpoint_path": Path("x.json")},
        {"resume": True, "checkpoint_path": None},
    ],
)
def test_invalid_resume_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        QLearningTrainingConfig(**kwargs)


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


def test_non_a19_agent_trains_and_configures_correctly(tmp_path):
    """Any valid corridor agent ID (not just A19) should train without errors."""
    trainer, environments = make_trainer(
        tmp_path,
        [result(5, 1.0, agent_id="A26"), result(10, 2.0, truncated=True, agent_id="A26")],
        agent_id="A26",
    )

    summaries = trainer.train()

    assert len(summaries) == 2
    assert all(
        environment.config.agent_ids == ("A26",)
        for environment in environments
    )
    assert trainer.agent.training_episode_count == 2


def test_unknown_agent_id_is_rejected():
    """An agent ID that is not in the selected corridor must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown agent_id"):
        QLearningTrainingConfig(agent_id="UNKNOWN_AGENT")


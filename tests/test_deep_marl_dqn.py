"""Tests for the shared DQN trainer, using the fake SUMO env."""

from __future__ import annotations

import csv

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer
from src.training.deep_marl_dqn import (
    CONTROLLER_NAME,
    DqnConfig,
    DqnTrainer,
    ReplayBuffer,
    SharedQNetwork,
)
from tests.test_gym_wrapper import FakeEnvironment, _specs

AGENTS = ("A19", "A26")


def make_trainer(tmp_path, episodes=2, **overrides) -> DqnTrainer:
    settings = dict(
        agent_ids=AGENTS,
        episodes=episodes,
        checkpoint_path=tmp_path / "dqn.pt",
        results_path=tmp_path / "results.csv",
        hidden_size=16,
        minibatch_size=8,
        gradient_steps=5,
        target_update_steps=3,
        buffer_size=1000,
    )
    settings.update(overrides)
    config = DqnConfig(**settings)
    return DqnTrainer(
        config,
        environment_factory=lambda resolved: FakeEnvironment(resolved),
        space_specs=_specs(config.agent_ids),
    )


def test_network_returns_q_values_and_their_maximum():
    network = SharedQNetwork(input_size=10, hidden_size=16)
    q_values, best = network(torch.rand(8, 10))
    assert q_values.shape == (8, 2)
    assert torch.equal(best, q_values.max(dim=-1).values)


def test_epsilon_falls_linearly_then_stays_at_the_floor(tmp_path):
    trainer = make_trainer(tmp_path, episodes=10, exploration_fraction=0.5)
    assert trainer.epsilon(1) == pytest.approx(1.0)
    assert trainer.epsilon(3) == pytest.approx(1.0 - 2 / 5 * 0.95)
    assert trainer.epsilon(6) == pytest.approx(0.05)
    assert trainer.epsilon(10) == pytest.approx(0.05)


def test_greedy_actions_ignore_epsilon(tmp_path):
    trainer = make_trainer(tmp_path)
    batch = np.random.default_rng(0).random((2, trainer.input_size), dtype=np.float32)
    expected = trainer.network(torch.from_numpy(batch))[0].argmax(dim=-1).numpy()
    for _ in range(20):
        actions, _, _ = trainer._act(batch, greedy=True)
        assert np.array_equal(actions, expected)


def test_full_exploration_picks_both_actions(tmp_path):
    trainer = make_trainer(tmp_path)  # epsilon is 1.0 in the first episode
    batch = np.zeros((2, trainer.input_size), dtype=np.float32)
    seen = {int(a) for _ in range(50) for a in trainer._act(batch, greedy=False)[0]}
    assert seen == {0, 1}


def test_replay_buffer_wraps_around_and_keeps_the_newest():
    buffer = ReplayBuffer(capacity=4, input_size=1)
    values = np.arange(6, dtype=np.float32)
    buffer.add(values[:, None], np.zeros(6), values, values[:, None], np.zeros(6))
    assert buffer.size == 4
    assert sorted(buffer.rewards.tolist()) == [2.0, 3.0, 4.0, 5.0]


def test_training_fills_the_buffer_and_changes_the_network(tmp_path):
    trainer = make_trainer(tmp_path)
    before = [p.detach().clone() for p in trainer.network.parameters()]
    summaries = trainer.train()
    assert trainer.buffer.size == sum(s.decision_steps for s in summaries) * len(AGENTS)
    assert any(not torch.equal(b, a) for b, a in zip(before, trainer.network.parameters()))


def test_target_network_syncs_every_target_update_steps(tmp_path):
    trainer = make_trainer(tmp_path, episodes=1, gradient_steps=3, target_update_steps=3)
    trainer.train()
    for online, target in zip(trainer.network.parameters(), trainer.target_network.parameters()):
        assert torch.equal(online, target)


def test_last_step_only_stops_bootstrapping_on_termination(tmp_path):
    trainer = make_trainer(tmp_path)
    rollout = {
        "obs": np.zeros((3, 2, trainer.input_size), dtype=np.float32),
        "actions": np.zeros((3, 2), dtype=np.int64),
        "rewards": np.zeros((3, 2), dtype=np.float32),
        "last_batch": np.ones((2, trainer.input_size), dtype=np.float32),
        "terminated": False,
    }
    trainer._update(rollout)
    assert trainer.buffer.dones[:6].sum() == 0
    # the final transition's next state is the batch after the last step
    assert trainer.buffer.next_obs[4:6].min() == 1.0


def test_evaluation_appends_one_row_under_its_own_label(tmp_path):
    make_trainer(tmp_path).train()
    summary = make_trainer(tmp_path).evaluate()
    assert summary.decision_steps > 0
    with (tmp_path / "results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["controller"] for row in rows] == [CONTROLLER_NAME]


def test_ppo_checkpoint_cannot_be_loaded_as_dqn(tmp_path):
    config = DeepMarlConfig(agent_ids=AGENTS, checkpoint_path=tmp_path / "dqn.pt", hidden_size=16)
    DeepMarlTrainer(config, space_specs=_specs(AGENTS)).save_checkpoint()
    with pytest.raises(RuntimeError):
        make_trainer(tmp_path).load_checkpoint(for_training=False)


def test_run_script_uses_its_own_checkpoint_path():
    from scripts.experiments.run_deep_marl import (
        default_checkpoint_path as ppo_checkpoint_path,
    )
    from scripts.experiments.run_dqn import default_checkpoint_path, parse_args

    assert default_checkpoint_path("medium", 42, "local") != ppo_checkpoint_path(
        "medium", 42, "local"
    )
    args = parse_args(["train", "--scenario", "high"])
    assert args.episodes == 300
    assert args.learning_rate == pytest.approx(3e-4)
    assert args.gradient_steps == 1680

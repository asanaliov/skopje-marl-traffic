"""Tests for the parameter-shared deep MARL trainer, using the fake SUMO env."""

from __future__ import annotations

import csv

import numpy as np
import pytest

pytest.importorskip("torch")

from src.training.deep_marl import (  # noqa: E402
    CONTROLLER_NAME,
    DeepMarlConfig,
    DeepMarlTrainer,
    compute_gae,
    controller_label,
)
from tests.test_gym_wrapper import FakeEnvironment, _specs  # noqa: E402

AGENTS = ("A19", "A26")


def make_trainer(tmp_path, **overrides) -> DeepMarlTrainer:
    config = DeepMarlConfig(
        agent_ids=AGENTS,
        episodes=2,
        checkpoint_path=tmp_path / "deep.pt",
        results_path=tmp_path / "results.csv",
        hidden_size=16,
        minibatch_size=8,
        **overrides,
    )
    return DeepMarlTrainer(
        config,
        environment_factory=lambda resolved: FakeEnvironment(resolved),
        space_specs=_specs(config.agent_ids),
    )


def test_observations_are_padded_and_tagged_with_a_one_hot_agent_id(tmp_path):
    trainer = make_trainer(tmp_path)
    width = trainer.max_feature_count
    batch = trainer._stack({"A19": np.ones(3), "A26": np.ones(width)})
    assert batch.shape == (2, width + 2)
    assert batch[0, 3:width].sum() == 0
    assert list(batch[0, width:]) == [1.0, 0.0]
    assert list(batch[1, width:]) == [0.0, 1.0]


def test_gae_bootstraps_only_truncated_episodes():
    rewards = np.ones((3, 1))
    values = np.zeros((3, 1))
    last = np.array([10.0])
    truncated, _ = compute_gae(rewards, values, last, False, 1.0, 1.0)
    terminated, _ = compute_gae(rewards, values, last, True, 1.0, 1.0)
    assert truncated[-1, 0] == pytest.approx(11.0)
    assert terminated[-1, 0] == pytest.approx(1.0)


def test_training_updates_weights_and_writes_a_resumable_checkpoint(tmp_path):
    trainer = make_trainer(tmp_path)
    before = [p.clone() for p in trainer.network.parameters()]
    summaries = trainer.train()
    assert [s.episode for s in summaries] == [1, 2]
    assert any(
        not np.allclose(b.detach().numpy(), a.detach().numpy())
        for b, a in zip(before, trainer.network.parameters())
    )
    resumed = make_trainer(tmp_path)
    assert resumed.train(resume=True) == ()
    assert resumed.completed_episodes == 2


def test_training_writes_no_row_to_the_results_csv(tmp_path):
    make_trainer(tmp_path).train()
    assert not (tmp_path / "results.csv").exists()


def test_checkpoint_from_another_scenario_is_rejected(tmp_path):
    make_trainer(tmp_path).train()
    other = make_trainer(tmp_path, scenario="high")
    with pytest.raises(ValueError, match="scenario"):
        other.load_checkpoint(for_training=False)


def test_cross_seed_evaluation_needs_an_explicit_opt_in(tmp_path):
    make_trainer(tmp_path).train()
    other = make_trainer(tmp_path, seed=43)
    with pytest.raises(ValueError, match="seed"):
        other.load_checkpoint(for_training=False)
    allowed = make_trainer(tmp_path, seed=43, allow_cross_seed_evaluation=True)
    allowed.load_checkpoint(for_training=False)


def test_controller_labels_never_collide_with_tabular_ones():
    labels = {controller_label(m) for m in ("local", "neighbor_aware", "global")}
    assert len(labels) == 3
    assert all(label.startswith(CONTROLLER_NAME) for label in labels)
    assert not labels & {"marl_global_reward", "marl_neighbor_reward"}


def test_config_orders_agents_and_rejects_unknown_ones():
    config = DeepMarlConfig(agent_ids=("A26", "A19"))
    assert config.agent_ids == ("A19", "A26")
    with pytest.raises(ValueError):
        DeepMarlConfig(agent_ids=("A99",))


def test_return_scaler_brings_scenarios_of_different_magnitude_to_unit_scale():
    from src.training.deep_marl import RunningReturnScaler

    peaks = []
    for magnitude in (1.0, 50.0):
        scaler = RunningReturnScaler(gamma=0.99, clip=10.0)
        rewards = -magnitude * np.ones((200, 4), dtype=np.float32)
        peaks.append(np.abs(scaler.scale(rewards)).max())
    assert peaks[0] < 1.0
    assert peaks[1] == pytest.approx(peaks[0], rel=1e-3)


def test_resume_with_different_hyperparameters_is_rejected(tmp_path):
    make_trainer(tmp_path).train()
    changed = make_trainer(tmp_path, learning_rate=1e-3)
    with pytest.raises(ValueError, match="learning_rate"):
        changed.train(resume=True)
    # Evaluation only needs the same network shape.
    evaluator = make_trainer(tmp_path, learning_rate=1e-3)
    evaluator.load_checkpoint(for_training=False)


def test_resume_restores_the_reward_statistics(tmp_path):
    first = make_trainer(tmp_path)
    first.train()
    resumed = make_trainer(tmp_path)
    resumed.load_checkpoint(for_training=True)
    assert resumed.reward_scaler.state() == first.reward_scaler.state()


def test_evaluation_appends_one_labelled_row_and_counts_its_steps(tmp_path):
    make_trainer(tmp_path).train()
    evaluator = make_trainer(tmp_path, reward_mode="local")
    summary = evaluator.evaluate()
    assert summary.decision_steps > 0
    with (tmp_path / "results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["controller"] for row in rows] == [CONTROLLER_NAME]
    assert rows[0]["demand_seconds"] == "3600.0"

"""Tests for the self-attention PPO trainer, using the fake SUMO env."""

from __future__ import annotations

import csv

import pytest

torch = pytest.importorskip("torch")

from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer  # noqa: E402
from src.training.deep_marl_attention import (  # noqa: E402
    CONTROLLER_NAME,
    AttentionActorCritic,
    AttentionPpoConfig,
    AttentionPpoTrainer,
)
from tests.test_gym_wrapper import FakeEnvironment, _specs  # noqa: E402

AGENTS = ("A19", "A26")


def make_trainer(tmp_path, episodes=2, **overrides) -> AttentionPpoTrainer:
    config = AttentionPpoConfig(
        agent_ids=AGENTS,
        episodes=episodes,
        checkpoint_path=tmp_path / "attention.pt",
        results_path=tmp_path / "results.csv",
        hidden_size=16,
        minibatch_size=8,
        **overrides,
    )
    return AttentionPpoTrainer(
        config,
        environment_factory=lambda resolved: FakeEnvironment(resolved),
        space_specs=_specs(config.agent_ids),
    )


def weights(trainer) -> list:
    return [p.detach().clone() for p in trainer.network.parameters()]


def test_network_keeps_one_output_per_agent_with_and_without_a_step_dimension():
    network = AttentionActorCritic(input_size=10, hidden_size=16, attention_heads=4)
    logits, values = network(torch.zeros(8, 10))
    assert logits.shape == (8, 2)
    assert values.shape == (8,)
    logits, values = network(torch.zeros(5, 8, 10))
    assert logits.shape == (5, 8, 2)
    assert values.shape == (5, 8)


def test_one_junctions_observation_changes_the_others_decision():
    torch.manual_seed(0)
    network = AttentionActorCritic(input_size=10, hidden_size=16, attention_heads=4)
    inputs = torch.rand(3, 10)
    changed = inputs.clone()
    changed[2] += 1.0
    before, _ = network(inputs)
    after, _ = network(changed)
    assert not torch.allclose(before[0], after[0])


def test_mlp_decisions_stay_local_as_the_comparison_baseline():
    config = DeepMarlConfig(agent_ids=AGENTS, hidden_size=16)
    trainer = DeepMarlTrainer(config, space_specs=_specs(AGENTS))
    inputs = torch.rand(2, trainer.input_size)
    changed = inputs.clone()
    changed[1] += 1.0
    assert torch.equal(trainer.network(inputs)[0][0], trainer.network(changed)[0][0])


def test_without_attention_a_junction_only_uses_its_own_observation():
    torch.manual_seed(0)
    network = AttentionActorCritic(input_size=10, hidden_size=16, attention_heads=4)
    torch.nn.init.zeros_(network.attention.out_proj.weight)
    torch.nn.init.zeros_(network.attention.out_proj.bias)
    inputs = torch.rand(3, 10)
    changed = inputs.clone()
    changed[2] += 1.0
    assert torch.equal(network(inputs)[0][0], network(changed)[0][0])


def test_attention_weights_form_a_distribution_over_agents():
    network = AttentionActorCritic(input_size=10, hidden_size=16, attention_heads=4)
    matrix = network.attention_weights(torch.rand(8, 10))
    assert matrix.shape == (8, 8)
    assert torch.allclose(matrix.sum(dim=-1), torch.ones(8))


def test_update_sees_whole_timesteps_and_keeps_the_sample_count(tmp_path):
    trainer = make_trainer(tmp_path)
    seen = []
    original = trainer.network.forward

    def spy(inputs):
        seen.append(inputs.shape)
        return original(inputs)

    trainer.network.forward = spy
    trainer.train()
    batched = [shape for shape in seen if len(shape) == 3]
    assert batched
    assert all(shape[1] == len(AGENTS) for shape in batched)
    assert max(shape[0] * shape[1] for shape in batched) == trainer.config.minibatch_size


def test_training_updates_attention_weights(tmp_path):
    trainer = make_trainer(tmp_path)
    before = trainer.network.attention.out_proj.weight.detach().clone()
    trainer.train()
    assert not torch.equal(before, trainer.network.attention.out_proj.weight)


def test_resumed_training_matches_an_uninterrupted_run(tmp_path):
    # stopping at 2 of 3 is faked with episodes=2, which would shift the lr
    # decay schedule; a real resume keeps --episodes, so decay is off here
    straight = make_trainer(tmp_path / "straight", episodes=3, learning_rate_decay=False)
    straight.train()
    make_trainer(tmp_path / "interrupted", episodes=2, learning_rate_decay=False).train()
    resumed = make_trainer(tmp_path / "interrupted", episodes=3, learning_rate_decay=False)
    resumed.train(resume=True)
    assert resumed.completed_episodes == 3
    for expected, actual in zip(weights(straight), weights(resumed)):
        assert torch.equal(expected, actual)


def test_checkpoint_write_leaves_no_partial_file(tmp_path):
    make_trainer(tmp_path).train()
    assert (tmp_path / "attention.pt").is_file()
    assert not (tmp_path / "attention.pt.tmp").exists()


def test_checkpoint_with_another_head_count_is_rejected(tmp_path):
    make_trainer(tmp_path).train()
    other = make_trainer(tmp_path, attention_heads=2)
    with pytest.raises(ValueError, match="attention_heads"):
        other.load_checkpoint(for_training=False)


def test_mlp_checkpoint_cannot_be_loaded_as_attention(tmp_path):
    config = DeepMarlConfig(
        agent_ids=AGENTS,
        checkpoint_path=tmp_path / "attention.pt",
        hidden_size=16,
    )
    DeepMarlTrainer(config, space_specs=_specs(AGENTS)).save_checkpoint()
    with pytest.raises(ValueError, match="attention_heads"):
        make_trainer(tmp_path).load_checkpoint(for_training=False)


def test_heads_must_divide_the_hidden_size():
    with pytest.raises(ValueError, match="divisible"):
        AttentionPpoConfig(hidden_size=16, attention_heads=3)
    with pytest.raises(ValueError, match="attention_heads"):
        AttentionPpoConfig(attention_heads=0)


def test_evaluation_appends_one_row_under_its_own_label(tmp_path):
    make_trainer(tmp_path).train()
    summary = make_trainer(tmp_path).evaluate()
    assert summary.decision_steps > 0
    with (tmp_path / "results.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["controller"] for row in rows] == [CONTROLLER_NAME]
    assert rows[0]["demand_seconds"] == "3600.0"


def test_run_script_trains_nothing_on_the_ppo_checkpoint_path():
    from scripts.experiments.run_attention_ppo import default_checkpoint_path, parse_args
    from scripts.experiments.run_deep_marl import (
        default_checkpoint_path as ppo_checkpoint_path,
    )

    assert default_checkpoint_path("medium", 42, "local") != ppo_checkpoint_path(
        "medium", 42, "local"
    )
    args = parse_args(["train", "--scenario", "high"])
    assert args.attention_heads == 4
    assert args.episodes == 300

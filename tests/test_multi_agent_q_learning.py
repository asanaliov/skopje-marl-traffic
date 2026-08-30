"""Focused tests for the multi-agent independent Q-learning runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.q_learning_agent import QLearningAgent, QLearningConfig
from src.agents.state_encoder import TrafficStateEncoder
from src.environment.actions import ActionResult, ActionStatus, TrafficAction
from src.environment.multi_agent_environment import MultiAgentStepResult
from src.environment.observations import TrafficObservation
from src.environment.selected_corridor import (
    SELECTED_CORRIDOR,
    nearest_neighbor_ids,
)
from src.training.multi_agent_q_learning import (
    CONTROLLER_NAME,
    SPATIAL_CONTROLLER_NAME,
    MultiAgentQLearningConfig,
    MultiAgentQLearningTrainer,
)


ALL_AGENTS = SELECTED_CORRIDOR.agent_ids


@pytest.fixture(autouse=True)
def _no_real_results_writes(monkeypatch):
    """Keep evaluate() in tests out of the real results/experiments.csv.

    Tests drive a FakeEnvironment, so any row written would be
    meaningless noise in real experiment data.
    """
    monkeypatch.setattr(
        "src.training.multi_agent_q_learning.append_result",
        lambda *args, **kwargs: None,
    )


def observation(agent_id: str, time: float, queue: int = 0) -> TrafficObservation:
    return TrafficObservation(
        agent_id=agent_id,
        traffic_light_id=f"cluster_{agent_id}",
        simulation_time=time,
        incoming_lane_ids=(f"lane_{agent_id}",),
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


def result(
    time: float,
    reward: float,
    *,
    agent_ids=ALL_AGENTS,
    terminated=False,
    truncated=False,
):
    """Build one step result giving every agent the same reward."""
    return MultiAgentStepResult(
        observations={
            agent_id: observation(agent_id, time, int(time))
            for agent_id in agent_ids
        },
        rewards={agent_id: reward for agent_id in agent_ids},
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
                for agent_id in agent_ids
            },
        },
    )


class FakeEnvironment:
    def __init__(self, config, results, agent_ids=ALL_AGENTS):
        self.config = config
        self.results = list(results)
        self.agent_ids = tuple(agent_ids)
        self.reset_count = 0
        self.step_count = 0
        self.closed = False
        self.actions = []

    def reset(self):
        self.reset_count += 1
        return {
            agent_id: observation(agent_id, 0.0) for agent_id in self.agent_ids
        }

    def step(self, actions):
        self.actions.append(dict(actions))
        step_result = self.results[self.step_count]
        self.step_count += 1
        return step_result

    def close(self):
        self.closed = True


def make_trainer(
    tmp_path: Path,
    results,
    *,
    mode="train",
    agents=None,
    agent_ids=ALL_AGENTS,
    episodes=None,
    q_learning_config=None,
):
    environments = []

    def factory(config, on_raw_step=None):
        environment = FakeEnvironment(config, results, agent_ids=agent_ids)
        environments.append(environment)
        return environment

    if episodes is None:
        episodes = 2 if mode == "train" else 1

    config = MultiAgentQLearningConfig(
        agent_ids=agent_ids,
        scenario="low",
        episodes=episodes,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode=mode,
    )

    trainer = MultiAgentQLearningTrainer(
        config,
        agents=agents,
        environment_factory=factory,
        q_learning_config=q_learning_config,
    )
    return trainer, environments


def test_all_eight_agents_act_and_learn_in_the_same_episode(tmp_path):
    trainer, environments = make_trainer(
        tmp_path,
        [result(5, 1.0), result(10, 2.0, truncated=True)],
    )

    summaries = trainer.train()

    assert len(trainer.agents) == 8
    assert trainer.agent_ids == ALL_AGENTS
    assert len(summaries) == 2
    assert all(
        environment.config.agent_ids == ALL_AGENTS
        for environment in environments
    )
    # Independent RL: every agent optimizes only its own junction.
    assert all(
        environment.config.reward_mode == "local"
        for environment in environments
    )
    assert all(
        environment.reset_count == 1 and environment.closed
        for environment in environments
    )
    # Every decision must carry an action for all eight agents at once.
    assert all(
        tuple(step_actions) == ALL_AGENTS
        for environment in environments
        for step_actions in environment.actions
    )
    assert all(
        isinstance(action, TrafficAction)
        for environment in environments
        for step_actions in environment.actions
        for action in step_actions.values()
    )

    # 8 agents x (1.0 + 2.0) reward each.
    assert summaries[0].combined_total_reward == pytest.approx(24.0)
    assert summaries[0].decision_steps == 2
    assert summaries[0].agents["A19"].total_reward == pytest.approx(3.0)
    assert set(summaries[0].agents) == set(ALL_AGENTS)
    assert summaries[0].action_status_counts["kept"] == 16
    assert trainer.completed_training_episodes == 2
    assert all(agent.q_table for agent in trainer.agents.values())


def test_each_agent_keeps_a_separate_q_table(tmp_path):
    """Rewards differing per agent must not bleed across Q-tables."""

    def uneven(time, *, terminated=False, truncated=False):
        step_result = result(
            time,
            0.0,
            terminated=terminated,
            truncated=truncated,
        )
        rewards = {
            agent_id: float(index)
            for index, agent_id in enumerate(ALL_AGENTS)
        }
        return MultiAgentStepResult(
            observations=step_result.observations,
            rewards=rewards,
            terminated=step_result.terminated,
            truncated=step_result.truncated,
            info=step_result.info,
        )

    trainer, _ = make_trainer(
        tmp_path,
        [uneven(5, terminated=True)],
        episodes=1,
        q_learning_config=QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        ),
    )
    summaries = trainer.train()

    for index, agent_id in enumerate(ALL_AGENTS):
        assert summaries[0].agents[agent_id].total_reward == pytest.approx(
            float(index)
        )
        # alpha=1.0 with a terminal update writes the reward straight in.
        assert sum(trainer.agents[agent_id].q_table.values()) == pytest.approx(
            float(index)
        )
    # Eight distinct learners, each holding its own values -- not one
    # shared table that every agent writes into.
    assert len({id(agent) for agent in trainer.agents.values()}) == 8
    assert len(
        {
            tuple(sorted(agent.q_table.values()))
            for agent in trainer.agents.values()
        }
    ) == 8


def test_default_agents_get_independent_exploration_streams(tmp_path):
    """Agents sharing one RNG seed would explore in lockstep."""
    trainer, _ = make_trainer(tmp_path, [], episodes=1)
    seeds = [agent.config.random_seed for agent in trainer.agents.values()]
    assert len(set(seeds)) == 8


def test_reset_and_step_expose_states_for_every_agent(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    try:
        states = trainer.reset()
        assert set(states) == set(ALL_AGENTS)

        decision = trainer.step(training=True)
        assert set(decision.actions) == set(ALL_AGENTS)
        assert set(decision.rewards) == set(ALL_AGENTS)
        assert set(decision.states) == set(ALL_AGENTS)
        assert decision.combined_reward == pytest.approx(8.0)
        assert decision.terminated

        with pytest.raises(RuntimeError, match="episode is complete"):
            trainer.step(training=True)
    finally:
        trainer.close()


def test_step_before_reset_is_rejected(tmp_path):
    trainer, _ = make_trainer(tmp_path, [], episodes=1)
    with pytest.raises(RuntimeError, match="reset\\(\\) must be called"):
        trainer.step(training=True)


def test_terminated_update_does_not_bootstrap_and_truncated_does(tmp_path):
    config = QLearningConfig(
        alpha=1.0,
        gamma=0.5,
        epsilon=0.0,
        minimum_epsilon=0.0,
    )

    terminated_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2.0, terminated=True)],
        episodes=1,
        q_learning_config=config,
    )
    terminated_trainer.train()

    truncated_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2.0, truncated=True)],
        episodes=1,
        q_learning_config=config,
    )
    truncated_trainer.train()

    for agent_id in ALL_AGENTS:
        terminated_values = terminated_trainer.agents[agent_id].q_table
        truncated_values = truncated_trainer.agents[agent_id].q_table
        assert sum(terminated_values.values()) == pytest.approx(2.0)
        assert sum(truncated_values.values()) == pytest.approx(2.0)


def test_checkpoint_round_trip_preserves_every_agent(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 3.0, terminated=True)],
        episodes=1,
        q_learning_config=QLearningConfig(
            alpha=1.0,
            epsilon=0.8,
            minimum_epsilon=0.0,
        ),
    )
    trainer.train()
    expected = {
        agent_id: dict(agent.q_table)
        for agent_id, agent in trainer.agents.items()
    }

    restored, _ = make_trainer(
        tmp_path,
        [result(5, 0.0, truncated=True)],
        mode="evaluate",
    )
    restored.load_checkpoint()

    for agent_id in ALL_AGENTS:
        assert dict(restored.agents[agent_id].q_table) == expected[agent_id]
        assert (
            restored.agents[agent_id].epsilon
            == trainer.agents[agent_id].epsilon
        )
    assert (
        restored.completed_training_episodes
        == trainer.completed_training_episodes
    )

    payload = json.loads((tmp_path / "checkpoint.json").read_text())
    assert payload["schema_version"] == 1
    assert payload["controller"] == CONTROLLER_NAME
    assert payload["agent_ids"] == list(ALL_AGENTS)
    assert set(payload["agents"]) == set(ALL_AGENTS)
    assert all(
        "q_table" in agent_payload and "epsilon" in agent_payload
        for agent_payload in payload["agents"].values()
    )


def test_evaluation_does_not_update_or_decay(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 2.0, terminated=True)],
        episodes=1,
        q_learning_config=QLearningConfig(epsilon=0.4, minimum_epsilon=0.0),
    )
    trainer.train()
    trained = {
        agent_id: (dict(agent.q_table), agent.epsilon)
        for agent_id, agent in trainer.agents.items()
    }

    evaluator, environments = make_trainer(
        tmp_path,
        [result(5, 2.0, terminated=True)],
        mode="evaluate",
    )
    evaluator.evaluate()

    for agent_id in ALL_AGENTS:
        expected_table, expected_epsilon = trained[agent_id]
        assert dict(evaluator.agents[agent_id].q_table) == expected_table
        assert evaluator.agents[agent_id].epsilon == expected_epsilon
    assert evaluator.completed_training_episodes == 1
    assert environments[0].closed


def test_evaluation_writes_combined_metrics_under_controller_label(
    tmp_path, monkeypatch
):
    written = []
    monkeypatch.setattr(
        "src.training.multi_agent_q_learning.append_result",
        lambda metrics, *args, **kwargs: written.append(metrics),
    )

    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    trainer.train()

    evaluator, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        mode="evaluate",
    )
    evaluator.evaluate()

    assert len(written) == 1
    metrics = written[0]
    assert metrics.controller == "multi_agent_independent_rl"
    assert metrics.scenario == "low"
    # Combined reward across all eight agents, not one agent's share.
    assert metrics.total_reward == pytest.approx(8.0)
    assert metrics.demand_seconds == pytest.approx(10.0)


def test_training_episodes_are_not_written_to_results(tmp_path, monkeypatch):
    written = []
    monkeypatch.setattr(
        "src.training.multi_agent_q_learning.append_result",
        lambda metrics, *args, **kwargs: written.append(metrics),
    )

    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    trainer.train()
    assert written == []


def test_resume_continues_every_agent(tmp_path):
    first_trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True), result(5, 2.0, terminated=True)],
        episodes=2,
        q_learning_config=QLearningConfig(
            alpha=1.0,
            epsilon=0.8,
            minimum_epsilon=0.0,
        ),
    )
    first_trainer.train()
    assert first_trainer.completed_training_episodes == 2
    epsilon_after_two = first_trainer.agents["A19"].epsilon

    config = MultiAgentQLearningConfig(
        scenario="low",
        episodes=4,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    resumed = MultiAgentQLearningTrainer(
        config,
        environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(
            cfg,
            [result(5, 3.0, terminated=True), result(5, 4.0, terminated=True)],
        ),
    )
    summaries = resumed.train()

    assert [summary.episode for summary in summaries] == [3, 4]
    assert resumed.completed_training_episodes == 4
    assert resumed.agents["A19"].epsilon != epsilon_after_two
    assert all(agent.q_table for agent in resumed.agents.values())


def test_resume_already_complete_is_a_noop(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True), result(5, 2.0, terminated=True)],
        episodes=2,
    )
    trainer.train()

    config = MultiAgentQLearningConfig(
        scenario="low",
        episodes=2,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "checkpoint.json",
        mode="train",
        resume=True,
    )
    resumed = MultiAgentQLearningTrainer(
        config,
        environment_factory=lambda cfg, on_raw_step=None: FakeEnvironment(
            cfg, []
        ),
    )
    assert resumed.train() == ()
    assert resumed.completed_training_episodes == 2


def test_checkpoint_rejects_mismatched_scenario_seed_or_agents(tmp_path):
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    trainer.train()
    checkpoint = tmp_path / "checkpoint.json"

    mismatches = [
        ("scenario", {"scenario": "high"}),
        ("seed", {"scenario": "low", "seed": 7}),
        ("agents", {"scenario": "low", "agent_ids": ("A19", "A20")}),
    ]
    for expected_message, overrides in mismatches:
        config = MultiAgentQLearningConfig(
            episodes=2,
            episode_seconds=10,
            decision_interval_seconds=5,
            checkpoint_path=checkpoint,
            mode="train",
            resume=True,
            **overrides,
        )
        with pytest.raises(ValueError, match=expected_message):
            MultiAgentQLearningTrainer(
                config,
                environment_factory=lambda cfg, on_raw_step=None: (
                    FakeEnvironment(cfg, [])
                ),
            ).train()


def test_single_agent_checkpoint_is_rejected(tmp_path):
    """A19-only checkpoints must not silently load into the 8-agent runner."""
    checkpoint = tmp_path / "single.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_id": "A19",
                "scenario": "low",
                "seed": 42,
                "epsilon": 1.0,
                "q_table": [],
                "training_episode_count": 0,
            }
        ),
        encoding="utf-8",
    )
    trainer = MultiAgentQLearningTrainer(
        MultiAgentQLearningConfig(
            scenario="low",
            mode="evaluate",
            checkpoint_path=checkpoint,
        )
    )
    with pytest.raises(ValueError, match="controller"):
        trainer.load_checkpoint()


def test_malformed_and_unsupported_checkpoints_are_rejected(tmp_path):
    path = tmp_path / "bad.json"
    trainer = MultiAgentQLearningTrainer(
        MultiAgentQLearningConfig(mode="evaluate", checkpoint_path=path)
    )
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        trainer.load_checkpoint()
    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        trainer.load_checkpoint()


def test_incomplete_environment_observations_are_rejected(tmp_path):
    """A missing agent must fail loudly, not train seven agents silently."""
    partial = ALL_AGENTS[:-1]
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, agent_ids=partial, terminated=True)],
        agent_ids=ALL_AGENTS,
        episodes=1,
    )

    def factory(config, on_raw_step=None):
        return FakeEnvironment(
            config,
            [result(5, 1.0, agent_ids=partial, terminated=True)],
            agent_ids=partial,
        )

    trainer._environment_factory = factory
    with pytest.raises(ValueError, match="missing configured agents"):
        trainer.train()


def test_subset_of_agents_is_supported(tmp_path):
    subset = ("A19", "A20")
    trainer, environments = make_trainer(
        tmp_path,
        [result(5, 1.0, agent_ids=subset, terminated=True)],
        agent_ids=subset,
        episodes=1,
    )
    summaries = trainer.train()

    assert trainer.agent_ids == subset
    assert len(trainer.agents) == 2
    assert environments[0].config.agent_ids == subset
    assert summaries[0].combined_total_reward == pytest.approx(2.0)


def test_agent_ids_are_normalized_to_corridor_order():
    config = MultiAgentQLearningConfig(agent_ids=("A29", "A9", "A20"))
    assert config.agent_ids == ("A9", "A20", "A29")


def test_mismatched_agent_overrides_are_rejected():
    config = MultiAgentQLearningConfig(agent_ids=("A19", "A20"))
    with pytest.raises(ValueError, match="Missing learners"):
        MultiAgentQLearningTrainer(config, agents={"A19": QLearningAgent()})
    with pytest.raises(ValueError, match="unconfigured agents"):
        MultiAgentQLearningTrainer(
            config,
            agents={
                "A19": QLearningAgent(),
                "A20": QLearningAgent(),
                "A9": QLearningAgent(),
            },
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"agent_ids": ()},
        {"agent_ids": ("A19", "A19")},
        {"agent_ids": ("NOPE",)},
        {"agent_ids": "A19"},
        {"episodes": 0},
        {"episode_seconds": 0},
        {"decision_interval_seconds": 0},
        {"checkpoint_interval": 0},
        {"mode": "sideways"},
        {"resume": True, "mode": "evaluate", "checkpoint_path": Path("x.json")},
        {"resume": True, "checkpoint_path": None},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MultiAgentQLearningConfig(**kwargs)


class _RecordingTrainer:
    """Capture the config the CLI builds without running any simulation."""

    instances: list["_RecordingTrainer"] = []

    def __init__(self, config, **kwargs):
        self.config = config
        self.trained = False
        self.evaluated = False
        _RecordingTrainer.instances.append(self)

    def train(self):
        self.trained = True
        return ()

    def evaluate(self):
        self.evaluated = True
        return ()


@pytest.fixture
def cli(monkeypatch):
    """Import the runner script and stub out its trainer."""
    import scripts.run_multi_agent_q_learning as module

    _RecordingTrainer.instances = []
    monkeypatch.setattr(module, "MultiAgentQLearningTrainer", _RecordingTrainer)
    return module


def test_cli_train_builds_a_full_corridor_config(cli, monkeypatch, tmp_path):
    checkpoint = tmp_path / "cli.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multi_agent_q_learning.py",
            "train",
            "--scenario",
            "low",
            "--episodes",
            "3",
            "--checkpoint",
            str(checkpoint),
        ],
    )
    assert cli.main() == 0

    trainer = _RecordingTrainer.instances[-1]
    assert trainer.trained
    assert trainer.config.mode == "train"
    assert trainer.config.agent_ids == ALL_AGENTS
    assert trainer.config.episodes == 3
    assert trainer.config.scenario == "low"
    assert trainer.config.checkpoint_path == checkpoint


def test_cli_evaluate_runs_exactly_one_episode(cli, monkeypatch, tmp_path):
    """Evaluation is greedy on a fixed seed -- extra episodes would only
    append identical duplicate rows to results/experiments.csv."""
    checkpoint = tmp_path / "cli.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multi_agent_q_learning.py",
            "evaluate",
            "--scenario",
            "low",
            "--checkpoint",
            str(checkpoint),
        ],
    )
    assert cli.main() == 0

    trainer = _RecordingTrainer.instances[-1]
    assert trainer.evaluated
    assert trainer.config.mode == "evaluate"
    assert trainer.config.episodes == 1


def test_cli_agents_flag_selects_a_subset(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multi_agent_q_learning.py",
            "train",
            "--checkpoint",
            str(tmp_path / "cli.json"),
            "--agents",
            "A20",
            "A19",
        ],
    )
    assert cli.main() == 0
    assert _RecordingTrainer.instances[-1].config.agent_ids == ("A19", "A20")

def spatial_trainer(
    tmp_path: Path,
    results,
    *,
    mode="train",
    agent_ids=ALL_AGENTS,
    episodes=1,
    neighbor_limit=2,
    q_learning_config=None,
):
    """Build a trainer whose agents also observe their nearest neighbors."""
    environments = []

    def factory(config, on_raw_step=None):
        environment = FakeEnvironment(config, results, agent_ids=agent_ids)
        environments.append(environment)
        return environment

    config = MultiAgentQLearningConfig(
        agent_ids=agent_ids,
        scenario="low",
        episodes=episodes,
        episode_seconds=10,
        decision_interval_seconds=5,
        checkpoint_path=tmp_path / "spatial.json",
        mode=mode,
        spatial_observations=True,
        spatial_neighbor_limit=neighbor_limit,
    )
    trainer = MultiAgentQLearningTrainer(
        config,
        environment_factory=factory,
        q_learning_config=q_learning_config,
    )
    return trainer, environments


def congested_result(congested_agents, *, time=5.0, terminated=True):
    """Build a step result where only the named agents hold a long queue."""
    return MultiAgentStepResult(
        observations={
            agent_id: observation(
                agent_id,
                time,
                queue=9 if agent_id in congested_agents else 0,
            )
            for agent_id in ALL_AGENTS
        },
        rewards={agent_id: 0.0 for agent_id in ALL_AGENTS},
        terminated=terminated,
        truncated=False,
        info={"simulation_time": time, "action_results": {}},
    )


def test_local_runs_keep_states_free_of_neighbor_features(tmp_path):
    """The independent baseline must stay exactly as it was."""
    trainer, _ = make_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        episodes=1,
    )
    assert trainer.controller_name == CONTROLLER_NAME
    assert all(
        neighbor_ids == ()
        for neighbor_ids in trainer.neighbor_ids_by_agent.values()
    )
    try:
        states = trainer.reset()
        assert all(state.neighbor_queue_flags == () for state in states.values())
    finally:
        trainer.close()


def test_spatial_agents_observe_their_nearest_neighbors(tmp_path):
    trainer, _ = spatial_trainer(tmp_path, [result(5, 1.0, terminated=True)])

    assert trainer.controller_name == SPATIAL_CONTROLLER_NAME
    assert trainer.neighbor_ids_by_agent == {
        agent_id: nearest_neighbor_ids(
            SELECTED_CORRIDOR,
            agent_id,
            limit=2,
            observed_agent_ids=ALL_AGENTS,
        )
        for agent_id in ALL_AGENTS
    }
    try:
        states = trainer.reset()
        for agent_id in ALL_AGENTS:
            assert len(states[agent_id].neighbor_queue_flags) == len(
                trainer.neighbor_ids_by_agent[agent_id]
            )
    finally:
        trainer.close()


def test_neighbor_congestion_reaches_the_observing_agent(tmp_path):
    """A19 watches A18 and A26, so a queue at A26 must show up in its state."""
    trainer, _ = spatial_trainer(tmp_path, [congested_result(("A26",))])
    assert trainer.neighbor_ids_by_agent["A19"] == ("A18", "A26")
    try:
        trainer.reset()
        decision = trainer.step(training=True)
    finally:
        trainer.close()

    # The A19 junction itself is empty in this step; only the shared flag moved.
    assert decision.states["A19"].total_queue_bucket == 0
    assert decision.states["A19"].neighbor_queue_flags == (0, 1)
    # A24 only watches A25, which is quiet.
    assert decision.states["A24"].neighbor_queue_flags == (0,)


def test_spatial_states_separate_otherwise_identical_local_traffic(tmp_path):
    """Same local queues, different neighborhoods -- different table keys."""
    quiet_trainer, _ = spatial_trainer(tmp_path, [congested_result(())])
    busy_trainer, _ = spatial_trainer(tmp_path, [congested_result(("A26",))])

    try:
        quiet_trainer.reset()
        quiet = quiet_trainer.step(training=True).states["A19"]
        busy_trainer.reset()
        busy = busy_trainer.step(training=True).states["A19"]
    finally:
        quiet_trainer.close()
        busy_trainer.close()

    assert quiet.total_queue_bucket == busy.total_queue_bucket
    assert quiet != busy


def test_neighbor_limit_bounds_the_shared_state(tmp_path):
    """A26 has six neighbors; one flag each would multiply its table by 64."""
    trainer, _ = spatial_trainer(tmp_path, [], neighbor_limit=1)
    assert trainer.neighbor_ids_by_agent["A26"] == ("A20",)
    assert all(
        len(neighbor_ids) <= 1
        for neighbor_ids in trainer.neighbor_ids_by_agent.values()
    )


def test_spatial_subset_only_observes_controlled_agents(tmp_path):
    """A subset run must not read a junction the environment is not stepping."""
    subset = ("A19", "A26")
    trainer, _ = spatial_trainer(
        tmp_path,
        [result(5, 1.0, agent_ids=subset, terminated=True)],
        agent_ids=subset,
    )
    assert trainer.neighbor_ids_by_agent == {"A19": ("A26",), "A26": ("A19",)}
    summaries = trainer.train()
    assert summaries[0].decision_steps == 1


def test_spatial_agents_with_no_observed_neighbor_stay_local(tmp_path):
    trainer, _ = spatial_trainer(
        tmp_path,
        [result(5, 1.0, agent_ids=("A19",), terminated=True)],
        agent_ids=("A19",),
    )
    assert trainer.neighbor_ids_by_agent == {"A19": ()}
    try:
        states = trainer.reset()
        assert states["A19"].neighbor_queue_flags == ()
    finally:
        trainer.close()


def test_spatial_evaluation_is_labelled_apart_from_the_local_baseline(
    tmp_path, monkeypatch
):
    """Acceptance criterion: spatial results are comparable to local ones."""
    written = []
    monkeypatch.setattr(
        "src.training.multi_agent_q_learning.append_result",
        lambda metrics, *args, **kwargs: written.append(metrics),
    )

    trainer, _ = spatial_trainer(tmp_path, [result(5, 1.0, terminated=True)])
    trainer.train()
    evaluator, _ = spatial_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        mode="evaluate",
    )
    evaluator.evaluate()

    assert len(written) == 1
    assert written[0].controller == "multi_agent_spatial_rl"
    assert written[0].controller != CONTROLLER_NAME


def test_spatial_checkpoints_round_trip_with_their_neighbor_flags(tmp_path):
    trainer, _ = spatial_trainer(
        tmp_path,
        [congested_result(("A26",))],
        q_learning_config=QLearningConfig(
            alpha=1.0,
            epsilon=0.0,
            minimum_epsilon=0.0,
        ),
    )
    trainer.train()
    expected = {
        agent_id: dict(agent.q_table)
        for agent_id, agent in trainer.agents.items()
    }
    assert any(
        state.neighbor_queue_flags for state, _ in trainer.agents["A19"].q_table
    )

    restored, _ = spatial_trainer(
        tmp_path,
        [congested_result(("A26",))],
        mode="evaluate",
    )
    restored.load_checkpoint()
    for agent_id in ALL_AGENTS:
        assert dict(restored.agents[agent_id].q_table) == expected[agent_id]

    payload = json.loads((tmp_path / "spatial.json").read_text())
    assert payload["controller"] == SPATIAL_CONTROLLER_NAME
    assert payload["spatial_neighbor_ids"]["A19"] == ["A18", "A26"]


def test_local_and_spatial_checkpoints_are_not_interchangeable(tmp_path):
    """Their Q-table keys mean different things, so mixing them is refused."""
    spatial, _ = spatial_trainer(tmp_path, [result(5, 1.0, terminated=True)])
    spatial.train()

    local = MultiAgentQLearningTrainer(
        MultiAgentQLearningConfig(
            scenario="low",
            mode="evaluate",
            checkpoint_path=tmp_path / "spatial.json",
        )
    )
    with pytest.raises(ValueError, match="controller"):
        local.load_checkpoint()


def test_checkpoint_from_a_different_neighborhood_is_refused(tmp_path):
    """Changing the neighbor limit changes what every stored state means."""
    trainer, _ = spatial_trainer(tmp_path, [result(5, 1.0, terminated=True)])
    trainer.train()

    widened, _ = spatial_trainer(
        tmp_path,
        [result(5, 1.0, terminated=True)],
        mode="evaluate",
        neighbor_limit=3,
    )
    with pytest.raises(ValueError, match="different"):
        widened.load_checkpoint()


def test_a_preconfigured_spatial_encoder_is_rejected():
    """Neighbors are per-agent, so one shared spatial encoder is a bug."""
    config = MultiAgentQLearningConfig(
        agent_ids=("A19", "A26"),
        spatial_observations=True,
    )
    with pytest.raises(ValueError, match="must not be configured"):
        MultiAgentQLearningTrainer(
            config,
            encoder=TrafficStateEncoder(neighbor_ids=("A26",)),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spatial_observations": "yes"},
        {"spatial_neighbor_limit": 0},
        {"spatial_neighbor_limit": -1},
        {"spatial_neighbor_limit": 1.5},
    ],
)
def test_invalid_spatial_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MultiAgentQLearningConfig(**kwargs)


def test_cli_enables_spatial_observations(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multi_agent_q_learning.py",
            "train",
            "--checkpoint",
            str(tmp_path / "cli.json"),
            "--spatial-observations",
            "--neighbor-limit",
            "3",
        ],
    )
    assert cli.main() == 0

    trainer = _RecordingTrainer.instances[-1]
    assert trainer.config.spatial_observations is True
    assert trainer.config.spatial_neighbor_limit == 3


def test_cli_defaults_to_purely_local_observations(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_multi_agent_q_learning.py",
            "train",
            "--checkpoint",
            str(tmp_path / "cli.json"),
        ],
    )
    assert cli.main() == 0
    assert _RecordingTrainer.instances[-1].config.spatial_observations is False

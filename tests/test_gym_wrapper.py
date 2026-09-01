"""Unit tests for the Gymnasium and PettingZoo wrappers.

The wrappers are exercised against a fake `MultiAgentTrafficEnvironment`, so
these tests never start SUMO. The two standard compliance suites -- PettingZoo's
`parallel_api_test` and Gymnasium's `check_env` -- run here as well, because
what they check is the wrapper's API contract, not the traffic simulation
behind it. `scripts/check_gym_wrapper.py` runs the same two suites against real
SUMO.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest
from gymnasium import spaces
from gymnasium.utils.env_checker import check_env
from pettingzoo.test import parallel_api_test

import src.environment.gym_wrapper as gym_wrapper
from src.environment.actions import ActionResult, ActionStatus, TrafficAction
from src.environment.gym_wrapper import (
    AgentSpaceSpec,
    CorridorParallelEnv,
    SingleAgentTrafficEnv,
    audited_space_specs,
    observation_vector,
)
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentStepResult,
)
from src.environment.observations import (
    ObservationNormalizationConfig,
    TrafficObservation,
)
from src.environment.rewards import RewardBreakdown
from src.environment.selected_corridor import SELECTED_CORRIDOR


LANE_COUNT = 3
PHASE_COUNT = 4
EPISODE_STEPS = 4


def _specs(agent_ids: tuple[str, ...]) -> dict[str, AgentSpaceSpec]:
    """Return uniform fake observation shapes for the given agents."""
    return {
        agent_id: AgentSpaceSpec(
            agent_id=agent_id,
            lane_count=LANE_COUNT,
            phase_count=PHASE_COUNT,
        )
        for agent_id in agent_ids
    }


class FakeSignal:
    """TrafficSignal-like source of the metadata the wrapper reads."""

    def __init__(self, agent_id: str, lane_count: int, phase_count: int) -> None:
        self.agent_id = agent_id
        self.phase_count = phase_count
        self.incoming_lane_ids = tuple(
            f"{agent_id}_lane_{index}" for index in range(lane_count)
        )

    def normalization_config(
        self,
        base_config: ObservationNormalizationConfig | None = None,
    ) -> ObservationNormalizationConfig:
        """Return caps with one speed cap per fake lane."""
        config = base_config or ObservationNormalizationConfig()
        return replace(
            config,
            lane_speed_caps=(13.89,) * len(self.incoming_lane_ids),
        )


class FakeEnvironment:
    """Deterministic stand-in for `MultiAgentTrafficEnvironment`."""

    instances: list[FakeEnvironment] = []

    def __init__(
        self,
        config: MultiAgentEnvironmentConfig,
        *,
        lane_count: int = LANE_COUNT,
        phase_count: int = PHASE_COUNT,
        episode_steps: int = EPISODE_STEPS,
        terminate: bool = True,
    ) -> None:
        self.config = config
        self.lane_count = lane_count
        self.phase_count = phase_count
        self.episode_steps = episode_steps
        self.terminate = terminate
        self.applied_actions: list[dict[str, TrafficAction]] = []
        self.close_calls = 0
        self.decision_step = 0
        self._signals: dict[str, FakeSignal] = {}
        FakeEnvironment.instances.append(self)

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Return the configured agents."""
        return self.config.agent_ids

    @property
    def traffic_signals(self) -> Mapping[str, FakeSignal]:
        """Return the fake wrappers created by the last reset."""
        return MappingProxyType(dict(self._signals))

    def _observation(self, agent_id: str) -> TrafficObservation:
        """Return one deterministic observation for the current step."""
        queue = self.decision_step % 3
        return TrafficObservation(
            agent_id=agent_id,
            traffic_light_id=SELECTED_CORRIDOR.agent_to_traffic_light[agent_id],
            simulation_time=float(self.decision_step * 5),
            incoming_lane_ids=self._signals[agent_id].incoming_lane_ids,
            queue_lengths=(queue,) * self.lane_count,
            vehicle_counts=(queue + 1,) * self.lane_count,
            mean_waiting_times=(float(queue),) * self.lane_count,
            mean_speeds=(1.5,) * self.lane_count,
            current_phase_index=self.decision_step % self.phase_count,
            current_phase_state="GG",
            current_phase_elapsed_seconds=float(self.decision_step),
            is_green_phase=True,
            is_transition_phase=False,
        )

    def reset(self) -> Mapping[str, TrafficObservation]:
        """Start a fake episode and return the first observations."""
        self.decision_step = 0
        self._signals = {
            agent_id: FakeSignal(agent_id, self.lane_count, self.phase_count)
            for agent_id in self.agent_ids
        }
        return MappingProxyType(
            {agent_id: self._observation(agent_id) for agent_id in self.agent_ids}
        )

    def step(
        self,
        actions: Mapping[str, TrafficAction],
    ) -> MultiAgentStepResult:
        """Record actions and return a deterministic transition."""
        self.applied_actions.append(dict(actions))
        self.decision_step += 1
        finished = self.decision_step >= self.episode_steps
        observations = {
            agent_id: self._observation(agent_id) for agent_id in self.agent_ids
        }
        action_results = {
            agent_id: ActionResult(
                requested_action=action,
                status=(
                    ActionStatus.KEPT
                    if action is TrafficAction.KEEP
                    else ActionStatus.APPLIED
                ),
                previous_phase_index=0,
                resulting_phase_index=int(action),
                phase_changed=action is TrafficAction.NEXT_GREEN,
                message="fake action result",
            )
            for agent_id, action in actions.items()
        }
        breakdowns = {
            agent_id: RewardBreakdown(
                queue_component=-1.0,
                waiting_component=-0.5,
                switch_component=0.0,
                total_reward=-1.5,
            )
            for agent_id in self.agent_ids
        }
        return MultiAgentStepResult(
            observations=MappingProxyType(observations),
            rewards=MappingProxyType(
                {agent_id: -1.5 for agent_id in self.agent_ids}
            ),
            terminated=finished and self.terminate,
            truncated=finished and not self.terminate,
            info=MappingProxyType(
                {
                    "simulation_time": float(self.decision_step * 5),
                    "decision_step": self.decision_step,
                    "action_results": MappingProxyType(action_results),
                    "local_reward_breakdowns": MappingProxyType(breakdowns),
                }
            ),
        )

    def close(self) -> None:
        """Record a close request."""
        self.close_calls += 1


def make_parallel(
    agent_ids: tuple[str, ...] = ("A19", "A26"),
    **environment_kwargs: Any,
) -> CorridorParallelEnv:
    """Build a parallel wrapper backed by the fake environment."""
    config = MultiAgentEnvironmentConfig(agent_ids=agent_ids)
    return CorridorParallelEnv(
        config,
        space_specs=_specs(config.agent_ids),
        environment_factory=lambda resolved: FakeEnvironment(
            resolved,
            **environment_kwargs,
        ),
    )


def make_single_agent(
    agent_id: str = "A19",
    **environment_kwargs: Any,
) -> SingleAgentTrafficEnv:
    """Build a single-agent wrapper backed by the fake environment."""
    return SingleAgentTrafficEnv(
        agent_id,
        space_specs=_specs((agent_id,)),
        environment_factory=lambda resolved: FakeEnvironment(
            resolved,
            **environment_kwargs,
        ),
    )


def test_audited_specs_cover_every_selected_agent() -> None:
    """Every corridor agent can be sized without starting SUMO."""
    specs = audited_space_specs()
    assert tuple(specs) == SELECTED_CORRIDOR.agent_ids
    assert all(spec.lane_count > 0 for spec in specs.values())
    assert all(spec.phase_count > 0 for spec in specs.values())


def test_feature_count_matches_normalized_features() -> None:
    """The declared space length equals what the observation actually returns."""
    spec = AgentSpaceSpec(
        agent_id="A19",
        lane_count=LANE_COUNT,
        phase_count=PHASE_COUNT,
    )
    observation = FakeEnvironment(
        MultiAgentEnvironmentConfig(agent_ids=("A19",))
    )
    observations = observation.reset()
    features = observations["A19"].normalized_features(PHASE_COUNT)
    assert len(features) == spec.feature_count
    assert spec.feature_count == 4 * LANE_COUNT + 1 + PHASE_COUNT


def test_audited_spec_matches_normalized_features_for_a19() -> None:
    """The audited A19 shape is the shape an A19 observation produces."""
    spec = audited_space_specs(("A19",))["A19"]
    lane_ids = tuple(f"A19_lane_{index}" for index in range(spec.lane_count))
    observation = TrafficObservation(
        agent_id="A19",
        traffic_light_id=SELECTED_CORRIDOR.agent_to_traffic_light["A19"],
        simulation_time=0.0,
        incoming_lane_ids=lane_ids,
        queue_lengths=(0,) * spec.lane_count,
        vehicle_counts=(0,) * spec.lane_count,
        mean_waiting_times=(0.0,) * spec.lane_count,
        mean_speeds=(0.0,) * spec.lane_count,
        current_phase_index=0,
        current_phase_state="GG",
        current_phase_elapsed_seconds=0.0,
        is_green_phase=True,
        is_transition_phase=False,
    )
    assert len(observation.normalized_features(spec.phase_count)) == spec.feature_count


@pytest.mark.parametrize(
    ("lane_count", "phase_count"),
    ((0, 4), (3, 0), (-1, 4), (3, -2)),
)
def test_spec_rejects_impossible_shapes(lane_count: int, phase_count: int) -> None:
    """A junction always has at least one lane and one phase."""
    with pytest.raises(ValueError, match="must be a positive integer"):
        AgentSpaceSpec(
            agent_id="A19",
            lane_count=lane_count,
            phase_count=phase_count,
        )


def test_observation_vector_rejects_wrong_feature_count() -> None:
    """A stale audit is reported instead of silently reshaping observations."""
    environment = FakeEnvironment(MultiAgentEnvironmentConfig(agent_ids=("A19",)))
    observation = environment.reset()["A19"]
    wrong_spec = AgentSpaceSpec(
        agent_id="A19",
        lane_count=LANE_COUNT + 1,
        phase_count=PHASE_COUNT,
    )
    with pytest.raises(ValueError, match="observation features"):
        observation_vector(observation, wrong_spec)


def test_spaces_are_bounded_ratios_and_two_discrete_actions() -> None:
    """Observations are clipped ratios; actions are exactly KEEP and NEXT_GREEN."""
    environment = make_parallel()
    observation_space = environment.observation_space("A19")
    assert isinstance(observation_space, spaces.Box)
    assert observation_space.dtype == np.float32
    assert observation_space.shape == (4 * LANE_COUNT + 1 + PHASE_COUNT,)
    assert float(observation_space.low.min()) == 0.0
    assert float(observation_space.high.max()) == 1.0

    action_space = environment.action_space("A19")
    assert isinstance(action_space, spaces.Discrete)
    assert action_space.n == len(TrafficAction) == 2


def test_spaces_are_the_same_object_on_every_lookup() -> None:
    """PettingZoo requires identical space objects so seeding works."""
    environment = make_parallel()
    assert environment.observation_space("A19") is environment.observation_space("A19")
    assert environment.action_space("A19") is environment.action_space("A19")


def test_unknown_agent_space_lookup_is_reported() -> None:
    """Asking for an uncontrolled agent names the controlled ones."""
    environment = make_parallel(agent_ids=("A19",))
    with pytest.raises(ValueError, match="Unknown agent 'A26'"):
        environment.observation_space("A26")


def test_reset_returns_one_observation_and_info_per_agent() -> None:
    """Reset follows the parallel API: observation and info dicts by agent."""
    environment = make_parallel()
    observations, infos = environment.reset()
    assert set(observations) == set(environment.agents) == {"A19", "A26"}
    assert set(infos) == {"A19", "A26"}
    for agent_id, observation in observations.items():
        assert environment.observation_space(agent_id).contains(observation)


def test_step_translates_integer_actions_into_traffic_actions() -> None:
    """Library-sampled integers reach the environment as safe actions."""
    environment = make_parallel()
    environment.reset()
    environment.step({"A19": 0, "A26": np.int64(1)})
    applied = FakeEnvironment.instances[-1].applied_actions[-1]
    assert applied == {
        "A19": TrafficAction.KEEP,
        "A26": TrafficAction.NEXT_GREEN,
    }


@pytest.mark.parametrize("action", (2, -1))
def test_step_rejects_actions_outside_the_action_space(action: int) -> None:
    """Only the two documented actions are accepted."""
    environment = make_parallel(agent_ids=("A19",))
    environment.reset()
    with pytest.raises(ValueError, match="outside the discrete"):
        environment.step({"A19": action})


def test_step_rejects_missing_and_unknown_agents() -> None:
    """The parallel API requires exactly one action per live agent."""
    environment = make_parallel()
    environment.reset()
    with pytest.raises(ValueError, match="missing live agents: A26"):
        environment.step({"A19": 0})
    environment.reset()
    with pytest.raises(ValueError, match="not live: A29"):
        environment.step({"A19": 0, "A26": 0, "A29": 0})


def test_terminated_episode_empties_the_agent_list() -> None:
    """A finished episode reports no live agents until the next reset."""
    environment = make_parallel(episode_steps=2)
    environment.reset()
    environment.step({"A19": 0, "A26": 0})
    _, _, terminations, truncations, _ = environment.step({"A19": 0, "A26": 0})
    assert all(terminations.values())
    assert not any(truncations.values())
    assert environment.agents == []
    assert environment.step({}) == ({}, {}, {}, {}, {})


def test_max_cycles_truncates_a_long_episode() -> None:
    """The optional cycle limit truncates without claiming termination."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment = CorridorParallelEnv(
        config,
        max_cycles=2,
        space_specs=_specs(config.agent_ids),
        environment_factory=lambda resolved: FakeEnvironment(
            resolved,
            episode_steps=100,
        ),
    )
    environment.reset()
    environment.step({"A19": 0})
    _, _, terminations, truncations, _ = environment.step({"A19": 0})
    assert not any(terminations.values())
    assert all(truncations.values())
    assert environment.agents == []


def test_step_info_reports_the_safety_outcome_of_each_action() -> None:
    """Rejected and forced phase changes stay visible to the training loop."""
    environment = make_parallel(agent_ids=("A19",))
    environment.reset()
    _, _, _, _, infos = environment.step({"A19": 1})
    assert infos["A19"]["action_status"] == ActionStatus.APPLIED.value
    assert infos["A19"]["phase_changed"] is True
    assert infos["A19"]["local_reward"] == pytest.approx(-1.5)


def test_reset_seed_selects_a_generated_scenario_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seed with generated demand becomes the episode's demand seed."""
    monkeypatch.setattr(
        gym_wrapper,
        "_generated_scenario_exists",
        lambda config: True,
    )
    environment = make_parallel(agent_ids=("A19",))
    environment.reset(seed=7)
    assert environment.config.seed == 7
    assert FakeEnvironment.instances[-1].config.seed == 7


def test_reset_seed_without_generated_demand_warns_and_keeps_the_scenario() -> None:
    """Libraries seed freely, so an ungenerated seed warns instead of failing."""
    environment = make_parallel(agent_ids=("A19",))
    with pytest.warns(UserWarning, match="no demand has been generated"):
        environment.reset(seed=123456)
    assert environment.config.seed == 42
    assert FakeEnvironment.instances[-1].config.seed == 42


def test_close_releases_the_wrapped_environment() -> None:
    """Closing the wrapper closes SUMO exactly once."""
    environment = make_parallel(agent_ids=("A19",))
    environment.reset()
    created = FakeEnvironment.instances[-1]
    environment.close()
    assert created.close_calls == 1
    assert environment.agents == []


def test_live_program_mismatch_is_reported_at_reset() -> None:
    """A space sized for the wrong program fails loudly before training."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment = CorridorParallelEnv(
        config,
        space_specs={
            "A19": AgentSpaceSpec(
                agent_id="A19",
                lane_count=LANE_COUNT,
                phase_count=PHASE_COUNT + 1,
            )
        },
        environment_factory=FakeEnvironment,
    )
    with pytest.raises(ValueError, match="observation space was sized for"):
        environment.reset()


def test_parallel_environment_passes_the_pettingzoo_api_test() -> None:
    """The wrapper satisfies PettingZoo's parallel API contract."""
    parallel_api_test(make_parallel(), num_cycles=EPISODE_STEPS + 2)


def test_single_agent_environment_passes_the_gymnasium_checker() -> None:
    """The wrapper satisfies Gymnasium's environment checker."""
    check_env(make_single_agent(episode_steps=1000), skip_render_check=True)


def test_single_agent_environment_returns_the_gymnasium_step_tuple() -> None:
    """One agent is controlled and the other traffic lights are left alone."""
    environment = make_single_agent(episode_steps=2)
    observation, info = environment.reset()
    assert environment.observation_space.contains(observation)
    assert info == {}
    assert environment.config.agent_ids == ("A19",)

    observation, reward, terminated, truncated, info = environment.step(1)
    assert environment.observation_space.contains(observation)
    assert reward == pytest.approx(-1.5)
    assert terminated is False
    assert truncated is False
    assert info["action_status"] == ActionStatus.APPLIED.value

    _, _, terminated, _, _ = environment.step(0)
    assert terminated is True
    with pytest.raises(RuntimeError, match="episode is complete"):
        environment.step(0)


def test_single_agent_environment_rejects_an_uncontrolled_agent() -> None:
    """Only corridor agents can be wrapped."""
    with pytest.raises(ValueError, match="Unknown selected agent IDs"):
        SingleAgentTrafficEnv("A99")

"""Focused unit tests for the SUMO multi-agent environment orchestrator.

The tests use fake TraCI and TrafficSignal objects and never start SUMO.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.environment.multi_agent_environment as environment_module
from src.environment.actions import (
    ActionResult,
    ActionStatus,
    TrafficAction,
)
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentTrafficEnvironment,
)
from src.environment.observations import TrafficObservation
from src.environment.rewards import RewardBreakdown, RewardWeights


class FakeSimulation:
    """Mutable simulation domain with deterministic counters."""

    def __init__(
        self,
        expected_count: int = 10,
        natural_completion_step: int | None = None,
    ) -> None:
        self.initial_expected_count = expected_count
        self.expected_count = expected_count
        self.natural_completion_step = natural_completion_step
        self.time = 0.0
        self.step_length = 1.0
        self.step_calls = 0

    def reset(self, step_length: float) -> None:
        """Reset one fake episode."""
        self.expected_count = self.initial_expected_count
        self.time = 0.0
        self.step_length = step_length
        self.step_calls = 0

    def advance(self) -> None:
        """Advance one configured fake SUMO step."""
        self.time += self.step_length
        self.step_calls += 1
        if (
            self.natural_completion_step is not None
            and self.step_calls >= self.natural_completion_step
        ):
            self.expected_count = 0

    def getTime(self) -> float:  # noqa: N802
        """Return current simulated time."""
        return self.time

    def getMinExpectedNumber(self) -> int:  # noqa: N802
        """Return active and future fake vehicles."""
        return self.expected_count

    def getDepartedNumber(self) -> int:  # noqa: N802
        """Return one departure per simulated step."""
        return 1

    def getArrivedNumber(self) -> int:  # noqa: N802
        """Return one arrival every second step."""
        return int(self.step_calls % 2 == 0)


class FakeVehicleDomain:
    """Expose active vehicles for the optional halted count."""

    def getIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return two active fake vehicles."""
        return ("halted", "moving")

    def getSpeed(self, vehicle_id: str) -> float:  # noqa: N802
        """Return one halted and one moving speed."""
        return 0.0 if vehicle_id == "halted" else 10.0


class FakeTraCI:
    """TraCI-like module that records lifecycle and stepping calls."""

    def __init__(
        self,
        expected_count: int = 10,
        natural_completion_step: int | None = None,
    ) -> None:
        self.simulation = FakeSimulation(
            expected_count=expected_count,
            natural_completion_step=natural_completion_step,
        )
        self.vehicle = FakeVehicleDomain()
        self.trafficlight = SimpleNamespace()
        self.lane = SimpleNamespace()
        self.start_commands: list[tuple[str, ...]] = []
        self.close_calls = 0

    def start(self, command: list[str]) -> None:
        """Record startup and reset the fake episode clock."""
        self.start_commands.append(tuple(command))
        step_length_index = command.index("--step-length") + 1
        self.simulation.reset(float(command[step_length_index]))

    def simulationStep(self) -> None:  # noqa: N802
        """Advance one fake simulation step."""
        self.simulation.advance()

    def close(self) -> None:
        """Record a close request."""
        self.close_calls += 1


class FakeTrafficSignal:
    """TrafficSignal-like wrapper with isolated action and observation state."""

    def __init__(
        self,
        *,
        agent_id: str,
        traffic_light_id: str,
        traci_connection: FakeTraCI,
        reward_weights: RewardWeights,
        factory: FakeTrafficSignalFactory,
        **_: object,
    ) -> None:
        self.agent_id = agent_id
        self.traffic_light_id = traffic_light_id
        self._traci = traci_connection
        self._reward_weights = reward_weights
        self._factory = factory
        self.actions: list[TrafficAction] = []
        self.synchronize_calls = 0
        self.observe_calls = 0
        self.fail_observe = False

    def apply_action(self, action: TrafficAction) -> ActionResult:
        """Record and return a configured safety result."""
        self.actions.append(action)
        status = self._factory.status_by_agent.get(
            self.agent_id,
            ActionStatus.KEPT if action is TrafficAction.KEEP else ActionStatus.APPLIED,
        )
        phase_changed = status in {
            ActionStatus.APPLIED,
            ActionStatus.FORCED_MAXIMUM_GREEN,
        }
        return ActionResult(
            requested_action=action,
            status=status,
            previous_phase_index=0,
            resulting_phase_index=1 if phase_changed else 0,
            phase_changed=phase_changed,
            message="fake action result",
        )

    def synchronize(self) -> None:
        """Record explicit environment synchronization."""
        self.synchronize_calls += 1

    def observe(self) -> TrafficObservation:
        """Return one deterministic observation for this agent."""
        self.observe_calls += 1
        if self.fail_observe:
            raise RuntimeError("fake observation failure")
        queue_length = self._factory.queue_by_agent.get(self.agent_id, 1)
        is_transition = self.agent_id in self._factory.transition_agents
        return TrafficObservation(
            agent_id=self.agent_id,
            traffic_light_id=self.traffic_light_id,
            simulation_time=self._traci.simulation.getTime(),
            incoming_lane_ids=(f"{self.agent_id}_lane",),
            queue_lengths=(queue_length,),
            vehicle_counts=(queue_length,),
            mean_waiting_times=(0.0,),
            mean_speeds=(0.0,),
            current_phase_index=1 if is_transition else 0,
            current_phase_state="yy" if is_transition else "GG",
            current_phase_elapsed_seconds=0.0,
            is_green_phase=not is_transition,
            is_transition_phase=is_transition,
        )

    def calculate_local_reward(
        self,
        observation: TrafficObservation,
        phase_switched: bool = False,
    ) -> RewardBreakdown:
        """Return a predictable local reward breakdown."""
        queue_component = (
            -self._reward_weights.queue_weight * sum(observation.queue_lengths)
        )
        switch_component = (
            -self._reward_weights.switch_penalty_weight * int(phase_switched)
        )
        total = queue_component + switch_component
        return RewardBreakdown(
            queue_component=queue_component,
            waiting_component=0.0,
            switch_component=switch_component,
            total_reward=total,
        )


class FakeTrafficSignalFactory:
    """Construct fake wrappers and retain them by agent."""

    def __init__(
        self,
        queue_by_agent: dict[str, int] | None = None,
        fail_agent: str | None = None,
    ) -> None:
        self.queue_by_agent = queue_by_agent or {}
        self.fail_agent = fail_agent
        self.status_by_agent: dict[str, ActionStatus] = {}
        self.transition_agents: set[str] = set()
        self.signals: dict[str, FakeTrafficSignal] = {}
        self.created_agent_ids: list[str] = []

    def __call__(self, **kwargs: Any) -> FakeTrafficSignal:
        """Create one fake signal or raise at the configured agent."""
        agent_id = str(kwargs["agent_id"])
        self.created_agent_ids.append(agent_id)
        if agent_id == self.fail_agent:
            raise RuntimeError("fake wrapper initialization failure")
        signal = FakeTrafficSignal(factory=self, **kwargs)
        self.signals[agent_id] = signal
        return signal


def make_environment(
    config: MultiAgentEnvironmentConfig,
    *,
    traci: FakeTraCI | None = None,
    factory: FakeTrafficSignalFactory | None = None,
) -> tuple[
    MultiAgentTrafficEnvironment,
    FakeTraCI,
    FakeTrafficSignalFactory,
]:
    """Build an environment with injected fakes."""
    fake_traci = traci or FakeTraCI()
    fake_factory = factory or FakeTrafficSignalFactory()
    environment = MultiAgentTrafficEnvironment(
        config,
        traci_connection=fake_traci,
        traffic_signal_factory=fake_factory,
        sumo_executable=Path("sumo"),
    )
    return environment, fake_traci, fake_factory


@pytest.mark.parametrize("scenario", ("unknown", "", "very_high"))
def test_config_rejects_invalid_scenario(scenario: str) -> None:
    """Only the three canonical scenario names are accepted."""
    with pytest.raises(ValueError, match="Unknown traffic-demand scenario"):
        MultiAgentEnvironmentConfig(scenario=scenario)


@pytest.mark.parametrize("seed", (-1, 1.5, True))
def test_config_rejects_invalid_seed(seed: object) -> None:
    """Seeds must be non-negative integers."""
    with pytest.raises(ValueError, match="seed must be a non-negative integer"):
        MultiAgentEnvironmentConfig(seed=seed)  # type: ignore[arg-type]


def test_reset_rejects_missing_scenario_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reset reports a missing generated scenario before starting SUMO."""
    missing_file = tmp_path / "missing.sumocfg"
    monkeypatch.setattr(
        environment_module,
        "scenario_output_files",
        lambda _scenario, _seed: SimpleNamespace(configuration_file=missing_file),
    )
    environment, traci, _ = make_environment(MultiAgentEnvironmentConfig())

    with pytest.raises(FileNotFoundError, match="configuration is missing"):
        environment.reset()

    assert traci.start_commands == []


def test_config_rejects_agent_outside_selected_corridor() -> None:
    """Unknown traffic-light agents are never silently accepted."""
    with pytest.raises(ValueError, match="Unknown selected agent IDs"):
        MultiAgentEnvironmentConfig(agent_ids=("A19", "A999"))


def test_config_orders_subset_by_official_corridor_order() -> None:
    """Caller order cannot change deterministic environment ordering."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A26", "A19"))
    assert config.agent_ids == ("A19", "A26")


def test_default_config_uses_all_eight_agents_in_official_order() -> None:
    """The default configuration exposes exactly the selected corridor."""
    config = MultiAgentEnvironmentConfig()
    assert config.agent_ids == (
        "A9",
        "A18",
        "A19",
        "A20",
        "A24",
        "A25",
        "A26",
        "A29",
    )


@pytest.mark.parametrize("sumo_seed", (-1, 1.5, True))
def test_config_rejects_invalid_sumo_seed(sumo_seed: object) -> None:
    """The optional SUMO seed follows the same rule as the demand seed."""
    with pytest.raises(ValueError, match="sumo_seed must be a non-negative"):
        MultiAgentEnvironmentConfig(sumo_seed=sumo_seed)  # type: ignore[arg-type]


def test_sumo_seed_defaults_to_the_demand_seed() -> None:
    """Without an explicit SUMO seed the demand seed still seeds SUMO."""
    config = MultiAgentEnvironmentConfig(seed=42, agent_ids=("A19",))
    environment, traci, _ = make_environment(config)

    environment.reset()

    command = traci.start_commands[0]
    assert config.simulation_seed == 42
    assert command[command.index("--seed") + 1] == "42"
    environment.close()


def test_sumo_seed_varies_the_simulation_without_changing_the_demand() -> None:
    """A separate SUMO seed leaves the generated scenario file untouched."""
    config = MultiAgentEnvironmentConfig(
        seed=42,
        sumo_seed=123,
        agent_ids=("A19",),
    )
    environment, traci, _ = make_environment(config)

    environment.reset()

    command = traci.start_commands[0]
    assert command[command.index("--seed") + 1] == "123"
    assert "medium_seed_42.sumocfg" in command[command.index("-c") + 1]
    environment.close()


def test_single_agent_reset_and_keep_step() -> None:
    """A19 can run alone and receives one action, observation, and reward."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, traci, factory = make_environment(config)

    observations = environment.reset()
    result = environment.step({"A19": TrafficAction.KEEP})

    assert tuple(observations) == ("A19",)
    assert factory.signals["A19"].actions == [TrafficAction.KEEP]
    assert traci.simulation.step_calls == 5
    assert factory.signals["A19"].synchronize_calls == 1
    assert tuple(result.observations) == ("A19",)
    assert tuple(result.rewards) == ("A19",)
    assert result.info["departed_vehicle_count"] == 5
    assert result.info["halted_vehicle_count"] == 1
    environment.close()


def test_single_agent_next_green_is_forwarded_once() -> None:
    """NEXT_GREEN reaches only the configured wrapper and is not duplicated."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, _, factory = make_environment(config)
    environment.reset()

    result = environment.step({"A19": TrafficAction.NEXT_GREEN})

    assert factory.signals["A19"].actions == [TrafficAction.NEXT_GREEN]
    action_results = result.info["action_results"]
    assert action_results["A19"].status is ActionStatus.APPLIED
    environment.close()


def test_minimum_green_rejection_is_preserved_in_info() -> None:
    """The environment returns the wrapper's safety result unchanged."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    factory = FakeTrafficSignalFactory()
    factory.status_by_agent["A19"] = ActionStatus.REJECTED_MINIMUM_GREEN
    environment, _, _ = make_environment(config, factory=factory)
    environment.reset()

    result = environment.step({"A19": TrafficAction.NEXT_GREEN})

    assert (
        result.info["action_results"]["A19"].status
        is ActionStatus.REJECTED_MINIMUM_GREEN
    )
    environment.close()


def test_close_is_idempotent_and_reset_can_run_again() -> None:
    """Repeated close calls are harmless and a later reset starts fresh."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, traci, _ = make_environment(config)
    environment.close()
    environment.reset()
    environment.close()
    environment.close()
    observations = environment.reset()

    assert tuple(observations) == ("A19",)
    assert len(traci.start_commands) == 2
    assert traci.close_calls == 1
    environment.close()


def test_two_agents_require_complete_action_mapping() -> None:
    """Controlled mode rejects a missing configured agent action."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
    environment, traci, _ = make_environment(config)
    environment.reset()

    with pytest.raises(ValueError, match="missing configured agents: A26"):
        environment.step({"A19": TrafficAction.KEEP})

    assert traci.close_calls == 1


def test_two_agents_reject_unknown_action_agent() -> None:
    """Controlled mode rejects action keys outside the configured subset."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
    environment, _, _ = make_environment(config)
    environment.reset()

    with pytest.raises(ValueError, match="unknown or unconfigured agents"):
        environment.step(
            {
                "A19": TrafficAction.KEEP,
                "A26": TrafficAction.KEEP,
                "A9": TrafficAction.KEEP,
            }
        )


def test_controlled_mode_rejects_invalid_action_value() -> None:
    """Only TrafficAction enum values are accepted by the environment API."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, _, _ = make_environment(config)
    environment.reset()

    with pytest.raises(ValueError, match="Invalid traffic actions"):
        environment.step({"A19": 99})  # type: ignore[dict-item]


def test_two_agent_actions_and_results_remain_isolated() -> None:
    """Each action is sent once to its matching wrapper."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A26", "A19"))
    environment, _, factory = make_environment(config)
    observations = environment.reset()

    result = environment.step(
        {
            "A19": TrafficAction.KEEP,
            "A26": TrafficAction.NEXT_GREEN,
        }
    )

    assert tuple(observations) == ("A19", "A26")
    assert factory.signals["A19"].actions == [TrafficAction.KEEP]
    assert factory.signals["A26"].actions == [TrafficAction.NEXT_GREEN]
    assert tuple(result.observations) == ("A19", "A26")
    assert tuple(result.rewards) == ("A19", "A26")
    environment.close()


def test_incomplete_actions_are_allowed_when_configured() -> None:
    """Optional partial mappings act only on explicitly named wrappers."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19", "A26"),
        require_complete_action_mappings=False,
    )
    environment, _, factory = make_environment(config)
    environment.reset()

    environment.step({"A19": TrafficAction.KEEP})

    assert factory.signals["A19"].actions == [TrafficAction.KEEP]
    assert factory.signals["A26"].actions == []
    environment.close()


def test_full_configuration_constructs_and_steps_eight_wrappers() -> None:
    """The default episode preserves all eight official agents."""
    config = MultiAgentEnvironmentConfig()
    environment, _, factory = make_environment(config)
    observations = environment.reset()
    actions = dict.fromkeys(config.agent_ids, TrafficAction.KEEP)

    result = environment.step(actions)

    assert tuple(factory.created_agent_ids) == config.agent_ids
    assert len(observations) == 8
    assert tuple(observations) == config.agent_ids
    assert len(result.observations) == 8
    assert len(result.rewards) == 8
    environment.close()


def test_local_reward_mode_returns_each_local_reward() -> None:
    """Local mode keeps each agent's own queue-based result."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19", "A26"),
        reward_mode="local",
    )
    factory = FakeTrafficSignalFactory({"A19": 10, "A26": 20})
    environment, _, _ = make_environment(config, factory=factory)
    environment.reset()

    result = environment.step(
        {"A19": TrafficAction.KEEP, "A26": TrafficAction.KEEP}
    )

    assert result.rewards == {"A19": -10.0, "A26": -20.0}
    environment.close()


def test_neighbor_aware_reward_uses_configured_neighbors() -> None:
    """A19 and A26 blend only their configured local rewards."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19", "A26"),
        reward_mode="neighbor_aware",
    )
    factory = FakeTrafficSignalFactory({"A19": 10, "A26": 20})
    environment, _, _ = make_environment(config, factory=factory)
    environment.reset()

    result = environment.step(
        {"A19": TrafficAction.KEEP, "A26": TrafficAction.KEEP}
    )

    assert result.rewards["A19"] == pytest.approx(-13.0)
    assert result.rewards["A26"] == pytest.approx(-17.0)
    environment.close()


def test_neighbor_aware_reward_falls_back_to_local_without_subset_neighbor() -> None:
    """Configured agents with no configured neighbor retain local reward."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19", "A24"),
        reward_mode="neighbor_aware",
    )
    factory = FakeTrafficSignalFactory({"A19": 10, "A24": 20})
    environment, _, _ = make_environment(config, factory=factory)
    environment.reset()

    result = environment.step(
        {"A19": TrafficAction.KEEP, "A24": TrafficAction.KEEP}
    )

    assert result.rewards == {"A19": -10.0, "A24": -20.0}
    environment.close()


def test_global_reward_mode_returns_shared_mean() -> None:
    """Global mode gives every configured agent the local arithmetic mean."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19", "A26"),
        reward_mode="global",
    )
    factory = FakeTrafficSignalFactory({"A19": 10, "A26": 20})
    environment, _, _ = make_environment(config, factory=factory)
    environment.reset()

    result = environment.step(
        {"A19": TrafficAction.KEEP, "A26": TrafficAction.KEEP}
    )

    assert result.rewards == {"A19": -15.0, "A26": -15.0}
    environment.close()


def test_step_before_reset_fails_clearly() -> None:
    """No step may run without a live episode."""
    environment, _, _ = make_environment(
        MultiAgentEnvironmentConfig(agent_ids=("A19",))
    )
    with pytest.raises(RuntimeError, match=r"reset\(\) must be called"):
        environment.step({"A19": TrafficAction.KEEP})


def test_observation_only_step_issues_no_actions() -> None:
    """None advances original SUMO control without wrapper action requests."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
    environment, _, factory = make_environment(config)
    environment.reset()

    result = environment.step(None)

    assert factory.signals["A19"].actions == []
    assert factory.signals["A26"].actions == []
    assert result.info["action_results"] == {}
    environment.close()


def test_natural_completion_sets_terminated() -> None:
    """No active or expected vehicles produces natural termination."""
    traci = FakeTraCI(natural_completion_step=1)
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, _, _ = make_environment(config, traci=traci)
    environment.reset()

    result = environment.step(None)

    assert result.terminated is True
    assert result.truncated is False
    assert traci.simulation.step_calls == 1
    environment.close()


def test_configured_time_limit_sets_truncated() -> None:
    """An episode with expected vehicles truncates at its configured duration."""
    config = MultiAgentEnvironmentConfig(
        agent_ids=("A19",),
        demand_seconds=5,
        cooldown_seconds=0,
    )
    environment, _, _ = make_environment(config)
    environment.reset()

    result = environment.step(None)

    assert result.terminated is False
    assert result.truncated is True
    environment.close()


def test_context_manager_closes_active_connection() -> None:
    """Leaving the context safely closes TraCI."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, traci, _ = make_environment(config)

    with environment:
        environment.reset()

    assert traci.close_calls == 1
    assert environment.is_running is False


def test_reset_failure_after_start_closes_connection() -> None:
    """Partial wrapper initialization cannot leak a TraCI session."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
    factory = FakeTrafficSignalFactory(fail_agent="A26")
    environment, traci, _ = make_environment(config, factory=factory)

    with pytest.raises(RuntimeError, match="wrapper initialization failure"):
        environment.reset()

    assert traci.close_calls == 1
    assert environment.is_running is False


def test_step_exception_closes_connection() -> None:
    """A runtime observation failure cleans up the active SUMO connection."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, traci, factory = make_environment(config)
    environment.reset()
    factory.signals["A19"].fail_observe = True

    with pytest.raises(RuntimeError, match="fake observation failure"):
        environment.step(None)

    assert traci.close_calls == 1
    assert environment.is_running is False


def test_constructing_environment_does_not_start_sumo() -> None:
    """Import and construction remain free of SUMO startup side effects."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19",))
    environment, traci, _ = make_environment(config)

    assert traci.start_commands == []
    assert environment.is_running is False

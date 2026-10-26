"""Unit tests for the imported actuated baseline.

These tests use only fake TraCI domains and fake TrafficSignal wrappers
(mirroring ``tests/test_multi_agent_environment.py``); they never launch
SUMO or SUMO-GUI.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

import scripts.experiments.run_imported_actuated_experiment as run_imported_actuated_experiment
import scripts.experiments.run_imported_actuated_suite as run_imported_actuated_suite
import src.baselines.imported_actuated as imported_actuated_module
from scripts.experiments.run_imported_actuated_experiment import (
    parse_args as parse_experiment_args,
    run_experiment,
)
from src.baselines.imported_actuated import (
    BASELINE_NOTICE,
    CONTROLLER_NAME,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DECISION_INTERVAL_SECONDS,
    DEFAULT_DEMAND_SECONDS,
    ImportedActuatedController,
    _validate_controller_name,
    build_environment_config,
)
from src.environment.actions import TrafficAction
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentTrafficEnvironment,
)
from src.environment.observations import TrafficObservation
from src.environment.rewards import RewardBreakdown, RewardWeights
from src.environment.selected_corridor import SELECTED_CORRIDOR
from src.evaluation.results_writer import read_results


# ---------------------------------------------------------------------------
# Fakes: a fully self-contained TraCI stand-in, no SUMO/SUMO-GUI required.
# Mirrors tests/test_multi_agent_environment.py's fakes, extended with the
# extra lane/vehicle/simulation surface MetricsCollector and the shared
# per-agent diagnostics accumulator read.
# ---------------------------------------------------------------------------


class FakeSimulation:
    """Mutable simulation domain that completes after one decision round."""

    def __init__(self, natural_completion_step: int = 1) -> None:
        self.initial_expected_count = 5
        self.expected_count = self.initial_expected_count
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
        if self.step_calls >= self.natural_completion_step:
            self.expected_count = 0

    def getTime(self) -> float:  # noqa: N802
        """Return the current fake simulated time."""
        return self.time

    def getMinExpectedNumber(self) -> int:  # noqa: N802
        """Return the active-plus-future fake vehicle count."""
        return self.expected_count

    def getDepartedNumber(self) -> int:  # noqa: N802
        """Return one fake departure per simulated step."""
        return 1

    def getArrivedNumber(self) -> int:  # noqa: N802
        """Return one fake arrival per simulated step."""
        return 1

    def getDepartedIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return fixed fake departed vehicle IDs."""
        return ("v1", "v2")

    def getArrivedIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return no fake arrivals."""
        return ()

    def getStartingTeleportIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return no fake teleports."""
        return ()


class FakeVehicleDomain:
    """Fake vehicle domain with two fixed active vehicles."""

    def getIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return two fake active vehicles."""
        return ("halted", "moving")

    def getSpeed(self, vehicle_id: str) -> float:  # noqa: N802
        """Return one halted and one moving speed."""
        return 0.0 if vehicle_id == "halted" else 10.0

    def getAccumulatedWaitingTime(self, vehicle_id: str) -> float:  # noqa: N802
        """Return a fixed fake accumulated waiting time."""
        return 0.0

    def getWaitingTime(self, vehicle_id: str) -> float:  # noqa: N802
        """Return a fixed fake current waiting time."""
        return 0.0


class FakeLaneDomain:
    """Fake lane domain reporting no queued vehicles anywhere."""

    def getLastStepVehicleIDs(self, lane_id: str) -> tuple[str, ...]:  # noqa: N802
        """Return an empty fake lane snapshot."""
        return ()

    def getLastStepHaltingNumber(self, lane_id: str) -> int:  # noqa: N802
        """Return zero fake halted vehicles on every lane."""
        return 0


class FakeTraCI:
    """TraCI-like module supporting the environment and the shared metrics."""

    def __init__(self, natural_completion_step: int = 1) -> None:
        self.simulation = FakeSimulation(natural_completion_step)
        self.vehicle = FakeVehicleDomain()
        self.lane = FakeLaneDomain()
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
    """Minimal TrafficSignal-like wrapper isolated from real TraCI calls."""

    def __init__(
        self,
        *,
        agent_id: str,
        traffic_light_id: str,
        traci_connection: FakeTraCI,
        reward_weights: RewardWeights,
        factory: "FakeTrafficSignalFactory",
        **_: object,
    ) -> None:
        self.agent_id = agent_id
        self.traffic_light_id = traffic_light_id
        self._traci = traci_connection
        self._reward_weights = reward_weights
        self._factory = factory
        self.actions: list[TrafficAction] = []
        self.synchronize_calls = 0
        self.fail_observe = False

    def apply_action(self, action: TrafficAction):
        """Record any action request (never expected to be called here)."""
        self.actions.append(action)
        raise AssertionError(
            "imported_actuated must never call TrafficSignal.apply_action."
        )

    def synchronize(self) -> None:
        """Record explicit environment synchronization."""
        self.synchronize_calls += 1

    def observe(self) -> TrafficObservation:
        """Return one deterministic, always-green observation."""
        if self.fail_observe:
            raise RuntimeError("fake observation failure")
        lane_id = f"{self.agent_id}_lane"
        return TrafficObservation(
            agent_id=self.agent_id,
            traffic_light_id=self.traffic_light_id,
            simulation_time=self._traci.simulation.getTime(),
            incoming_lane_ids=(lane_id,),
            queue_lengths=(0,),
            vehicle_counts=(0,),
            mean_waiting_times=(0.0,),
            mean_speeds=(0.0,),
            current_phase_index=0,
            current_phase_state="GGrr",
            current_phase_elapsed_seconds=0.0,
            is_green_phase=True,
            is_transition_phase=False,
        )

    def calculate_local_reward(
        self,
        observation: TrafficObservation,
        phase_switched: bool = False,
    ) -> RewardBreakdown:
        """Return a fixed zero reward breakdown (unused by this baseline)."""
        return RewardBreakdown(
            queue_component=0.0,
            waiting_component=0.0,
            switch_component=0.0,
            total_reward=0.0,
        )


class FakeTrafficSignalFactory:
    """Construct fake wrappers and retain them by agent."""

    def __init__(self) -> None:
        self.signals: dict[str, FakeTrafficSignal] = {}
        self.created_agent_ids: list[str] = []

    def __call__(self, **kwargs: Any) -> FakeTrafficSignal:
        """Create one fake signal for the requested agent."""
        agent_id = str(kwargs["agent_id"])
        self.created_agent_ids.append(agent_id)
        signal = FakeTrafficSignal(factory=self, **kwargs)
        self.signals[agent_id] = signal
        return signal


def make_environment(
    config: MultiAgentEnvironmentConfig | None = None,
    *,
    traci: FakeTraCI | None = None,
    factory: FakeTrafficSignalFactory | None = None,
) -> tuple[MultiAgentTrafficEnvironment, FakeTraCI, FakeTrafficSignalFactory]:
    """Build an eight-agent environment with injected fakes."""
    fake_traci = traci or FakeTraCI()
    fake_factory = factory or FakeTrafficSignalFactory()
    environment = MultiAgentTrafficEnvironment(
        config or build_environment_config(scenario="medium", seed=42),
        traci_connection=fake_traci,
        traffic_signal_factory=fake_factory,
        sumo_executable=Path("sumo"),
    )
    return environment, fake_traci, fake_factory


# ---------------------------------------------------------------------------
# Controller identifier
# ---------------------------------------------------------------------------


def test_controller_name_constant() -> None:
    """The controller identifier must be exactly imported_actuated."""
    assert CONTROLLER_NAME == "imported_actuated"


@pytest.mark.parametrize(
    "forbidden_name",
    ["skopje_official", "official_skopje", "original_skopje_controller"],
)
def test_forbidden_controller_names_rejected(forbidden_name: str) -> None:
    """Names implying an official Skopje timing plan must never be used."""
    with pytest.raises(ValueError):
        _validate_controller_name(forbidden_name)


def test_wrong_controller_name_rejected() -> None:
    """Any name other than the canonical constant is rejected too."""
    with pytest.raises(ValueError):
        _validate_controller_name("static_fixed_time")


# ---------------------------------------------------------------------------
# All eight selected agents, deterministic order
# ---------------------------------------------------------------------------


def test_build_environment_config_uses_all_eight_agents_in_order() -> None:
    """The config builder must always configure the full selected corridor."""
    config = build_environment_config(scenario="medium", seed=42)
    assert config.agent_ids == SELECTED_CORRIDOR.agent_ids
    assert len(config.agent_ids) == 8


def test_build_environment_config_cannot_be_narrowed() -> None:
    """Callers cannot shrink the configured agent set via overrides."""
    config = build_environment_config(
        scenario="medium", seed=42, agent_ids=("A19",)
    )
    assert config.agent_ids == SELECTED_CORRIDOR.agent_ids


def test_build_environment_config_forwards_scenario_seed_demand_cooldown() -> None:
    """Scenario, seed, demand duration, and cooldown duration are forwarded."""
    config = build_environment_config(
        scenario="high", seed=7, demand_seconds=1200.0, cooldown_seconds=300.0
    )
    assert config.scenario == "high"
    assert config.seed == 7
    assert config.demand_seconds == 1200.0
    assert config.cooldown_seconds == 300.0


def test_default_demand_and_cooldown_seconds() -> None:
    """Defaults are 3600 demand seconds plus 600 cooldown seconds."""
    assert DEFAULT_DEMAND_SECONDS == 3600.0
    assert DEFAULT_COOLDOWN_SECONDS == 600.0
    config = build_environment_config(scenario="medium", seed=42)
    assert config.demand_seconds == 3600.0
    assert config.cooldown_seconds == 600.0


def test_decision_interval_matches_sumo_step_length_by_default() -> None:
    """decision_interval_seconds must equal sumo_step_length_seconds.

    This is a correctness requirement, not just a default: run_experiment()
    calls collector.record_step() exactly once per environment.step(None)
    call. If decision_interval_seconds ever exceeded sumo_step_length_seconds
    again, MultiAgentTrafficEnvironment would silently advance multiple raw
    SUMO steps per call while metrics were sampled only once, undercounting
    departures/arrivals on the skipped steps -- exactly the bug this test
    guards against (see "Metrics sampling granularity" in
    sumo/skopje/documentation/imported_actuated_baseline.md).
    """
    assert DEFAULT_DECISION_INTERVAL_SECONDS == 1.0
    config = build_environment_config(scenario="medium", seed=42)
    assert config.decision_interval_seconds == config.sumo_step_length_seconds


def test_controller_requires_a_multi_agent_environment() -> None:
    """Only a real MultiAgentTrafficEnvironment may be wrapped."""
    with pytest.raises(TypeError):
        ImportedActuatedController(object())  # type: ignore[arg-type]


def test_controller_requires_all_eight_agents() -> None:
    """A narrower environment configuration must be rejected."""
    config = MultiAgentEnvironmentConfig(agent_ids=("A19", "A26"))
    environment, _, _ = make_environment(config)
    with pytest.raises(ValueError, match="all eight selected"):
        ImportedActuatedController(environment)


def test_controller_agent_ids_match_selected_corridor_order() -> None:
    """The controller exposes agents in the official corridor order."""
    environment, _, _ = make_environment()
    controller = ImportedActuatedController(environment)
    assert controller.agent_ids == SELECTED_CORRIDOR.agent_ids


# ---------------------------------------------------------------------------
# environment.step(None) is used; zero actions are ever issued
# ---------------------------------------------------------------------------


def test_step_uses_environment_step_none_and_issues_no_actions() -> None:
    """Every controller.step() call must forward environment.step(None)."""
    environment, _, factory = make_environment()
    controller = ImportedActuatedController(environment)
    controller.reset()

    result = controller.step()

    assert tuple(factory.created_agent_ids) == SELECTED_CORRIDOR.agent_ids
    for agent_id in SELECTED_CORRIDOR.agent_ids:
        assert factory.signals[agent_id].actions == []
    assert result.info["action_results"] == {}
    controller.close()


def test_step_never_calls_apply_action_across_multiple_steps() -> None:
    """No KEEP or NEXT_GREEN request is ever issued, across repeated steps."""
    environment, traci, factory = make_environment(
        build_environment_config(scenario="medium", seed=42),
    )
    # Allow a few decision rounds before natural completion.
    traci.simulation.natural_completion_step = 15
    traci.simulation.initial_expected_count = 5
    controller = ImportedActuatedController(environment)
    controller.reset()

    terminated = truncated = False
    steps = 0
    while not (terminated or truncated) and steps < 10:
        result = controller.step()
        terminated, truncated = result.terminated, result.truncated
        steps += 1

    for agent_id in SELECTED_CORRIDOR.agent_ids:
        assert factory.signals[agent_id].actions == []
    controller.close()


def test_reset_and_close_delegate_to_the_environment() -> None:
    """reset()/close() must simply forward to the wrapped environment."""
    environment, traci, _ = make_environment()
    controller = ImportedActuatedController(environment)

    observations = controller.reset()
    assert tuple(observations) == SELECTED_CORRIDOR.agent_ids

    controller.close()
    assert traci.close_calls == 1
    assert environment.is_running is False


# ---------------------------------------------------------------------------
# run_experiment(): scenario/seed/demand/cooldown forwarding, metrics
# collection through the shared package, controller=imported_actuated,
# and cleanup on success and on failure.
# ---------------------------------------------------------------------------


def _build_experiment_environment(
    *,
    natural_completion_step: int = 1,
) -> tuple[MultiAgentTrafficEnvironment, FakeTraCI, FakeTrafficSignalFactory]:
    config = build_environment_config(
        scenario="medium",
        seed=42,
        demand_seconds=3600.0,
        cooldown_seconds=600.0,
    )
    traci = FakeTraCI(natural_completion_step=natural_completion_step)
    factory = FakeTrafficSignalFactory()
    return make_environment(config, traci=traci, factory=factory)


class FakeScheduledSimulation(FakeSimulation):
    """Fake simulation that departs specific vehicles on specific raw steps.

    Regression coverage for the exact bug this baseline once had against
    real SUMO: ``simulation.getDepartedIDList()`` /
    ``getArrivedIDList()`` report vehicles departed or arrived only since
    the previous ``simulationStep()`` call. If metrics were ever sampled
    less often than once per raw SUMO step again (for example, by raising
    ``decision_interval_seconds`` above ``sumo_step_length_seconds``), the
    departures scheduled on the skipped steps would silently never be
    counted -- which is exactly what produced ``arrived_vehicles cannot
    exceed departed_vehicles`` on real low/medium/high seed-42 runs before
    this was fixed.
    """

    def __init__(
        self,
        departures_by_step: dict[int, tuple[str, ...]],
        natural_completion_step: int,
    ) -> None:
        super().__init__(natural_completion_step)
        self.departures_by_step = departures_by_step

    def getDepartedIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return only the vehicles scheduled for the step just completed."""
        return self.departures_by_step.get(self.step_calls, ())


def test_run_experiment_counts_departures_from_every_raw_sumo_step(
    tmp_path: Path,
) -> None:
    """Every raw step's departures must be counted, not just the last one.

    Regression test for the decision-interval/metrics-sampling bug: three
    distinct vehicles depart on three separate raw SUMO steps. If metrics
    were still sampled once per multi-step decision interval instead of
    once per raw step, this would undercount departed_vehicles and could
    reproduce the real "arrived_vehicles cannot exceed departed_vehicles"
    failure.
    """
    environment, traci, _ = _build_experiment_environment(
        natural_completion_step=3,
    )
    traci.simulation = FakeScheduledSimulation(
        departures_by_step={1: ("v1",), 2: ("v2",), 3: ("v3",)},
        natural_completion_step=3,
    )

    metrics = run_experiment(
        traci=traci,
        environment=environment,
        scenario="medium",
        seed=42,
        demand_seconds=3600.0,
        cooldown_seconds=600.0,
        output_path=tmp_path / "experiments.csv",
        print_reports=False,
    )

    assert metrics.departed_vehicles == 3
    assert traci.close_calls == 1


def test_run_experiment_writes_controller_and_forwards_run_parameters(
    tmp_path: Path,
) -> None:
    """The saved result must carry controller=imported_actuated plus inputs."""
    environment, traci, factory = _build_experiment_environment()
    output_path = tmp_path / "experiments.csv"

    metrics = run_experiment(
        traci=traci,
        environment=environment,
        scenario="medium",
        seed=42,
        demand_seconds=3600.0,
        cooldown_seconds=600.0,
        output_path=output_path,
        print_reports=False,
    )

    assert metrics.controller == CONTROLLER_NAME
    assert metrics.scenario == "medium"
    assert metrics.seed == 42
    assert metrics.demand_seconds == 3600.0
    assert metrics.cooldown_seconds == 600.0
    assert metrics.fixed_green_seconds is None
    assert metrics.total_reward is None
    assert traci.close_calls == 1

    rows = read_results(output_path)
    assert len(rows) == 1
    assert rows[0]["controller"] == CONTROLLER_NAME
    assert rows[0]["scenario"] == "medium"
    assert rows[0]["seed"] == "42"


def test_run_experiment_configures_all_eight_agents_in_order(
    tmp_path: Path,
) -> None:
    """Every selected agent must appear in per-agent diagnostics, in order."""
    environment, traci, factory = _build_experiment_environment()

    metrics = run_experiment(
        traci=traci,
        environment=environment,
        scenario="medium",
        seed=42,
        demand_seconds=3600.0,
        cooldown_seconds=600.0,
        output_path=tmp_path / "experiments.csv",
        print_reports=False,
    )

    assert tuple(factory.created_agent_ids) == SELECTED_CORRIDOR.agent_ids
    assert tuple(diag.agent_id for diag in metrics.per_agent) == (
        SELECTED_CORRIDOR.agent_ids
    )
    assert all(diag.phase_change_count == 0 for diag in metrics.per_agent)


def test_run_experiment_cleans_up_on_exception(tmp_path: Path) -> None:
    """A mid-run failure must still close TraCI, per the acceptance criteria."""
    environment, traci, factory = _build_experiment_environment(
        natural_completion_step=15,
    )
    factory_signal_id = SELECTED_CORRIDOR.agent_ids[0]

    original_step = environment.step

    def _failing_step(actions):
        factory.signals[factory_signal_id].fail_observe = True
        return original_step(actions)

    environment.step = _failing_step  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="fake observation failure"):
        run_experiment(
            traci=traci,
            environment=environment,
            scenario="medium",
            seed=42,
            demand_seconds=3600.0,
            cooldown_seconds=600.0,
            output_path=tmp_path / "experiments.csv",
            print_reports=False,
        )

    assert traci.close_calls == 1
    assert environment.is_running is False


# ---------------------------------------------------------------------------
# CLI validation: invalid scenarios and missing seed files are rejected.
# ---------------------------------------------------------------------------


def test_parse_args_rejects_invalid_scenario() -> None:
    """argparse must reject any scenario outside the canonical three."""
    with pytest.raises(SystemExit):
        parse_experiment_args(["--scenario", "extreme", "--seed", "42"])


def test_missing_seed_file_is_rejected_before_sumo_starts() -> None:
    """A missing generated scenario must fail before SUMO/TraCI is touched."""
    exit_code = run_imported_actuated_experiment.main(
        ["--scenario", "low", "--seed", "999999999"]
    )
    assert exit_code == 1


# ---------------------------------------------------------------------------
# No reinforcement-learning module is imported; original inputs untouched.
# ---------------------------------------------------------------------------


_NEW_MODULE_FILES = (
    Path(imported_actuated_module.__file__),
    Path(run_imported_actuated_experiment.__file__),
    Path(run_imported_actuated_suite.__file__),
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "src.agents",
    "src.training",
)


def _imported_module_names(source_path: Path) -> set[str]:
    """Return every module named in an import/import-from statement."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module_file", _NEW_MODULE_FILES)
def test_no_reinforcement_learning_module_is_imported(module_file: Path) -> None:
    """This baseline must never import Q-learning or training modules."""
    imported_names = _imported_module_names(module_file)
    for name in imported_names:
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in _FORBIDDEN_IMPORT_PREFIXES
        ), f"{module_file.name} must not import {name!r}."


@pytest.mark.parametrize("module_file", _NEW_MODULE_FILES)
def test_no_demand_or_network_generation_helpers_are_imported(
    module_file: Path,
) -> None:
    """This baseline must only read existing scenario files, never write them."""
    imported_names = _imported_module_names(module_file)
    assert "src.demand.xml_writer" not in imported_names or module_file.name in {
        "run_imported_actuated_experiment.py",
        "run_imported_actuated_suite.py",
    }
    forbidden_generation_modules = {
        "src.demand.network_routes",
    }
    assert not (imported_names & forbidden_generation_modules)


def test_baseline_notice_matches_documentation_wording() -> None:
    """The printed baseline notice must match the required documentation text."""
    assert BASELINE_NOTICE == (
        "The imported actuated baseline evaluates the traffic-light programs "
        "contained in the imported SUMO network without issuing manual "
        "phase-control actions. These programs are used as a simulation "
        "baseline and are not claimed to reproduce the official operational "
        "traffic-control system of the City of Skopje."
    )

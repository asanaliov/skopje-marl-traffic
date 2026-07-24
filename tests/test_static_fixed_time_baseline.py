"""Unit tests for the static fixed-time baseline controller.

These tests use only fake TraCI domains and never launch SUMO or SUMO-GUI.
"""

from __future__ import annotations

import inspect

import pytest

from src.baselines.static_fixed_time import (
    CONTROLLER_NAME,
    StaticFixedTimeConfig,
    StaticFixedTimeController,
    _validate_controller_name,
)
from src.environment.actions import is_transition_phase_state
from src.environment.selected_corridor import SELECTED_CORRIDOR


TEST_AGENT_IDS = SELECTED_CORRIDOR.agent_ids[:2]
TRAFFIC_LIGHT_IDS = tuple(
    SELECTED_CORRIDOR.agent_to_traffic_light[agent_id] for agent_id in TEST_AGENT_IDS
)
PHASE_STATES = ("GGrr", "yyrr", "rrrr", "rrGG", "rryy")
CONTROLLED_LANES = ("lane_a", "lane_b")


class FakePhase:
    """Minimal TraCI phase object."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.duration = 3.0 if is_transition_phase_state(state) else 30.0


class FakeLogic:
    """Minimal active TraCI program logic shared by every fake traffic light."""

    def __init__(self, phase_states: tuple[str, ...]) -> None:
        self.programID = "0"
        self.phases = tuple(FakePhase(state) for state in phase_states)


class FakeSimulationDomain:
    """Mutable simulation clock for fake domains."""

    def __init__(self) -> None:
        self.time = 0.0

    def getTime(self) -> float:  # noqa: N802
        """Return the fake simulation time."""
        return self.time


class FakeTrafficLightDomain:
    """Fake multi-traffic-light domain that records every mutating call."""

    def __init__(
        self,
        simulation: FakeSimulationDomain,
        traffic_light_ids: tuple[str, ...],
        phase_states: tuple[str, ...] = PHASE_STATES,
        controlled_lanes: tuple[str, ...] = CONTROLLED_LANES,
    ) -> None:
        self.simulation = simulation
        self.traffic_light_ids = traffic_light_ids
        self.phase_states = phase_states
        self.controlled_lanes = controlled_lanes
        self.logic = FakeLogic(phase_states)
        self.phase_index = dict.fromkeys(traffic_light_ids, 0)
        self.spent_duration = dict.fromkeys(traffic_light_ids, 0.0)
        self.next_switch = dict.fromkeys(traffic_light_ids, 30.0)
        self.set_phase_calls: dict[str, list[int]] = {
            tlid: [] for tlid in traffic_light_ids
        }
        self.set_phase_duration_calls: dict[str, list[float]] = {
            tlid: [] for tlid in traffic_light_ids
        }

    def getIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return every fake traffic-light ID."""
        return self.traffic_light_ids

    def getProgram(self, traffic_light_id: str) -> str:  # noqa: N802
        """Return the active fake program."""
        return "0"

    def getAllProgramLogics(  # noqa: N802
        self, traffic_light_id: str
    ) -> tuple[FakeLogic, ...]:
        """Return the shared active fake program logic."""
        return (self.logic,)

    def getControlledLanes(self, traffic_light_id: str) -> tuple[str, ...]:  # noqa: N802
        """Return fake controlled lane IDs."""
        return self.controlled_lanes

    def getPhase(self, traffic_light_id: str) -> int:  # noqa: N802
        """Return the current fake phase index."""
        return self.phase_index[traffic_light_id]

    def getRedYellowGreenState(self, traffic_light_id: str) -> str:  # noqa: N802
        """Return the current fake phase state."""
        return self.phase_states[self.phase_index[traffic_light_id]]

    def getSpentDuration(self, traffic_light_id: str) -> float:  # noqa: N802
        """Return current fake phase elapsed time."""
        return self.spent_duration[traffic_light_id]

    def getNextSwitch(self, traffic_light_id: str) -> float:  # noqa: N802
        """Return the scheduled absolute fake switch time."""
        return self.next_switch[traffic_light_id]

    def setPhase(self, traffic_light_id: str, phase_index: int) -> None:  # noqa: N802
        """Record and apply one fake phase-index change."""
        self.set_phase_calls[traffic_light_id].append(phase_index)
        self.phase_index[traffic_light_id] = phase_index
        self.spent_duration[traffic_light_id] = 0.0
        self.next_switch[traffic_light_id] = self.simulation.time + 3.0

    def setPhaseDuration(  # noqa: N802
        self, traffic_light_id: str, duration_seconds: float
    ) -> None:
        """Record and apply one fake remaining-duration change."""
        self.set_phase_duration_calls[traffic_light_id].append(duration_seconds)
        self.next_switch[traffic_light_id] = self.simulation.time + duration_seconds


class FakeLaneDomain:
    """Fake lane snapshots with no vehicles present."""

    def getLastStepVehicleIDs(self, lane_id: str) -> tuple[str, ...]:  # noqa: N802
        """Return an empty fake lane snapshot."""
        return ()

    def getMaxSpeed(self, lane_id: str) -> float:  # noqa: N802
        """Return a fake lane speed limit."""
        return 13.9


class FakeVehicleDomain:
    """Fake vehicle domain; unused because no vehicles are ever present."""

    def getSpeed(self, vehicle_id: str) -> float:  # noqa: N802
        """Never called: no vehicles are present in these fixtures."""
        raise KeyError(vehicle_id)

    def getAccumulatedWaitingTime(self, vehicle_id: str) -> float:  # noqa: N802
        """Never called: no vehicles are present in these fixtures."""
        raise KeyError(vehicle_id)


class FakeTraCI:
    """Small injected multi-traffic-light TraCI-like connection."""

    def __init__(self, traffic_light_ids: tuple[str, ...]) -> None:
        self.simulation = FakeSimulationDomain()
        self.trafficlight = FakeTrafficLightDomain(self.simulation, traffic_light_ids)
        self.lane = FakeLaneDomain()
        self.vehicle = FakeVehicleDomain()

    def advance(self, seconds: float) -> None:
        """Advance the fake clock and every phase's fake elapsed time."""
        self.simulation.time += seconds
        for traffic_light_id in self.trafficlight.traffic_light_ids:
            self.trafficlight.spent_duration[traffic_light_id] += seconds


def make_controller(
    fixed_green_seconds: float = 10.0,
    decision_interval_seconds: float = 5.0,
    traffic_light_ids: tuple[str, ...] = TRAFFIC_LIGHT_IDS,
    agent_ids: tuple[str, ...] = TEST_AGENT_IDS,
) -> tuple[StaticFixedTimeController, FakeTraCI]:
    """Build a controller around a fresh fake multi-agent TraCI connection."""
    fake_traci = FakeTraCI(traffic_light_ids)
    controller = StaticFixedTimeController(
        fake_traci,
        config=StaticFixedTimeConfig(
            fixed_green_seconds=fixed_green_seconds,
            decision_interval_seconds=decision_interval_seconds,
        ),
        agent_ids=agent_ids,
    )
    return controller, fake_traci


def test_controller_name_constant() -> None:
    """The controller identifier must be exactly static_fixed_time."""
    assert CONTROLLER_NAME == "static_fixed_time"


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
        _validate_controller_name("fixed_time")


@pytest.mark.parametrize("invalid_seconds", [0.0, -5.0, float("nan"), float("inf")])
def test_config_rejects_invalid_fixed_green_seconds(invalid_seconds: float) -> None:
    """Non-positive or non-finite fixed_green_seconds must be rejected."""
    with pytest.raises(ValueError):
        StaticFixedTimeConfig(fixed_green_seconds=invalid_seconds)


@pytest.mark.parametrize("invalid_seconds", [0.0, -1.0, float("nan")])
def test_config_rejects_invalid_decision_interval(invalid_seconds: float) -> None:
    """Non-positive or non-finite decision_interval_seconds must be rejected."""
    with pytest.raises(ValueError):
        StaticFixedTimeConfig(decision_interval_seconds=invalid_seconds)


def test_action_policy_sets_equal_minimum_and_maximum_green() -> None:
    """Fixed timing is enforced by making minimum and maximum green equal."""
    config = StaticFixedTimeConfig(fixed_green_seconds=20.0, decision_interval_seconds=5.0)
    policy = config.action_policy()
    assert policy.minimum_green_seconds == 20.0
    assert policy.maximum_green_seconds == 20.0
    assert policy.decision_interval_seconds == 5.0


def test_decision_interval_is_capped_to_fixed_green_seconds() -> None:
    """A too-large decision interval must not exceed the fixed green duration."""
    config = StaticFixedTimeConfig(fixed_green_seconds=3.0, decision_interval_seconds=5.0)
    policy = config.action_policy()
    assert policy.decision_interval_seconds == 3.0


def test_default_agent_ids_is_the_selected_corridor() -> None:
    """The controller must default to the official eight selected agents."""
    signature = inspect.signature(StaticFixedTimeController.__init__)
    assert signature.parameters["agent_ids"].default == SELECTED_CORRIDOR.agent_ids


def test_controller_requires_at_least_one_agent() -> None:
    """An empty agent selection must be rejected rather than silently no-op."""
    fake_traci = FakeTraCI(())
    with pytest.raises(ValueError):
        StaticFixedTimeController(fake_traci, agent_ids=())


def test_controller_initializes_one_signal_per_agent() -> None:
    """Every requested agent must get its own TrafficSignal wrapper."""
    controller, _ = make_controller()
    assert set(controller.signals) == set(TEST_AGENT_IDS)
    for signal in controller.signals.values():
        assert signal.phase_states == PHASE_STATES
        assert signal.current_phase_index == 0


def test_step_before_decision_interval_issues_no_commands() -> None:
    """No TraCI mutation should happen before the first decision is due."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    issued = controller.step(0.0)
    assert issued is False
    for traffic_light_id in TRAFFIC_LIGHT_IDS:
        assert fake_traci.trafficlight.set_phase_calls[traffic_light_id] == []


def test_green_is_held_until_the_configured_fixed_duration() -> None:
    """Requests before fixed_green_seconds must hold green, not switch."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    fake_traci.advance(5.0)
    controller.step(fake_traci.simulation.time)

    for traffic_light_id in TRAFFIC_LIGHT_IDS:
        assert fake_traci.trafficlight.phase_index[traffic_light_id] == 0
        assert fake_traci.trafficlight.set_phase_calls[traffic_light_id] == []
    for agent_id in TEST_AGENT_IDS:
        assert controller.phase_change_counts[agent_id] == 0


def test_switches_to_the_immediate_next_phase_at_the_fixed_duration() -> None:
    """At exactly fixed_green_seconds, the wrapper must enter the next phase."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    fake_traci.advance(5.0)
    controller.step(fake_traci.simulation.time)
    fake_traci.advance(5.0)
    controller.step(fake_traci.simulation.time)

    for traffic_light_id in TRAFFIC_LIGHT_IDS:
        assert fake_traci.trafficlight.phase_index[traffic_light_id] == 1
        assert fake_traci.trafficlight.set_phase_calls[traffic_light_id] == [1]
    for agent_id in TEST_AGENT_IDS:
        assert controller.phase_change_counts[agent_id] == 1


def test_transition_duration_is_the_original_program_duration() -> None:
    """The forced transition must use its own original duration, not fixed_green."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    fake_traci.advance(10.0)
    controller.step(fake_traci.simulation.time)

    for traffic_light_id in TRAFFIC_LIGHT_IDS:
        calls = fake_traci.trafficlight.set_phase_duration_calls[traffic_light_id]
        assert calls[-1] == pytest.approx(3.0)
        assert calls[-1] != 10.0


def test_phase_order_is_preserved_without_skipping() -> None:
    """The wrapper must land on phase 1 (yellow), never jump to phase 3 (green)."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    fake_traci.advance(10.0)
    controller.step(fake_traci.simulation.time)

    for traffic_light_id in TRAFFIC_LIGHT_IDS:
        resulting_state = fake_traci.trafficlight.phase_states[
            fake_traci.trafficlight.phase_index[traffic_light_id]
        ]
        assert is_transition_phase_state(resulting_state)
        assert fake_traci.trafficlight.phase_index[traffic_light_id] == 1


def test_final_phase_by_agent_reports_the_synchronized_state() -> None:
    """final_phase_by_agent must reflect the most recent synchronized phase."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    fake_traci.advance(10.0)
    controller.step(fake_traci.simulation.time)

    final_phases = controller.final_phase_by_agent()
    for agent_id in TEST_AGENT_IDS:
        assert final_phases[agent_id] == "yyrr"


def test_step_returns_true_only_when_a_decision_round_runs() -> None:
    """step() must report whether it actually issued a decision round."""
    controller, fake_traci = make_controller(
        fixed_green_seconds=10.0, decision_interval_seconds=5.0
    )
    assert controller.step(0.0) is False
    fake_traci.advance(5.0)
    assert controller.step(fake_traci.simulation.time) is True

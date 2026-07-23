"""Unit tests for the traffic-signal agent interface.

These tests use only fake TraCI domains and never launch SUMO or SUMO-GUI.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from src.environment.actions import (
    ActionPolicyConfig,
    ActionStatus,
    TrafficAction,
    find_green_phase_indices,
    find_immediate_next_phase_index,
    find_next_green_phase_index,
    is_green_phase_state,
    is_transition_phase_state,
)
from src.environment.observations import (
    ObservationNormalizationConfig,
    TrafficObservation,
    calculate_mean_speed,
    calculate_mean_waiting_time,
    count_queued_vehicles,
    count_vehicles_on_lane,
)
from src.environment.rewards import (
    RewardWeights,
    calculate_local_reward,
    global_corridor_reward,
    neighbor_aware_reward,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR
from src.environment.traffic_signal import TrafficSignal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "A19"
TRAFFIC_LIGHT_ID = SELECTED_CORRIDOR.agent_to_traffic_light[AGENT_ID]
DEFAULT_PHASE_STATES = ("GGrr", "yyrr", "rrrr", "rrGG", "rryy")


class FakePhase:
    """Minimal TraCI phase object."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.duration = 3.0 if is_transition_phase_state(state) else 30.0


class FakeLogic:
    """Minimal active TraCI program logic."""

    def __init__(self, phase_states: tuple[str, ...]) -> None:
        self.programID = "0"
        self.phases = tuple(FakePhase(state) for state in phase_states)


class FakeSimulationDomain:
    """Mutable simulation clock for fake domains."""

    def __init__(self, simulation_time: float = 0.0) -> None:
        self.time = simulation_time

    def getTime(self) -> float:  # noqa: N802
        """Return the fake simulation time."""
        return self.time


class FakeTrafficLightDomain:
    """Fake traffic-light domain that records every mutating call."""

    def __init__(
        self,
        simulation: FakeSimulationDomain,
        phase_states: tuple[str, ...] = DEFAULT_PHASE_STATES,
        controlled_lanes: tuple[str, ...] = ("lane_2", "lane_1", "lane_2"),
        available: bool = True,
    ) -> None:
        self.simulation = simulation
        self.phase_states = phase_states
        self.controlled_lanes = controlled_lanes
        self.available = available
        self.phase_index = 0
        self.spent_duration = 0.0
        self.next_switch = 42.0
        self.set_phase_calls: list[int] = []
        self.set_phase_duration_calls: list[float] = []
        self.logic = FakeLogic(phase_states)

    def getIDList(self) -> tuple[str, ...]:  # noqa: N802
        """Return the selected controller when configured as available."""
        return (TRAFFIC_LIGHT_ID,) if self.available else ()

    def getProgram(self, traffic_light_id: str) -> str:  # noqa: N802
        """Return the active fake program."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return "0"

    def getAllProgramLogics(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> tuple[FakeLogic, ...]:
        """Return the active fake program logic."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return (self.logic,)

    def getControlledLanes(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> tuple[str, ...]:
        """Return fake controlled lane IDs."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return self.controlled_lanes

    def getPhase(self, traffic_light_id: str) -> int:  # noqa: N802
        """Return the current fake phase index."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return self.phase_index

    def getRedYellowGreenState(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> str:
        """Return the current fake phase state."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return self.phase_states[self.phase_index]

    def getSpentDuration(self, traffic_light_id: str) -> float:  # noqa: N802
        """Return current fake phase elapsed time."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return self.spent_duration

    def getNextSwitch(self, traffic_light_id: str) -> float:  # noqa: N802
        """Return the scheduled absolute fake switch time."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        return self.next_switch

    def setPhase(self, traffic_light_id: str, phase_index: int) -> None:  # noqa: N802
        """Record and apply one fake phase-index change."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        self.set_phase_calls.append(phase_index)
        self.phase_index = phase_index
        self.spent_duration = 0.0
        self.next_switch = self.simulation.time + 3.0

    def setPhaseDuration(  # noqa: N802
        self,
        traffic_light_id: str,
        duration_seconds: float,
    ) -> None:
        """Record and apply one fake remaining-duration change."""
        assert traffic_light_id == TRAFFIC_LIGHT_ID
        self.set_phase_duration_calls.append(duration_seconds)
        self.next_switch = self.simulation.time + duration_seconds


class FakeLaneDomain:
    """Fake lane snapshots and speed limits."""

    def __init__(self) -> None:
        self.vehicles = {
            "lane_2": ("queued", "threshold", "moving"),
            "lane_1": (),
        }
        self.speed_limits = {"lane_2": 15.0, "lane_1": 10.0}

    def getLastStepVehicleIDs(self, lane_id: str) -> tuple[str, ...]:  # noqa: N802
        """Return one fake lane snapshot."""
        return self.vehicles[lane_id]

    def getMaxSpeed(self, lane_id: str) -> float:  # noqa: N802
        """Return one fake lane speed limit."""
        return self.speed_limits[lane_id]


class FakeVehicleDomain:
    """Fake vehicle metrics with optional transient disappearance."""

    def __init__(self) -> None:
        self.speeds = {
            "queued": 0.05,
            "threshold": 0.1,
            "moving": 10.0,
        }
        self.waiting_times = {
            "queued": 30.0,
            "threshold": 15.0,
            "moving": 0.0,
        }
        self.disappeared: set[str] = set()

    def getSpeed(self, vehicle_id: str) -> float:  # noqa: N802
        """Return one fake speed or simulate a vanished vehicle."""
        if vehicle_id in self.disappeared:
            raise KeyError(vehicle_id)
        return self.speeds[vehicle_id]

    def getAccumulatedWaitingTime(  # noqa: N802
        self,
        vehicle_id: str,
    ) -> float:
        """Return one fake accumulated waiting time."""
        if vehicle_id in self.disappeared:
            raise KeyError(vehicle_id)
        return self.waiting_times[vehicle_id]


class FakeTraCI:
    """Small injected TraCI-like connection."""

    def __init__(
        self,
        phase_states: tuple[str, ...] = DEFAULT_PHASE_STATES,
        controlled_lanes: tuple[str, ...] = ("lane_2", "lane_1", "lane_2"),
        available: bool = True,
    ) -> None:
        self.simulation = FakeSimulationDomain()
        self.trafficlight = FakeTrafficLightDomain(
            self.simulation,
            phase_states,
            controlled_lanes,
            available,
        )
        self.lane = FakeLaneDomain()
        self.vehicle = FakeVehicleDomain()


def make_signal(
    traci: FakeTraCI | None = None,
    action_policy: ActionPolicyConfig | None = None,
    expected_lanes: tuple[str, ...] | None = None,
) -> tuple[TrafficSignal, FakeTraCI]:
    """Build a selected wrapper around a fake TraCI connection."""
    fake_traci = traci or FakeTraCI()
    signal = TrafficSignal(
        agent_id=AGENT_ID,
        traffic_light_id=TRAFFIC_LIGHT_ID,
        traci_connection=fake_traci,
        action_policy=action_policy,
        expected_incoming_lane_ids=expected_lanes,
    )
    return signal, fake_traci


def make_observation(
    queue_lengths: tuple[int, ...] = (0,),
    vehicle_counts: tuple[int, ...] = (0,),
    waiting_times: tuple[float, ...] = (0.0,),
    speeds: tuple[float, ...] = (0.0,),
    phase_index: int = 0,
    elapsed: float = 0.0,
) -> TrafficObservation:
    """Create one valid observation for pure-function tests."""
    return TrafficObservation(
        agent_id=AGENT_ID,
        traffic_light_id=TRAFFIC_LIGHT_ID,
        simulation_time=10.0,
        incoming_lane_ids=("lane_1",),
        queue_lengths=queue_lengths,
        vehicle_counts=vehicle_counts,
        mean_waiting_times=waiting_times,
        mean_speeds=speeds,
        current_phase_index=phase_index,
        current_phase_state="GGrr",
        current_phase_elapsed_seconds=elapsed,
        is_green_phase=True,
        is_transition_phase=False,
    )


def test_queue_threshold_is_strictly_below_point_one() -> None:
    """A speed equal to the threshold must not count as queued."""
    assert count_queued_vehicles((0.0, 0.099, 0.1, 0.101)) == 2


def test_empty_lane_helpers_return_zeros() -> None:
    """Empty lane inputs must never produce NaN."""
    assert count_queued_vehicles(()) == 0
    assert count_vehicles_on_lane(()) == 0
    assert calculate_mean_waiting_time(()) == 0.0
    assert calculate_mean_speed(()) == 0.0


def test_mean_speed_and_waiting_time_are_arithmetic_means() -> None:
    """Metric helpers must use a deterministic arithmetic mean."""
    assert calculate_mean_speed((2.0, 4.0, 9.0)) == pytest.approx(5.0)
    assert calculate_mean_waiting_time((3.0, 6.0, 12.0)) == pytest.approx(7.0)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("queue_lengths", (-1,)),
        ("vehicle_counts", (-1,)),
        ("mean_waiting_times", (-0.1,)),
        ("mean_speeds", (-0.1,)),
        ("mean_waiting_times", (math.nan,)),
        ("mean_speeds", (math.inf,)),
    ),
)
def test_observation_rejects_negative_or_nonfinite_lane_metrics(
    field_name: str,
    invalid_value: tuple[object, ...],
) -> None:
    """Observation validation must reject invalid lane metrics."""
    observation = make_observation()
    with pytest.raises(ValueError):
        replace(observation, **{field_name: invalid_value})


def test_observation_requires_equal_lane_tuple_lengths() -> None:
    """Every lane metric must align with exactly one lane ID."""
    with pytest.raises(ValueError, match="same length"):
        make_observation(queue_lengths=(0, 1))


def test_normalized_features_are_clipped_and_deterministic() -> None:
    """Lane-major feature ordering must remain stable and bounded."""
    observation = make_observation(
        queue_lengths=(40,),
        vehicle_counts=(60,),
        waiting_times=(600.0,),
        speeds=(30.0,),
        phase_index=1,
        elapsed=120.0,
    )
    features = observation.normalized_features(
        phase_count=3,
        config=ObservationNormalizationConfig(
            queue_cap=20.0,
            vehicle_count_cap=30.0,
            waiting_time_cap=300.0,
            speed_cap=15.0,
            phase_elapsed_cap=60.0,
        ),
    )
    assert features == (1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0)
    assert all(0.0 <= feature <= 1.0 for feature in features)
    assert observation.normalized_features(
        phase_count=3,
        config=ObservationNormalizationConfig(speed_cap=15.0),
    ) == observation.normalized_features(
        phase_count=3,
        config=ObservationNormalizationConfig(speed_cap=15.0),
    )


def test_normalized_feature_order_and_phase_one_hot_encoding() -> None:
    """Features must use queue, count, waiting, speed, elapsed, then one-hot."""
    observation = make_observation(
        queue_lengths=(10,),
        vehicle_counts=(15,),
        waiting_times=(150.0,),
        speeds=(5.0,),
        phase_index=2,
        elapsed=30.0,
    )
    features = observation.normalized_features(
        phase_count=4,
        config=ObservationNormalizationConfig(speed_cap=10.0),
    )
    assert features == (
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.0,
        0.0,
        1.0,
        0.0,
    )


def test_traffic_action_values_are_stable() -> None:
    """The two-action numeric contract must not change."""
    assert TrafficAction.KEEP.value == 0
    assert TrafficAction.NEXT_GREEN.value == 1


@pytest.mark.parametrize(
    ("state", "is_green", "is_transition"),
    (
        ("GGrr", True, False),
        ("ggrr", True, False),
        ("Gyyrr", False, True),
        ("rrrr", False, True),
        ("rrGG", True, False),
    ),
)
def test_phase_state_classification(
    state: str,
    is_green: bool,
    is_transition: bool,
) -> None:
    """Green, yellow, and all-red states must be classified safely."""
    assert is_green_phase_state(state) is is_green
    assert is_transition_phase_state(state) is is_transition


def test_phase_discovery_and_cyclic_selection() -> None:
    """Green searches and immediate phase selection must be cyclic."""
    states = ("GGrr", "yyrr", "rrGG", "rryy")
    assert find_green_phase_indices(states) == (0, 2)
    assert find_next_green_phase_index(0, states) == 2
    assert find_next_green_phase_index(2, states) == 0
    assert find_immediate_next_phase_index(3, len(states)) == 0


@pytest.mark.parametrize(
    "config",
    (
        ActionPolicyConfig(minimum_green_seconds=10.0),
        ActionPolicyConfig(
            minimum_green_seconds=5.0,
            maximum_green_seconds=5.0,
            decision_interval_seconds=5.0,
        ),
    ),
)
def test_valid_action_policy_configs(config: ActionPolicyConfig) -> None:
    """Valid boundary configurations must be accepted."""
    assert config.minimum_green_seconds > 0.0


@pytest.mark.parametrize(
    "kwargs",
    (
        {"minimum_green_seconds": 0.0},
        {"minimum_green_seconds": 20.0, "maximum_green_seconds": 10.0},
        {"decision_interval_seconds": 0.0},
        {"maximum_green_seconds": 4.0, "decision_interval_seconds": 5.0},
    ),
)
def test_invalid_action_policy_configs_are_rejected(
    kwargs: dict[str, float],
) -> None:
    """Invalid timing rules must fail before they reach TraCI."""
    with pytest.raises(ValueError):
        ActionPolicyConfig(**kwargs)


def test_reward_weights_must_be_nonnegative() -> None:
    """Negative local reward weights are invalid."""
    with pytest.raises(ValueError):
        RewardWeights(queue_weight=-1.0)


def test_no_congestion_has_zero_local_reward_without_switch_penalty() -> None:
    """An empty lane should produce a neutral local reward."""
    reward = calculate_local_reward(make_observation())
    assert reward.total_reward == 0.0


def test_larger_queue_and_waiting_values_are_more_negative() -> None:
    """Increasing either congestion term must lower the reward."""
    clear = calculate_local_reward(make_observation())
    queued = calculate_local_reward(
        make_observation(
            queue_lengths=(3,),
            vehicle_counts=(3,),
            waiting_times=(0.0,),
        )
    )
    waiting = calculate_local_reward(
        make_observation(
            queue_lengths=(0,),
            vehicle_counts=(1,),
            waiting_times=(50.0,),
        )
    )
    assert queued.total_reward < clear.total_reward
    assert waiting.total_reward < clear.total_reward


def test_switch_penalty_and_reward_breakdown_sum() -> None:
    """Every component must be visible and sum to the reported total."""
    breakdown = calculate_local_reward(
        make_observation(
            queue_lengths=(2,),
            vehicle_counts=(2,),
            waiting_times=(10.0,),
        ),
        phase_switched=True,
        weights=RewardWeights(
            queue_weight=2.0,
            waiting_weight=0.5,
            switch_penalty_weight=3.0,
        ),
    )
    assert breakdown.queue_component == -4.0
    assert breakdown.waiting_component == -5.0
    assert breakdown.switch_component == -3.0
    assert breakdown.total_reward == pytest.approx(
        breakdown.queue_component
        + breakdown.waiting_component
        + breakdown.switch_component
    )


def test_neighbor_aware_reward_and_empty_neighbor_fallback() -> None:
    """Neighbor rewards must use their mean or fall back to the local reward."""
    assert neighbor_aware_reward(-10.0, ()) == -10.0
    assert neighbor_aware_reward(-10.0, (-4.0, -6.0)) == pytest.approx(-8.5)


@pytest.mark.parametrize(
    ("local_weight", "neighbor_weight"),
    ((-0.1, 1.1), (0.8, 0.3), (math.nan, math.nan)),
)
def test_invalid_neighbor_weights_are_rejected(
    local_weight: float,
    neighbor_weight: float,
) -> None:
    """Neighbor weights must be finite, non-negative, and sum to one."""
    with pytest.raises(ValueError):
        neighbor_aware_reward(
            -1.0,
            (-2.0,),
            local_weight=local_weight,
            neighbor_weight=neighbor_weight,
        )


def test_global_corridor_reward_is_arithmetic_mean() -> None:
    """Global helper must average available local rewards."""
    assert global_corridor_reward((-3.0, -6.0, 0.0)) == pytest.approx(-3.0)


def test_empty_global_corridor_reward_is_explicitly_rejected() -> None:
    """An empty global reward has no meaningful arithmetic mean."""
    with pytest.raises(ValueError, match="At least one"):
        global_corridor_reward(())


def test_selected_mapping_validation_rejects_unknown_or_mismatched_ids() -> None:
    """Only official agent-to-controller pairs may be wrapped."""
    traci = FakeTraCI()
    with pytest.raises(ValueError, match="Unknown selected agent"):
        TrafficSignal("unknown", TRAFFIC_LIGHT_ID, traci)
    with pytest.raises(ValueError, match="maps to"):
        TrafficSignal(AGENT_ID, "wrong-controller", traci)


def test_controlled_lanes_are_deduplicated_in_source_order() -> None:
    """Repeated controlled lanes must preserve their first occurrence."""
    signal, _ = make_signal()
    assert signal.incoming_lane_ids == ("lane_2", "lane_1")


def test_expected_lanes_define_stable_order_after_validation() -> None:
    """A matching expected lane tuple may select a stable feature order."""
    signal, _ = make_signal(expected_lanes=("lane_1", "lane_2"))
    assert signal.incoming_lane_ids == ("lane_1", "lane_2")


def test_observation_reads_injected_fake_traci_data() -> None:
    """TrafficSignal.observe must build per-lane values from injected domains."""
    signal, _ = make_signal()
    observation = signal.observe()
    assert observation.incoming_lane_ids == ("lane_2", "lane_1")
    assert observation.queue_lengths == (1, 0)
    assert observation.vehicle_counts == (3, 0)
    assert observation.mean_waiting_times == (15.0, 0.0)
    assert observation.mean_speeds == (pytest.approx(10.15 / 3.0), 0.0)
    assert observation.is_green_phase
    assert not observation.is_transition_phase


def test_observation_skips_a_vehicle_that_disappears_mid_query() -> None:
    """A transient vehicle lookup failure must not discard the whole lane."""
    signal, traci = make_signal()
    traci.vehicle.disappeared.add("threshold")
    observation = signal.observe()
    assert observation.vehicle_counts == (2, 0)
    assert observation.queue_lengths == (1, 0)
    assert observation.mean_waiting_times == (15.0, 0.0)


def test_missing_controller_and_missing_lanes_fail_clearly() -> None:
    """Structural runtime errors must not be silently treated as empty traffic."""
    with pytest.raises(ValueError, match="missing"):
        make_signal(FakeTraCI(available=False))
    with pytest.raises(ValueError, match="controls no incoming lanes"):
        make_signal(FakeTraCI(controlled_lanes=()))


def test_transition_actions_are_blocked_without_traci_mutation() -> None:
    """No action may interrupt an original yellow phase."""
    signal, traci = make_signal()
    traci.trafficlight.phase_index = 1
    traci.trafficlight.spent_duration = 1.0
    result = signal.apply_action(TrafficAction.NEXT_GREEN)
    assert result.status is ActionStatus.TRANSITION_IN_PROGRESS
    assert not result.phase_changed
    assert traci.trafficlight.set_phase_calls == []


def test_minimum_green_rejects_switch_and_holds_phase() -> None:
    """NEXT_GREEN must not switch before the minimum green time."""
    signal, traci = make_signal()
    traci.simulation.time = 5.0
    traci.trafficlight.spent_duration = 5.0
    traci.trafficlight.next_switch = 6.0
    result = signal.apply_action(TrafficAction.NEXT_GREEN)
    assert result.status is ActionStatus.REJECTED_MINIMUM_GREEN
    assert traci.trafficlight.set_phase_calls == []
    assert traci.trafficlight.set_phase_duration_calls == [5.0]


def test_switch_after_minimum_uses_only_immediate_original_phase() -> None:
    """A permitted switch must enter yellow index 1 rather than green index 3."""
    signal, traci = make_signal()
    original_states = tuple(
        phase.state for phase in traci.trafficlight.logic.phases
    )
    traci.simulation.time = 10.0
    traci.trafficlight.spent_duration = 10.0
    result = signal.apply_action(TrafficAction.NEXT_GREEN)
    assert result.status is ActionStatus.APPLIED
    assert result.previous_phase_index == 0
    assert result.resulting_phase_index == 1
    assert traci.trafficlight.set_phase_calls == [1]
    assert traci.trafficlight.set_phase_duration_calls == [3.0]
    assert tuple(
        phase.state for phase in traci.trafficlight.logic.phases
    ) == original_states


def test_keep_forces_immediate_transition_at_maximum_green() -> None:
    """KEEP must enter the immediate yellow phase at the maximum green."""
    signal, traci = make_signal()
    traci.simulation.time = 60.0
    traci.trafficlight.spent_duration = 60.0
    result = signal.apply_action(TrafficAction.KEEP)
    assert result.status is ActionStatus.FORCED_MAXIMUM_GREEN
    assert result.resulting_phase_index == 1
    assert traci.trafficlight.set_phase_calls == [1]


def test_direct_green_to_conflicting_green_is_never_applied() -> None:
    """An unsafe program layout must not receive a direct setPhase call."""
    traci = FakeTraCI(phase_states=("GGrr", "rrGG"))
    signal, _ = make_signal(traci)
    traci.simulation.time = 10.0
    traci.trafficlight.spent_duration = 10.0
    result = signal.apply_action(TrafficAction.NEXT_GREEN)
    assert result.status is ActionStatus.INVALID_ACTION
    assert not result.phase_changed
    assert traci.trafficlight.set_phase_calls == []


def test_synchronize_tracks_automatic_phase_changes() -> None:
    """Automatic transition completion must update index, state, and elapsed."""
    signal, traci = make_signal()
    traci.simulation.time = 20.0
    traci.trafficlight.phase_index = 3
    traci.trafficlight.spent_duration = 2.0
    signal.synchronize()
    observation = signal.observe()
    assert signal.current_phase_index == 3
    assert observation.current_phase_index == 3
    assert observation.current_phase_state == "rrGG"
    assert observation.current_phase_elapsed_seconds == 2.0
    assert observation.is_green_phase


def test_normalization_config_uses_lane_limits_and_maximum_green() -> None:
    """The wrapper should prefer runtime lane speed limits over its fallback."""
    signal, _ = make_signal()
    config = signal.normalization_config()
    assert config.lane_speed_caps == (15.0, 10.0)
    assert config.phase_elapsed_cap == 60.0


def test_traffic_signal_reward_delegates_to_pure_reward_function() -> None:
    """The wrapper must not store or calculate experiment metrics."""
    signal, _ = make_signal()
    observation = signal.observe()
    assert signal.calculate_local_reward(observation) == calculate_local_reward(
        observation
    )


def test_interface_sources_do_not_start_sumo_or_import_evaluation() -> None:
    """Importable interface modules must remain lifecycle and metrics independent."""
    interface_files = (
        PROJECT_ROOT / "src" / "environment" / "observations.py",
        PROJECT_ROOT / "src" / "environment" / "actions.py",
        PROJECT_ROOT / "src" / "environment" / "rewards.py",
        PROJECT_ROOT / "src" / "environment" / "traffic_signal.py",
    )
    combined_source = "\n".join(
        path.read_text(encoding="utf-8") for path in interface_files
    )
    forbidden_evaluation_import = "src." + "evaluation"
    assert forbidden_evaluation_import not in combined_source
    assert ".start(" not in combined_source
    assert ".close(" not in combined_source
    assert "setProgramLogic" not in combined_source

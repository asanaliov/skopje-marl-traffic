"""Safe TraCI wrapper for one selected traffic-light agent."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol

from src.environment.actions import (
    ActionPolicyConfig,
    ActionResult,
    ActionStatus,
    TrafficAction,
    find_green_phase_indices,
    find_immediate_next_phase_index,
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
    RewardBreakdown,
    RewardWeights,
    calculate_local_reward,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR


class _SimulationDomain(Protocol):
    """TraCI simulation operations used by ``TrafficSignal``."""

    def getTime(self) -> float:  # noqa: N802
        """Return the current simulation time."""


class _TrafficLightDomain(Protocol):
    """TraCI traffic-light operations used by ``TrafficSignal``."""

    def getIDList(self) -> Sequence[str]:  # noqa: N802
        """Return available traffic-light IDs."""

    def getProgram(self, traffic_light_id: str) -> str:  # noqa: N802
        """Return the active program ID."""

    def getAllProgramLogics(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> Sequence[Any]:
        """Return all program logic objects."""

    def getControlledLanes(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> Sequence[str]:
        """Return controlled incoming lane IDs."""

    def getPhase(self, traffic_light_id: str) -> int:  # noqa: N802
        """Return the current phase index."""

    def getRedYellowGreenState(  # noqa: N802
        self,
        traffic_light_id: str,
    ) -> str:
        """Return the current signal state."""

    def setPhase(self, traffic_light_id: str, phase_index: int) -> None:  # noqa: N802
        """Select one original program phase."""

    def setPhaseDuration(  # noqa: N802
        self,
        traffic_light_id: str,
        duration_seconds: float,
    ) -> None:
        """Set the remaining duration of the current phase."""


class _LaneDomain(Protocol):
    """TraCI lane operations used by ``TrafficSignal``."""

    def getLastStepVehicleIDs(self, lane_id: str) -> Sequence[str]:  # noqa: N802
        """Return vehicle IDs observed on one lane."""


class _VehicleDomain(Protocol):
    """TraCI vehicle operations used by ``TrafficSignal``."""

    def getSpeed(self, vehicle_id: str) -> float:  # noqa: N802
        """Return one vehicle speed."""

    def getAccumulatedWaitingTime(self, vehicle_id: str) -> float:  # noqa: N802
        """Return one vehicle's accumulated waiting time."""


class TraCIConnection(Protocol):
    """Small structural interface required from an injected TraCI connection."""

    simulation: _SimulationDomain
    trafficlight: _TrafficLightDomain
    lane: _LaneDomain
    vehicle: _VehicleDomain


def _deduplicate_preserving_order(values: Sequence[str]) -> tuple[str, ...]:
    """Remove duplicate strings while retaining their first source position."""
    return tuple(dict.fromkeys(values))


def _logic_program_id(logic: Any) -> str:
    """Read a TraCI logic program ID across supported object variants."""
    program_id = getattr(logic, "programID", None)
    if program_id is not None:
        return str(program_id)
    getter = getattr(logic, "getSubID", None)
    if callable(getter):
        return str(getter())
    raise ValueError("A traffic-light program logic is missing its program ID.")


def _logic_phases(logic: Any) -> tuple[Any, ...]:
    """Read a TraCI logic's immutable phase snapshot."""
    phases = getattr(logic, "phases", None)
    if phases is None:
        getter = getattr(logic, "getPhases", None)
        if not callable(getter):
            raise ValueError("The active traffic-light logic does not expose phases.")
        phases = getter()
    return tuple(phases)


class TrafficSignal:
    """One selected traffic-light agent backed by an injected TraCI connection.

    The wrapper never starts or closes SUMO.
    Its owner controls the simulation lifecycle and decides when to observe or
    apply a safe high-level action.
    """

    def __init__(
        self,
        agent_id: str,
        traffic_light_id: str,
        traci_connection: TraCIConnection,
        action_policy: ActionPolicyConfig | None = None,
        reward_weights: RewardWeights | None = None,
        expected_incoming_lane_ids: Sequence[str] | None = None,
    ) -> None:
        """Validate the selected mapping and initialize the runtime snapshot."""
        self.agent_id = agent_id
        self.traffic_light_id = traffic_light_id
        self._traci = traci_connection
        self.action_policy = action_policy or ActionPolicyConfig()
        self.reward_weights = reward_weights or RewardWeights()
        self._expected_incoming_lane_ids = (
            tuple(expected_incoming_lane_ids)
            if expected_incoming_lane_ids is not None
            else None
        )
        self._phase_states: tuple[str, ...] = ()
        self._phase_durations: tuple[float, ...] = ()
        self._green_phase_indices: tuple[int, ...] = ()
        self._incoming_lane_ids: tuple[str, ...] = ()
        self._phase_index = 0
        self._phase_state = ""
        self._phase_start_time = 0.0
        self._phase_elapsed_seconds = 0.0
        self._initialized = False
        self.initialize()

    @property
    def phase_states(self) -> tuple[str, ...]:
        """Return the active program's original phase states."""
        return self._phase_states

    @property
    def phase_count(self) -> int:
        """Return the active program's phase count."""
        return len(self._phase_states)

    @property
    def phase_durations(self) -> tuple[float, ...]:
        """Return the active program's original phase durations."""
        return self._phase_durations

    @property
    def green_phase_indices(self) -> tuple[int, ...]:
        """Return original indices classified as green phases."""
        return self._green_phase_indices

    @property
    def incoming_lane_ids(self) -> tuple[str, ...]:
        """Return deterministic deduplicated controlled incoming lane IDs."""
        return self._incoming_lane_ids

    @property
    def current_phase_index(self) -> int:
        """Return the most recently synchronized phase index."""
        return self._phase_index

    def _validate_selected_mapping(self) -> None:
        """Require this wrapper to match one official selected agent mapping."""
        if not self.agent_id.strip():
            raise ValueError("agent_id must not be empty.")
        if not self.traffic_light_id.strip():
            raise ValueError("traffic_light_id must not be empty.")
        expected_traffic_light_id = SELECTED_CORRIDOR.agent_to_traffic_light.get(
            self.agent_id
        )
        if expected_traffic_light_id is None:
            selected = ", ".join(SELECTED_CORRIDOR.agent_ids)
            raise ValueError(
                f"Unknown selected agent {self.agent_id!r}. Choose one of: {selected}."
            )
        if self.traffic_light_id != expected_traffic_light_id:
            raise ValueError(
                f"Selected agent {self.agent_id} maps to "
                f"{expected_traffic_light_id!r}, not {self.traffic_light_id!r}."
            )

    def _read_program_phases(self) -> tuple[tuple[str, ...], tuple[float, ...]]:
        """Read phase states and durations from the active runtime program."""
        traffic_lights = self._traci.trafficlight
        active_program_id = str(traffic_lights.getProgram(self.traffic_light_id))
        matching_logics = [
            logic
            for logic in traffic_lights.getAllProgramLogics(self.traffic_light_id)
            if _logic_program_id(logic) == active_program_id
        ]
        if not matching_logics:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} has no logic for active "
                f"program {active_program_id!r}."
            )
        if len(matching_logics) > 1:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} exposes duplicate logic "
                f"definitions for active program {active_program_id!r}."
            )
        phases = _logic_phases(matching_logics[0])
        if not phases:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} has no program phases."
            )
        states = tuple(str(getattr(phase, "state", "")) for phase in phases)
        if any(not state for state in states):
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} has an empty phase state."
            )
        durations = tuple(
            float(getattr(phase, "duration", math.nan)) for phase in phases
        )
        if any(
            not math.isfinite(duration) or duration <= 0.0
            for duration in durations
        ):
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} has an invalid "
                "original phase duration."
            )
        return states, durations

    def _read_incoming_lanes(self) -> tuple[str, ...]:
        """Read and deterministically deduplicate controlled incoming lanes."""
        detected = _deduplicate_preserving_order(
            tuple(
                str(lane_id)
                for lane_id in self._traci.trafficlight.getControlledLanes(
                    self.traffic_light_id
                )
            )
        )
        if not detected:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} controls no incoming lanes."
            )
        if any(not lane_id for lane_id in detected):
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} returned an empty lane ID."
            )

        if self._expected_incoming_lane_ids is None:
            return detected

        expected = _deduplicate_preserving_order(
            tuple(str(lane_id) for lane_id in self._expected_incoming_lane_ids)
        )
        if not expected or any(not lane_id for lane_id in expected):
            raise ValueError("Expected incoming lane IDs must be non-empty.")
        if set(expected) != set(detected):
            missing = sorted(set(expected) - set(detected))
            unexpected = sorted(set(detected) - set(expected))
            raise ValueError(
                f"Controlled lanes for {self.traffic_light_id!r} do not match the "
                f"expected lanes. Missing={missing}, unexpected={unexpected}."
            )
        return expected

    def _simulation_time(self) -> float:
        """Read and validate current SUMO simulation time."""
        simulation_time = float(self._traci.simulation.getTime())
        if not math.isfinite(simulation_time) or simulation_time < 0.0:
            raise ValueError(
                f"SUMO returned invalid simulation time {simulation_time!r}."
            )
        return simulation_time

    def _read_direct_spent_duration(self) -> float | None:
        """Use TraCI's direct spent-duration API when the connection exposes it."""
        getter = getattr(self._traci.trafficlight, "getSpentDuration", None)
        if not callable(getter):
            return None
        try:
            elapsed = float(getter(self.traffic_light_id))
        except (AttributeError, NotImplementedError):
            return None
        if not math.isfinite(elapsed) or elapsed < 0.0:
            raise ValueError(
                f"SUMO returned invalid phase spent duration {elapsed!r} for "
                f"{self.traffic_light_id!r}."
            )
        return elapsed

    def initialize(self) -> None:
        """Load the active program, incoming lanes, and current phase snapshot."""
        self._validate_selected_mapping()
        available_ids = set(self._traci.trafficlight.getIDList())
        if self.traffic_light_id not in available_ids:
            raise ValueError(
                f"Selected traffic-light controller {self.traffic_light_id!r} "
                "is missing from the active SUMO connection."
            )

        self._phase_states, self._phase_durations = self._read_program_phases()
        self._green_phase_indices = find_green_phase_indices(self._phase_states)
        if not self._green_phase_indices:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} has no valid green phase."
            )
        self._incoming_lane_ids = self._read_incoming_lanes()

        simulation_time = self._simulation_time()
        phase_index = int(
            self._traci.trafficlight.getPhase(self.traffic_light_id)
        )
        self._validate_phase_index(phase_index)
        phase_state = str(
            self._traci.trafficlight.getRedYellowGreenState(self.traffic_light_id)
        )
        if not phase_state:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} returned an empty state."
            )
        elapsed = self._read_direct_spent_duration()
        self._phase_index = phase_index
        self._phase_state = phase_state
        self._phase_elapsed_seconds = elapsed if elapsed is not None else 0.0
        self._phase_start_time = simulation_time - self._phase_elapsed_seconds
        self._initialized = True

    def _validate_phase_index(self, phase_index: int) -> None:
        """Require one runtime index to exist in the active program."""
        if phase_index < 0 or phase_index >= len(self._phase_states):
            raise ValueError(
                f"SUMO phase index {phase_index} is outside the active "
                f"{len(self._phase_states)}-phase program for "
                f"{self.traffic_light_id!r}."
            )

    def synchronize(self) -> None:
        """Synchronize tracked phase timing with automatic or external changes."""
        if not self._initialized:
            raise RuntimeError("TrafficSignal must be initialized before use.")
        simulation_time = self._simulation_time()
        phase_index = int(
            self._traci.trafficlight.getPhase(self.traffic_light_id)
        )
        self._validate_phase_index(phase_index)
        phase_state = str(
            self._traci.trafficlight.getRedYellowGreenState(self.traffic_light_id)
        )
        if not phase_state:
            raise ValueError(
                f"Traffic light {self.traffic_light_id!r} returned an empty state."
            )

        direct_elapsed = self._read_direct_spent_duration()
        if direct_elapsed is not None:
            elapsed = direct_elapsed
            phase_start_time = simulation_time - elapsed
        elif phase_index != self._phase_index:
            elapsed = 0.0
            phase_start_time = simulation_time
        else:
            elapsed = max(simulation_time - self._phase_start_time, 0.0)
            phase_start_time = self._phase_start_time

        self._phase_index = phase_index
        self._phase_state = phase_state
        self._phase_elapsed_seconds = elapsed
        self._phase_start_time = phase_start_time

    @staticmethod
    def _is_transient_vehicle_lookup_error(error: Exception) -> bool:
        """Recognize a vehicle that vanished after the lane snapshot was read."""
        error_type = type(error)
        return isinstance(error, KeyError) or (
            error_type.__name__ == "TraCIException"
            and error_type.__module__.startswith("traci")
        )

    def observe(self) -> TrafficObservation:
        """Read one lane-level observation without changing the signal program."""
        self.synchronize()
        queue_lengths: list[int] = []
        vehicle_counts: list[int] = []
        mean_waiting_times: list[float] = []
        mean_speeds: list[float] = []

        for lane_id in self._incoming_lane_ids:
            lane_vehicle_ids = tuple(
                self._traci.lane.getLastStepVehicleIDs(lane_id)
            )
            sampled_vehicle_ids: list[str] = []
            speeds: list[float] = []
            waiting_times: list[float] = []
            for vehicle_id in lane_vehicle_ids:
                try:
                    speed = float(self._traci.vehicle.getSpeed(vehicle_id))
                    waiting_time = float(
                        self._traci.vehicle.getAccumulatedWaitingTime(vehicle_id)
                    )
                except Exception as error:
                    if self._is_transient_vehicle_lookup_error(error):
                        continue
                    raise
                sampled_vehicle_ids.append(vehicle_id)
                speeds.append(speed)
                waiting_times.append(waiting_time)

            vehicle_counts.append(count_vehicles_on_lane(sampled_vehicle_ids))
            queue_lengths.append(count_queued_vehicles(speeds))
            mean_waiting_times.append(calculate_mean_waiting_time(waiting_times))
            mean_speeds.append(calculate_mean_speed(speeds))

        return TrafficObservation(
            agent_id=self.agent_id,
            traffic_light_id=self.traffic_light_id,
            simulation_time=self._simulation_time(),
            incoming_lane_ids=self._incoming_lane_ids,
            queue_lengths=tuple(queue_lengths),
            vehicle_counts=tuple(vehicle_counts),
            mean_waiting_times=tuple(mean_waiting_times),
            mean_speeds=tuple(mean_speeds),
            current_phase_index=self._phase_index,
            current_phase_state=self._phase_state,
            current_phase_elapsed_seconds=self._phase_elapsed_seconds,
            is_green_phase=is_green_phase_state(self._phase_state),
            is_transition_phase=is_transition_phase_state(self._phase_state),
        )

    def normalization_config(
        self,
        base_config: ObservationNormalizationConfig | None = None,
    ) -> ObservationNormalizationConfig:
        """Build normalization caps using lane speed limits when available."""
        config = base_config or ObservationNormalizationConfig()
        get_max_speed = getattr(self._traci.lane, "getMaxSpeed", None)
        lane_speed_caps = config.lane_speed_caps
        if callable(get_max_speed):
            lane_speed_caps = tuple(
                float(get_max_speed(lane_id)) for lane_id in self._incoming_lane_ids
            )
        return replace(
            config,
            phase_elapsed_cap=self.action_policy.maximum_green_seconds,
            lane_speed_caps=lane_speed_caps,
        )

    @staticmethod
    def _coerce_action(action: TrafficAction | int) -> TrafficAction | None:
        """Convert a supported integer to ``TrafficAction`` without guessing."""
        if isinstance(action, bool):
            return None
        try:
            return TrafficAction(action)
        except (TypeError, ValueError):
            return None

    def _remaining_phase_duration(self, simulation_time: float) -> float | None:
        """Read the scheduled remaining phase duration when TraCI exposes it."""
        getter = getattr(self._traci.trafficlight, "getNextSwitch", None)
        if not callable(getter):
            return None
        try:
            next_switch = float(getter(self.traffic_light_id))
        except (AttributeError, NotImplementedError):
            return None
        if not math.isfinite(next_switch):
            raise ValueError(
                f"SUMO returned invalid next-switch time {next_switch!r} for "
                f"{self.traffic_light_id!r}."
            )
        return max(next_switch - simulation_time, 0.0)

    def _hold_current_green(self, minimum_remaining: float) -> None:
        """Keep green only as long as timing policy and the next decision need."""
        maximum_remaining = max(
            self.action_policy.maximum_green_seconds
            - self._phase_elapsed_seconds,
            0.0,
        )
        desired_remaining = min(max(minimum_remaining, 0.0), maximum_remaining)
        if desired_remaining <= 0.0:
            return

        simulation_time = self._simulation_time()
        current_remaining = self._remaining_phase_duration(simulation_time)
        duration_to_set: float | None = None
        tolerance = 1e-9
        if current_remaining is None:
            duration_to_set = desired_remaining
        elif current_remaining + tolerance < desired_remaining:
            duration_to_set = desired_remaining
        elif current_remaining - tolerance > maximum_remaining:
            duration_to_set = maximum_remaining

        if duration_to_set is not None:
            self._traci.trafficlight.setPhaseDuration(
                self.traffic_light_id,
                duration_to_set,
            )

    def _transition_to_immediate_next_phase(
        self,
        requested_action: TrafficAction,
        status: ActionStatus,
    ) -> ActionResult:
        """Enter exactly one original transition phase without skipping."""
        previous_phase_index = self._phase_index
        next_phase_index = find_immediate_next_phase_index(
            previous_phase_index,
            self.phase_count,
        )
        next_phase_state = self._phase_states[next_phase_index]
        if (
            next_phase_index == previous_phase_index
            or not is_transition_phase_state(next_phase_state)
        ):
            return ActionResult(
                requested_action=requested_action,
                status=ActionStatus.INVALID_ACTION,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message=(
                    "The immediate next original program phase is not a safe "
                    "yellow or all-red transition phase."
                ),
            )

        self._traci.trafficlight.setPhase(
            self.traffic_light_id,
            next_phase_index,
        )
        self._traci.trafficlight.setPhaseDuration(
            self.traffic_light_id,
            self._phase_durations[next_phase_index],
        )
        simulation_time = self._simulation_time()
        self._phase_index = next_phase_index
        self._phase_state = next_phase_state
        self._phase_start_time = simulation_time
        self._phase_elapsed_seconds = 0.0
        return ActionResult(
            requested_action=requested_action,
            status=status,
            previous_phase_index=previous_phase_index,
            resulting_phase_index=next_phase_index,
            phase_changed=True,
            message=(
                "Entered the immediate next original transition phase; SUMO "
                "will continue through the remaining program sequence."
            ),
        )

    def apply_action(self, action: TrafficAction | int) -> ActionResult:
        """Apply KEEP or initiate a safe transition toward the next green."""
        self.synchronize()
        previous_phase_index = self._phase_index
        requested_action = self._coerce_action(action)
        if requested_action is None:
            return ActionResult(
                requested_action=action,
                status=ActionStatus.INVALID_ACTION,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message=(
                    "Only TrafficAction.KEEP and TrafficAction.NEXT_GREEN are valid."
                ),
            )

        if is_transition_phase_state(self._phase_state):
            return ActionResult(
                requested_action=requested_action,
                status=ActionStatus.TRANSITION_IN_PROGRESS,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message=(
                    "The original yellow or all-red transition is still in progress."
                ),
            )
        if not is_green_phase_state(self._phase_state):
            return ActionResult(
                requested_action=requested_action,
                status=ActionStatus.INVALID_ACTION,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message="The current program phase is neither green nor a transition.",
            )

        elapsed = self._phase_elapsed_seconds
        if requested_action is TrafficAction.KEEP:
            if elapsed >= self.action_policy.maximum_green_seconds:
                return self._transition_to_immediate_next_phase(
                    requested_action,
                    ActionStatus.FORCED_MAXIMUM_GREEN,
                )
            self._hold_current_green(
                min(
                    self.action_policy.decision_interval_seconds,
                    self.action_policy.maximum_green_seconds - elapsed,
                )
            )
            return ActionResult(
                requested_action=requested_action,
                status=ActionStatus.KEPT,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message="Kept the current green within the maximum-green limit.",
            )

        if elapsed < self.action_policy.minimum_green_seconds:
            self._hold_current_green(
                max(
                    self.action_policy.minimum_green_seconds - elapsed,
                    self.action_policy.decision_interval_seconds,
                )
            )
            return ActionResult(
                requested_action=requested_action,
                status=ActionStatus.REJECTED_MINIMUM_GREEN,
                previous_phase_index=previous_phase_index,
                resulting_phase_index=previous_phase_index,
                phase_changed=False,
                message=(
                    "Rejected NEXT_GREEN because the minimum green time has "
                    "not been satisfied."
                ),
            )

        return self._transition_to_immediate_next_phase(
            requested_action,
            ActionStatus.APPLIED,
        )

    def calculate_local_reward(
        self,
        observation: TrafficObservation,
        phase_switched: bool = False,
    ) -> RewardBreakdown:
        """Delegate local learning feedback to the pure reward function."""
        if observation.agent_id != self.agent_id:
            raise ValueError(
                f"Observation belongs to {observation.agent_id!r}, not "
                f"{self.agent_id!r}."
            )
        if observation.traffic_light_id != self.traffic_light_id:
            raise ValueError(
                "Observation traffic-light ID does not match this wrapper."
            )
        return calculate_local_reward(
            observation,
            phase_switched=phase_switched,
            weights=self.reward_weights,
        )


__all__ = ["TraCIConnection", "TrafficSignal"]

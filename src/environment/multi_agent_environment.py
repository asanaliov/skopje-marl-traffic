"""SUMO lifecycle orchestration for selected traffic-light agents."""

from __future__ import annotations

import importlib
import math
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from src.demand.scenarios import get_scenario
from src.demand.xml_writer import scenario_output_files
from src.environment.actions import (
    ActionPolicyConfig,
    ActionResult,
    ActionStatus,
    TrafficAction,
)
from src.environment.observations import TrafficObservation
from src.environment.rewards import (
    RewardBreakdown,
    RewardWeights,
    global_corridor_reward,
    neighbor_aware_reward,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR
from src.environment.traffic_signal import TrafficSignal


RewardMode = Literal["local", "neighbor_aware", "global"]
_REWARD_MODES = ("local", "neighbor_aware", "global")


def _validate_finite_seconds(
    value: float,
    field_name: str,
    *,
    allow_zero: bool = False,
) -> float:
    """Return one valid duration as a float."""
    seconds = float(value)
    valid_sign = seconds >= 0.0 if allow_zero else seconds > 0.0
    if not math.isfinite(seconds) or not valid_sign:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be a finite {qualifier} value.")
    return seconds


@dataclass(frozen=True, slots=True)
class MultiAgentEnvironmentConfig:
    """Immutable settings for one single-agent or multi-agent SUMO episode."""

    scenario: str = "medium"
    seed: int = 42
    sumo_seed: int | None = None
    agent_ids: tuple[str, ...] = SELECTED_CORRIDOR.agent_ids
    demand_seconds: float = 3600.0
    cooldown_seconds: float = 600.0
    decision_interval_seconds: float = 5.0
    sumo_step_length_seconds: float = 1.0
    gui: bool = False
    reward_mode: RewardMode = "local"
    action_policy: ActionPolicyConfig = field(default_factory=ActionPolicyConfig)
    reward_weights: RewardWeights = field(default_factory=RewardWeights)
    require_complete_action_mappings: bool = True
    neighbor_local_weight: float = 0.7
    neighbor_reward_weight: float = 0.3

    def __post_init__(self) -> None:
        """Validate values and normalize configured agents to corridor order."""
        scenario = get_scenario(str(self.scenario)).name
        if (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or self.seed < 0
        ):
            raise ValueError("seed must be a non-negative integer.")
        if self.sumo_seed is not None and (
            not isinstance(self.sumo_seed, int)
            or isinstance(self.sumo_seed, bool)
            or self.sumo_seed < 0
        ):
            raise ValueError("sumo_seed must be a non-negative integer or None.")
        if isinstance(self.agent_ids, str):
            raise ValueError("agent_ids must be a non-empty sequence of agent IDs.")

        requested_agent_ids = tuple(self.agent_ids)
        if not requested_agent_ids:
            raise ValueError("agent_ids must contain at least one selected agent.")
        if any(not isinstance(agent_id, str) for agent_id in requested_agent_ids):
            raise ValueError("agent_ids must contain only strings.")
        if len(requested_agent_ids) != len(set(requested_agent_ids)):
            raise ValueError("agent_ids must not contain duplicates.")

        unknown_agent_ids = sorted(
            set(requested_agent_ids) - set(SELECTED_CORRIDOR.agent_ids)
        )
        if unknown_agent_ids:
            valid_agents = ", ".join(SELECTED_CORRIDOR.agent_ids)
            unknown = ", ".join(unknown_agent_ids)
            raise ValueError(
                f"Unknown selected agent IDs: {unknown}. Choose from: {valid_agents}."
            )
        ordered_agent_ids = tuple(
            agent_id
            for agent_id in SELECTED_CORRIDOR.agent_ids
            if agent_id in requested_agent_ids
        )

        demand_seconds = _validate_finite_seconds(
            self.demand_seconds,
            "demand_seconds",
        )
        cooldown_seconds = _validate_finite_seconds(
            self.cooldown_seconds,
            "cooldown_seconds",
            allow_zero=True,
        )
        decision_interval = _validate_finite_seconds(
            self.decision_interval_seconds,
            "decision_interval_seconds",
        )
        step_length = _validate_finite_seconds(
            self.sumo_step_length_seconds,
            "sumo_step_length_seconds",
        )
        steps_per_decision = decision_interval / step_length
        if not math.isclose(
            steps_per_decision,
            round(steps_per_decision),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "decision_interval_seconds must be an integer multiple of "
                "sumo_step_length_seconds."
            )

        if self.reward_mode not in _REWARD_MODES:
            valid_modes = ", ".join(_REWARD_MODES)
            raise ValueError(
                f"Unknown reward_mode {self.reward_mode!r}. Choose from: {valid_modes}."
            )
        if not isinstance(self.gui, bool):
            raise ValueError("gui must be a boolean.")
        if not isinstance(self.require_complete_action_mappings, bool):
            raise ValueError("require_complete_action_mappings must be a boolean.")
        if not isinstance(self.action_policy, ActionPolicyConfig):
            raise TypeError("action_policy must be an ActionPolicyConfig.")
        if not isinstance(self.reward_weights, RewardWeights):
            raise TypeError("reward_weights must be RewardWeights.")

        neighbor_weights = (
            float(self.neighbor_local_weight),
            float(self.neighbor_reward_weight),
        )
        if any(
            not math.isfinite(weight) or weight < 0.0
            for weight in neighbor_weights
        ):
            raise ValueError(
                "Neighbor reward weights must be finite and non-negative."
            )
        if not math.isclose(
            sum(neighbor_weights),
            1.0,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError("Neighbor reward weights must sum to 1.0.")

        object.__setattr__(self, "scenario", scenario)
        object.__setattr__(self, "agent_ids", ordered_agent_ids)
        object.__setattr__(self, "demand_seconds", demand_seconds)
        object.__setattr__(self, "cooldown_seconds", cooldown_seconds)
        object.__setattr__(
            self,
            "decision_interval_seconds",
            decision_interval,
        )
        object.__setattr__(self, "sumo_step_length_seconds", step_length)
        object.__setattr__(
            self,
            "action_policy",
            replace(
                self.action_policy,
                decision_interval_seconds=decision_interval,
            ),
        )
        object.__setattr__(self, "neighbor_local_weight", neighbor_weights[0])
        object.__setattr__(self, "neighbor_reward_weight", neighbor_weights[1])

    @property
    def simulation_seed(self) -> int:
        """Return the seed handed to SUMO for this episode.

        ``seed`` selects the *generated demand file*, so it also decides which
        vehicles exist at all. ``sumo_seed`` seeds only SUMO's own randomness --
        driver imperfection, lane choices -- on top of that fixed demand, which
        is what a caller wants when it needs episode-to-episode variation
        without a second generated scenario. It defaults to ``seed``, so an
        episode that sets neither behaves exactly as before.
        """
        return self.seed if self.sumo_seed is None else self.sumo_seed

    @property
    def total_duration_seconds(self) -> float:
        """Return the demand period plus the cooldown period."""
        return self.demand_seconds + self.cooldown_seconds


@dataclass(frozen=True, slots=True)
class MultiAgentStepResult:
    """Immutable result of one environment decision interval."""

    observations: Mapping[str, TrafficObservation]
    rewards: Mapping[str, float]
    terminated: bool
    truncated: bool
    info: Mapping[str, object]


def _load_traci() -> Any:
    """Import TraCI from Python or the configured SUMO installation."""
    try:
        return importlib.import_module("traci")
    except ImportError as initial_error:
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            tools_directory = Path(sumo_home) / "tools"
            if tools_directory.is_dir() and str(tools_directory) not in sys.path:
                sys.path.insert(0, str(tools_directory))
                try:
                    return importlib.import_module("traci")
                except ImportError:
                    pass
        raise RuntimeError(
            "Could not import traci. Install the project requirements or set "
            "SUMO_HOME to the SUMO installation."
        ) from initial_error


def _find_sumo_executable(use_gui: bool) -> Path:
    """Locate SUMO on PATH or below SUMO_HOME."""
    executable_name = "sumo-gui" if use_gui else "sumo"
    executable_path = shutil.which(executable_name)
    if executable_path:
        return Path(executable_path)

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_directory = Path(sumo_home) / "bin"
        for candidate in (
            bin_directory / executable_name,
            bin_directory / f"{executable_name}.exe",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        f"{executable_name} was not found on PATH or under SUMO_HOME."
    )


class MultiAgentTrafficEnvironment:
    """Own one SUMO connection and coordinate selected TrafficSignal wrappers."""

    def __init__(
        self,
        config: MultiAgentEnvironmentConfig | None = None,
        *,
        traci_connection: Any | None = None,
        traffic_signal_factory: Callable[..., Any] = TrafficSignal,
        sumo_executable: str | Path | None = None,
        on_raw_step: Callable[[Any], None] | None = None,
    ) -> None:
        """Store validated configuration without starting SUMO."""
        self.config = config or MultiAgentEnvironmentConfig()
        if not isinstance(self.config, MultiAgentEnvironmentConfig):
            raise TypeError("config must be a MultiAgentEnvironmentConfig.")
        self._provided_traci = traci_connection
        self._traffic_signal_factory = traffic_signal_factory
        self._provided_sumo_executable = (
            Path(sumo_executable) if sumo_executable is not None else None
        )
        self._traci: Any | None = None
        self._on_raw_step = on_raw_step
        self._traffic_signals: dict[str, Any] = {}
        self._started = False
        self._done = False
        self._episode_start_time = 0.0
        self._decision_step = 0
        self._departed_vehicle_count = 0
        self._arrived_vehicle_count = 0

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Return configured agents in official corridor order."""
        return self.config.agent_ids

    @property
    def traffic_signals(self) -> Mapping[str, Any]:
        """Return the live TrafficSignal wrappers by agent.

        The mapping is empty until ``reset()`` has started SUMO, and it is
        read-only: the environment stays the single owner of the wrappers.
        Callers that need controller metadata which only exists once SUMO is
        running -- the active program's phase count, or the lane speed limits
        behind ``normalization_config()`` -- read it from here instead of
        opening a second TraCI connection.
        """
        return MappingProxyType(dict(self._traffic_signals))

    @property
    def is_running(self) -> bool:
        """Return whether this instance currently owns a live TraCI session."""
        return self._started and self._traci is not None

    def __enter__(self) -> MultiAgentTrafficEnvironment:
        """Return this environment while deferring startup to reset()."""
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool:
        """Always close TraCI and propagate any exception."""
        self.close()
        return False

    def _sumo_command(self, configuration_file: Path) -> list[str]:
        """Build the command for this episode without changing input files."""
        executable = self._provided_sumo_executable or _find_sumo_executable(
            self.config.gui
        )
        return [
            str(executable),
            "-c",
            str(configuration_file.resolve()),
            "--end",
            f"{self.config.total_duration_seconds:g}",
            "--seed",
            str(self.config.simulation_seed),
            "--step-length",
            f"{self.config.sumo_step_length_seconds:g}",
        ]

    def _simulation_time(self) -> float:
        """Read a valid simulation time from the active connection."""
        if self._traci is None:
            raise RuntimeError("The environment has no active TraCI connection.")
        simulation_time = float(self._traci.simulation.getTime())
        if not math.isfinite(simulation_time) or simulation_time < 0.0:
            raise ValueError(
                f"SUMO returned invalid simulation time {simulation_time!r}."
            )
        return simulation_time

    def _collect_observations(self) -> Mapping[str, TrafficObservation]:
        """Observe every configured wrapper in deterministic order."""
        observations = {
            agent_id: self._traffic_signals[agent_id].observe()
            for agent_id in self.agent_ids
        }
        return MappingProxyType(observations)

    def reset(self) -> Mapping[str, TrafficObservation]:
        """Restart SUMO, create all wrappers, and return initial observations."""
        self.close()
        scenario = get_scenario(self.config.scenario)
        if self.config.seed < 0:
            raise ValueError("seed must be a non-negative integer.")
        outputs = scenario_output_files(scenario.name, self.config.seed)
        if not outputs.configuration_file.is_file():
            raise FileNotFoundError(
                "Generated scenario configuration is missing: "
                f"{outputs.configuration_file}. Generate scenario "
                f"{scenario.name!r} with seed {self.config.seed} first."
            )

        command = self._sumo_command(outputs.configuration_file)
        connection = self._provided_traci or _load_traci()
        self._traci = connection
        self._started = True
        try:
            connection.start(command)
            self._traffic_signals = {}
            for agent_id in self.agent_ids:
                traffic_light_id = SELECTED_CORRIDOR.agent_to_traffic_light[agent_id]
                signal = self._traffic_signal_factory(
                    agent_id=agent_id,
                    traffic_light_id=traffic_light_id,
                    traci_connection=connection,
                    action_policy=self.config.action_policy,
                    reward_weights=self.config.reward_weights,
                )
                if getattr(signal, "agent_id", None) != agent_id:
                    raise ValueError(
                        "TrafficSignal creation returned the wrong agent for "
                        f"{agent_id}."
                    )
                if getattr(signal, "traffic_light_id", None) != traffic_light_id:
                    raise ValueError(
                        "TrafficSignal creation returned the wrong traffic-light "
                        f"mapping for {agent_id}."
                    )
                self._traffic_signals[agent_id] = signal

            if tuple(self._traffic_signals) != self.agent_ids:
                raise RuntimeError(
                    "Not all configured TrafficSignal wrappers were created."
                )

            self._episode_start_time = self._simulation_time()
            self._decision_step = 0
            self._departed_vehicle_count = 0
            self._arrived_vehicle_count = 0
            self._done = False
            return self._collect_observations()
        except Exception:
            self.close()
            raise

    def _validate_actions(
        self,
        actions: Mapping[str, TrafficAction],
    ) -> None:
        """Reject incomplete, unknown, or invalid controlled action mappings."""
        if not isinstance(actions, Mapping):
            raise TypeError("actions must be a mapping or None.")
        unknown_agents = sorted(set(actions) - set(self.agent_ids))
        if unknown_agents:
            raise ValueError(
                "Actions contain unknown or unconfigured agents: "
                f"{', '.join(unknown_agents)}."
            )
        if self.config.require_complete_action_mappings:
            missing_agents = [
                agent_id for agent_id in self.agent_ids if agent_id not in actions
            ]
            if missing_agents:
                raise ValueError(
                    "Actions are missing configured agents: "
                    f"{', '.join(missing_agents)}."
                )
        invalid_actions = {
            agent_id: action
            for agent_id, action in actions.items()
            if not isinstance(action, TrafficAction)
        }
        if invalid_actions:
            details = ", ".join(
                f"{agent_id}={action!r}"
                for agent_id, action in invalid_actions.items()
            )
            raise ValueError(f"Invalid traffic actions: {details}.")

    def _advance_simulation(self) -> tuple[int, int]:
        """Advance one decision interval one SUMO step at a time."""
        if self._traci is None:
            raise RuntimeError("The environment has no active TraCI connection.")
        step_count = round(
            self.config.decision_interval_seconds
            / self.config.sumo_step_length_seconds
        )
        departed_this_step = 0
        arrived_this_step = 0
        time_limit = (
            self._episode_start_time + self.config.total_duration_seconds
        )
        for _ in range(step_count):
            self._traci.simulationStep()
            if self._on_raw_step is not None:
                self._on_raw_step(self._traci)
            get_departed = getattr(
                self._traci.simulation,
                "getDepartedNumber",
                None,
            )
            get_arrived = getattr(
                self._traci.simulation,
                "getArrivedNumber",
                None,
            )
            if callable(get_departed):
                departed_this_step += int(get_departed())
            if callable(get_arrived):
                arrived_this_step += int(get_arrived())
            if int(self._traci.simulation.getMinExpectedNumber()) <= 0:
                break
            if self._simulation_time() >= time_limit:
                break
        self._departed_vehicle_count += departed_this_step
        self._arrived_vehicle_count += arrived_this_step
        return departed_this_step, arrived_this_step

    def _calculate_rewards(
        self,
        observations: Mapping[str, TrafficObservation],
        action_results: Mapping[str, ActionResult],
    ) -> tuple[Mapping[str, RewardBreakdown], Mapping[str, float]]:
        """Calculate local breakdowns and convert them to the selected mode."""
        local_breakdowns = {
            agent_id: self._traffic_signals[agent_id].calculate_local_reward(
                observations[agent_id],
                phase_switched=(
                    action_results[agent_id].phase_changed
                    if agent_id in action_results
                    else False
                ),
            )
            for agent_id in self.agent_ids
        }
        local_rewards = {
            agent_id: breakdown.total_reward
            for agent_id, breakdown in local_breakdowns.items()
        }

        if self.config.reward_mode == "local":
            rewards = local_rewards
        elif self.config.reward_mode == "neighbor_aware":
            configured_agents = set(self.agent_ids)
            rewards = {
                agent_id: neighbor_aware_reward(
                    local_rewards[agent_id],
                    (
                        local_rewards[neighbor_id]
                        for neighbor_id in SELECTED_CORRIDOR.neighbor_map[agent_id]
                        if neighbor_id in configured_agents
                    ),
                    local_weight=self.config.neighbor_local_weight,
                    neighbor_weight=self.config.neighbor_reward_weight,
                )
                for agent_id in self.agent_ids
            }
        else:
            global_reward = global_corridor_reward(local_rewards.values())
            rewards = dict.fromkeys(self.agent_ids, global_reward)

        return MappingProxyType(local_breakdowns), MappingProxyType(rewards)

    def _halted_vehicle_count(self) -> int | None:
        """Count halted active vehicles when the connection exposes vehicle IDs."""
        if self._traci is None:
            return None
        get_vehicle_ids = getattr(self._traci.vehicle, "getIDList", None)
        get_speed = getattr(self._traci.vehicle, "getSpeed", None)
        if not callable(get_vehicle_ids) or not callable(get_speed):
            return None

        halted_count = 0
        for vehicle_id in tuple(get_vehicle_ids()):
            try:
                halted_count += float(get_speed(vehicle_id)) < 0.1
            except Exception:
                continue
        return halted_count

    def step(
        self,
        actions: Mapping[str, TrafficAction] | None,
    ) -> MultiAgentStepResult:
        """Apply optional safe actions and advance one decision interval."""
        if not self.is_running:
            raise RuntimeError("reset() must be called before step().")
        if self._done:
            raise RuntimeError("The episode is complete. Call reset() before step().")

        try:
            action_results: dict[str, ActionResult] = {}
            if actions is not None:
                self._validate_actions(actions)
                for agent_id in self.agent_ids:
                    if agent_id in actions:
                        action_results[agent_id] = self._traffic_signals[
                            agent_id
                        ].apply_action(actions[agent_id])

            departed_this_step, arrived_this_step = self._advance_simulation()
            for agent_id in self.agent_ids:
                self._traffic_signals[agent_id].synchronize()
            observations = self._collect_observations()
            local_breakdowns, rewards = self._calculate_rewards(
                observations,
                action_results,
            )

            self._decision_step += 1
            simulation_time = self._simulation_time()
            active_expected_count = int(
                self._traci.simulation.getMinExpectedNumber()
            )
            terminated = active_expected_count <= 0
            time_limit_reached = (
                simulation_time - self._episode_start_time
                >= self.config.total_duration_seconds - 1e-9
            )
            truncated = time_limit_reached and not terminated
            self._done = terminated or truncated

            transition_agents = tuple(
                agent_id
                for agent_id, observation in observations.items()
                if observation.is_transition_phase
            )
            forced_agents = tuple(
                agent_id
                for agent_id, result in action_results.items()
                if result.status is ActionStatus.FORCED_MAXIMUM_GREEN
            )
            info = MappingProxyType(
                {
                    "simulation_time": simulation_time,
                    "decision_step": self._decision_step,
                    "scenario": self.config.scenario,
                    "seed": self.config.seed,
                    "agent_ids": self.agent_ids,
                    "action_results": MappingProxyType(action_results),
                    "local_reward_breakdowns": local_breakdowns,
                    "reward_mode": self.config.reward_mode,
                    "departed_vehicle_count": self._departed_vehicle_count,
                    "arrived_vehicle_count": self._arrived_vehicle_count,
                    "departed_vehicle_count_this_step": departed_this_step,
                    "arrived_vehicle_count_this_step": arrived_this_step,
                    "active_expected_vehicle_count": active_expected_count,
                    "halted_vehicle_count": self._halted_vehicle_count(),
                    "transition_agents": transition_agents,
                    "forced_maximum_green_agents": forced_agents,
                }
            )
            return MultiAgentStepResult(
                observations=observations,
                rewards=rewards,
                terminated=terminated,
                truncated=truncated,
                info=info,
            )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Close TraCI safely and clear all runtime state."""
        connection = self._traci
        should_close = self._started and connection is not None
        self._traci = None
        self._traffic_signals = {}
        self._started = False
        self._done = False
        self._episode_start_time = 0.0
        self._decision_step = 0
        self._departed_vehicle_count = 0
        self._arrived_vehicle_count = 0
        if should_close:
            try:
                connection.close()
            except Exception:
                pass


__all__ = [
    "MultiAgentEnvironmentConfig",
    "MultiAgentStepResult",
    "MultiAgentTrafficEnvironment",
    "RewardMode",
]

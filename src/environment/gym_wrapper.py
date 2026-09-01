"""Standard Gymnasium and PettingZoo interfaces for the selected corridor.

`MultiAgentTrafficEnvironment` speaks the project's own vocabulary: it takes
`TrafficAction` values and returns `TrafficObservation` objects, which is what
the tabular Q-learning trainers want, because they discretize those
observations themselves. Deep RL libraries want the opposite: fixed-size float
vectors, integer actions, and the exact `reset()` / `step()` signatures of the
standard APIs.

This module is that adapter, and only that adapter. It adds no learning, no
reward shaping, and no state beyond what the wrapped environment already
produces:

* `CorridorParallelEnv` is the PettingZoo **parallel** API -- every corridor
  agent acts in the same decision interval, which is exactly how the SUMO
  environment already works, so no turn-based conversion is involved. Use it
  with multi-agent libraries (Ray/RLlib, MAPPO implementations, ...).
* `SingleAgentTrafficEnv` is the Gymnasium API for exactly one corridor agent
  while the other traffic lights stay on their imported SUMO programs -- the
  same experimental setup as `src/training/independent_q_learning.py`, but
  usable directly with Stable-Baselines3.

Observations are `TrafficObservation.normalized_features()`, so every value is
already clipped into ``[0.0, 1.0]``: per lane the queue length, vehicle count,
mean waiting time and mean speed, then the normalized phase elapsed time, then
a one-hot vector over the program's phases.

The observation size therefore depends on how many lanes a junction controls
and how many phases its program has -- both facts about the *running* network.
Deep RL libraries need the spaces before anything is running, so the spaces are
sized from the audited corridor metadata in
`sumo/skopje/documentation/traffic_light_audit.csv` and then verified against
the live SUMO program on every `reset()`, which turns a stale audit into a
readable error instead of a silent shape mismatch deep inside a training loop.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal

import numpy as np
from gymnasium import Env, spaces
from pettingzoo import ParallelEnv

from src.demand.xml_writer import scenario_output_files
from src.environment.actions import TrafficAction
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentStepResult,
    MultiAgentTrafficEnvironment,
)
from src.environment.observations import (
    ObservationNormalizationConfig,
    TrafficObservation,
)
from src.environment.selected_corridor import (
    SELECTED_CORRIDOR,
    controlled_lane_counts_by_agent,
    phase_counts_by_agent,
)


ENVIRONMENT_NAME = "skopje_corridor_v0"
"""PettingZoo environment name, versioned so later observation changes are visible."""

LANE_FEATURE_COUNT = 4
"""Queue length, vehicle count, mean waiting time, and mean speed per lane."""

PHASE_ELAPSED_FEATURE_COUNT = 1
"""The single normalized phase-elapsed feature between lane and one-hot features."""

OBSERVATION_DTYPE = np.float32
"""Deep RL libraries expect float32 observations; the features are plain ratios."""

DEFAULT_GYM_AGENT_ID = "A19"
"""The corridor agent the single-agent trainers already use as their default."""

EnvironmentFactory = Callable[
    [MultiAgentEnvironmentConfig],
    MultiAgentTrafficEnvironment,
]

RenderMode = Literal["human"]


def _generated_scenario_exists(config: MultiAgentEnvironmentConfig) -> bool:
    """Return whether the demand for this scenario and seed was generated."""
    outputs = scenario_output_files(config.scenario, config.seed)
    return outputs.configuration_file.is_file()


def _build_environment(
    config: MultiAgentEnvironmentConfig,
) -> MultiAgentTrafficEnvironment:
    """Create the real SUMO environment for one wrapper instance."""
    return MultiAgentTrafficEnvironment(config)


@dataclass(frozen=True, slots=True)
class AgentSpaceSpec:
    """Immutable observation shape of one corridor agent.

    ``lane_count`` counts deduplicated controlled incoming lanes, exactly as
    `TrafficSignal` reports them, and ``phase_count`` counts the phases of the
    agent's active traffic-light program including its yellow and all-red
    transition phases.
    """

    agent_id: str
    lane_count: int
    phase_count: int

    def __post_init__(self) -> None:
        """Reject shapes that could not describe a real traffic light."""
        if not self.agent_id.strip():
            raise ValueError("agent_id must not be empty.")
        for field_name in ("lane_count", "phase_count"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"{field_name} for {self.agent_id} must be a positive integer, "
                    f"got {value!r}."
                )

    @property
    def feature_count(self) -> int:
        """Return the length of one ``normalized_features()`` tuple."""
        return (
            LANE_FEATURE_COUNT * self.lane_count
            + PHASE_ELAPSED_FEATURE_COUNT
            + self.phase_count
        )

    def observation_space(self) -> spaces.Box:
        """Return a new continuous observation space for this agent."""
        return spaces.Box(
            low=0.0,
            high=1.0,
            shape=(self.feature_count,),
            dtype=OBSERVATION_DTYPE,
        )


def action_space() -> spaces.Discrete:
    """Return a new discrete action space: 0 is KEEP, 1 is NEXT_GREEN."""
    return spaces.Discrete(len(TrafficAction))


def audited_space_specs(
    agent_ids: Iterable[str] | None = None,
) -> Mapping[str, AgentSpaceSpec]:
    """Return observation shapes taken from the audited corridor metadata.

    This is what lets a library ask for `observation_space` before any SUMO
    process exists. The values come from the same audit CSV that defines the
    selected corridor, and every `reset()` re-checks them against the running
    network.
    """
    requested = (
        tuple(SELECTED_CORRIDOR.agent_ids) if agent_ids is None else tuple(agent_ids)
    )
    unknown = sorted(set(requested) - set(SELECTED_CORRIDOR.agent_ids))
    if unknown:
        valid = ", ".join(SELECTED_CORRIDOR.agent_ids)
        raise ValueError(
            f"Unknown selected agent IDs: {', '.join(unknown)}. Choose from: {valid}."
        )

    lane_counts = controlled_lane_counts_by_agent(SELECTED_CORRIDOR)
    phase_counts = phase_counts_by_agent(SELECTED_CORRIDOR)
    specs: dict[str, AgentSpaceSpec] = {}
    for agent_id in requested:
        lane_count = lane_counts[agent_id]
        phase_count = phase_counts[agent_id]
        if lane_count is None or phase_count is None:
            raise ValueError(
                f"The traffic-light audit has no controlled lane count or phase "
                f"count for {agent_id}, so its observation space cannot be sized. "
                "Re-run scripts/audit_traffic_lights.py."
            )
        specs[agent_id] = AgentSpaceSpec(
            agent_id=agent_id,
            lane_count=lane_count,
            phase_count=phase_count,
        )
    return specs


def observation_vector(
    observation: TrafficObservation,
    spec: AgentSpaceSpec,
    normalization: ObservationNormalizationConfig | None = None,
) -> np.ndarray:
    """Convert one observation into a float32 vector matching ``spec``."""
    features = observation.normalized_features(spec.phase_count, normalization)
    if len(features) != spec.feature_count:
        raise ValueError(
            f"Agent {spec.agent_id} produced {len(features)} observation features "
            f"but its space declares {spec.feature_count}. The traffic-light audit "
            "no longer matches the running network; re-run "
            "scripts/audit_traffic_lights.py."
        )
    return np.asarray(features, dtype=OBSERVATION_DTYPE)


def _coerce_action(agent_id: str, action: Any) -> TrafficAction:
    """Convert one sampled discrete action into a validated TrafficAction."""
    if isinstance(action, TrafficAction):
        return action
    if isinstance(action, bool) or isinstance(action, np.bool_):
        raise ValueError(
            f"Action for {agent_id} must be an integer action index, not a boolean."
        )
    if isinstance(action, (int, np.integer)):
        try:
            return TrafficAction(int(action))
        except ValueError as error:
            valid = ", ".join(
                f"{member.value}={member.name}" for member in TrafficAction
            )
            raise ValueError(
                f"Action {int(action)} for {agent_id} is outside the discrete "
                f"action space. Valid actions: {valid}."
            ) from error
    if (
        isinstance(action, np.ndarray)
        and action.shape == ()
        and action.dtype.kind in "iu"
    ):
        return _coerce_action(agent_id, action.item())
    raise TypeError(
        f"Action for {agent_id} must be an integer action index or a TrafficAction, "
        f"got {type(action).__name__}."
    )


class _CorridorRunner:
    """Shared SUMO lifecycle and feature encoding for both public wrappers.

    Both wrapped APIs need the same three things: start the environment,
    turn `TrafficObservation` objects into vectors sized by the audited
    specs, and confirm the running program still matches those specs. Keeping
    that here means the PettingZoo and Gymnasium classes only differ in how
    they *shape* the same values.
    """

    def __init__(
        self,
        config: MultiAgentEnvironmentConfig,
        *,
        environment_factory: EnvironmentFactory,
        normalization: ObservationNormalizationConfig | None,
        space_specs: Mapping[str, AgentSpaceSpec] | None,
    ) -> None:
        """Store configuration and resolve the observation shape of every agent."""
        if not isinstance(config, MultiAgentEnvironmentConfig):
            raise TypeError("config must be a MultiAgentEnvironmentConfig.")
        self.config = config
        self._environment_factory = environment_factory
        self._normalization = normalization
        self.space_specs = dict(
            space_specs
            if space_specs is not None
            else audited_space_specs(config.agent_ids)
        )
        missing = [
            agent_id
            for agent_id in config.agent_ids
            if agent_id not in self.space_specs
        ]
        if missing:
            raise ValueError(
                "Observation space specifications are missing configured agents: "
                f"{', '.join(missing)}."
            )
        self._environment: MultiAgentTrafficEnvironment | None = None
        self._normalizations: dict[str, ObservationNormalizationConfig] = {}

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Return the configured agents in official corridor order."""
        return self.config.agent_ids

    @property
    def environment(self) -> MultiAgentTrafficEnvironment | None:
        """Return the wrapped environment, or None before the first reset."""
        return self._environment

    def start(self, seed: int | None) -> Mapping[str, TrafficObservation]:
        """Close any previous episode and start a new one."""
        self.close()
        config = self.config
        if seed is not None:
            requested_seed = int(seed)
            if requested_seed != config.seed:
                # A seed here selects a *generated demand file*, not a live RNG:
                # only generated scenarios exist as episodes. Deep RL libraries
                # seed environments with numbers of their own choosing, so an
                # ungenerated seed keeps the configured scenario and says so
                # rather than failing a training run that never asked for a
                # different demand.
                candidate = replace(config, seed=requested_seed)
                if _generated_scenario_exists(candidate):
                    config = candidate
                    self.config = config
                else:
                    missing = scenario_output_files(
                        candidate.scenario,
                        candidate.seed,
                    ).configuration_file
                    warnings.warn(
                        f"reset(seed={requested_seed}) was ignored: no demand "
                        f"has been generated at {missing}, so the episode keeps "
                        f"the configured seed {config.seed}. Generate it with "
                        "python scripts/generate_traffic_demand.py --scenario "
                        f"{candidate.scenario} --seed {requested_seed}.",
                        UserWarning,
                        stacklevel=3,
                    )
        environment = self._environment_factory(config)
        self._environment = environment
        observations = environment.reset()
        self._resolve_normalizations()
        return observations

    def _resolve_normalizations(self) -> None:
        """Confirm the live programs match the declared spaces and cache caps."""
        if self._environment is None:
            raise RuntimeError("The environment was not started.")
        signals = self._environment.traffic_signals
        self._normalizations = {}
        for agent_id in self.agent_ids:
            signal = signals[agent_id]
            spec = self.space_specs[agent_id]
            live_phase_count = int(signal.phase_count)
            live_lane_count = len(tuple(signal.incoming_lane_ids))
            if (
                live_phase_count != spec.phase_count
                or live_lane_count != spec.lane_count
            ):
                raise ValueError(
                    f"The running SUMO program for {agent_id} has "
                    f"{live_lane_count} controlled lanes and {live_phase_count} "
                    f"phases, but its observation space was sized for "
                    f"{spec.lane_count} lanes and {spec.phase_count} phases. "
                    "Re-run scripts/audit_traffic_lights.py, or pass matching "
                    "space_specs."
                )
            self._normalizations[agent_id] = signal.normalization_config(
                self._normalization
            )

    def vector(self, observation: TrafficObservation) -> np.ndarray:
        """Encode one observation with this episode's normalization caps."""
        agent_id = observation.agent_id
        return observation_vector(
            observation,
            self.space_specs[agent_id],
            self._normalizations.get(agent_id, self._normalization),
        )

    def vectors(
        self,
        observations: Mapping[str, TrafficObservation],
    ) -> dict[str, np.ndarray]:
        """Encode every configured agent's observation."""
        return {
            agent_id: self.vector(observations[agent_id])
            for agent_id in self.agent_ids
        }

    def step(
        self,
        actions: Mapping[str, TrafficAction],
    ) -> MultiAgentStepResult:
        """Advance the wrapped environment by one decision interval."""
        if self._environment is None:
            raise RuntimeError("reset() must be called before step().")
        return self._environment.step(dict(actions))

    def close(self) -> None:
        """Close SUMO and forget this episode's runtime state."""
        environment = self._environment
        self._environment = None
        self._normalizations = {}
        if environment is not None:
            environment.close()


def _agent_info(
    agent_id: str,
    observation: TrafficObservation,
    result: MultiAgentStepResult,
) -> dict[str, Any]:
    """Return one agent's diagnostic info entry for a completed step."""
    action_results = result.info.get("action_results", {})
    action_result = action_results.get(agent_id) if action_results else None
    breakdowns = result.info.get("local_reward_breakdowns", {})
    breakdown = breakdowns.get(agent_id) if breakdowns else None
    info: dict[str, Any] = {
        "simulation_time": result.info.get("simulation_time"),
        "decision_step": result.info.get("decision_step"),
        "current_phase_index": observation.current_phase_index,
        "is_transition_phase": observation.is_transition_phase,
        "total_queue_length": sum(observation.queue_lengths),
    }
    if action_result is not None:
        info["action_status"] = action_result.status.value
        info["phase_changed"] = action_result.phase_changed
    if breakdown is not None:
        info["local_reward"] = breakdown.total_reward
    return info


def _resolved_config(
    config: MultiAgentEnvironmentConfig | None,
    render_mode: RenderMode | None,
) -> MultiAgentEnvironmentConfig:
    """Return the episode configuration, honouring the requested render mode."""
    resolved = config or MultiAgentEnvironmentConfig()
    if not isinstance(resolved, MultiAgentEnvironmentConfig):
        raise TypeError("config must be a MultiAgentEnvironmentConfig.")
    if render_mode is not None and render_mode not in ("human",):
        raise ValueError(
            f"Unsupported render_mode {render_mode!r}. Use 'human' or None."
        )
    if render_mode == "human" and not resolved.gui:
        resolved = replace(resolved, gui=True)
    return resolved


class CorridorParallelEnv(ParallelEnv):
    """The selected Skopje corridor as a PettingZoo parallel environment.

    Every configured agent observes, acts, and is rewarded in the same
    decision interval. Termination is a property of the SUMO episode rather
    than of a single junction, so all agents finish together: `terminated`
    when no vehicle is left to simulate, `truncated` when the configured
    episode duration -- or the optional `max_cycles` -- runs out.

    ``render_mode='human'`` means SUMO-GUI draws the running simulation
    itself, so `render()` has nothing left to do and returns None.
    """

    metadata = {
        "render_modes": ["human"],
        "name": ENVIRONMENT_NAME,
        "is_parallelizable": True,
    }

    def __init__(
        self,
        config: MultiAgentEnvironmentConfig | None = None,
        *,
        render_mode: RenderMode | None = None,
        max_cycles: int | None = None,
        normalization: ObservationNormalizationConfig | None = None,
        space_specs: Mapping[str, AgentSpaceSpec] | None = None,
        environment_factory: EnvironmentFactory = _build_environment,
    ) -> None:
        """Build the fixed agent set and spaces without starting SUMO."""
        resolved = _resolved_config(config, render_mode)
        if max_cycles is not None and (
            not isinstance(max_cycles, int)
            or isinstance(max_cycles, bool)
            or max_cycles <= 0
        ):
            raise ValueError("max_cycles must be a positive integer or None.")

        self._runner = _CorridorRunner(
            resolved,
            environment_factory=environment_factory,
            normalization=normalization,
            space_specs=space_specs,
        )
        self.render_mode = render_mode
        self.max_cycles = max_cycles
        self.possible_agents = list(resolved.agent_ids)
        self.agents: list[str] = []
        # PettingZoo requires the *identical* space object on every lookup, so
        # both spaces are built once here instead of per call.
        self._observation_spaces = {
            agent_id: self._runner.space_specs[agent_id].observation_space()
            for agent_id in self.possible_agents
        }
        self._action_spaces = {
            agent_id: action_space() for agent_id in self.possible_agents
        }
        self._decision_step = 0

    @property
    def config(self) -> MultiAgentEnvironmentConfig:
        """Return the configuration of the current or next episode."""
        return self._runner.config

    @property
    def observation_spaces(self) -> Mapping[str, spaces.Box]:
        """Return every agent's observation space."""
        return dict(self._observation_spaces)

    @property
    def action_spaces(self) -> Mapping[str, spaces.Discrete]:
        """Return every agent's action space."""
        return dict(self._action_spaces)

    def observation_space(self, agent: str) -> spaces.Box:
        """Return one agent's continuous observation space."""
        return self._space(self._observation_spaces, agent)

    def action_space(self, agent: str) -> spaces.Discrete:
        """Return one agent's discrete KEEP / NEXT_GREEN action space."""
        return self._space(self._action_spaces, agent)

    def _space(self, source: Mapping[str, Any], agent: str) -> Any:
        """Look up one agent's space with a readable error."""
        try:
            return source[agent]
        except KeyError:
            valid = ", ".join(self.possible_agents)
            raise ValueError(
                f"Unknown agent {agent!r}. This environment controls: {valid}."
            ) from None

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, dict[str, Any]]]:
        """Restart SUMO and return the first observation of every agent.

        ``seed`` selects the generated demand file for the episode, matching
        the ``--seed`` of the training runners. Only generated scenarios exist
        as episodes, so a seed without generated demand keeps the configured
        one and warns, naming the file and the command that would create it.
        ``options`` is accepted for API compatibility and is not used.
        """
        observations = self._runner.start(seed)
        self.agents = list(self.possible_agents)
        self._decision_step = 0
        vectors = self._runner.vectors(observations)
        infos: dict[str, dict[str, Any]] = {
            agent_id: {} for agent_id in self.agents
        }
        return vectors, infos

    def step(
        self,
        actions: Mapping[str, Any],
    ) -> tuple[
        dict[str, np.ndarray],
        dict[str, float],
        dict[str, bool],
        dict[str, bool],
        dict[str, dict[str, Any]],
    ]:
        """Apply one action per live agent and advance one decision interval."""
        if not self.agents:
            # PettingZoo's contract for a finished episode: nothing is live, so
            # there is nothing to report until reset() is called.
            return {}, {}, {}, {}, {}
        if not isinstance(actions, Mapping):
            raise TypeError("actions must be a mapping of agent ID to action.")

        unknown = sorted(set(actions) - set(self.agents))
        if unknown:
            raise ValueError(
                f"Actions contain agents that are not live: {', '.join(unknown)}."
            )
        missing = [agent_id for agent_id in self.agents if agent_id not in actions]
        if missing:
            raise ValueError(
                f"Actions are missing live agents: {', '.join(missing)}."
            )

        traffic_actions = {
            agent_id: _coerce_action(agent_id, action)
            for agent_id, action in actions.items()
        }
        result = self._runner.step(traffic_actions)
        self._decision_step += 1

        reached_cycle_limit = (
            self.max_cycles is not None and self._decision_step >= self.max_cycles
        )
        truncated = result.truncated or (
            reached_cycle_limit and not result.terminated
        )
        observations = self._runner.vectors(result.observations)
        rewards = {
            agent_id: float(result.rewards[agent_id]) for agent_id in self.agents
        }
        terminations = dict.fromkeys(self.agents, result.terminated)
        truncations = dict.fromkeys(self.agents, truncated)
        infos = {
            agent_id: _agent_info(
                agent_id,
                result.observations[agent_id],
                result,
            )
            for agent_id in self.agents
        }
        if result.terminated or truncated:
            self.agents = []
        return observations, rewards, terminations, truncations, infos

    def render(self) -> None:
        """Return None: with ``render_mode='human'`` SUMO-GUI draws itself."""
        return None

    def close(self) -> None:
        """Close SUMO and mark every agent as finished."""
        self.agents = []
        self._runner.close()

    def __enter__(self) -> CorridorParallelEnv:
        """Return this environment; SUMO starts in reset()."""
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object | None,
    ) -> bool:
        """Always close SUMO and propagate any exception."""
        self.close()
        return False


class SingleAgentTrafficEnv(Env):
    """One corridor traffic light as a standard Gymnasium environment.

    Only ``agent_id`` is controlled; every other traffic light in the Skopje
    network keeps running its imported SUMO program. That is the same setup as
    the single-agent tabular trainer, which is what makes a Stable-Baselines3
    run on this environment directly comparable with those results.
    """

    metadata = {"render_modes": ["human"], "name": ENVIRONMENT_NAME}

    def __init__(
        self,
        agent_id: str = DEFAULT_GYM_AGENT_ID,
        config: MultiAgentEnvironmentConfig | None = None,
        *,
        render_mode: RenderMode | None = None,
        max_episode_steps: int | None = None,
        normalization: ObservationNormalizationConfig | None = None,
        space_specs: Mapping[str, AgentSpaceSpec] | None = None,
        environment_factory: EnvironmentFactory = _build_environment,
    ) -> None:
        """Restrict the wrapped environment to exactly one controlled agent."""
        resolved = _resolved_config(config, render_mode)
        if tuple(resolved.agent_ids) != (agent_id,):
            resolved = replace(resolved, agent_ids=(agent_id,))
        self.agent_id = agent_id
        self._parallel = CorridorParallelEnv(
            resolved,
            render_mode=render_mode,
            max_cycles=max_episode_steps,
            normalization=normalization,
            space_specs=space_specs,
            environment_factory=environment_factory,
        )
        self.render_mode = render_mode
        self.observation_space = self._parallel.observation_space(agent_id)
        self.action_space = self._parallel.action_space(agent_id)

    @property
    def config(self) -> MultiAgentEnvironmentConfig:
        """Return the configuration of the current or next episode."""
        return self._parallel.config

    @property
    def parallel_env(self) -> CorridorParallelEnv:
        """Return the wrapped parallel environment for shared inspection."""
        return self._parallel

    def reset(
        self,
        *,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Restart SUMO and return this agent's first observation."""
        super().reset(seed=seed)
        observations, infos = self._parallel.reset(seed=seed, options=options)
        return observations[self.agent_id], infos[self.agent_id]

    def step(
        self,
        action: Any,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Apply one action and advance a single decision interval."""
        if not self._parallel.agents:
            raise RuntimeError("The episode is complete. Call reset() before step().")
        observations, rewards, terminations, truncations, infos = self._parallel.step(
            {self.agent_id: action}
        )
        return (
            observations[self.agent_id],
            float(rewards[self.agent_id]),
            bool(terminations[self.agent_id]),
            bool(truncations[self.agent_id]),
            infos[self.agent_id],
        )

    def render(self) -> None:
        """Return None: with ``render_mode='human'`` SUMO-GUI draws itself."""
        return None

    def close(self) -> None:
        """Close SUMO."""
        self._parallel.close()


def make_parallel_env(
    agent_ids: Sequence[str] | None = None,
    **kwargs: Any,
) -> CorridorParallelEnv:
    """Return a PettingZoo parallel environment for the given corridor agents."""
    config = kwargs.pop("config", None) or MultiAgentEnvironmentConfig()
    if agent_ids is not None:
        config = replace(config, agent_ids=tuple(agent_ids))
    return CorridorParallelEnv(config, **kwargs)


def make_single_agent_env(
    agent_id: str = DEFAULT_GYM_AGENT_ID,
    **kwargs: Any,
) -> SingleAgentTrafficEnv:
    """Return a Gymnasium environment controlling exactly one corridor agent."""
    return SingleAgentTrafficEnv(agent_id, **kwargs)


__all__ = [
    "AgentSpaceSpec",
    "CorridorParallelEnv",
    "DEFAULT_GYM_AGENT_ID",
    "ENVIRONMENT_NAME",
    "LANE_FEATURE_COUNT",
    "OBSERVATION_DTYPE",
    "PHASE_ELAPSED_FEATURE_COUNT",
    "SingleAgentTrafficEnv",
    "action_space",
    "audited_space_specs",
    "make_parallel_env",
    "make_single_agent_env",
    "observation_vector",
]

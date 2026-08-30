"""Multi-agent independent Q-learning across the selected Skopje corridor.

This is the "Independent Reinforcement Learning" comparison baseline: all
eight corridor agents act in the *same* SUMO episode, but each one keeps
its own tabular Q-table and learns only from its own local reward by
default. There is no shared value function and no joint action space --
that is exactly what makes ``reward_mode="local"`` the independent
baseline that coordinated MARL work has to beat.

Contrast with ``src/training/independent_q_learning.py``, which drives a
single agent (A19) while the other seven traffic lights stay on their
imported SUMO programs.

``spatial_observations`` adds one communication channel: each agent
additionally sees a coarse congestion flag for its nearest neighbors, so
it can anticipate an arriving platoon. ``reward_mode`` adds a second,
independent channel: agents can keep learning from purely local rewards
(the default), or have their reward blended with their neighbors'
rewards (``neighbor_aware``), or replaced by the corridor-wide mean
reward (``global``) so that greedy local optimization does not just
shove a bottleneck onto the next junction. See
``src/environment/rewards.py`` and
``MultiAgentEnvironmentConfig.reward_mode`` for how the mixing itself is
calculated -- this module only has to select the mode and forward it.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from src.agents.q_learning_agent import QLearningAgent, QLearningConfig
from src.agents.state_encoder import DiscreteTrafficState, TrafficStateEncoder
from src.environment.actions import TrafficAction
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentTrafficEnvironment,
    RewardMode,
)
from src.environment.selected_corridor import (
    SELECTED_CORRIDOR,
    nearest_neighbor_ids,
)
from src.evaluation.collector import MetricsCollector
from src.evaluation.results_writer import append_result
from src.training.checkpoint_state import state_from_json, state_to_json


TrainingMode = Literal["train", "evaluate"]

CONTROLLER_NAME = "multi_agent_independent_rl"
SPATIAL_CONTROLLER_NAME = "multi_agent_spatial_rl"
NEIGHBOR_REWARD_CONTROLLER_NAME = "marl_neighbor_reward"
GLOBAL_REWARD_CONTROLLER_NAME = "marl_global_reward"
CHECKPOINT_SCHEMA_VERSION = 1
DEFAULT_SPATIAL_NEIGHBOR_LIMIT = 2
"""Nearest neighbors observed per agent when spatial observations are on.

Each observed neighbor adds one bit to a tabular state, doubling the
reachable Q-table. Two neighbors keeps that growth at four times the local
state space even for A26, which has six audited neighbors.
"""

_REWARD_MODES: tuple[RewardMode, ...] = ("local", "neighbor_aware", "global")


@dataclass(frozen=True, slots=True)
class MultiAgentQLearningConfig:
    """Immutable settings for one multi-agent training or evaluation run."""

    agent_ids: tuple[str, ...] = SELECTED_CORRIDOR.agent_ids
    scenario: str = "medium"
    seed: int = 42
    episodes: int = 10
    episode_seconds: float = 600.0
    cooldown_seconds: float = 600.0
    decision_interval_seconds: float = 5.0
    gui: bool = False
    checkpoint_path: Path | None = None
    checkpoint_interval: int = 1
    mode: TrainingMode = "train"
    resume: bool = False
    spatial_observations: bool = False
    spatial_neighbor_limit: int = DEFAULT_SPATIAL_NEIGHBOR_LIMIT
    reward_mode: RewardMode = "local"

    def __post_init__(self) -> None:
        """Validate runner settings before a SUMO process is started."""
        if isinstance(self.agent_ids, str):
            raise ValueError("agent_ids must be a non-empty sequence of agent IDs.")
        requested = tuple(self.agent_ids)
        if not requested:
            raise ValueError("agent_ids must contain at least one agent.")
        if any(not isinstance(agent_id, str) for agent_id in requested):
            raise ValueError("agent_ids must contain only strings.")
        if len(requested) != len(set(requested)):
            raise ValueError("agent_ids must not contain duplicates.")
        unknown = sorted(set(requested) - set(SELECTED_CORRIDOR.agent_ids))
        if unknown:
            valid = ", ".join(SELECTED_CORRIDOR.agent_ids)
            raise ValueError(
                f"Unknown selected agent IDs: {', '.join(unknown)}. "
                f"Choose from: {valid}."
            )
        # Normalize to official corridor order so checkpoints, printed
        # summaries, and the environment all agree on agent ordering
        # regardless of how the caller listed them.
        requested_set = set(requested)
        object.__setattr__(
            self,
            "agent_ids",
            tuple(
                agent_id
                for agent_id in SELECTED_CORRIDOR.agent_ids
                if agent_id in requested_set
            ),
        )

        if (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or self.seed < 0
        ):
            raise ValueError("seed must be a non-negative integer.")
        if (
            not isinstance(self.episodes, int)
            or isinstance(self.episodes, bool)
            or self.episodes <= 0
        ):
            raise ValueError("episodes must be a positive integer.")
        for value, name in (
            (self.episode_seconds, "episode_seconds"),
            (self.cooldown_seconds, "cooldown_seconds"),
            (self.decision_interval_seconds, "decision_interval_seconds"),
        ):
            numeric = float(value)
            if not math.isfinite(numeric) or numeric <= 0.0:
                raise ValueError(f"{name} must be a finite positive value.")
            object.__setattr__(self, name, numeric)
        if not isinstance(self.gui, bool):
            raise ValueError("gui must be a boolean.")
        if (
            not isinstance(self.checkpoint_interval, int)
            or isinstance(self.checkpoint_interval, bool)
            or self.checkpoint_interval <= 0
        ):
            raise ValueError("checkpoint_interval must be a positive integer.")
        if self.mode not in ("train", "evaluate"):
            raise ValueError("mode must be 'train' or 'evaluate'.")
        if self.checkpoint_path is not None:
            object.__setattr__(self, "checkpoint_path", Path(self.checkpoint_path))
        if self.mode == "evaluate" and self.checkpoint_path is None:
            raise ValueError("evaluation requires an existing checkpoint path.")
        if not isinstance(self.resume, bool):
            raise ValueError("resume must be a boolean.")
        if self.resume and self.mode != "train":
            raise ValueError("resume is only supported in 'train' mode.")
        if self.resume and self.checkpoint_path is None:
            raise ValueError("resume requires a checkpoint path.")
        if not isinstance(self.spatial_observations, bool):
            raise ValueError("spatial_observations must be a boolean.")
        if (
            not isinstance(self.spatial_neighbor_limit, int)
            or isinstance(self.spatial_neighbor_limit, bool)
            or self.spatial_neighbor_limit <= 0
        ):
            raise ValueError(
                "spatial_neighbor_limit must be a positive integer."
            )
        if self.reward_mode not in _REWARD_MODES:
            valid_modes = ", ".join(_REWARD_MODES)
            raise ValueError(
                f"Unknown reward_mode {self.reward_mode!r}. Choose from: "
                f"{valid_modes}."
            )


@dataclass(frozen=True, slots=True)
class AgentEpisodeSummary:
    """Immutable per-agent metrics for one multi-agent episode."""

    agent_id: str
    total_reward: float
    mean_reward_per_decision: float
    final_epsilon: float
    q_table_state_count: int
    keep_action_count: int
    next_green_action_count: int


@dataclass(frozen=True, slots=True)
class MultiAgentEpisodeSummary:
    """Immutable combined metrics for one multi-agent episode."""

    episode: int
    scenario: str
    seed: int
    simulated_seconds: float
    decision_steps: int
    combined_total_reward: float
    mean_combined_reward_per_decision: float
    agents: Mapping[str, AgentEpisodeSummary]
    action_status_counts: Mapping[str, int]
    terminated: bool
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))
        object.__setattr__(
            self,
            "action_status_counts",
            MappingProxyType(dict(self.action_status_counts)),
        )


@dataclass(frozen=True, slots=True)
class MultiAgentDecisionResult:
    """Immutable result of one multi-agent decision interval."""

    actions: Mapping[str, TrafficAction]
    rewards: Mapping[str, float]
    combined_reward: float
    states: Mapping[str, DiscreteTrafficState]
    terminated: bool
    truncated: bool
    info: Mapping[str, object]

    def __post_init__(self) -> None:
        for field_name in ("actions", "rewards", "states"):
            object.__setattr__(
                self,
                field_name,
                MappingProxyType(dict(getattr(self, field_name))),
            )


class MultiAgentQLearningTrainer:
    """Train or evaluate one independent tabular learner per corridor agent."""

    def __init__(
        self,
        config: MultiAgentQLearningConfig | None = None,
        *,
        agents: Mapping[str, QLearningAgent] | None = None,
        encoder: TrafficStateEncoder | None = None,
        environment_factory: Callable[..., Any] | None = None,
        q_learning_config: QLearningConfig | None = None,
    ) -> None:
        self.config = config or MultiAgentQLearningConfig()
        self.encoder = encoder or TrafficStateEncoder()
        self.neighbor_ids_by_agent = self._build_neighbor_ids()
        self._encoders = self._build_encoders()
        self.agents = self._build_agents(agents, q_learning_config)
        self._environment_factory = (
            environment_factory or MultiAgentTrafficEnvironment
        )
        self.summaries: list[MultiAgentEpisodeSummary] = []

        # Live episode state, owned by reset() / step() / close().
        self._environment: Any | None = None
        self._collector: MetricsCollector | None = None
        self._states: dict[str, DiscreteTrafficState] = {}
        self._episode_finished = True
        self._simulated_seconds = 0.0

    def _build_neighbor_ids(self) -> Mapping[str, tuple[str, ...]]:
        """Return the neighbors each agent observes, empty when purely local.

        Only agents this run actually controls can be observed: a subset run
        must not read a junction nobody is stepping.
        """
        if not self.config.spatial_observations:
            return MappingProxyType(
                {agent_id: () for agent_id in self.config.agent_ids}
            )
        return MappingProxyType(
            {
                agent_id: nearest_neighbor_ids(
                    SELECTED_CORRIDOR,
                    agent_id,
                    limit=self.config.spatial_neighbor_limit,
                    observed_agent_ids=self.config.agent_ids,
                )
                for agent_id in self.config.agent_ids
            }
        )

    def _build_encoders(self) -> Mapping[str, TrafficStateEncoder]:
        """Return one encoder per agent, spatial ones carrying its neighbors."""
        if self.encoder.neighbor_ids is not None:
            raise ValueError(
                "The shared encoder must not be configured with neighbor_ids. "
                "Set spatial_observations=True instead, so every agent gets "
                "an encoder holding its own neighbors."
            )
        if not self.config.spatial_observations:
            return MappingProxyType(
                {agent_id: self.encoder for agent_id in self.config.agent_ids}
            )
        return MappingProxyType(
            {
                agent_id: TrafficStateEncoder(
                    self.encoder.config,
                    green_phase_indices=self.encoder.green_phase_indices,
                    neighbor_ids=neighbor_ids or None,
                )
                for agent_id, neighbor_ids in self.neighbor_ids_by_agent.items()
            }
        )

    @property
    def controller_name(self) -> str:
        """Return the results label for this run's reward and observation mode.

        Reward mode takes priority in the label because it changes what
        every agent's Q-values actually mean -- a neighbor-aware or global
        run is not comparable to (and must not silently share a checkpoint
        or a results row with) a local-only run, spatial or not.
        """
        if self.config.reward_mode == "neighbor_aware":
            return NEIGHBOR_REWARD_CONTROLLER_NAME
        if self.config.reward_mode == "global":
            return GLOBAL_REWARD_CONTROLLER_NAME
        return (
            SPATIAL_CONTROLLER_NAME
            if self.config.spatial_observations
            else CONTROLLER_NAME
        )

    def _encode_all(
        self,
        observations: Mapping[str, Any],
    ) -> dict[str, DiscreteTrafficState]:
        """Encode every agent, handing spatial encoders the shared snapshot.

        All agents are encoded from the same observation snapshot, so the
        neighbor flags an agent sees describe the corridor at the moment it
        chooses its action.
        """
        return {
            agent_id: self._encoders[agent_id].encode(
                observations[agent_id],
                observations if self.neighbor_ids_by_agent[agent_id] else None,
            )
            for agent_id in self.config.agent_ids
        }

    def _build_agents(
        self,
        agents: Mapping[str, QLearningAgent] | None,
        q_learning_config: QLearningConfig | None,
    ) -> dict[str, QLearningAgent]:
        """Return exactly one learner per configured agent, in corridor order."""
        if agents is not None:
            missing = [
                agent_id
                for agent_id in self.config.agent_ids
                if agent_id not in agents
            ]
            if missing:
                raise ValueError(
                    f"Missing learners for configured agents: {', '.join(missing)}."
                )
            unknown = sorted(set(agents) - set(self.config.agent_ids))
            if unknown:
                raise ValueError(
                    f"Learners given for unconfigured agents: {', '.join(unknown)}."
                )
            return {agent_id: agents[agent_id] for agent_id in self.config.agent_ids}

        base_config = q_learning_config or QLearningConfig()
        # Each learner gets its own RNG stream. Sharing one seed across all
        # eight agents would make them explore in lockstep -- identical
        # epsilon-greedy coin flips on every step -- which is a correlated
        # joint policy, not independent learning.
        return {
            agent_id: QLearningAgent(
                replace(base_config, random_seed=base_config.random_seed + index)
            )
            for index, agent_id in enumerate(self.config.agent_ids)
        }

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Return configured agents in official corridor order."""
        return self.config.agent_ids

    def _environment_config(self) -> MultiAgentEnvironmentConfig:
        return MultiAgentEnvironmentConfig(
            scenario=self.config.scenario,
            seed=self.config.seed,
            agent_ids=self.config.agent_ids,
            demand_seconds=self.config.episode_seconds,
            cooldown_seconds=self.config.cooldown_seconds,
            decision_interval_seconds=self.config.decision_interval_seconds,
            gui=self.config.gui,
            reward_mode=self.config.reward_mode,
        )

    def _validate_agent_mapping(
        self,
        mapping: Mapping[str, Any],
        field_name: str,
    ) -> None:
        """Require exactly one entry per configured agent."""
        if not isinstance(mapping, Mapping):
            raise TypeError(f"{field_name} must be a mapping.")
        missing = [
            agent_id
            for agent_id in self.config.agent_ids
            if agent_id not in mapping
        ]
        if missing:
            raise ValueError(
                f"{field_name} is missing configured agents: {', '.join(missing)}."
            )
        unknown = sorted(set(mapping) - set(self.config.agent_ids))
        if unknown:
            raise ValueError(
                f"{field_name} contains unconfigured agents: {', '.join(unknown)}."
            )

    def reset(self) -> Mapping[str, DiscreteTrafficState]:
        """Start one episode and return the initial state of every agent."""
        self.close()

        def _on_raw_step(traci_connection: Any) -> None:
            # The collector only exists once reset() below has learned which
            # incoming lanes to monitor, so earlier steps are simply skipped.
            if self._collector is not None:
                self._collector.record_step(traci_connection)

        environment = self._environment_factory(
            self._environment_config(),
            on_raw_step=_on_raw_step,
        )
        self._environment = environment
        try:
            observations = environment.reset()
            self._validate_agent_mapping(observations, "observations")
            monitored_lanes = sorted(
                {
                    lane_id
                    for observation in observations.values()
                    for lane_id in observation.incoming_lane_ids
                }
            )
            self._collector = MetricsCollector(
                controller=self.controller_name,
                scenario=self.config.scenario,
                seed=self.config.seed,
                monitored_lanes=monitored_lanes,
            )
            self._states = self._encode_all(observations)
            self._episode_finished = False
            self._simulated_seconds = 0.0
            return MappingProxyType(dict(self._states))
        except Exception:
            self.close()
            raise

    def step(self, *, training: bool = True) -> MultiAgentDecisionResult:
        """Act with every agent once, then apply independent Q-updates."""
        if self._environment is None:
            raise RuntimeError("reset() must be called before step().")
        if self._episode_finished:
            raise RuntimeError(
                "The episode is complete. Call reset() before step()."
            )

        actions = {
            agent_id: self.agents[agent_id].select_action(
                self._states[agent_id],
                training=training,
            )
            for agent_id in self.config.agent_ids
        }
        result = self._environment.step(actions)
        self._validate_agent_mapping(result.observations, "observations")
        self._validate_agent_mapping(result.rewards, "rewards")

        next_states = self._encode_all(result.observations)
        rewards = {
            agent_id: float(result.rewards[agent_id])
            for agent_id in self.config.agent_ids
        }
        terminated = bool(result.terminated)
        truncated = bool(result.truncated)

        if training:
            for agent_id in self.config.agent_ids:
                self.agents[agent_id].update(
                    self._states[agent_id],
                    actions[agent_id],
                    rewards[agent_id],
                    next_states[agent_id],
                    terminated=terminated,
                )

        combined_reward = sum(rewards.values())
        if self._collector is not None:
            self._collector.add_reward(combined_reward)

        self._states = next_states
        self._episode_finished = terminated or truncated
        self._simulated_seconds = float(
            result.info.get(
                "simulation_time",
                result.observations[self.config.agent_ids[0]].simulation_time,
            )
        )
        return MultiAgentDecisionResult(
            actions=actions,
            rewards=rewards,
            combined_reward=combined_reward,
            states=next_states,
            terminated=terminated,
            truncated=truncated,
            info=result.info,
        )

    def close(self) -> None:
        """Close any live environment and clear per-episode state."""
        environment = self._environment
        self._environment = None
        self._collector = None
        self._states = {}
        self._episode_finished = True
        if environment is not None:
            environment.close()

    def _checkpoint_payload(self) -> dict[str, Any]:
        agents_payload: dict[str, Any] = {}
        for agent_id, agent in self.agents.items():
            entries = [
                {
                    "state": state_to_json(state),
                    "action": action.name,
                    "value": value,
                }
                for (state, action), value in agent.q_table.items()
            ]
            entries.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
            agents_payload[agent_id] = {
                "q_learning_config": asdict(agent.config),
                "epsilon": agent.epsilon,
                "q_table": entries,
                "training_episode_count": agent.training_episode_count,
            }
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "controller": self.controller_name,
            "agent_ids": list(self.config.agent_ids),
            "encoder_config": asdict(self.encoder.config),
            "agents": agents_payload,
            "scenario": self.config.scenario,
            "seed": self.config.seed,
            "reward_mode": self.config.reward_mode,
            # The observed neighbors are part of what a Q-table key means.
            # Recording them lets a load refuse a checkpoint whose states
            # were built from a different neighborhood.
            "spatial_neighbor_ids": {
                agent_id: list(neighbor_ids)
                for agent_id, neighbor_ids in self.neighbor_ids_by_agent.items()
            },
        }

    def save_checkpoint(self, path: Path | None = None) -> Path:
        """Atomically save every Q-table and exploration state as one JSON file."""
        checkpoint = path or self.config.checkpoint_path
        target = Path(checkpoint) if checkpoint else None
        if target is None:
            raise ValueError("A checkpoint path is required to save a checkpoint.")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(self._checkpoint_payload(), indent=2, sort_keys=True) + "\n"
        )
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
        return target

    def load_checkpoint(self, path: Path | None = None) -> Path:
        """Load and validate a multi-agent checkpoint into every learner."""
        checkpoint = path or self.config.checkpoint_path
        target = Path(checkpoint) if checkpoint else None
        if target is None or not target.is_file():
            raise FileNotFoundError(f"Checkpoint does not exist: {target}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Could not read checkpoint {target}: {error}"
            ) from error
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"Malformed checkpoint {target}: root must be an object."
            )
        if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("Unsupported checkpoint schema version.")
        if payload.get("controller") != self.controller_name:
            raise ValueError(
                f"Checkpoint {target} was written by controller "
                f"{payload.get('controller')!r}, not "
                f"{self.controller_name!r}. Single-agent A19 checkpoints are "
                "not interchangeable with multi-agent ones, and spatial or "
                "coordinated-reward checkpoints hold states or scales that "
                "other modes cannot read."
            )
        checkpoint_agent_ids = tuple(payload.get("agent_ids", ()))
        if checkpoint_agent_ids != self.config.agent_ids:
            raise ValueError(
                f"Checkpoint {target} holds agents {checkpoint_agent_ids}, not "
                f"{self.config.agent_ids}. Refusing to load a checkpoint for a "
                "different set of agents."
            )
        if payload.get("scenario") != self.config.scenario:
            raise ValueError(
                f"Checkpoint {target} was trained on scenario "
                f"{payload.get('scenario')!r}, not {self.config.scenario!r}. "
                "Refusing to load a checkpoint from a different scenario -- "
                "this would silently mix traffic patterns into one Q-table."
            )
        if payload.get("seed") != self.config.seed:
            raise ValueError(
                f"Checkpoint {target} was trained with seed "
                f"{payload.get('seed')!r}, not {self.config.seed!r}. "
                "Refusing to load a checkpoint from a different seed."
            )
        if payload.get("reward_mode", "local") != self.config.reward_mode:
            raise ValueError(
                f"Checkpoint {target} was trained with reward_mode "
                f"{payload.get('reward_mode', 'local')!r}, not "
                f"{self.config.reward_mode!r}. Refusing to load a checkpoint "
                "trained under a different reward mode -- the Q-values were "
                "learned from a differently scaled reward signal."
            )

        checkpoint_neighbor_ids = payload.get("spatial_neighbor_ids")
        if checkpoint_neighbor_ids is not None:
            stored = {
                agent_id: tuple(neighbor_ids)
                for agent_id, neighbor_ids in checkpoint_neighbor_ids.items()
            }
            if stored != dict(self.neighbor_ids_by_agent):
                raise ValueError(
                    f"Checkpoint {target} observes neighbors {stored}, not "
                    f"{dict(self.neighbor_ids_by_agent)}. Refusing to load a "
                    "checkpoint whose states were encoded from a different "
                    "neighborhood."
                )

        agents_payload = payload.get("agents")
        if not isinstance(agents_payload, Mapping):
            raise ValueError(
                f"Malformed checkpoint {target}: 'agents' must be an object."
            )
        self._validate_agent_mapping(agents_payload, "checkpoint agents")

        try:
            for agent_id in self.config.agent_ids:
                agent_payload = agents_payload[agent_id]
                entries: dict[tuple[Any, TrafficAction], float] = {}
                for entry in agent_payload["q_table"]:
                    action = TrafficAction[entry["action"]]
                    entries[(state_from_json(entry["state"]), action)] = float(
                        entry["value"]
                    )
                self.agents[agent_id].load_q_table(
                    entries,
                    epsilon=float(agent_payload["epsilon"]),
                    training_episode_count=int(
                        agent_payload["training_episode_count"]
                    ),
                )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Malformed checkpoint {target}: {error}") from error
        return target

    @property
    def completed_training_episodes(self) -> int:
        """Return the shared episode count, requiring every agent to agree."""
        counts = {
            agent_id: agent.training_episode_count
            for agent_id, agent in self.agents.items()
        }
        distinct = set(counts.values())
        if len(distinct) > 1:
            details = ", ".join(
                f"{agent_id}={count}" for agent_id, count in sorted(counts.items())
            )
            raise ValueError(
                "Agents disagree on how many episodes they have trained "
                f"({details}). Every agent learns in the same episodes, so "
                "this means learners were mixed from different runs."
            )
        return distinct.pop() if distinct else 0

    def _total_q_table_states(self) -> int:
        """Return the summed distinct-state count across all Q-tables."""
        return sum(
            len({state for state, _ in agent.q_table})
            for agent in self.agents.values()
        )

    def _mean_epsilon(self) -> float:
        if not self.agents:
            return 0.0
        return sum(agent.epsilon for agent in self.agents.values()) / len(self.agents)

    def _run_episode(
        self,
        episode: int,
        *,
        training: bool,
    ) -> MultiAgentEpisodeSummary:
        action_counts = {
            agent_id: Counter() for agent_id in self.config.agent_ids
        }
        reward_totals = dict.fromkeys(self.config.agent_ids, 0.0)
        status_counts: Counter = Counter()
        decision_steps = 0
        terminated = False
        truncated = False
        try:
            self.reset()
            while not self._episode_finished:
                decision = self.step(training=training)
                decision_steps += 1
                for agent_id in self.config.agent_ids:
                    action_counts[agent_id][decision.actions[agent_id].name] += 1
                    reward_totals[agent_id] += decision.rewards[agent_id]
                for action_result in decision.info.get(
                    "action_results", {}
                ).values():
                    status = getattr(action_result, "status", action_result)
                    status_counts[getattr(status, "value", str(status))] += 1
                terminated = decision.terminated
                truncated = decision.truncated

            if training:
                for agent in self.agents.values():
                    agent.end_episode()

            # Only evaluation episodes reach the shared results CSV. Training
            # episodes are exploratory and would otherwise flood
            # results/experiments.csv with rows that mean nothing for the
            # baseline comparison.
            if not training and self._collector is not None:
                episode_metrics = self._collector.finalize(
                    simulation_seconds=self._simulated_seconds
                )
                episode_metrics = replace(
                    episode_metrics,
                    demand_seconds=self.config.episode_seconds,
                    cooldown_seconds=self.config.cooldown_seconds,
                )
                append_result(episode_metrics)

            agent_summaries = {
                agent_id: AgentEpisodeSummary(
                    agent_id=agent_id,
                    total_reward=reward_totals[agent_id],
                    mean_reward_per_decision=(
                        reward_totals[agent_id] / decision_steps
                        if decision_steps
                        else 0.0
                    ),
                    final_epsilon=self.agents[agent_id].epsilon,
                    q_table_state_count=len(
                        {state for state, _ in self.agents[agent_id].q_table}
                    ),
                    keep_action_count=action_counts[agent_id][
                        TrafficAction.KEEP.name
                    ],
                    next_green_action_count=action_counts[agent_id][
                        TrafficAction.NEXT_GREEN.name
                    ],
                )
                for agent_id in self.config.agent_ids
            }
            combined_total_reward = sum(reward_totals.values())
            return MultiAgentEpisodeSummary(
                episode=episode,
                scenario=self.config.scenario,
                seed=self.config.seed,
                simulated_seconds=self._simulated_seconds,
                decision_steps=decision_steps,
                combined_total_reward=combined_total_reward,
                mean_combined_reward_per_decision=(
                    combined_total_reward / decision_steps
                    if decision_steps
                    else 0.0
                ),
                agents=agent_summaries,
                action_status_counts=status_counts,
                terminated=terminated,
                truncated=truncated,
            )
        finally:
            self.close()

    def run(self) -> tuple[MultiAgentEpisodeSummary, ...]:
        """Run configured training or evaluation episodes."""
        if self.config.mode == "evaluate":
            self.load_checkpoint()
        completed_episodes = 0
        if self.config.mode == "train" and self.config.resume:
            checkpoint_path = self.config.checkpoint_path
            if checkpoint_path is not None and Path(checkpoint_path).is_file():
                self.load_checkpoint()
                completed_episodes = self.completed_training_episodes
                print(
                    f"Resumed from checkpoint {checkpoint_path}: "
                    f"completed_episodes={completed_episodes} "
                    f"mean_epsilon={self._mean_epsilon():.4f} "
                    f"states={self._total_q_table_states()}"
                )
            else:
                print(
                    "--resume was set but no checkpoint exists yet at "
                    f"{checkpoint_path}; starting a new run."
                )
        if completed_episodes >= self.config.episodes:
            print(
                f"Checkpoint already has {completed_episodes} completed "
                f"episodes, which meets or exceeds --episodes "
                f"{self.config.episodes}; nothing left to train."
            )
            self.summaries = []
            return tuple(self.summaries)

        self.summaries = []
        for episode in range(completed_episodes + 1, self.config.episodes + 1):
            summary = self._run_episode(
                episode,
                training=self.config.mode == "train",
            )
            self.summaries.append(summary)
            print(
                f"Episode {episode}: agents={len(self.agents)} "
                f"steps={summary.decision_steps} "
                f"seconds={summary.simulated_seconds:.1f} "
                f"combined_reward={summary.combined_total_reward:.3f} "
                f"mean_epsilon={self._mean_epsilon():.4f} "
                f"states={self._total_q_table_states()}"
            )
            for agent_id in self.config.agent_ids:
                agent_summary = summary.agents[agent_id]
                print(
                    f"  {agent_id}: reward={agent_summary.total_reward:.3f} "
                    f"keep={agent_summary.keep_action_count} "
                    f"next_green={agent_summary.next_green_action_count} "
                    f"states={agent_summary.q_table_state_count}"
                )
            if (
                self.config.mode == "train"
                and self.config.checkpoint_path
                and episode % self.config.checkpoint_interval == 0
            ):
                self.save_checkpoint()
        if self.config.mode == "train" and self.config.checkpoint_path:
            self.save_checkpoint()

        checkpoint = self.config.checkpoint_path or "none"
        if self.summaries:
            mean_reward = sum(
                item.combined_total_reward for item in self.summaries
            ) / len(self.summaries)
            best_reward = max(
                item.combined_total_reward for item in self.summaries
            )
            mean_reward_text = f"{mean_reward:.3f}"
            best_reward_text = f"{best_reward:.3f}"
        else:
            mean_reward_text = "n/a"
            best_reward_text = "n/a"
        print(
            f"Summary: episodes_this_run={len(self.summaries)} "
            f"total_episodes={self.completed_training_episodes} "
            f"controller={self.controller_name} "
            f"reward_mode={self.config.reward_mode} "
            f"agents={len(self.agents)} "
            f"mean_epsilon={self._mean_epsilon():.4f} "
            f"states={self._total_q_table_states()} "
            f"mean_combined_reward={mean_reward_text} "
            f"best_combined_reward={best_reward_text} "
            f"checkpoint={checkpoint}"
        )
        return tuple(self.summaries)

    def train(self) -> tuple[MultiAgentEpisodeSummary, ...]:
        """Run training episodes."""
        if self.config.mode != "train":
            raise ValueError("Trainer configuration is not in training mode.")
        return self.run()

    def evaluate(self) -> tuple[MultiAgentEpisodeSummary, ...]:
        """Run evaluation episodes from the configured checkpoint."""
        if self.config.mode != "evaluate":
            raise ValueError("Trainer configuration is not in evaluation mode.")
        return self.run()


__all__ = [
    "CONTROLLER_NAME",
    "DEFAULT_SPATIAL_NEIGHBOR_LIMIT",
    "GLOBAL_REWARD_CONTROLLER_NAME",
    "NEIGHBOR_REWARD_CONTROLLER_NAME",
    "SPATIAL_CONTROLLER_NAME",
    "AgentEpisodeSummary",
    "MultiAgentDecisionResult",
    "MultiAgentEpisodeSummary",
    "MultiAgentQLearningConfig",
    "MultiAgentQLearningTrainer",
]
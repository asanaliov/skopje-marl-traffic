"""A19 independent tabular Q-learning training and evaluation runner."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from src.agents.q_learning_agent import QLearningAgent, QLearningConfig
from src.agents.state_encoder import DiscreteTrafficState, TrafficStateEncoder
from src.environment.actions import TrafficAction
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentStepResult,
    MultiAgentTrafficEnvironment,
)
from src.evaluation.collector import MetricsCollector
from src.evaluation.results_writer import append_result


TrainingMode = Literal["train", "evaluate"]
CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class QLearningTrainingConfig:
    """Immutable settings for one A19 training or evaluation run."""

    agent_id: str = "A19"
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

    def __post_init__(self) -> None:
        """Validate runner settings before a SUMO process is started."""
        if self.agent_id != "A19":
            raise ValueError("This runner currently supports agent_id='A19' only.")
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


@dataclass(frozen=True, slots=True)
class EpisodeSummary:
    """Immutable metrics for one runner episode."""

    episode: int
    scenario: str
    seed: int
    simulated_seconds: float
    decision_steps: int
    total_reward: float
    mean_reward_per_decision: float
    final_epsilon: float
    q_table_state_count: int
    keep_action_count: int
    next_green_action_count: int
    action_status_counts: Mapping[str, int]
    terminated: bool
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "action_status_counts",
            MappingProxyType(dict(self.action_status_counts)),
        )


def _state_to_json(state: Any) -> dict[str, Any]:
    if isinstance(state, DiscreteTrafficState):
        return {"type": "DiscreteTrafficState", **asdict(state)}
    if is_dataclass(state):
        return {"type": type(state).__name__, **asdict(state)}
    if isinstance(state, (str, int, float, bool)) or state is None:
        return {"type": "primitive", "value": state}
    if isinstance(state, tuple):
        return {"type": "tuple", "value": list(state)}
    raise TypeError(f"Unsupported checkpoint state type: {type(state).__name__}")


def _state_from_json(value: Mapping[str, Any]) -> Any:
    state_type = value.get("type")
    if state_type == "DiscreteTrafficState":
        fields = {
            field: value[field]
            for field in (
                "total_queue_bucket",
                "maximum_lane_queue_bucket",
                "mean_lane_waiting_time_bucket",
                "green_phase_position",
                "phase_elapsed_bucket",
                "is_transition_phase",
            )
        }
        return DiscreteTrafficState(**fields)
    if state_type == "primitive":
        return value.get("value")
    if state_type == "tuple":
        return tuple(value.get("value", ()))
    raise ValueError(f"Unsupported checkpoint state type: {state_type!r}.")


class IndependentQLearningTrainer:
    """Run one independently controlled A19 tabular learner through SUMO."""

    def __init__(
        self,
        config: QLearningTrainingConfig | None = None,
        *,
        agent: QLearningAgent | None = None,
        encoder: TrafficStateEncoder | None = None,
        environment_factory: Callable[..., Any] | None = None,
        q_learning_config: QLearningConfig | None = None,
    ) -> None:
        self.config = config or QLearningTrainingConfig()
        self.agent = agent or QLearningAgent(q_learning_config)
        self.encoder = encoder or TrafficStateEncoder()
        self._environment_factory = (
            environment_factory or MultiAgentTrafficEnvironment
        )
        self.summaries: list[EpisodeSummary] = []

    def _environment_config(self) -> MultiAgentEnvironmentConfig:
        return MultiAgentEnvironmentConfig(
            scenario=self.config.scenario,
            seed=self.config.seed,
            agent_ids=("A19",),
            demand_seconds=self.config.episode_seconds,
            cooldown_seconds=self.config.cooldown_seconds,
            decision_interval_seconds=self.config.decision_interval_seconds,
            gui=self.config.gui,
            reward_mode="local",
        )

    def _checkpoint_payload(self) -> dict[str, Any]:
        entries = [
            {
                "state": _state_to_json(state),
                "action": action.name,
                "value": value,
            }
            for (state, action), value in self.agent.q_table.items()
        ]
        entries.sort(key=lambda entry: json.dumps(entry, sort_keys=True))
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "agent_id": self.config.agent_id,
            "encoder_config": asdict(self.encoder.config),
            "q_learning_config": asdict(self.agent.config),
            "epsilon": self.agent.epsilon,
            "q_table": entries,
            "training_episode_count": self.agent.training_episode_count,
            "scenario": self.config.scenario,
            "seed": self.config.seed,
        }

    def save_checkpoint(self, path: Path | None = None) -> Path:
        """Atomically save an inspectable JSON checkpoint."""
        checkpoint = path or self.config.checkpoint_path
        target = Path(checkpoint) if checkpoint else None
        if target is None:
            raise ValueError("A checkpoint path is required to save a checkpoint.")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(self._checkpoint_payload(), indent=2, sort_keys=True)
            + "\n"
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
        """Load and validate a JSON checkpoint into the public agent API."""
        checkpoint = path or self.config.checkpoint_path
        target = Path(checkpoint) if checkpoint else None
        if target is None or not target.is_file():
            raise FileNotFoundError(f"Checkpoint does not exist: {target}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read checkpoint {target}: {error}") from error
        if not isinstance(payload, Mapping):
            raise ValueError(f"Malformed checkpoint {target}: root must be an object.")
        if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("Unsupported checkpoint schema version.")
        if payload.get("agent_id") != "A19":
            raise ValueError("Checkpoint agent_id must be 'A19'.")
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
        entries: dict[tuple[Any, TrafficAction], float] = {}
        try:
            for entry in payload["q_table"]:
                action = TrafficAction[entry["action"]]
                entries[(_state_from_json(entry["state"]), action)] = float(
                    entry["value"]
                )
            self.agent.load_q_table(
                entries,
                epsilon=float(payload["epsilon"]),
                training_episode_count=int(payload["training_episode_count"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Malformed checkpoint {target}: {error}") from error
        return target

    @staticmethod
    def _validate_observations(observations: Mapping[str, Any]) -> Any:
        if tuple(observations) != ("A19",):
            raise ValueError("The A19 runner requires exactly one A19 observation.")
        return observations["A19"]

    def _run_episode(self, episode: int, *, training: bool) -> EpisodeSummary:
        # `collector` is created just after reset() (once we know the
        # A19 agent's incoming lanes), but the environment needs the
        # on_raw_step hook wired in at construction time -- so we defer
        # through a closure that reads the enclosing `collector` variable
        # once it has been assigned below.
        collector: MetricsCollector | None = None

        def _on_raw_step(traci_conn: Any) -> None:
            if collector is not None:
                collector.record_step(traci_conn)

        environment = self._environment_factory(
            self._environment_config(),
            on_raw_step=_on_raw_step,
        )
        total_reward = 0.0
        decision_steps = 0
        action_counts = Counter()
        status_counts = Counter()
        terminated = False
        truncated = False
        simulated_seconds = 0.0
        try:
            observations = environment.reset()

            monitored_lanes = sorted(
                {
                    lane_id
                    for observation in observations.values()
                    for lane_id in observation.incoming_lane_ids
                }
            )
            collector = MetricsCollector(
                controller="independent_rl",
                scenario=self.config.scenario,
                seed=self.config.seed,
                monitored_lanes=monitored_lanes,
            )

            observation = self._validate_observations(observations)
            while not (terminated or truncated):
                state = self.encoder.encode(observation)
                action = self.agent.select_action(state, training=training)
                action_counts[action.name] += 1
                result: MultiAgentStepResult = environment.step({"A19": action})
                next_observation = self._validate_observations(result.observations)
                next_state = self.encoder.encode(next_observation)
                reward = float(result.rewards["A19"])
                total_reward += reward
                collector.add_reward(reward)
                decision_steps += 1
                terminated = result.terminated
                truncated = result.truncated
                if training:
                    self.agent.update(
                        state,
                        action,
                        reward,
                        next_state,
                        terminated=terminated,
                    )
                for action_result in result.info.get("action_results", {}).values():
                    status = getattr(action_result, "status", action_result)
                    status_counts[getattr(status, "value", str(status))] += 1
                simulated_seconds = float(
                    result.info.get(
                        "simulation_time",
                        next_observation.simulation_time,
                    )
                )
                observation = next_observation
            if training:
                self.agent.end_episode()

            # Only log evaluation episodes to the shared results CSV --
            # training episodes are noisy/exploratory and would otherwise
            # flood results/experiments.csv with dozens of rows that
            # aren't meaningful for the baseline comparison. Flip this
            # guard if you want every training episode logged too.
            if not training:
                episode_metrics = collector.finalize(
                    simulation_seconds=simulated_seconds
                )
                episode_metrics = replace(
                    episode_metrics,
                    demand_seconds=self.config.episode_seconds,
                    cooldown_seconds=self.config.cooldown_seconds,
                )
                append_result(episode_metrics)

            return EpisodeSummary(
                episode=episode,
                scenario=self.config.scenario,
                seed=self.config.seed,
                simulated_seconds=simulated_seconds,
                decision_steps=decision_steps,
                total_reward=total_reward,
                mean_reward_per_decision=(
                    total_reward / decision_steps if decision_steps else 0.0
                ),
                final_epsilon=self.agent.epsilon,
                q_table_state_count=len({state for state, _ in self.agent.q_table}),
                keep_action_count=action_counts[TrafficAction.KEEP.name],
                next_green_action_count=action_counts[TrafficAction.NEXT_GREEN.name],
                action_status_counts=status_counts,
                terminated=terminated,
                truncated=truncated,
            )
        finally:
            environment.close()

    def run(self) -> tuple[EpisodeSummary, ...]:
        """Run configured training or evaluation episodes."""
        if self.config.mode == "evaluate":
            self.load_checkpoint()
        completed_episodes = 0
        if self.config.mode == "train" and self.config.resume:
            checkpoint_path = self.config.checkpoint_path
            if checkpoint_path is not None and Path(checkpoint_path).is_file():
                self.load_checkpoint()
                completed_episodes = self.agent.training_episode_count
                print(
                    f"Resumed from checkpoint {checkpoint_path}: "
                    f"completed_episodes={completed_episodes} "
                    f"epsilon={self.agent.epsilon:.4f} "
                    f"states={len({state for state, _ in self.agent.q_table})}"
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
            summary = self._run_episode(episode, training=self.config.mode == "train")
            self.summaries.append(summary)
            print(
                f"Episode {episode}: steps={summary.decision_steps} "
                f"seconds={summary.simulated_seconds:.1f} "
                f"reward={summary.total_reward:.3f} "
                f"epsilon={summary.final_epsilon:.4f} "
                f"states={summary.q_table_state_count}"
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
                item.total_reward for item in self.summaries
            ) / len(self.summaries)
            best_reward = max(item.total_reward for item in self.summaries)
            mean_reward_text = f"{mean_reward:.3f}"
            best_reward_text = f"{best_reward:.3f}"
        else:
            mean_reward_text = "n/a"
            best_reward_text = "n/a"
        print(
            f"Summary: episodes_this_run={len(self.summaries)} "
            f"total_episodes={self.agent.training_episode_count} "
            f"epsilon={self.agent.epsilon:.4f} "
            f"states={len({state for state, _ in self.agent.q_table})} "
            f"mean_reward={mean_reward_text} "
            f"best_reward={best_reward_text} "
            f"checkpoint={checkpoint}"
        )
        return tuple(self.summaries)

    def train(self) -> tuple[EpisodeSummary, ...]:
        """Run training episodes."""
        if self.config.mode != "train":
            raise ValueError("Trainer configuration is not in training mode.")
        return self.run()

    def evaluate(self) -> tuple[EpisodeSummary, ...]:
        """Run evaluation episodes from the configured checkpoint."""
        if self.config.mode != "evaluate":
            raise ValueError("Trainer configuration is not in evaluation mode.")
        return self.run()


__all__ = [
    "EpisodeSummary",
    "IndependentQLearningTrainer",
    "QLearningTrainingConfig",
]
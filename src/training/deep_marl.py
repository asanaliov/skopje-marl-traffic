"""Parameter-shared independent PPO (IPPO) over the PettingZoo corridor wrapper.

Training regime
---------------
All eight corridor agents are controlled by **one** actor-critic network
(parameter sharing). This is independent PPO, not MAPPO: both the actor and
the critic see only the agent's own observation, so there is no centralised
critic. Every agent contributes its own transitions to the same PPO update, so the
network sees eight times as many samples per SUMO step -- which matters
because stepping SUMO, not the gradient update, is the compute bottleneck.

The eight junctions are *not* homogeneous: they have between 21 and 66
observation features and different phase programs. Sharing is therefore made
safe in two ways:

* observations are zero-padded to the widest agent (``max_feature_count``), and
* a one-hot agent ID is appended, so the network can still specialise its
  behaviour per junction while sharing what is common (queue -> switch).

The cost is that padded inputs carry no information for narrow junctions and
that a single network has to fit eight different dynamics. The alternative,
eight independent networks, would multiply the environment steps needed by
roughly the number of agents for the same data per network; that is not
affordable at 3600 s episodes.

Learning is per-agent decentralised execution: at evaluation time each agent
acts greedily from its own padded local observation and ID only. The critic is
also local, so the reward mode (``local`` / ``neighbor_aware`` / ``global``)
alone decides how much coordination the signal carries, mirroring the tabular
controllers. With the default ``local`` reward the controller is the deep
counterpart of ``multi_agent_independent_rl`` -- same agents, same per-junction
observations, same reward -- so the comparison isolates function approximation
versus tabular discretisation.

Rewards are divided by a running standard deviation of the discounted return
(as Stable-Baselines3's ``VecNormalize`` does), because raw per-step rewards
differ several-fold between the low and high scenarios and a single hand-set
scale would suit only one of them. The statistics are saved in the checkpoint.

Evaluation follows the tabular protocol exactly: one greedy episode of
``demand_seconds`` + ``cooldown_seconds`` on the configured scenario/seed,
appended to ``results/experiments.csv`` under its own controller label.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from src.environment.gym_wrapper import (
    CorridorParallelEnv,
    audited_space_specs,
)
from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentTrafficEnvironment,
    RewardMode,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR
from src.evaluation.collector import MetricsCollector
from src.evaluation.results_writer import append_result


CONTROLLER_NAME = "marl_deep_ppo"
CHECKPOINT_SCHEMA_VERSION = 2
DEFAULT_TRAINING_EPISODES = 300
"""Matches the tabular MARL runs, so both methods get the same SUMO budget."""

_HYPERPARAMETERS = (
    "hidden_size",
    "learning_rate",
    "gamma",
    "gae_lambda",
    "clip_range",
    "entropy_coefficient",
    "value_coefficient",
    "max_grad_norm",
    "update_epochs",
    "minibatch_size",
    "reward_clip",
    "decision_interval_seconds",
    "episode_seconds",
    "cooldown_seconds",
)
"""Settings a resumed run must share with its checkpoint."""
_REWARD_SUFFIX = {"local": "", "neighbor_aware": "_neighbor", "global": "_global"}


def controller_label(reward_mode: str) -> str:
    """Return the results-CSV label; never shared with a tabular controller."""
    return CONTROLLER_NAME + _REWARD_SUFFIX[reward_mode]


@dataclass(frozen=True, slots=True)
class DeepMarlConfig:
    """Immutable settings for one deep MARL training or evaluation run."""

    agent_ids: tuple[str, ...] = SELECTED_CORRIDOR.agent_ids
    scenario: str = "medium"
    seed: int = 42
    episodes: int = DEFAULT_TRAINING_EPISODES
    episode_seconds: float = 3600.0
    cooldown_seconds: float = 600.0
    decision_interval_seconds: float = 5.0
    reward_mode: RewardMode = "local"
    checkpoint_path: Path | None = None
    results_path: Path | None = Path("results/experiments.csv")
    gui: bool = False
    hidden_size: int = 128
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    entropy_coefficient: float = 0.01
    value_coefficient: float = 0.5
    max_grad_norm: float = 0.5
    update_epochs: int = 4
    minibatch_size: int = 512
    reward_clip: float = 10.0
    torch_seed: int = 0
    allow_cross_seed_evaluation: bool = False

    def __post_init__(self) -> None:
        """Validate settings before a SUMO process is started."""
        if not self.agent_ids:
            raise ValueError("agent_ids must contain at least one agent.")
        unknown = sorted(set(self.agent_ids) - set(SELECTED_CORRIDOR.agent_ids))
        if unknown:
            raise ValueError(f"Unknown selected agent IDs: {', '.join(unknown)}.")
        if self.reward_mode not in _REWARD_SUFFIX:
            raise ValueError(f"Unknown reward_mode {self.reward_mode!r}.")
        for name in ("episodes", "hidden_size", "update_epochs", "minibatch_size"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero.")
        object.__setattr__(
            self,
            "agent_ids",
            tuple(a for a in SELECTED_CORRIDOR.agent_ids if a in self.agent_ids),
        )


class RunningReturnScaler:
    """Running variance of discounted returns, used to scale raw rewards."""

    def __init__(self, gamma: float, clip: float) -> None:
        self.gamma = gamma
        self.clip = clip
        self.count = 1e-4
        self.mean = 0.0
        self.var = 1.0

    def _update(self, values: np.ndarray) -> None:
        batch_mean = float(values.mean())
        batch_var = float(values.var())
        batch_count = values.size
        delta = batch_mean - self.mean
        total = self.count + batch_count
        self.mean += delta * batch_count / total
        m2 = (
            self.var * self.count
            + batch_var * batch_count
            + delta**2 * self.count * batch_count / total
        )
        self.var = m2 / total
        self.count = total

    def scale(self, rewards: np.ndarray) -> np.ndarray:
        """Update statistics from a (steps, agents) episode and scale it."""
        returns = np.zeros_like(rewards)
        running = np.zeros(rewards.shape[1:], dtype=rewards.dtype)
        for step in range(rewards.shape[0]):
            running = running * self.gamma + rewards[step]
            returns[step] = running
        self._update(returns)
        scaled = rewards / np.sqrt(self.var + 1e-8)
        return np.clip(scaled, -self.clip, self.clip).astype(np.float32)

    def state(self) -> dict[str, float]:
        return {"count": self.count, "mean": self.mean, "var": self.var}

    def load(self, state: Mapping[str, float]) -> None:
        self.count = float(state["count"])
        self.mean = float(state["mean"])
        self.var = float(state["var"])


class SharedActorCritic(nn.Module):
    """One MLP with a policy head and a value head, shared by every agent."""

    def __init__(self, input_size: int, hidden_size: int, action_count: int = 2):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.policy_head = nn.Linear(hidden_size, action_count)
        self.value_head = nn.Linear(hidden_size, 1)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.body(inputs)
        return self.policy_head(hidden), self.value_head(hidden).squeeze(-1)


def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    last_value: np.ndarray,
    terminated: bool,
    gamma: float,
    gae_lambda: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (advantages, returns) for a (steps, agents) episode rollout.

    ``last_value`` bootstraps a *truncated* episode (the time limit is not a
    real end of the task); a *terminated* episode bootstraps from zero.
    """
    steps = rewards.shape[0]
    advantages = np.zeros_like(rewards)
    next_value = np.zeros_like(last_value) if terminated else last_value
    running = np.zeros_like(last_value)
    for step in reversed(range(steps)):
        delta = rewards[step] + gamma * next_value - values[step]
        running = delta + gamma * gae_lambda * running
        advantages[step] = running
        next_value = values[step]
    return advantages, advantages + values


@dataclass(frozen=True, slots=True)
class DeepEpisodeSummary:
    """Outcome of one training or evaluation episode."""

    episode: int
    decision_steps: int
    simulated_seconds: float
    combined_total_reward: float
    terminated: bool
    truncated: bool
    policy_loss: float = 0.0
    value_loss: float = 0.0
    entropy: float = 0.0
    keep_fraction: float = 0.0
    wall_seconds: float = 0.0


class DeepMarlTrainer:
    """Trains and evaluates the shared PPO policy on the corridor wrapper."""

    def __init__(
        self,
        config: DeepMarlConfig,
        *,
        environment_factory: Callable[..., Any] | None = None,
        space_specs: Mapping[str, Any] | None = None,
    ) -> None:
        """Build the network; the two optional hooks let tests avoid SUMO."""
        self.config = config
        self._custom_factory = environment_factory
        self._space_specs = space_specs
        specs = space_specs or audited_space_specs(config.agent_ids)
        self.max_feature_count = max(s.feature_count for s in specs.values())
        self.input_size = self.max_feature_count + len(config.agent_ids)
        torch.manual_seed(config.torch_seed)
        self.rng = np.random.default_rng(config.torch_seed)
        self.network = SharedActorCritic(self.input_size, config.hidden_size)
        self.optimizer = torch.optim.Adam(
            self.network.parameters(), lr=config.learning_rate, eps=1e-5
        )
        self.reward_scaler = RunningReturnScaler(config.gamma, config.reward_clip)
        self.completed_episodes = 0

    # ------------------------------------------------------------------ obs
    def _stack(self, observations: Mapping[str, np.ndarray]) -> np.ndarray:
        """Pad every agent's vector and append its one-hot ID -> (agents, D)."""
        agents = self.config.agent_ids
        batch = np.zeros((len(agents), self.input_size), dtype=np.float32)
        for row, agent_id in enumerate(agents):
            vector = observations[agent_id]
            batch[row, : len(vector)] = vector
            batch[row, self.max_feature_count + row] = 1.0
        return batch

    def _environment_config(self, sumo_seed: int | None = None):
        cfg = self.config
        return MultiAgentEnvironmentConfig(
            scenario=cfg.scenario,
            seed=cfg.seed,
            sumo_seed=sumo_seed,
            agent_ids=cfg.agent_ids,
            demand_seconds=cfg.episode_seconds,
            cooldown_seconds=cfg.cooldown_seconds,
            decision_interval_seconds=cfg.decision_interval_seconds,
            gui=cfg.gui,
            reward_mode=cfg.reward_mode,
        )

    # -------------------------------------------------------------- episodes
    def _act(self, batch: np.ndarray, *, greedy: bool):
        with torch.no_grad():
            logits, values = self.network(torch.from_numpy(batch))
            if greedy:
                actions = logits.argmax(dim=-1)
                return actions.numpy(), None, values.numpy()
            dist = torch.distributions.Categorical(logits=logits)
            actions = dist.sample()
            return actions.numpy(), dist.log_prob(actions).numpy(), values.numpy()

    def _run_episode(
        self,
        episode: int,
        *,
        training: bool,
        sumo_seed: int | None = None,
        collector_factory: Callable[[Any], MetricsCollector] | None = None,
    ) -> tuple[DeepEpisodeSummary, dict[str, np.ndarray] | None]:
        started = time.monotonic()
        agents = self.config.agent_ids
        collector: MetricsCollector | None = None
        live_environment: list[MultiAgentTrafficEnvironment] = []

        def factory(resolved: MultiAgentEnvironmentConfig):
            def on_raw_step(traci_connection: Any) -> None:
                if collector is not None:
                    collector.record_step(traci_connection)

            if self._custom_factory is not None:
                environment = self._custom_factory(resolved)
            else:
                environment = MultiAgentTrafficEnvironment(
                    resolved, on_raw_step=on_raw_step
                )
            live_environment[:] = [environment]
            return environment

        parallel = CorridorParallelEnv(
            self._environment_config(sumo_seed),
            environment_factory=factory,
            space_specs=self._space_specs,
        )
        obs_log, act_log, logp_log, val_log, rew_log = [], [], [], [], []
        terminated = truncated = False
        simulated_seconds = 0.0
        total_reward = 0.0
        decision_steps = 0
        try:
            observations, _ = parallel.reset()
            if collector_factory is not None:
                collector = collector_factory(live_environment[0])
            batch = self._stack(observations)
            while True:
                actions, logp, values = self._act(batch, greedy=not training)
                observations, rewards, terms, truncs, infos = parallel.step(
                    {a: int(actions[i]) for i, a in enumerate(agents)}
                )
                reward_row = np.array([rewards[a] for a in agents], dtype=np.float32)
                decision_steps += 1
                total_reward += float(reward_row.sum())
                if collector is not None:
                    collector.add_reward(float(reward_row.sum()))
                simulated_seconds = float(
                    infos[agents[0]].get("simulation_time") or simulated_seconds
                )
                if training:
                    obs_log.append(batch)
                    act_log.append(actions)
                    logp_log.append(logp)
                    val_log.append(values)
                    rew_log.append(reward_row)
                terminated = bool(terms[agents[0]])
                truncated = bool(truncs[agents[0]])
                batch = self._stack(observations)
                if terminated or truncated:
                    break
            if collector is not None and self.config.results_path is not None:
                metrics = collector.finalize(simulation_seconds=simulated_seconds)
                metrics = replace(
                    metrics,
                    demand_seconds=self.config.episode_seconds,
                    cooldown_seconds=self.config.cooldown_seconds,
                )
                append_result(metrics, path=self.config.results_path)
        finally:
            parallel.close()

        rollout = None
        keep_fraction = 0.0
        if training:
            actions_array = np.stack(act_log)
            keep_fraction = float((actions_array == 0).mean())
            rollout = {
                "obs": np.stack(obs_log),
                "actions": actions_array,
                "logp": np.stack(logp_log),
                "values": np.stack(val_log),
                "rewards": self.reward_scaler.scale(np.stack(rew_log)),
                "last_batch": batch,
                "terminated": terminated,
            }
        summary = DeepEpisodeSummary(
            episode=episode,
            decision_steps=decision_steps,
            simulated_seconds=simulated_seconds,
            combined_total_reward=total_reward,
            terminated=terminated,
            truncated=truncated,
            keep_fraction=keep_fraction,
            wall_seconds=time.monotonic() - started,
        )
        return summary, rollout

    # ---------------------------------------------------------------- update
    def _update(self, rollout: dict[str, np.ndarray]) -> tuple[float, float, float]:
        cfg = self.config
        with torch.no_grad():
            _, last_values = self.network(torch.from_numpy(rollout["last_batch"]))
        advantages, returns = compute_gae(
            rollout["rewards"],
            rollout["values"],
            last_values.numpy(),
            bool(rollout["terminated"]),
            cfg.gamma,
            cfg.gae_lambda,
        )
        flat = lambda a: torch.from_numpy(a.reshape(-1, *a.shape[2:]))  # noqa: E731
        obs = flat(rollout["obs"])
        actions = flat(rollout["actions"]).long()
        old_logp = flat(rollout["logp"])
        adv = flat(advantages)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        ret = flat(returns)

        count = obs.shape[0]
        policy_loss = value_loss = entropy = 0.0
        batches = 0
        for _ in range(cfg.update_epochs):
            order = torch.from_numpy(self.rng.permutation(count))
            for start in range(0, count, cfg.minibatch_size):
                index = order[start : start + cfg.minibatch_size]
                logits, values = self.network(obs[index])
                dist = torch.distributions.Categorical(logits=logits)
                ratio = torch.exp(dist.log_prob(actions[index]) - old_logp[index])
                clipped = torch.clamp(ratio, 1 - cfg.clip_range, 1 + cfg.clip_range)
                p_loss = -torch.min(ratio * adv[index], clipped * adv[index]).mean()
                v_loss = 0.5 * (values - ret[index]).pow(2).mean()
                ent = dist.entropy().mean()
                loss = (
                    p_loss
                    + cfg.value_coefficient * v_loss
                    - cfg.entropy_coefficient * ent
                )
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.network.parameters(), cfg.max_grad_norm)
                self.optimizer.step()
                policy_loss += p_loss.item()
                value_loss += v_loss.item()
                entropy += ent.item()
                batches += 1
        return policy_loss / batches, value_loss / batches, entropy / batches

    # ------------------------------------------------------------ checkpoint
    def save_checkpoint(self, path: Path | None = None) -> Path:
        target = Path(path or self.config.checkpoint_path or "")
        if not str(target):
            raise ValueError("A checkpoint path is required.")
        target.parent.mkdir(parents=True, exist_ok=True)
        cfg = self.config
        torch.save(
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "network": self.network.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "completed_episodes": self.completed_episodes,
                "agent_ids": list(cfg.agent_ids),
                "scenario": cfg.scenario,
                "seed": cfg.seed,
                "reward_mode": cfg.reward_mode,
                "input_size": self.input_size,
                "hyperparameters": {k: getattr(cfg, k) for k in _HYPERPARAMETERS},
                "reward_scaler": self.reward_scaler.state(),
            },
            target,
        )
        return target

    def load_checkpoint(self, path: Path | None = None, *, for_training: bool) -> Path:
        source = Path(path or self.config.checkpoint_path or "")
        if not source.is_file():
            raise FileNotFoundError(f"Checkpoint not found: {source}")
        payload = torch.load(source, map_location="cpu", weights_only=False)
        cfg = self.config
        if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("Unsupported deep MARL checkpoint schema version.")
        expected = {
            "agent_ids": list(cfg.agent_ids),
            "scenario": cfg.scenario,
            "reward_mode": cfg.reward_mode,
            "input_size": self.input_size,
        }
        if for_training or not cfg.allow_cross_seed_evaluation:
            expected["seed"] = cfg.seed
        for key, value in expected.items():
            if payload.get(key) != value:
                raise ValueError(
                    f"Checkpoint {key}={payload.get(key)!r} does not match this "
                    f"run ({value!r})."
                )
        # Evaluation only needs a network of the same shape; resuming training
        # with different hyperparameters would silently splice two runs.
        stored = payload["hyperparameters"]
        checked = _HYPERPARAMETERS if for_training else ("hidden_size",)
        for key in checked:
            if stored.get(key) != getattr(cfg, key):
                raise ValueError(
                    f"Checkpoint {key}={stored.get(key)!r} does not match this "
                    f"run ({getattr(cfg, key)!r})."
                )
        self.network.load_state_dict(payload["network"])
        if for_training:
            self.optimizer.load_state_dict(payload["optimizer"])
            self.reward_scaler.load(payload["reward_scaler"])
        self.completed_episodes = int(payload["completed_episodes"])
        return source

    # ------------------------------------------------------------------- run
    def train(self, *, resume: bool = False) -> tuple[DeepEpisodeSummary, ...]:
        cfg = self.config
        if (
            resume
            and cfg.checkpoint_path is not None
            and Path(cfg.checkpoint_path).is_file()
        ):
            self.load_checkpoint(for_training=True)
            print(f"Resumed at completed_episodes={self.completed_episodes}")
        summaries = []
        for episode in range(self.completed_episodes + 1, cfg.episodes + 1):
            # SUMO randomness varies per episode; the demand file stays fixed.
            summary, rollout = self._run_episode(
                episode, training=True, sumo_seed=cfg.seed + episode
            )
            p_loss, v_loss, entropy = self._update(rollout)
            summary = replace(
                summary,
                policy_loss=p_loss,
                value_loss=v_loss,
                entropy=entropy,
            )
            self.completed_episodes = episode
            summaries.append(summary)
            # Same "Episode N:" shape as the tabular trainers so
            # scripts/analysis/training_curve.py can parse the log.
            print(
                f"Episode {episode}: agents={len(cfg.agent_ids)} "
                f"steps={summary.decision_steps} "
                f"seconds={summary.simulated_seconds:.1f} "
                f"combined_reward={summary.combined_total_reward:.3f} "
                f"entropy={entropy:.3f} keep_fraction={summary.keep_fraction:.3f} "
                f"policy_loss={p_loss:.4f} value_loss={v_loss:.4f} "
                f"wall_seconds={summary.wall_seconds:.0f}",
                flush=True,
            )
            if cfg.checkpoint_path is not None:
                self.save_checkpoint()
        return tuple(summaries)

    def evaluate(self) -> DeepEpisodeSummary:
        cfg = self.config
        self.load_checkpoint(for_training=False)
        label = controller_label(cfg.reward_mode)

        def make_collector(environment: Any) -> MetricsCollector:
            lanes = sorted(
                {
                    lane
                    for agent_id in cfg.agent_ids
                    for lane in environment.traffic_signals[agent_id].incoming_lane_ids
                }
            )
            return MetricsCollector(
                controller=label,
                scenario=cfg.scenario,
                seed=cfg.seed,
                monitored_lanes=lanes,
            )

        summary, _ = self._run_episode(
            self.completed_episodes,
            training=False,
            sumo_seed=None,
            collector_factory=make_collector,
        )
        print(
            f"Evaluation: controller={label} scenario={cfg.scenario} "
            f"seed={cfg.seed} steps={summary.decision_steps} "
            f"seconds={summary.simulated_seconds:.1f} "
            f"combined_reward={summary.combined_total_reward:.3f} "
            f"trained_episodes={self.completed_episodes}"
        )
        return summary

"""Parameter-shared DQN for the corridor junctions.

The value-based counterpart of ``marl_deep_ppo``: the same observations, local
reward, padded input with a one-hot agent ID, episodes and 2x128 network, but
one Q-value head instead of policy and value heads. Each agent picks the action
with the highest Q-value (epsilon-greedy while training).

* Every agent step goes into one shared replay buffer, so a single update learns
  from all eight junctions and from older episodes.
* Double DQN: the online network picks the next action and a target network,
  copied every ``target_update_steps`` gradient steps, scores it.
* Epsilon falls linearly from ``epsilon_start`` to ``epsilon_end`` over the
  first ``exploration_fraction`` of the episodes, so a resume lands on the same
  value.
* The replay buffer is not saved in checkpoints, so a resumed run starts with
  an empty one.

Unlike PPO, the settings here were not tuned on this corridor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer

CONTROLLER_NAME = "marl_deep_dqn"


@dataclass(frozen=True, slots=True)
class DqnConfig(DeepMarlConfig):
    """Deep MARL settings with DQN defaults (Stable-Baselines3 values where they apply)."""

    learning_rate: float = 1e-4
    max_grad_norm: float = 10.0
    minibatch_size: int = 256
    buffer_size: int = 200_000
    gradient_steps: int = 840
    """Gradient steps after each episode, one per decision step."""
    target_update_steps: int = 1000
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    exploration_fraction: float = 0.3

    def __post_init__(self) -> None:
        # zero-argument super() fails in a dataclass with slots.
        DeepMarlConfig.__post_init__(self)
        for name in ("buffer_size", "gradient_steps", "target_update_steps"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero.")
        if not 0.0 <= self.epsilon_end <= self.epsilon_start <= 1.0:
            raise ValueError("Need 0 <= epsilon_end <= epsilon_start <= 1.")
        if not 0.0 < self.exploration_fraction <= 1.0:
            raise ValueError("exploration_fraction must be in (0, 1].")


class SharedQNetwork(nn.Module):
    """The ``marl_deep_ppo`` MLP body with one Q-value per action."""

    def __init__(self, input_size: int, hidden_size: int, action_count: int = 2):
        super().__init__()
        self.body = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.q_head = nn.Linear(hidden_size, action_count)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        # the (scores, values) pair the shared trainer expects; greedy = argmax
        q_values = self.q_head(self.body(inputs))
        return q_values, q_values.max(dim=-1).values


class ReplayBuffer:
    """Fixed-size ring buffer of single-agent transitions."""

    def __init__(self, capacity: int, input_size: int) -> None:
        self.capacity = capacity
        self.obs = np.zeros((capacity, input_size), dtype=np.float32)
        self.next_obs = np.zeros((capacity, input_size), dtype=np.float32)
        self.actions = np.zeros(capacity, dtype=np.int64)
        self.rewards = np.zeros(capacity, dtype=np.float32)
        self.dones = np.zeros(capacity, dtype=np.float32)
        self.position = 0
        self.size = 0

    def add(self, obs, actions, rewards, next_obs, dones) -> None:
        for start in range(0, len(actions), self.capacity):
            end = min(start + self.capacity, len(actions))
            index = (self.position + np.arange(end - start)) % self.capacity
            self.obs[index] = obs[start:end]
            self.actions[index] = actions[start:end]
            self.rewards[index] = rewards[start:end]
            self.next_obs[index] = next_obs[start:end]
            self.dones[index] = dones[start:end]
            self.position = int((index[-1] + 1) % self.capacity)
            self.size = min(self.size + end - start, self.capacity)

    def sample(self, count: int, rng: np.random.Generator) -> dict[str, torch.Tensor]:
        index = rng.integers(0, self.size, size=count)
        return {
            "obs": torch.from_numpy(self.obs[index]),
            "actions": torch.from_numpy(self.actions[index]),
            "rewards": torch.from_numpy(self.rewards[index]),
            "next_obs": torch.from_numpy(self.next_obs[index]),
            "dones": torch.from_numpy(self.dones[index]),
        }


class DqnTrainer(DeepMarlTrainer):
    """Trains and evaluates the shared DQN on the corridor wrapper."""

    controller_name = CONTROLLER_NAME
    hyperparameters = (
        *DeepMarlTrainer.hyperparameters,
        "buffer_size",
        "gradient_steps",
        "target_update_steps",
        "epsilon_start",
        "epsilon_end",
        "exploration_fraction",
    )
    log_names = ("td_loss", "mean_q", "epsilon")

    def __init__(self, config: DqnConfig, **hooks) -> None:
        super().__init__(config, **hooks)
        self.target_network = self._build_network()
        self.target_network.load_state_dict(self.network.state_dict())
        self.buffer = ReplayBuffer(config.buffer_size, self.input_size)
        self.gradient_step_count = 0

    def _build_network(self) -> nn.Module:
        return SharedQNetwork(self.input_size, self.config.hidden_size)

    def epsilon(self, episode: int) -> float:
        cfg = self.config
        progress = (episode - 1) / max(1.0, cfg.exploration_fraction * cfg.episodes)
        return max(cfg.epsilon_end, cfg.epsilon_start - progress * (cfg.epsilon_start - cfg.epsilon_end))

    def _act(self, batch: np.ndarray, *, greedy: bool):
        with torch.no_grad():
            q_values, best = self.network(torch.from_numpy(batch))
        actions = q_values.argmax(dim=-1).numpy()
        if not greedy:
            explore = self.rng.random(len(actions)) < self.epsilon(self.completed_episodes + 1)
            random_actions = self.rng.integers(0, q_values.shape[-1], size=len(actions))
            actions = np.where(explore, random_actions, actions)
        # PPO's log-probs and values are unused here
        zeros = np.zeros(len(actions), dtype=np.float32)
        return actions, zeros, best.numpy()

    def _update(self, rollout: dict[str, np.ndarray]) -> tuple[float, float, float]:
        cfg = self.config
        obs = rollout["obs"]  # (steps, agents, features)
        next_obs = np.concatenate([obs[1:], rollout["last_batch"][None]], axis=0)
        dones = np.zeros(obs.shape[:2], dtype=np.float32)
        # a time-limit stop is not a real end, so only termination stops bootstrapping
        dones[-1] = float(bool(rollout["terminated"]))
        self.buffer.add(
            obs.reshape(-1, obs.shape[-1]),
            rollout["actions"].reshape(-1),
            rollout["rewards"].reshape(-1),
            next_obs.reshape(-1, obs.shape[-1]),
            dones.reshape(-1),
        )

        losses, q_means = [], []
        for _ in range(cfg.gradient_steps):
            batch = self.buffer.sample(cfg.minibatch_size, self.rng)
            q_values, _ = self.network(batch["obs"])
            chosen = q_values.gather(1, batch["actions"][:, None]).squeeze(1)
            with torch.no_grad():
                # double dqn: online net picks the action, target net scores it
                next_actions = self.network(batch["next_obs"])[0].argmax(dim=-1, keepdim=True)
                next_q = self.target_network(batch["next_obs"])[0].gather(1, next_actions).squeeze(1)
                target = batch["rewards"] + cfg.gamma * (1.0 - batch["dones"]) * next_q
            loss = nn.functional.smooth_l1_loss(chosen, target)
            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.network.parameters(), cfg.max_grad_norm)
            self.optimizer.step()
            self.gradient_step_count += 1
            if self.gradient_step_count % cfg.target_update_steps == 0:
                self.target_network.load_state_dict(self.network.state_dict())
            losses.append(loss.item())
            q_means.append(chosen.mean().item())
        return float(np.mean(losses)), float(np.mean(q_means)), self.epsilon(self.completed_episodes + 1)

    def load_checkpoint(self, path: Path | None = None, *, for_training: bool) -> Path:
        source = super().load_checkpoint(path, for_training=for_training)
        self.target_network.load_state_dict(self.network.state_dict())
        return source

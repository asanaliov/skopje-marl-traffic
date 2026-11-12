"""Parameter-shared PPO with self-attention across the corridor junctions.

``marl_deep_ppo`` decides from each junction's own observation. This controller
inserts one self-attention layer between the two hidden layers of that network,
so each junction can also use the state of the other seven and learns how much
weight to give each one. The corridor is small and densely linked, so every
junction attends to every other instead of following a fixed neighbor graph.

The attention output is added to the junction's own encoding. Without attention
the network is therefore the ``marl_deep_ppo`` network, and the two controllers
share observations, local reward, PPO settings and training budget.

Two consequences matter for the comparison:

* All eight observations are needed at execution time, so the controller is not
  decentralized.
* The critic attends too, so it is effectively centralized. A difference from
  ``marl_deep_ppo`` measures shared information, not the actor's attention alone.

Attention needs all agents of one decision together. The PPO update therefore
shuffles whole timesteps rather than single agent samples, keeping the number of
samples and gradient steps per episode unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer


CONTROLLER_NAME = "marl_attention_ppo"


@dataclass(frozen=True, slots=True)
class AttentionPpoConfig(DeepMarlConfig):
    """Deep MARL settings plus the size of the attention layer."""

    attention_heads: int = 4

    def __post_init__(self) -> None:
        # zero-argument super() fails in a dataclass with slots.
        DeepMarlConfig.__post_init__(self)
        if self.attention_heads <= 0:
            raise ValueError("attention_heads must be greater than zero.")
        if self.hidden_size % self.attention_heads:
            raise ValueError("hidden_size must be divisible by attention_heads.")


class AttentionActorCritic(nn.Module):
    """Shared actor-critic whose agents attend to each other.

    Inputs have shape ``(agents, features)`` or ``(steps, agents, features)``.
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        attention_heads: int,
        action_count: int = 2,
    ):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_size, hidden_size), nn.Tanh())
        self.norm = nn.LayerNorm(hidden_size)
        self.attention = nn.MultiheadAttention(
            hidden_size, attention_heads, batch_first=True
        )
        self.decoder = nn.Sequential(nn.Linear(hidden_size, hidden_size), nn.Tanh())
        self.policy_head = nn.Linear(hidden_size, action_count)
        self.value_head = nn.Linear(hidden_size, 1)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        encoded = self.encoder(inputs)
        tokens = self.norm(encoded)
        attended, _ = self.attention(tokens, tokens, tokens, need_weights=False)
        hidden = self.decoder(encoded + attended)
        return self.policy_head(hidden), self.value_head(hidden).squeeze(-1)

    def attention_weights(self, inputs: torch.Tensor) -> torch.Tensor:
        """Return how much each agent (row) attends to each agent (column)."""
        tokens = self.norm(self.encoder(inputs))
        _, weights = self.attention(tokens, tokens, tokens, need_weights=True)
        return weights


class AttentionPpoTrainer(DeepMarlTrainer):
    """Trains and evaluates the attention policy on the corridor wrapper."""

    controller_name = CONTROLLER_NAME
    hyperparameters = (*DeepMarlTrainer.hyperparameters, "attention_heads")
    # weights have the same shape for any head count, so loading alone can't catch it.
    evaluation_hyperparameters = ("hidden_size", "attention_heads", "approach_range_m")

    def _build_network(self) -> nn.Module:
        return AttentionActorCritic(
            self.input_size, self.config.hidden_size, self.config.attention_heads
        )

    def _samples(self, array: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(array)

    def _minibatch_length(self) -> int:
        return max(1, self.config.minibatch_size // len(self.config.agent_ids))

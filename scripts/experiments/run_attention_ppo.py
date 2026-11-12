"""Train or evaluate the self-attention PPO controller.

All eight selected corridor agents share one actor-critic network with a
self-attention layer across the junctions; see
``src/training/deep_marl_attention.py``. Evaluation runs one greedy episode on
the same protocol as every other controller and appends it to
``results/experiments.csv`` under ``marl_attention_ppo`` (``_neighbor`` /
``_global`` suffix for the other reward modes).

Requires PyTorch (``pip install torch``).

    python scripts/experiments/run_attention_ppo.py train --scenario medium --episodes 300
    python scripts/experiments/run_attention_ppo.py evaluate --scenario medium --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CHECKPOINT_DIR  # noqa: E402
from scripts.experiments.run_deep_marl import (  # noqa: E402
    DEFAULT_TRAINING_EPISODES,
    _common,
    _positive_float,
    _positive_int,
)


def default_checkpoint_path(scenario: str, seed: int, reward_mode: str) -> Path:
    """Deterministic checkpoint path from run arguments."""
    return (
        CHECKPOINT_DIR
        / f"deep_marl_attention_{reward_mode}_{scenario}_seed{seed}.pt"
    )


def _network(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hidden-size", type=_positive_int, default=128)
    parser.add_argument(
        "--attention-heads",
        type=_positive_int,
        default=4,
        help="Attention heads; must divide --hidden-size (default: 4).",
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    _common(train)
    _network(train)
    train.add_argument(
        "--episodes",
        type=_positive_int,
        default=DEFAULT_TRAINING_EPISODES,
        help="Training episodes (default: 300, the marl_deep_ppo budget).",
    )
    train.add_argument("--resume", action="store_true")
    train.add_argument("--learning-rate", type=_positive_float, default=3e-4)
    train.add_argument(
        "--lr-decay",
        action="store_true",
        help="Decay the learning rate linearly to zero over --episodes.",
    )
    train.add_argument("--update-epochs", type=_positive_int, default=4)
    train.add_argument("--entropy-coefficient", type=_positive_float, default=0.01)
    train.add_argument("--torch-seed", type=int, default=0)
    evaluate = sub.add_parser("evaluate")
    _common(evaluate)
    _network(evaluate)
    evaluate.add_argument("--allow-cross-seed", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        from src.training.deep_marl_attention import (
            AttentionPpoConfig,
            AttentionPpoTrainer,
        )
    except ImportError as error:
        print(f"[ERROR] PyTorch is required: pip install torch ({error})", file=sys.stderr)
        return 1

    checkpoint = args.checkpoint or default_checkpoint_path(
        args.scenario, args.seed, args.reward_mode
    )
    common = dict(
        agent_ids=tuple(args.agents),
        scenario=args.scenario,
        seed=args.seed,
        episode_seconds=args.episode_seconds,
        cooldown_seconds=args.cooldown_seconds,
        decision_interval_seconds=args.decision_interval,
        approach_range_m=args.approach_range,
        minimum_green_seconds=args.min_green,
        switch_penalty=args.switch_penalty,
        reward_mode=args.reward_mode,
        checkpoint_path=checkpoint,
        results_path=args.results_path,
        gui=args.gui,
        hidden_size=args.hidden_size,
        attention_heads=args.attention_heads,
    )
    print(
        f"Self-attention PPO over {len(args.agents)} agents: "
        f"{' '.join(args.agents)}; reward_mode={args.reward_mode}"
    )
    if args.command == "train":
        config = AttentionPpoConfig(
            **common,
            episodes=args.episodes,
            learning_rate=args.learning_rate,
            learning_rate_decay=args.lr_decay,
            update_epochs=args.update_epochs,
            entropy_coefficient=args.entropy_coefficient,
            torch_seed=args.torch_seed,
        )
        AttentionPpoTrainer(config).train(resume=args.resume)
    else:
        config = AttentionPpoConfig(
            **common,
            episodes=1,
            allow_cross_seed_evaluation=args.allow_cross_seed,
        )
        AttentionPpoTrainer(config).evaluate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

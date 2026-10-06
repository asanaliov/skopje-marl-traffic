"""Train or evaluate the parameter-shared deep MARL (PPO) controller.

All eight selected corridor agents share one actor-critic network trained
with PPO over the PettingZoo wrapper; see ``src/training/deep_marl.py`` for
the training regime and why parameter sharing was chosen. Evaluation runs one
greedy episode on the same protocol as every tabular controller and appends
it to ``results/experiments.csv`` under ``marl_deep_ppo`` (``_neighbor`` /
``_global`` suffix for the other reward modes).

Requires PyTorch (``pip install torch``).

    python scripts/run_deep_marl.py train --scenario medium --episodes 300
    python scripts/run_deep_marl.py evaluate --scenario medium --seed 42
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402

DEFAULT_TRAINING_EPISODES = 300  # kept in sync with src/training/deep_marl.py


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


def default_checkpoint_path(scenario: str, seed: int, reward_mode: str) -> Path:
    """Deterministic checkpoint path from run arguments."""
    return Path("checkpoints") / f"deep_marl_{reward_mode}_{scenario}_seed{seed}.pt"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", default="medium")
    parser.add_argument("--seed", type=_positive_int, default=42)
    parser.add_argument("--episode-seconds", type=_positive_float, default=3600.0)
    parser.add_argument("--cooldown-seconds", type=_non_negative_float, default=600.0)
    parser.add_argument("--decision-interval", type=_positive_float, default=5.0)
    parser.add_argument(
        "--reward-mode",
        choices=("local", "neighbor_aware", "global"),
        default="local",
        help=(
            "Reward every agent learns from (default: local, the deep "
            "counterpart of multi_agent_independent_rl)."
        ),
    )
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--results-path", type=Path, default=Path("results/experiments.csv"))
    parser.add_argument("--agents", nargs="+", default=list(SELECTED_CORRIDOR.agent_ids))
    parser.add_argument("--gui", action="store_true")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    _common(train)
    train.add_argument(
        "--episodes",
        type=_positive_int,
        default=DEFAULT_TRAINING_EPISODES,
        help="Training episodes (default: 300, the tabular MARL budget).",
    )
    train.add_argument("--resume", action="store_true")
    train.add_argument("--learning-rate", type=_positive_float, default=3e-4)
    train.add_argument("--hidden-size", type=_positive_int, default=128)
    train.add_argument("--torch-seed", type=int, default=0)
    evaluate = sub.add_parser("evaluate")
    _common(evaluate)
    evaluate.add_argument("--hidden-size", type=_positive_int, default=128)
    evaluate.add_argument("--allow-cross-seed", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer
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
        reward_mode=args.reward_mode,
        checkpoint_path=checkpoint,
        results_path=args.results_path,
        gui=args.gui,
        hidden_size=args.hidden_size,
    )
    print(
        f"Deep MARL (shared-parameter PPO) over {len(args.agents)} agents: "
        f"{' '.join(args.agents)}; reward_mode={args.reward_mode}"
    )
    if args.command == "train":
        config = DeepMarlConfig(
            **common,
            episodes=args.episodes,
            learning_rate=args.learning_rate,
            torch_seed=args.torch_seed,
        )
        DeepMarlTrainer(config).train(resume=args.resume)
    else:
        config = DeepMarlConfig(
            **common,
            episodes=1,
            allow_cross_seed_evaluation=args.allow_cross_seed,
        )
        DeepMarlTrainer(config).evaluate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

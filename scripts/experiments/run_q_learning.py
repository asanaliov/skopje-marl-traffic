"""Run an independent Q-learning SUMO trainer for any selected corridor agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.training.independent_q_learning import ( # noqa: E402
    IndependentQLearningTrainer,
    QLearningTrainingConfig,
)


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


def default_checkpoint_path(agent_id: str, scenario: str, seed: int) -> Path:
    """Generate a deterministic checkpoint path from run arguments."""
    return Path("checkpoints") / f"{agent_id}_{scenario}_seed{seed}.json"


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--agent-id",
        default="A19",
        help="Agent ID to train or evaluate. Must be one of the eight selected "
             "corridor agents (A9, A18, A19, A20, A24, A25, A26, A29). Default: A19.",
    )
    parser.add_argument("--scenario", default="medium")
    parser.add_argument("--seed", type=_positive_int, default=42)
    parser.add_argument("--episode-seconds", type=_positive_float, default=600.0)
    parser.add_argument("--cooldown-seconds", type=_positive_float, default=600.0)
    parser.add_argument("--decision-interval", type=_positive_float, default=5.0)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help=(
            "Path to save or load the checkpoint. If omitted, a deterministic path "
            "encoding agent ID, scenario, and seed is generated automatically."
        ),
    )
    parser.add_argument(
        "--results-path",
        type=Path,
        default=Path("results/experiments.csv"),
        help="Path to results CSV (default: results/experiments.csv).",
    )
    parser.add_argument("--gui", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run independent Q-learning for a selected corridor agent in SUMO."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser("train")
    _common_arguments(train)
    train.add_argument("--episodes", type=_positive_int, default=10)
    train.add_argument("--checkpoint-interval", type=_positive_int, default=1)
    train.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume from --checkpoint if it already exists, continuing the "
            "Q-table, epsilon, and episode count from where it left off "
            "instead of starting a fresh run. If no checkpoint exists yet, "
            "starts a new run normally."
        ),
    )

    evaluate = subparsers.add_parser("evaluate")
    _common_arguments(evaluate)
    evaluate.add_argument(
        "--allow-cross-seed",
        action="store_true",
        help=(
            "Allow evaluation traffic to use a different seed from the "
            "checkpoint's training traffic. Training and resume remain strict."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        f"This is a {args.agent_id} independent Q-learning run. No baseline comparison or "
        "coordinated MARL is active."
    )
    checkpoint_path = args.checkpoint or default_checkpoint_path(
        agent_id=args.agent_id,
        scenario=args.scenario,
        seed=args.seed,
    )
    if args.command == "train":
        config = QLearningTrainingConfig(
            agent_id=args.agent_id,
            scenario=args.scenario,
            seed=args.seed,
            episodes=args.episodes,
            episode_seconds=args.episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=args.gui,
            checkpoint_path=checkpoint_path,
            checkpoint_interval=args.checkpoint_interval,
            mode="train",
            resume=args.resume,
            results_path=args.results_path,
        )
        IndependentQLearningTrainer(config).train()
    else:
        config = QLearningTrainingConfig(
            agent_id=args.agent_id,
            scenario=args.scenario,
            seed=args.seed,
            episodes=1,
            episode_seconds=args.episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=args.gui,
            checkpoint_path=checkpoint_path,
            mode="evaluate",
            allow_cross_seed_evaluation=args.allow_cross_seed,
            results_path=args.results_path,
        )
        IndependentQLearningTrainer(config).evaluate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

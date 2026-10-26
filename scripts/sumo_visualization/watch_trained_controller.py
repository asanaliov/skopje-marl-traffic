"""Replay one saved traffic controller in the SUMO graphical simulator."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.environment.selected_corridor import SELECTED_CORRIDOR

CONTROLLERS = ("single-agent", "multi-agent", "deep-marl")
SCENARIOS = ("low", "medium", "high")
REWARD_MODES = ("local", "neighbor_aware", "global")


def positive_float(value: str) -> float:
    """Parse a positive simulation duration or decision interval."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_float(value: str) -> float:
    """Parse a non-negative cooldown duration."""
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive_int(value: str) -> int:
    """Parse a positive integer setting."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_int(value: str) -> int:
    """Parse a non-negative random seed."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def default_checkpoint(args: argparse.Namespace) -> Path:
    """Return the trained checkpoint path implied by the selected policy."""
    if args.controller == "single-agent":
        return (
            PROJECT_ROOT
            / "checkpoints"
            / "final_models"
            / f"{args.agent_id.lower()}_{args.scenario}.json"
        )
    if args.controller == "multi-agent":
        spatial_tag = "_spatial" if args.spatial_observations else ""
        return (
            PROJECT_ROOT
            / "checkpoints"
            / "final_models"
            / "marl"
            / f"marl_{args.reward_mode}_{args.scenario}_seed{args.seed}{spatial_tag}.json"
        )
    return (
        PROJECT_ROOT
        / "checkpoints"
        / f"deep_marl_{args.reward_mode}_{args.scenario}_seed{args.seed}.pt"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the controller and SUMO playback settings."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a saved controller greedily in SUMO GUI without starting "
            "training or adding a row to results/experiments.csv."
        )
    )
    parser.add_argument("--controller", required=True, choices=CONTROLLERS)
    parser.add_argument("--scenario", choices=SCENARIOS, default="medium")
    parser.add_argument("--seed", type=nonnegative_int, default=42)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        help="Checkpoint path. Defaults to the matching saved model under checkpoints/.",
    )
    parser.add_argument("--episode-seconds", type=positive_float, default=None)
    parser.add_argument("--cooldown-seconds", type=nonnegative_float, default=600.0)
    parser.add_argument("--decision-interval", type=positive_float, default=5.0)
    parser.add_argument(
        "--agent-id",
        default="A19",
        help="Controlled light for --controller single-agent (default: A19).",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(SELECTED_CORRIDOR.agent_ids),
        metavar="AGENT_ID",
        help="Lights for multi-agent and deep-MARL playback.",
    )
    parser.add_argument(
        "--reward-mode",
        choices=REWARD_MODES,
        default="local",
        help="Reward mode used by the multi-agent or deep-MARL checkpoint.",
    )
    parser.add_argument(
        "--spatial-observations",
        action="store_true",
        help="Load the multi-agent checkpoint trained with neighbor congestion inputs.",
    )
    parser.add_argument(
        "--spatial-neighbor-limit",
        type=positive_int,
        default=2,
        help="Number of neighbors represented in spatial tabular states (default: 2).",
    )
    parser.add_argument(
        "--hidden-size",
        type=positive_int,
        default=128,
        help="Shared PPO network width for deep MARL (default: 128).",
    )
    parser.add_argument(
        "--allow-cross-seed",
        action="store_true",
        help="Show this policy on the requested traffic seed instead of its training seed.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    """Evaluate the selected checkpoint with SUMO's graphical interface."""
    checkpoint = (args.checkpoint or default_checkpoint(args)).expanduser()
    if not checkpoint.is_absolute():
        checkpoint = Path.cwd() / checkpoint
    if not checkpoint.is_file():
        raise FileNotFoundError(
            f"Checkpoint not found: {checkpoint}\n"
            "Pass --checkpoint with a trained model file, or check the "
            "controller, scenario, reward mode, and seed."
        )

    episode_seconds = args.episode_seconds
    if episode_seconds is None:
        episode_seconds = 3600.0 if args.controller == "deep-marl" else 600.0
    print(
        f"Opening SUMO GUI for {args.controller}: scenario={args.scenario}, "
        f"seed={args.seed}, checkpoint={checkpoint}"
    )
    print("Playback is greedy evaluation. No training or results CSV update will occur.")

    if args.controller == "single-agent":
        from src.training.independent_q_learning import (
            IndependentQLearningTrainer,
            QLearningTrainingConfig,
        )

        config = QLearningTrainingConfig(
            agent_id=args.agent_id,
            scenario=args.scenario,
            seed=args.seed,
            episodes=1,
            episode_seconds=episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=True,
            checkpoint_path=checkpoint,
            mode="evaluate",
            allow_cross_seed_evaluation=args.allow_cross_seed,
            results_path=None,
        )
        IndependentQLearningTrainer(config).evaluate()
        return 0

    if args.controller == "multi-agent":
        from src.training.multi_agent_q_learning import (
            MultiAgentQLearningConfig,
            MultiAgentQLearningTrainer,
        )

        config = MultiAgentQLearningConfig(
            agent_ids=tuple(args.agents),
            scenario=args.scenario,
            seed=args.seed,
            episodes=1,
            episode_seconds=episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=True,
            checkpoint_path=checkpoint,
            mode="evaluate",
            allow_cross_seed_evaluation=args.allow_cross_seed,
            spatial_observations=args.spatial_observations,
            spatial_neighbor_limit=args.spatial_neighbor_limit,
            reward_mode=args.reward_mode,
            results_path=None,
        )
        MultiAgentQLearningTrainer(config).evaluate()
        return 0

    try:
        from src.training.deep_marl import DeepMarlConfig, DeepMarlTrainer
    except ImportError as error:
        raise RuntimeError("Deep MARL playback requires PyTorch: pip install torch") from error

    config = DeepMarlConfig(
        agent_ids=tuple(args.agents),
        scenario=args.scenario,
        seed=args.seed,
        episodes=1,
        episode_seconds=episode_seconds,
        cooldown_seconds=args.cooldown_seconds,
        decision_interval_seconds=args.decision_interval,
        reward_mode=args.reward_mode,
        checkpoint_path=checkpoint,
        results_path=None,
        gui=True,
        hidden_size=args.hidden_size,
        allow_cross_seed_evaluation=args.allow_cross_seed,
    )
    DeepMarlTrainer(config).evaluate()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Return a shell-friendly process status."""
    args = parse_args(argv)
    try:
        return run(args)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

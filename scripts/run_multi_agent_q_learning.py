"""Run the multi-agent independent Q-learning SUMO trainer.

All eight selected corridor agents learn concurrently in the same
episode, each with its own tabular Q-table (controller label
``multi_agent_independent_rl``, or ``multi_agent_spatial_rl`` with
``--spatial-observations``, which additionally lets every agent see a
coarse congestion flag for its nearest neighbors). See
``src/training/multi_agent_q_learning.py`` for how this differs from the
single-agent A19 runner in ``scripts/run_q_learning.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402
from src.training.multi_agent_q_learning import (  # noqa: E402
    DEFAULT_SPATIAL_NEIGHBOR_LIMIT,
    MultiAgentQLearningConfig,
    MultiAgentQLearningTrainer,
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


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scenario", default="medium")
    parser.add_argument("--seed", type=_positive_int, default=42)
    parser.add_argument("--episode-seconds", type=_positive_float, default=600.0)
    parser.add_argument("--cooldown-seconds", type=_positive_float, default=600.0)
    parser.add_argument("--decision-interval", type=_positive_float, default=5.0)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument(
        "--spatial-observations",
        action="store_true",
        help=(
            "Let every agent also observe a coarse congestion flag for its "
            "nearest neighbors instead of only its own junction. Results are "
            "written under the controller label multi_agent_spatial_rl, and "
            "the checkpoints of the two observation modes are not "
            "interchangeable."
        ),
    )
    parser.add_argument(
        "--neighbor-limit",
        type=_positive_int,
        default=DEFAULT_SPATIAL_NEIGHBOR_LIMIT,
        help=(
            "Nearest neighbors each agent observes with "
            "--spatial-observations (default: "
            f"{DEFAULT_SPATIAL_NEIGHBOR_LIMIT}). Every extra neighbor "
            "doubles the reachable tabular state space."
        ),
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(SELECTED_CORRIDOR.agent_ids),
        metavar="AGENT_ID",
        help=(
            "Selected corridor agents to control. Defaults to all eight: "
            f"{' '.join(SELECTED_CORRIDOR.agent_ids)}. A checkpoint is only "
            "loadable by a run configured with the same agent set."
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run multi-agent independent Q-learning in SUMO. Every agent "
            "keeps its own Q-table and its own local reward -- there is no "
            "coordination between them."
        )
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
            "Resume from --checkpoint if it already exists, continuing every "
            "agent's Q-table, epsilon, and episode count from where the run "
            "left off instead of starting fresh. If no checkpoint exists "
            "yet, starts a new run normally."
        ),
    )

    evaluate = subparsers.add_parser("evaluate")
    _common_arguments(evaluate)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    agent_ids = tuple(args.agents)
    observation_note = (
        "Each agent observes its own junction plus a congestion flag for "
        f"its {args.neighbor_limit} nearest observed neighbor(s)."
        if args.spatial_observations
        else "Each agent observes only its own junction."
    )
    print(
        f"This is a multi-agent independent Q-learning run over "
        f"{len(agent_ids)} agent(s): {', '.join(agent_ids)}. Each agent "
        "learns its own Q-table from its own local reward; no coordinated "
        f"reward mixing is active. {observation_note}"
    )
    if args.command == "train":
        config = MultiAgentQLearningConfig(
            agent_ids=agent_ids,
            scenario=args.scenario,
            seed=args.seed,
            episodes=args.episodes,
            episode_seconds=args.episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=args.gui,
            checkpoint_path=args.checkpoint,
            checkpoint_interval=args.checkpoint_interval,
            mode="train",
            resume=args.resume,
            spatial_observations=args.spatial_observations,
            spatial_neighbor_limit=args.neighbor_limit,
        )
        MultiAgentQLearningTrainer(config).train()
    else:
        config = MultiAgentQLearningConfig(
            agent_ids=agent_ids,
            scenario=args.scenario,
            seed=args.seed,
            # One episode only: evaluation is greedy and the SUMO seed is
            # fixed, so extra episodes would just append identical rows to
            # results/experiments.csv.
            episodes=1,
            episode_seconds=args.episode_seconds,
            cooldown_seconds=args.cooldown_seconds,
            decision_interval_seconds=args.decision_interval,
            gui=args.gui,
            checkpoint_path=args.checkpoint,
            mode="evaluate",
            spatial_observations=args.spatial_observations,
            spatial_neighbor_limit=args.neighbor_limit,
        )
        MultiAgentQLearningTrainer(config).evaluate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

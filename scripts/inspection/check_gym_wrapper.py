"""Run the standard RL API conformance suites against real SUMO.

`tests/test_gym_wrapper.py` runs PettingZoo's `parallel_api_test` and
Gymnasium's `check_env` against a fake environment, which keeps them fast
enough for every test run but proves only that the wrapper *code* obeys the
contracts. This script runs the same two suites against a real SUMO process, so
the observation spaces are checked against the traffic-light programs the
simulation actually loads.

Both suites restart the environment several times, so keep the episode short.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gymnasium.utils.env_checker import check_env  # noqa: E402
from pettingzoo.test import parallel_api_test  # noqa: E402

from src.environment.gym_wrapper import (  # noqa: E402
    DEFAULT_GYM_AGENT_ID,
    CorridorParallelEnv,
    SingleAgentTrafficEnv,
    audited_space_specs,
)
from src.environment.multi_agent_environment import (  # noqa: E402
    MultiAgentEnvironmentConfig,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402


DEFAULT_EPISODE_SECONDS = 120.0
DEFAULT_CYCLES = 5


def positive_number(value: str) -> float:
    """Parse one positive command-line number."""
    number = float(value)
    if number <= 0.0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def positive_integer(value: str) -> int:
    """Parse one positive command-line integer."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse conformance-check settings."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify the PettingZoo and Gymnasium wrappers against a running "
            "SUMO simulation."
        )
    )
    parser.add_argument("--scenario", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--seed", type=positive_integer, default=42)
    parser.add_argument(
        "--episode-seconds",
        type=positive_number,
        default=DEFAULT_EPISODE_SECONDS,
        help=(
            "Demand seconds per checked episode. The suites reset the "
            "environment several times, so short episodes keep the check fast."
        ),
    )
    parser.add_argument(
        "--decision-interval",
        type=positive_number,
        default=5.0,
    )
    parser.add_argument(
        "--cycles",
        type=positive_integer,
        default=DEFAULT_CYCLES,
        help="Decision intervals to step inside the PettingZoo API test.",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(SELECTED_CORRIDOR.agent_ids),
        metavar="AGENT_ID",
        help=(
            "Corridor agents to control in the PettingZoo check. Defaults to "
            f"all eight: {', '.join(SELECTED_CORRIDOR.agent_ids)}."
        ),
    )
    parser.add_argument(
        "--gym-agent",
        default=DEFAULT_GYM_AGENT_ID,
        help=(
            "The single agent checked through the Gymnasium API "
            f"(default: {DEFAULT_GYM_AGENT_ID})."
        ),
    )
    return parser.parse_args(argv)


def episode_config(
    args: argparse.Namespace,
    agent_ids: tuple[str, ...],
) -> MultiAgentEnvironmentConfig:
    """Build one short episode configuration for a conformance run."""
    return MultiAgentEnvironmentConfig(
        scenario=args.scenario,
        seed=args.seed,
        agent_ids=agent_ids,
        demand_seconds=args.episode_seconds,
        # No cooldown: a conformance check does not need the network to drain.
        cooldown_seconds=0.0,
        decision_interval_seconds=args.decision_interval,
    )


def report_spaces(agent_ids: tuple[str, ...]) -> None:
    """Print the observation shape every agent declares before SUMO starts."""
    print("Audited observation spaces (lanes x 4 + phase elapsed + one-hot phases):")
    for agent_id, spec in audited_space_specs(agent_ids).items():
        print(
            f"  {agent_id}: lanes={spec.lane_count} phases={spec.phase_count} "
            f"features={spec.feature_count}"
        )


def run_checks(args: argparse.Namespace) -> int:
    """Run both conformance suites and report which one failed."""
    agent_ids = tuple(args.agents)
    report_spaces(agent_ids)

    print(
        f"\nPettingZoo parallel_api_test: {len(agent_ids)} agents, "
        f"{args.cycles} decision intervals per reset."
    )
    parallel_environment = CorridorParallelEnv(episode_config(args, agent_ids))
    try:
        parallel_api_test(parallel_environment, num_cycles=args.cycles)
    finally:
        parallel_environment.close()

    print(f"\nGymnasium check_env: single agent {args.gym_agent}.")
    single_agent_environment = SingleAgentTrafficEnv(
        args.gym_agent,
        episode_config(args, (args.gym_agent,)),
    )
    try:
        check_env(single_agent_environment, skip_render_check=True)
    finally:
        single_agent_environment.close()
    print("Passed Gymnasium environment checker")

    print("\nBoth standard RL API suites passed against a live SUMO simulation.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and report failures without writing result files."""
    args = parse_args(argv)
    try:
        return run_checks(args)
    except Exception as error:
        print(f"[ERROR] Wrapper conformance check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

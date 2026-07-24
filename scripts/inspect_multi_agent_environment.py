"""Run a short console-only inspection of the multi-agent environment."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.environment.actions import TrafficAction  # noqa: E402
from src.environment.multi_agent_environment import (  # noqa: E402
    MultiAgentEnvironmentConfig,
    MultiAgentStepResult,
    MultiAgentTrafficEnvironment,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402


INSPECTION_NOTICE = (
    "This is a multi-agent environment inspection run. "
    "No learning algorithm is active."
)
DEFAULT_SECONDS = 120.0
DEFAULT_REPORT_INTERVAL_SECONDS = 60.0
CYCLE_INTERVAL_SECONDS = 10.0


def positive_number(value: str) -> float:
    """Parse one positive command-line number."""
    number = float(value)
    if number <= 0.0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def nonnegative_integer(value: str) -> int:
    """Parse one non-negative command-line integer."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse inspection settings."""
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one or more selected traffic-light agents through the "
            "shared SUMO environment."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=("low", "medium", "high"),
        default="medium",
    )
    parser.add_argument("--seed", type=nonnegative_integer, default=42)
    parser.add_argument(
        "--seconds",
        type=positive_number,
        default=DEFAULT_SECONDS,
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--agents",
        help="comma-separated selected agents, such as A19,A26",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="inspect all eight selected agents",
    )
    parser.add_argument(
        "--decision-interval",
        type=positive_number,
        default=5.0,
    )
    parser.add_argument(
        "--reward-mode",
        choices=("local", "neighbor_aware", "global"),
        default="local",
    )
    parser.add_argument(
        "--policy",
        choices=("original", "keep", "cycle"),
        default="original",
    )
    parser.add_argument(
        "--report-interval",
        type=positive_number,
        default=DEFAULT_REPORT_INTERVAL_SECONDS,
    )
    parser.add_argument("--gui", action="store_true")
    return parser.parse_args(argv)


def selected_agent_ids(
    agents_argument: str | None,
    use_all_agents: bool,
) -> tuple[str, ...]:
    """Parse agent input and normalize it through environment configuration."""
    if use_all_agents:
        return SELECTED_CORRIDOR.agent_ids
    requested = tuple(
        agent_id.strip()
        for agent_id in str(agents_argument).split(",")
        if agent_id.strip()
    )
    return MultiAgentEnvironmentConfig(agent_ids=requested).agent_ids


def actions_for_policy(
    policy: str,
    agent_ids: tuple[str, ...],
    next_simulation_time: float,
    next_cycle_time: float,
) -> tuple[Mapping[str, TrafficAction] | None, float]:
    """Build one deterministic inspection action mapping."""
    if policy == "original":
        return None, next_cycle_time
    if policy == "keep":
        return (
            dict.fromkeys(agent_ids, TrafficAction.KEEP),
            next_cycle_time,
        )

    use_next_green = next_simulation_time + 1e-9 >= next_cycle_time
    action = (
        TrafficAction.NEXT_GREEN if use_next_green else TrafficAction.KEEP
    )
    if use_next_green:
        while next_cycle_time <= next_simulation_time + 1e-9:
            next_cycle_time += CYCLE_INTERVAL_SECONDS
    return dict.fromkeys(agent_ids, action), next_cycle_time


def print_report(
    result: MultiAgentStepResult,
    action_status_counts: Counter[str],
) -> None:
    """Print one compact environment summary."""
    simulation_time = float(result.info["simulation_time"])
    total_queue = sum(
        sum(observation.queue_lengths)
        for observation in result.observations.values()
    )
    mean_queue = total_queue / len(result.observations)
    rewards = ", ".join(
        f"{agent_id}={reward:.3f}"
        for agent_id, reward in result.rewards.items()
    )
    statuses = (
        ", ".join(
            f"{status}={count}"
            for status, count in sorted(action_status_counts.items())
        )
        or "none=0"
    )
    transition_agents = result.info["transition_agents"]
    transition_text = ", ".join(transition_agents) if transition_agents else "none"
    print(f"\nSimulation time: {simulation_time:.0f} s")
    print(f"  configured_agents={','.join(result.info['agent_ids'])}")
    print(
        "  "
        f"departed={result.info['departed_vehicle_count']}, "
        f"arrived={result.info['arrived_vehicle_count']}, "
        f"active_expected={result.info['active_expected_vehicle_count']}"
    )
    print(f"  rewards={rewards}")
    print(f"  total_queue={total_queue}, mean_agent_queue={mean_queue:.2f}")
    print(f"  action_status_counts={statuses}")
    print(f"  agents_in_transition={transition_text}")
    print(
        f"  terminated={result.terminated}, truncated={result.truncated}"
    )


def run_inspection(args: argparse.Namespace) -> int:
    """Run one inspection and return a process status code."""
    agent_ids = selected_agent_ids(args.agents, args.all)
    config = MultiAgentEnvironmentConfig(
        scenario=args.scenario,
        seed=args.seed,
        agent_ids=agent_ids,
        demand_seconds=args.seconds,
        cooldown_seconds=0.0,
        decision_interval_seconds=args.decision_interval,
        gui=args.gui,
        reward_mode=args.reward_mode,
    )
    print(INSPECTION_NOTICE)
    print(
        f"scenario={config.scenario}, seed={config.seed}, "
        f"agents={','.join(config.agent_ids)}, policy={args.policy}, "
        f"reward_mode={config.reward_mode}"
    )

    action_status_counts: Counter[str] = Counter()
    action_request_count = 0
    next_report_time = min(args.report_interval, config.total_duration_seconds)
    next_cycle_time = CYCLE_INTERVAL_SECONDS
    last_result: MultiAgentStepResult | None = None

    with MultiAgentTrafficEnvironment(config) as environment:
        observations = environment.reset()
        while True:
            current_time = next(iter(observations.values())).simulation_time
            actions, next_cycle_time = actions_for_policy(
                args.policy,
                environment.agent_ids,
                current_time + config.decision_interval_seconds,
                next_cycle_time,
            )
            result = environment.step(actions)
            last_result = result
            observations = result.observations
            action_results = result.info["action_results"]
            action_request_count += len(action_results)
            action_status_counts.update(
                action_result.status.value
                for action_result in action_results.values()
            )

            simulation_time = float(result.info["simulation_time"])
            if (
                simulation_time + 1e-9 >= next_report_time
                or result.terminated
                or result.truncated
            ):
                print_report(result, action_status_counts)
                while next_report_time <= simulation_time + 1e-9:
                    next_report_time += args.report_interval
            if result.terminated or result.truncated:
                break

    if last_result is None:
        raise RuntimeError("The inspection ended before one environment step.")
    print("\nMulti-agent environment inspection summary")
    print(f"  observations={len(last_result.observations)}")
    print(f"  rewards={len(last_result.rewards)}")
    print(f"  action_requests={action_request_count}")
    print(f"  completed_seconds={last_result.info['simulation_time']:.0f}")
    print(f"  terminated={last_result.terminated}")
    print(f"  truncated={last_result.truncated}")
    if args.policy == "original":
        print("  original policy issued zero traffic-light action requests")
    print(f"\n{INSPECTION_NOTICE}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and report failures without writing result files."""
    args = parse_args(argv)
    try:
        return run_inspection(args)
    except Exception as error:
        print(
            f"[ERROR] Multi-agent environment inspection failed: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

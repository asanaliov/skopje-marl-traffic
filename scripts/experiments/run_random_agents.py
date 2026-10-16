"""Run random traffic-light agents as a SUMO-RL integration smoke test."""

from __future__ import annotations

import traceback
import argparse
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = PROJECT_ROOT / "sumo" / "benchmark" / "grid4x4"

# Edit these two constants if the downloaded benchmark uses different names.
NETWORK_FILE_NAME = "grid4x4.net.xml"
ROUTE_FILE_NAME = "grid4x4_1.rou.xml"
NETWORK_FILE = BENCHMARK_DIR / NETWORK_FILE_NAME
ROUTE_FILE = BENCHMARK_DIR / ROUTE_FILE_NAME

DEFAULT_SECONDS = 300
DELTA_TIME = 5
RANDOM_SEED = 42
REPORT_EVERY_STEPS = 12


def positive_integer(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error

    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parse_args() -> argparse.Namespace:
    """Parse smoke-test command-line options."""
    parser = argparse.ArgumentParser(
        description="Run random agents in the SUMO-RL grid4x4 benchmark."
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="launch sumo-gui instead of running headlessly",
    )
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=DEFAULT_SECONDS,
        help=f"simulation duration in seconds (default: {DEFAULT_SECONDS})",
    )
    return parser.parse_args()


def benchmark_files_available() -> bool:
    """Report missing benchmark inputs before SUMO-RL is imported."""
    missing_files = [
        path for path in (NETWORK_FILE, ROUTE_FILE) if not path.is_file()
    ]
    if not missing_files:
        return True

    print("[ERROR] Required grid4x4 benchmark files are missing:", file=sys.stderr)
    for path in missing_files:
        print(f"  - {path}", file=sys.stderr)
    print(
        f"\nPlace the benchmark network and route files in:\n  {BENCHMARK_DIR}",
        file=sys.stderr,
    )
    print(
        "If their names differ, edit NETWORK_FILE_NAME and ROUTE_FILE_NAME "
        "near the top of this script.",
        file=sys.stderr,
    )
    return False


def load_sumo_rl() -> ModuleType | None:
    """Import SUMO-RL with a concise dependency error."""
    try:
        import sumo_rl
    except Exception as error:
        print(
            f"[ERROR] Could not import sumo_rl: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        print(
            "Activate the project .venv and install requirements.txt first.",
            file=sys.stderr,
        )
        return None
    return sumo_rl


def run_random_agents(environment: Any) -> float:
    """Step all active agents with sampled actions until the episode ends."""
    environment.reset(seed=RANDOM_SEED)
    for index, agent in enumerate(environment.agents):
        environment.action_space(agent).seed(RANDOM_SEED + index)

    step_count = 0
    total_reward = 0.0
    print(f"Simulation started with {len(environment.agents)} active agents.")

    while environment.agents:
        actions = {
            agent: environment.action_space(agent).sample()
            for agent in environment.agents
        }
        _, rewards, _, _, _ = environment.step(actions)
        total_reward += sum(float(reward) for reward in rewards.values())
        step_count += 1

        if step_count % REPORT_EVERY_STEPS == 0 or not environment.agents:
            print(
                f"Step {step_count}: active agents={len(environment.agents)}, "
                f"total reward={total_reward:.2f}"
            )

    return total_reward


def main() -> int:
    """Create, run, and reliably close the SUMO-RL environment."""
    args = parse_args()
    if not benchmark_files_available():
        return 1

    sumo_rl = load_sumo_rl()
    if sumo_rl is None:
        return 1

    environment: Any | None = None
    try:
        environment = sumo_rl.parallel_env(
            net_file=str(NETWORK_FILE),
            route_file=str(ROUTE_FILE),
            use_gui=args.gui,
            num_seconds=args.seconds,
            delta_time=DELTA_TIME,
        )
        total_reward = run_random_agents(environment)
        print(f"Simulation completed. Total reward: {total_reward:.2f}")
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if environment is not None:
            environment.close()


if __name__ == "__main__":
    sys.exit(main())

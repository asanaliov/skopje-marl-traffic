"""Train one corridor agent with Stable-Baselines3 through the Gym wrapper.

This is the compatibility demonstration for `src/environment/gym_wrapper.py`:
it shows an unmodified deep RL library running its own standard training loop
on the Skopje SUMO environment. Stable-Baselines3 constructs the policy network
from the wrapper's spaces, calls `reset()` and `step()` itself, and never sees
`TrafficAction` or `TrafficObservation`.

It is deliberately *not* a benchmark run. A few hundred timesteps train nothing
worth comparing, so this script writes no row to `results/experiments.csv`; the
comparison table stays reserved for the tabular controllers that were actually
trained to convergence. Use it to confirm the wiring, to time an episode, or as
the starting point for a real deep RL experiment.

Stable-Baselines3 is an optional dependency (see `requirements-dev.txt`):

```powershell
pip install stable-baselines3
```
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.environment.gym_wrapper import (  # noqa: E402
    DEFAULT_GYM_AGENT_ID,
    SingleAgentTrafficEnv,
)
from src.environment.multi_agent_environment import (  # noqa: E402
    MultiAgentEnvironmentConfig,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402


DEFAULT_TIMESTEPS = 200
DEFAULT_EPISODE_SECONDS = 300.0
DEFAULT_DECISION_INTERVAL = 5.0
MISSING_LIBRARY_MESSAGE = (
    "Stable-Baselines3 is not installed. Install it with "
    "'pip install stable-baselines3' (it is listed in requirements-dev.txt)."
)


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
    """Parse demonstration settings."""
    parser = argparse.ArgumentParser(
        description=(
            "Run a short Stable-Baselines3 training loop on one selected "
            "corridor agent through the Gymnasium wrapper."
        )
    )
    parser.add_argument(
        "--algorithm",
        choices=("dqn", "ppo"),
        default="dqn",
        help="The Stable-Baselines3 algorithm to run (default: dqn).",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_GYM_AGENT_ID,
        help=(
            "The controlled corridor agent; every other traffic light keeps "
            f"its imported SUMO program. Choose from: "
            f"{', '.join(SELECTED_CORRIDOR.agent_ids)}."
        ),
    )
    parser.add_argument("--scenario", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--seed", type=positive_integer, default=42)
    parser.add_argument(
        "--timesteps",
        type=positive_integer,
        default=DEFAULT_TIMESTEPS,
        help=(
            "Training decision steps (default: "
            f"{DEFAULT_TIMESTEPS}). This demonstrates the integration; it does "
            "not train a competitive controller."
        ),
    )
    parser.add_argument(
        "--episode-seconds",
        type=positive_number,
        default=DEFAULT_EPISODE_SECONDS,
    )
    parser.add_argument(
        "--decision-interval",
        type=positive_number,
        default=DEFAULT_DECISION_INTERVAL,
    )
    parser.add_argument(
        "--evaluation-steps",
        type=positive_integer,
        default=20,
        help="Greedy decision steps to run after training (default: 20).",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=None,
        help="Optional path to save the trained Stable-Baselines3 model.",
    )
    parser.add_argument("--gui", action="store_true")
    return parser.parse_args(argv)


def build_environment(args: argparse.Namespace) -> SingleAgentTrafficEnv:
    """Build the Gymnasium environment for one corridor agent."""
    config = MultiAgentEnvironmentConfig(
        scenario=args.scenario,
        seed=args.seed,
        agent_ids=(args.agent,),
        demand_seconds=args.episode_seconds,
        # A demo does not need the network to drain after the demand ends.
        cooldown_seconds=0.0,
        decision_interval_seconds=args.decision_interval,
        gui=args.gui,
    )
    return SingleAgentTrafficEnv(
        args.agent,
        config,
        render_mode="human" if args.gui else None,
    )


def build_model(args: argparse.Namespace, environment: SingleAgentTrafficEnv):
    """Create the Stable-Baselines3 model sized for a short demonstration run."""
    from stable_baselines3 import DQN, PPO

    if args.algorithm == "dqn":
        return DQN(
            "MlpPolicy",
            environment,
            seed=args.seed,
            learning_starts=min(50, args.timesteps // 2),
            buffer_size=10_000,
            batch_size=32,
            train_freq=4,
            verbose=1,
        )
    # PPO collects n_steps transitions before every update, so a demo run has
    # to keep that rollout shorter than the run itself to update at all.
    rollout_steps = max(8, min(64, args.timesteps // 2))
    return PPO(
        "MlpPolicy",
        environment,
        seed=args.seed,
        n_steps=rollout_steps,
        batch_size=min(32, rollout_steps),
        verbose=1,
    )


def evaluate(
    model,
    environment: SingleAgentTrafficEnv,
    steps: int,
) -> tuple[float, int]:
    """Run the trained policy greedily and return total reward and steps taken."""
    observation, _ = environment.reset()
    total_reward = 0.0
    completed_steps = 0
    for _ in range(steps):
        action, _ = model.predict(observation, deterministic=True)
        observation, reward, terminated, truncated, _ = environment.step(action)
        total_reward += reward
        completed_steps += 1
        if terminated or truncated:
            break
    return total_reward, completed_steps


def run_demo(args: argparse.Namespace) -> int:
    """Train, optionally save, and greedily evaluate one deep RL policy."""
    try:
        import stable_baselines3  # noqa: F401
    except ImportError:
        print(f"[ERROR] {MISSING_LIBRARY_MESSAGE}", file=sys.stderr)
        return 1

    environment = build_environment(args)
    print(
        f"Controlled agent: {args.agent} "
        f"(traffic light {SELECTED_CORRIDOR.agent_to_traffic_light[args.agent]})"
    )
    print(f"Observation space: {environment.observation_space}")
    print(f"Action space: {environment.action_space} (0=KEEP, 1=NEXT_GREEN)")
    print(
        f"Algorithm: {args.algorithm.upper()}, timesteps: {args.timesteps}, "
        f"scenario: {args.scenario}, seed: {args.seed}"
    )

    try:
        model = build_model(args, environment)
        model.learn(total_timesteps=args.timesteps)
        if args.model_path is not None:
            args.model_path.parent.mkdir(parents=True, exist_ok=True)
            model.save(args.model_path)
            print(f"Saved the trained model to {args.model_path}")

        total_reward, completed_steps = evaluate(
            model,
            environment,
            args.evaluation_steps,
        )
    finally:
        environment.close()

    print("\nStable-Baselines3 demonstration summary")
    print(f"  trained_timesteps={args.timesteps}")
    print(f"  greedy_evaluation_steps={completed_steps}")
    print(f"  greedy_evaluation_total_reward={total_reward:.2f}")
    print(
        "\nThis run demonstrates library compatibility only. It is far too "
        "short to be a trained controller, so no row was written to "
        "results/experiments.csv."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and report failures without writing result files."""
    args = parse_args(argv)
    try:
        return run_demo(args)
    except Exception as error:
        print(f"[ERROR] Deep RL demonstration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

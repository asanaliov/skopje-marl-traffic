"""Run the imported actuated baseline across low, medium, and high scenarios.

Calls the same in-process ``run_experiment()`` as
``scripts/run_imported_actuated_experiment.py`` for each requested
scenario, so results are produced identically either way. This script
exists so the full validation suite required for this baseline can be run
with one command; see
``sumo/skopje/documentation/imported_actuated_baseline.md``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_candidate_review import load_traci  # noqa: E402
from scripts.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from scripts.run_imported_actuated_experiment import (  # noqa: E402
    DEFAULT_REPORT_INTERVAL_SECONDS,
    _print_final_summary,
    _project_relative,
    _resolve_scenario_and_demand,
    run_experiment,
)
from src.baselines.imported_actuated import (  # noqa: E402
    BASELINE_NOTICE,
    DEFAULT_COOLDOWN_SECONDS,
    build_environment_config,
)
from src.demand.scenarios import SCENARIOS  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402
from src.environment.multi_agent_environment import MultiAgentTrafficEnvironment  # noqa: E402
from src.evaluation.results_writer import DEFAULT_RESULTS_PATH  # noqa: E402


DEFAULT_SCENARIO_NAMES = ("low", "medium", "high")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse suite-level command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the imported actuated baseline across low, medium, and "
            "high synthetic Skopje demand scenarios and append results for "
            "each."
        )
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=tuple(SCENARIOS),
        default=list(DEFAULT_SCENARIO_NAMES),
        help="scenarios to run (default: low medium high)",
    )
    parser.add_argument(
        "--seed",
        type=nonnegative_integer,
        default=42,
        help="seed used for every scenario in this run (default: 42)",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=nonnegative_integer,
        default=int(DEFAULT_COOLDOWN_SECONDS),
    )
    parser.add_argument(
        "--report-interval",
        type=positive_integer,
        default=DEFAULT_REPORT_INTERVAL_SECONDS,
    )
    parser.add_argument("--gui", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help=f"results CSV path (default: {DEFAULT_RESULTS_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run every requested scenario sequentially with the same seed."""
    args = parse_args(argv)
    print(BASELINE_NOTICE)
    traci = load_traci()
    mode = "SUMO-GUI" if args.gui else "headless SUMO"

    run_count = 0
    failures: list[str] = []
    for scenario_name in args.scenarios:
        try:
            scenario, demand_seconds = _resolve_scenario_and_demand(
                scenario_name, None, args.seed
            )
        except FileNotFoundError as error:
            message = f"[SKIPPED] {scenario_name} seed={args.seed}: {error}"
            print(message, file=sys.stderr)
            failures.append(message)
            continue

        outputs = scenario_output_files(scenario.name, args.seed)
        print(
            f"\n=== {scenario.name} / seed={args.seed} ({mode}) "
            f"config={_project_relative(outputs.configuration_file)} ==="
        )
        try:
            config = build_environment_config(
                scenario=scenario.name,
                seed=args.seed,
                demand_seconds=float(demand_seconds),
                cooldown_seconds=float(args.cooldown_seconds),
                gui=args.gui,
            )
            environment = MultiAgentTrafficEnvironment(config, traci_connection=traci)
            metrics = run_experiment(
                traci=traci,
                environment=environment,
                scenario=scenario.name,
                seed=args.seed,
                demand_seconds=demand_seconds,
                cooldown_seconds=args.cooldown_seconds,
                output_path=args.output,
                report_interval=args.report_interval,
            )
            _print_final_summary(metrics)
            run_count += 1
        except Exception as error:  # noqa: BLE001
            message = f"[ERROR] {scenario.name} seed={args.seed} failed: {error}"
            print(message, file=sys.stderr)
            failures.append(message)

    print(f"\nCompleted {run_count} imported actuated run(s).")
    if failures:
        print(f"{len(failures)} run(s) failed or were skipped:", file=sys.stderr)
        for message in failures:
            print(f"  {message}", file=sys.stderr)
        return 1

    print(f"\n{BASELINE_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

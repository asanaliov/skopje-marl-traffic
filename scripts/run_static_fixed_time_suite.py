"""Run the static fixed-time baseline across low, medium, and high scenarios.

Calls the same in-process run_experiment() as
scripts/run_static_fixed_time_experiment.py for each requested scenario and
seed, so results are produced identically either way. This script exists so
the full validation suite required for this baseline can be run with one
command; see sumo/skopje/documentation/static_fixed_time_baseline.md.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_candidate_review import (  # noqa: E402
    find_sumo_executable,
    load_traci,
)
from scripts.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from scripts.run_static_fixed_time_experiment import (  # noqa: E402
    BASELINE_NOTICE,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_REPORT_INTERVAL_SECONDS,
    _print_final_summary,
    _project_relative,
    _resolve_demand_seconds,
    positive_float,
    run_experiment,
)
from src.baselines.static_fixed_time import DEFAULT_FIXED_GREEN_SECONDS  # noqa: E402
from src.demand.scenarios import SCENARIOS, get_scenario  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402
from src.evaluation.results_writer import DEFAULT_RESULTS_PATH  # noqa: E402


DEFAULT_SCENARIO_NAMES = ("low", "medium", "high")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse suite-level command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the static fixed-time baseline across low, medium, and high "
            "synthetic Skopje demand scenarios and append results for each."
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
        "--seeds",
        nargs="+",
        type=nonnegative_integer,
        default=[42],
        help="seeds to run for each scenario (default: 42)",
    )
    parser.add_argument(
        "--fixed-green-seconds",
        type=positive_float,
        default=DEFAULT_FIXED_GREEN_SECONDS,
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=nonnegative_integer,
        default=DEFAULT_COOLDOWN_SECONDS,
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run every requested (scenario, seed) pair sequentially."""
    args = parse_args(argv)
    print(BASELINE_NOTICE)
    executable = find_sumo_executable(args.gui)
    traci = load_traci()
    mode = "SUMO-GUI" if args.gui else "headless SUMO"

    run_count = 0
    failures: list[str] = []
    for scenario_name in args.scenarios:
        scenario = get_scenario(scenario_name)
        demand_seconds = _resolve_demand_seconds(scenario, None)
        for seed in args.seeds:
            outputs = scenario_output_files(scenario.name, seed)
            if not outputs.configuration_file.is_file():
                message = (
                    f"[SKIPPED] {scenario.name} seed={seed}: generated scenario "
                    f"configuration is missing: {outputs.configuration_file}. Run "
                    f"python scripts/generate_traffic_demand.py --scenario "
                    f"{scenario.name} --seed {seed} first."
                )
                print(message, file=sys.stderr)
                failures.append(message)
                continue

            print(
                f"\n=== {scenario.name} / seed={seed} ({mode}) "
                f"config={_project_relative(outputs.configuration_file)} ==="
            )
            try:
                metrics = run_experiment(
                    traci=traci,
                    executable=executable,
                    configuration_file=outputs.configuration_file,
                    scenario=scenario,
                    seed=seed,
                    fixed_green_seconds=args.fixed_green_seconds,
                    demand_seconds=demand_seconds,
                    cooldown_seconds=args.cooldown_seconds,
                    report_interval=args.report_interval,
                    output_path=args.output,
                )
                _print_final_summary(metrics)
                run_count += 1
            except Exception as error:  # noqa: BLE001
                message = f"[ERROR] {scenario.name} seed={seed} failed: {error}"
                print(message, file=sys.stderr)
                failures.append(message)

    print(f"\nCompleted {run_count} static fixed-time run(s).")
    if failures:
        print(f"{len(failures)} run(s) failed or were skipped:", file=sys.stderr)
        for message in failures:
            print(f"  {message}", file=sys.stderr)
        return 1

    print(f"\n{BASELINE_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

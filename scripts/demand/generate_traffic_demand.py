"""Generate reproducible synthetic passenger demand for Skopje scenarios."""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiments.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from src.config import (  # noqa: E402
    SKOPJE_CONFIG_DIR,
    SKOPJE_DEMAND_DIR,
    SKOPJE_DIR,
    resolve_sumo_xml_file,
)
from src.demand.network_routes import (  # noqa: E402
    RouteGenerationResult,
    generate_route_assignments,
    load_sumo_network,
)
from src.demand.scenarios import (  # noqa: E402
    SCENARIOS,
    TrafficDemandScenario,
    get_scenario,
)
from src.demand.xml_writer import (  # noqa: E402
    ScenarioOutputFiles,
    build_generation_metadata,
    calculate_route_length_statistics,
    normalize_duarouter_output,
    scenario_output_files,
    schedule_trips,
    write_generation_metadata,
    write_scenario_configuration,
    write_trips_file,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402


CANONICAL_DEMAND_ROOT = SKOPJE_DEMAND_DIR / "scenarios"
CANONICAL_CONFIG_ROOT = SKOPJE_CONFIG_DIR / "scenarios"


@dataclass(frozen=True, slots=True)
class GenerationSummary:
    """Generated files and diagnostics for one completed scenario."""

    scenario: TrafficDemandScenario
    outputs: ScenarioOutputFiles
    route_result: RouteGenerationResult
    duarouter_stdout: str
    duarouter_stderr: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse deterministic demand-generation arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate synthetic passenger demand for the selected Skopje corridor."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS),
        help="single scenario to generate",
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="generate low, medium, and high scenarios",
    )
    parser.add_argument(
        "--seed",
        type=nonnegative_integer,
        default=42,
        help="deterministic generation seed (default: 42)",
    )
    parser.add_argument(
        "--duration",
        type=positive_integer,
        help="override the canonical duration in seconds",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=CANONICAL_DEMAND_ROOT,
        help="root directory for generated demand scenarios",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing generated files",
    )
    return parser.parse_args(argv)


def find_duarouter_executable() -> Path:
    """Find duarouter on PATH or below SUMO_HOME."""
    executable_path = shutil.which("duarouter")
    if executable_path:
        return Path(executable_path)

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        for candidate in (
            Path(sumo_home) / "bin" / "duarouter",
            Path(sumo_home) / "bin" / "duarouter.exe",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "duarouter was not found on PATH or below SUMO_HOME. "
        "Install SUMO and expose its bin directory before generating demand."
    )


def _config_root_for_output(demand_root: Path) -> Path:
    """Use canonical configs for canonical demand and local configs otherwise."""
    if demand_root.resolve() == CANONICAL_DEMAND_ROOT.resolve():
        return CANONICAL_CONFIG_ROOT
    return demand_root / "config"


def _ensure_outputs_available(
    outputs: ScenarioOutputFiles,
    overwrite: bool,
) -> None:
    """Avoid accidentally replacing generated data without explicit permission."""
    existing_files = [
        path
        for path in (
            outputs.trips_file,
            outputs.route_file,
            outputs.configuration_file,
            outputs.metadata_file,
        )
        if path.exists()
    ]
    if existing_files and not overwrite:
        details = "\n".join(f"- {path}" for path in existing_files)
        raise FileExistsError(
            "Generated scenario files already exist. Use --overwrite to replace them:\n"
            f"{details}"
        )


def _run_duarouter(
    executable: Path,
    network_file: Path,
    trips_file: Path,
    raw_route_file: Path,
    seed: int,
) -> subprocess.CompletedProcess[str]:
    """Run duarouter safely and reject every reported routing failure."""
    command = [
        str(executable),
        "--net-file",
        str(network_file),
        "--route-files",
        str(trips_file),
        "--output-file",
        str(raw_route_file),
        "--seed",
        str(seed),
        "--ignore-errors",
        "false",
        "--repair",
        "false",
        "--write-metadata",
        "false",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "duarouter failed with exit code "
            f"{completed.returncode}.\nstdout:\n{completed.stdout.strip()}\n"
            f"stderr:\n{completed.stderr.strip()}"
        )
    if not raw_route_file.is_file():
        raise RuntimeError(
            f"duarouter exited successfully but did not create {raw_route_file}."
        )
    return completed


def _validate_duarouter_vehicle_count(route_file: Path, expected_count: int) -> None:
    """Confirm duarouter emitted exactly one vehicle per requested trip."""
    root = ET.parse(route_file).getroot()
    vehicle_count = len(root.findall("vehicle"))
    if vehicle_count != expected_count:
        raise RuntimeError(
            f"duarouter created {vehicle_count} vehicles, expected {expected_count}."
        )


def generate_scenario(
    scenario: TrafficDemandScenario,
    demand_root: Path,
    overwrite: bool,
    duarouter_executable: Path,
) -> GenerationSummary:
    """Generate, route, configure, and describe one synthetic scenario."""
    config_root = _config_root_for_output(demand_root)
    outputs = scenario_output_files(
        scenario.name,
        scenario.seed,
        demand_root=demand_root,
        config_root=config_root,
    )
    _ensure_outputs_available(outputs, overwrite)
    outputs.trips_file.parent.mkdir(parents=True, exist_ok=True)
    outputs.configuration_file.parent.mkdir(parents=True, exist_ok=True)

    network = load_sumo_network(SELECTED_CORRIDOR.network_file)
    rng = random.Random(scenario.seed)
    route_result = generate_route_assignments(network, scenario, rng)
    trips = schedule_trips(scenario, route_result.assignments, rng)

    with tempfile.TemporaryDirectory(
        prefix=".duarouter_",
        dir=outputs.trips_file.parent,
    ) as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        temporary_trips = temporary_directory / outputs.trips_file.name
        raw_route_file = temporary_directory / "raw.rou.xml"
        normalized_route_file = temporary_directory / outputs.route_file.name

        write_trips_file(temporary_trips, scenario, trips)
        completed = _run_duarouter(
            duarouter_executable,
            SELECTED_CORRIDOR.network_file,
            temporary_trips,
            raw_route_file,
            scenario.seed,
        )
        normalize_duarouter_output(raw_route_file, normalized_route_file)
        _validate_duarouter_vehicle_count(
            normalized_route_file,
            scenario.total_vehicle_count,
        )
        temporary_trips.replace(outputs.trips_file)
        normalized_route_file.replace(outputs.route_file)

    polygon_file = resolve_sumo_xml_file(
        SKOPJE_DIR / "polygons",
        "skopje_initial.poly.xml",
    )
    write_scenario_configuration(
        outputs.configuration_file,
        scenario,
        SELECTED_CORRIDOR.network_file,
        outputs.route_file,
        polygon_file=polygon_file,
    )
    metadata = build_generation_metadata(
        scenario,
        SELECTED_CORRIDOR,
        SELECTED_CORRIDOR.network_file,
        route_result.assignments,
        route_result.corridor_trip_count,
        route_result.background_trip_count,
    )
    write_generation_metadata(outputs.metadata_file, metadata)
    return GenerationSummary(
        scenario=scenario,
        outputs=outputs,
        route_result=route_result,
        duarouter_stdout=completed.stdout,
        duarouter_stderr=completed.stderr,
    )


def print_generation_summary(summary: GenerationSummary) -> None:
    """Print the required deterministic-generation diagnostics."""
    scenario = summary.scenario
    result = summary.route_result
    statistics = calculate_route_length_statistics(result.assignments)
    generated_count = len(result.assignments)
    corridor_percentage = 100.0 * result.corridor_trip_count / generated_count

    print(f"\nSynthetic traffic-demand generation summary: {scenario.name}")
    print(f"  Seed: {scenario.seed}")
    print(f"  Duration: {scenario.duration_seconds} s")
    print(f"  Requested vehicle count: {scenario.total_vehicle_count}")
    print(f"  Generated vehicle count: {generated_count}")
    print(f"  Corridor trips: {result.corridor_trip_count}")
    print(f"  Background trips: {result.background_trip_count}")
    print(f"  Corridor trip percentage: {corridor_percentage:.2f}%")
    print(
        "  Planned route length: "
        f"minimum={statistics.minimum_m:.2f} m, "
        f"mean={statistics.mean_m:.2f} m, "
        f"maximum={statistics.maximum_m:.2f} m"
    )
    distribution = ", ".join(
        f"{crossings} agents={count} trips"
        for crossings, count in result.crossing_distribution.items()
    )
    print(f"  Selected-agent crossing distribution: {distribution}")
    print(f"  Rejected pair attempts: {result.rejected_pair_attempts}")
    print(f"  Trips file: {summary.outputs.trips_file}")
    print(f"  Route file: {summary.outputs.route_file}")
    print(f"  Configuration file: {summary.outputs.configuration_file}")
    print(f"  Metadata file: {summary.outputs.metadata_file}")
    print("  duarouter result: success (exit code 0)")
    if summary.duarouter_stdout.strip():
        print(f"  duarouter stdout: {summary.duarouter_stdout.strip()}")
    if summary.duarouter_stderr.strip():
        print(f"  duarouter stderr: {summary.duarouter_stderr.strip()}")


def main(argv: Sequence[str] | None = None) -> int:
    """Generate one or all requested traffic-demand scenarios."""
    args = parse_args(argv)
    try:
        duarouter = find_duarouter_executable()
        scenario_names = tuple(SCENARIOS) if args.all else (args.scenario,)
        for scenario_name in scenario_names:
            canonical = get_scenario(scenario_name)
            scenario = replace(
                canonical,
                seed=args.seed,
                duration_seconds=args.duration or canonical.duration_seconds,
            )
            summary = generate_scenario(
                scenario,
                args.output_root.resolve(),
                args.overwrite,
                duarouter,
            )
            print_generation_summary(summary)
        print(
            "\nThese scenarios contain synthetic experimental demand, not official "
            "or measured Skopje traffic data."
        )
        return 0
    except Exception as error:
        print(f"[ERROR] Traffic-demand generation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Statically and dynamically validate generated synthetic traffic demand."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.network_inspection.run_candidate_review import (  # noqa: E402
    find_sumo_executable,
    load_traci,
)
from scripts.experiments.run_skopje_simulation import positive_integer  # noqa: E402
from scripts.experiments.run_traffic_scenario import (  # noqa: E402
    TrafficScenarioRunResult,
    run_scenario,
)
from src.demand.network_routes import (  # noqa: E402
    build_edge_to_agents,
    calculate_route_length,
    calculate_trip_split,
    load_selected_incoming_edges,
    load_sumo_network,
    passenger_compatible_edges,
    selected_agents_crossed,
)
from src.demand.scenarios import SCENARIOS, TrafficDemandScenario, get_scenario  # noqa: E402
from src.demand.xml_writer import (  # noqa: E402
    SYNTHETIC_DEMAND_STATEMENT,
    ScenarioOutputFiles,
    scenario_output_files,
    sha256_file,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402


DEFAULT_VALIDATION_SECONDS = 600


@dataclass(frozen=True, slots=True)
class StaticValidationResult:
    """Validated generated-route facts for one scenario."""

    vehicle_count: int
    corridor_trip_count: int
    background_trip_count: int
    corridor_percentage: float
    minimum_route_length_m: float
    mean_route_length_m: float
    maximum_route_length_m: float
    crossing_distribution: Mapping[int, int]
    selected_agent_route_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ScenarioValidationResult:
    """Static and headless validation outcomes for one scenario."""

    scenario: TrafficDemandScenario
    static: StaticValidationResult
    runtime: TrafficScenarioRunResult
    warnings: tuple[str, ...]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse static and headless validation options."""
    parser = argparse.ArgumentParser(
        description="Validate generated synthetic Skopje traffic-demand scenarios."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scenario", choices=tuple(SCENARIOS))
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=DEFAULT_VALIDATION_SECONDS,
    )
    return parser.parse_args(argv)


def _require_file(path: Path, description: str) -> None:
    """Raise a readable error when one generated file is unavailable."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing {description}: {path}")


def _validate_trip_file(
    scenario: TrafficDemandScenario,
    trips_file: Path,
) -> None:
    """Validate generated trip count, endpoints, IDs, and departure order."""
    root = ET.parse(trips_file).getroot()
    if root.tag != "routes":
        raise ValueError(f"Trips XML root must be <routes>: {trips_file}")
    vehicle_types = root.findall("vType")
    if len(vehicle_types) != 1:
        raise ValueError(
            f"Trips file must define exactly one vehicle type: {trips_file}"
        )
    if vehicle_types[0].get("vClass") != "passenger":
        raise ValueError(
            f"Trips vehicle type must use vClass='passenger': {trips_file}"
        )

    trips = root.findall("trip")
    if len(trips) != scenario.total_vehicle_count:
        raise ValueError(
            f"Trips file contains {len(trips)} trips, expected "
            f"{scenario.total_vehicle_count}: {trips_file}"
        )
    vehicle_ids = [trip.get("id", "") for trip in trips]
    if any(not vehicle_id for vehicle_id in vehicle_ids):
        raise ValueError(f"Trips file contains an empty vehicle ID: {trips_file}")
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise ValueError(f"Trips file contains duplicate vehicle IDs: {trips_file}")
    departures = [float(trip.get("depart", "nan")) for trip in trips]
    if departures != sorted(departures):
        raise ValueError(f"Trip departures are not sorted: {trips_file}")
    for trip in trips:
        origin = trip.get("from", "")
        destination = trip.get("to", "")
        if not origin or not destination:
            raise ValueError(f"Trip has an empty origin or destination: {trips_file}")
        if origin == destination:
            raise ValueError(
                f"Trip {trip.get('id')} has identical origin and destination {origin}."
            )
        if trip.get("departLane") != "best" or trip.get("departSpeed") != "max":
            raise ValueError(
                f"Trip {trip.get('id')} must use departLane='best' and "
                "departSpeed='max'."
            )


def _validate_route_file(
    scenario: TrafficDemandScenario,
    route_file: Path,
    network: Any,
) -> StaticValidationResult:
    """Validate every routed vehicle against the real passenger network."""
    root = ET.parse(route_file).getroot()
    if root.tag != "routes":
        raise ValueError(f"Route XML root must be <routes>: {route_file}")
    vehicles = root.findall("vehicle")
    if len(vehicles) != scenario.total_vehicle_count:
        raise ValueError(
            f"Route file contains {len(vehicles)} vehicles, expected "
            f"{scenario.total_vehicle_count}: {route_file}"
        )

    edges_by_id = {
        str(edge.getID()): edge for edge in passenger_compatible_edges(network)
    }
    edge_to_agents = build_edge_to_agents(load_selected_incoming_edges())
    corridor_count = 0
    route_lengths: list[float] = []
    crossing_distribution: Counter[int] = Counter()
    selected_agent_counts: Counter[str] = Counter()

    for vehicle in vehicles:
        route_element = vehicle.find("route")
        if route_element is None:
            raise ValueError(f"Vehicle {vehicle.get('id')} has no route element.")
        edge_ids = tuple(route_element.get("edges", "").split())
        if not edge_ids:
            raise ValueError(f"Vehicle {vehicle.get('id')} has an empty route.")
        if edge_ids[0] == edge_ids[-1]:
            raise ValueError(
                f"Vehicle {vehicle.get('id')} has identical route endpoints "
                f"{edge_ids[0]}."
            )
        unknown_edges = [edge_id for edge_id in edge_ids if edge_id not in edges_by_id]
        if unknown_edges:
            raise ValueError(
                f"Vehicle {vehicle.get('id')} uses missing, internal, or "
                f"passenger-incompatible edges: {', '.join(unknown_edges)}."
            )
        route_length = calculate_route_length(
            tuple(edges_by_id[edge_id] for edge_id in edge_ids)
        )
        if route_length < scenario.minimum_route_length_m:
            raise ValueError(
                f"Vehicle {vehicle.get('id')} route is {route_length:.2f} m, below "
                f"the required {scenario.minimum_route_length_m:.2f} m."
            )
        route_lengths.append(route_length)
        crossed_agents = selected_agents_crossed(edge_ids, edge_to_agents)
        crossing_count = len(crossed_agents)
        crossing_distribution[crossing_count] += 1
        selected_agent_counts.update(crossed_agents)
        if crossing_count >= scenario.minimum_selected_agents_crossed:
            corridor_count += 1

    corridor_percentage = corridor_count / len(vehicles)
    if abs(corridor_percentage - scenario.corridor_trip_share) > 0.01:
        raise ValueError(
            f"Scenario {scenario.name} corridor share is "
            f"{corridor_percentage:.2%}, expected approximately "
            f"{scenario.corridor_trip_share:.2%}."
        )
    return StaticValidationResult(
        vehicle_count=len(vehicles),
        corridor_trip_count=corridor_count,
        background_trip_count=len(vehicles) - corridor_count,
        corridor_percentage=corridor_percentage,
        minimum_route_length_m=min(route_lengths),
        mean_route_length_m=sum(route_lengths) / len(route_lengths),
        maximum_route_length_m=max(route_lengths),
        crossing_distribution=dict(sorted(crossing_distribution.items())),
        selected_agent_route_counts={
            agent_id: selected_agent_counts[agent_id]
            for agent_id in SELECTED_CORRIDOR.agent_ids
        },
    )


def _is_absolute_reference(value: str) -> bool:
    """Recognize POSIX and Windows absolute paths on every host platform."""
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _resolve_config_reference(configuration_file: Path, value: str) -> Path:
    """Resolve one required relative SUMO configuration reference."""
    if not value or "," in value:
        raise ValueError(
            f"Expected one configuration path in {configuration_file}, got {value!r}."
        )
    if _is_absolute_reference(value):
        raise ValueError(
            f"Scenario configuration path must be relative, got {value!r}."
        )
    path = (configuration_file.parent / value).resolve()
    if not path.is_file():
        raise FileNotFoundError(
            f"Scenario configuration references a missing file: {path}"
        )
    return path


def _validate_configuration(
    scenario: TrafficDemandScenario,
    outputs: ScenarioOutputFiles,
) -> None:
    """Validate relative network, route, polygon, view, and timing references."""
    root = ET.parse(outputs.configuration_file).getroot()
    network_element = root.find("input/net-file")
    route_element = root.find("input/route-files")
    if network_element is None or route_element is None:
        raise ValueError(
            f"Scenario configuration is missing network or route input: "
            f"{outputs.configuration_file}"
        )
    network_file = _resolve_config_reference(
        outputs.configuration_file,
        network_element.get("value", ""),
    )
    route_file = _resolve_config_reference(
        outputs.configuration_file,
        route_element.get("value", ""),
    )
    if network_file != SELECTED_CORRIDOR.network_file.resolve():
        raise ValueError(
            "Scenario configuration does not use the unchanged Skopje network."
        )
    if route_file != outputs.route_file.resolve():
        raise ValueError(
            "Scenario configuration does not reference its generated route file."
        )
    if any(
        route_file == original.resolve() for original in SELECTED_CORRIDOR.route_files
    ):
        raise ValueError("Scenario configuration must not mix original wizard demand.")

    additional_element = root.find("input/additional-files")
    if additional_element is not None:
        _resolve_config_reference(
            outputs.configuration_file,
            additional_element.get("value", ""),
        )
    view_element = root.find("gui_only/gui-settings-file")
    if view_element is not None:
        _resolve_config_reference(
            outputs.configuration_file,
            view_element.get("value", ""),
        )
    end_element = root.find("time/end")
    if (
        end_element is None
        or int(end_element.get("value", "-1")) != scenario.duration_seconds
    ):
        raise ValueError(
            f"Scenario configuration end time must be {scenario.duration_seconds} s."
        )
    ignore_errors = root.find("processing/ignore-route-errors")
    if ignore_errors is None or ignore_errors.get("value") != "false":
        raise ValueError("Scenario configuration must not ignore route errors.")


def _validate_metadata(
    scenario: TrafficDemandScenario,
    outputs: ScenarioOutputFiles,
    static_result: StaticValidationResult,
) -> None:
    """Validate required metadata fields and source-network identity."""
    metadata = json.loads(outputs.metadata_file.read_text(encoding="utf-8"))
    required_keys = {
        "background_trip_count",
        "corridor_trip_count",
        "duration_seconds",
        "generated_at_utc",
        "generated_vehicle_count",
        "generator_version",
        "network_file",
        "requested_vehicle_count",
        "route_length_m",
        "scenario",
        "seed",
        "selected_agent_crossing_distribution",
        "selected_agent_ids",
        "source_network_sha256",
        "synthetic_demand_notice",
    }
    missing_keys = required_keys - set(metadata)
    if missing_keys:
        raise ValueError(
            f"Metadata is missing keys: {', '.join(sorted(missing_keys))}."
        )
    if metadata["scenario"] != scenario.name or metadata["seed"] != scenario.seed:
        raise ValueError("Metadata scenario name or seed does not match the request.")
    if metadata["requested_vehicle_count"] != scenario.total_vehicle_count:
        raise ValueError("Metadata requested vehicle count is incorrect.")
    if metadata["generated_vehicle_count"] != static_result.vehicle_count:
        raise ValueError("Metadata generated vehicle count is incorrect.")
    expected_corridor_count, expected_background_count = calculate_trip_split(
        scenario.total_vehicle_count,
        scenario.corridor_trip_share,
    )
    if metadata["corridor_trip_count"] != expected_corridor_count:
        raise ValueError("Metadata planned corridor trip count is incorrect.")
    if metadata["background_trip_count"] != expected_background_count:
        raise ValueError("Metadata planned background trip count is incorrect.")
    if tuple(metadata["selected_agent_ids"]) != SELECTED_CORRIDOR.agent_ids:
        raise ValueError(
            "Metadata selected-agent IDs do not match the official corridor."
        )
    if metadata["source_network_sha256"] != sha256_file(SELECTED_CORRIDOR.network_file):
        raise ValueError("Metadata network checksum does not match the source network.")
    if "synthetic" not in metadata["synthetic_demand_notice"].lower():
        raise ValueError("Metadata must clearly identify the demand as synthetic.")


def validate_static_scenario(
    scenario: TrafficDemandScenario,
    outputs: ScenarioOutputFiles,
    network: Any,
) -> StaticValidationResult:
    """Run all file, XML, route, configuration, and metadata checks."""
    _require_file(outputs.trips_file, "trips file")
    _require_file(outputs.route_file, "route file")
    _require_file(outputs.configuration_file, "scenario configuration")
    _require_file(outputs.metadata_file, "generation metadata")
    _validate_trip_file(scenario, outputs.trips_file)
    static_result = _validate_route_file(scenario, outputs.route_file, network)
    _validate_configuration(scenario, outputs)
    _validate_metadata(scenario, outputs, static_result)
    return static_result


def _behavioral_warnings(
    scenario: TrafficDemandScenario,
    runtime: TrafficScenarioRunResult,
) -> tuple[str, ...]:
    """Report calibration observations without fragile exact queue thresholds."""
    warnings: list[str] = []
    zero_traffic_agents = [
        agent_id
        for agent_id, observation in runtime.agent_observations.items()
        if not observation.received_traffic
    ]
    if zero_traffic_agents:
        warnings.append(
            "Selected agents with zero observed traffic: "
            f"{', '.join(zero_traffic_agents)}."
        )
    if runtime.departed_vehicles and runtime.arrived_vehicles == 0:
        warnings.append("No departed vehicle completed a route during validation.")
    if runtime.teleport_count:
        warnings.append(
            f"SUMO reported {runtime.teleport_count} starting teleports during validation."
        )
    if scenario.name == "low" and any(
        observation.maximum_queue > 10
        for observation in runtime.agent_observations.values()
    ):
        warnings.append("Low demand produced a selected queue above 10 vehicles.")
    return tuple(warnings)


def _print_result(result: ScenarioValidationResult) -> None:
    """Print static facts, runtime statistics, coverage, and warnings."""
    static = result.static
    runtime = result.runtime
    print(f"\nSynthetic demand validation: {result.scenario.name}")
    print(f"  Vehicles: {static.vehicle_count}")
    print(
        f"  Corridor/background: {static.corridor_trip_count}/"
        f"{static.background_trip_count} ({static.corridor_percentage:.2%} corridor)"
    )
    print(
        "  Routed length: "
        f"minimum={static.minimum_route_length_m:.2f} m, "
        f"mean={static.mean_route_length_m:.2f} m, "
        f"maximum={static.maximum_route_length_m:.2f} m"
    )
    distribution = ", ".join(
        f"{count} agents={vehicles} vehicles"
        for count, vehicles in static.crossing_distribution.items()
    )
    print(f"  Selected-agent crossing distribution: {distribution}")
    print(f"  Departed vehicles: {runtime.departed_vehicles}")
    print(f"  Arrived vehicles: {runtime.arrived_vehicles}")
    print(f"  Active vehicles: {runtime.active_vehicles}")
    print(f"  Teleport count: {runtime.teleport_count}")
    print("  Route errors: 0")
    print(f"  Final network halting count: {runtime.final_network_halting_count}")
    print("  Selected-agent queue observations and coverage:")
    for agent_id, observation in runtime.agent_observations.items():
        print(
            f"    {agent_id}: reached="
            f"{'yes' if observation.received_traffic else 'no'}, "
            f"mean_queue={observation.mean_queue:.2f}, "
            f"maximum_queue={observation.maximum_queue}, "
            f"samples={observation.sample_count}, "
            f"generated_routes={static.selected_agent_route_counts[agent_id]}"
        )
    zero_traffic_agents = [
        agent_id
        for agent_id, observation in runtime.agent_observations.items()
        if not observation.received_traffic
    ]
    print(
        "  Selected agents with zero observed traffic: "
        f"{', '.join(zero_traffic_agents) if zero_traffic_agents else 'none'}"
    )
    for warning in result.warnings:
        print(f"  [WARNING] {warning}")


def _cross_scenario_warnings(
    results: Sequence[ScenarioValidationResult],
) -> tuple[str, ...]:
    """Compare behavioral load ordering without treating queue noise as invalid XML."""
    if len(results) != len(SCENARIOS):
        return ()
    by_name = {result.scenario.name: result for result in results}
    warnings: list[str] = []
    departed = [by_name[name].runtime.departed_vehicles for name in SCENARIOS]
    if not departed[0] < departed[1] < departed[2]:
        warnings.append(
            "Departed vehicle counts did not increase strictly from low to medium to high."
        )
    congestion_scores = {
        name: sum(
            observation.maximum_queue
            for observation in by_name[name].runtime.agent_observations.values()
        )
        for name in SCENARIOS
    }
    if congestion_scores["high"] <= congestion_scores["medium"]:
        warnings.append(
            "High demand did not produce a larger selected maximum-queue score "
            "than medium during this validation window."
        )
    return tuple(warnings)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one or all canonical generated scenarios."""
    args = parse_args(argv)
    try:
        if args.seed < 0:
            raise ValueError("Seed must be zero or greater.")
        names = tuple(SCENARIOS) if args.all else (args.scenario,)
        if args.all:
            counts = [SCENARIOS[name].total_vehicle_count for name in SCENARIOS]
            if not counts[0] < counts[1] < counts[2]:
                raise ValueError(
                    "Canonical vehicle counts must satisfy low < medium < high."
                )

        network = load_sumo_network(SELECTED_CORRIDOR.network_file)
        executable = find_sumo_executable(False)
        traci = load_traci()
        results: list[ScenarioValidationResult] = []
        print(SYNTHETIC_DEMAND_STATEMENT)
        for name in names:
            canonical = get_scenario(name)
            scenario = TrafficDemandScenario(
                name=canonical.name,
                duration_seconds=canonical.duration_seconds,
                total_vehicle_count=canonical.total_vehicle_count,
                corridor_trip_share=canonical.corridor_trip_share,
                minimum_selected_agents_crossed=(
                    canonical.minimum_selected_agents_crossed
                ),
                minimum_route_length_m=canonical.minimum_route_length_m,
                seed=args.seed,
                vehicle_type=canonical.vehicle_type,
            )
            outputs = scenario_output_files(name, args.seed)
            static_result = validate_static_scenario(scenario, outputs, network)
            runtime_result = run_scenario(
                traci,
                executable,
                outputs.configuration_file,
                SELECTED_CORRIDOR,
                args.seconds,
                args.seed,
                60,
                print_reports=False,
            )
            if runtime_result.completed_seconds < args.seconds:
                raise RuntimeError(
                    f"Scenario {name} stopped at {runtime_result.completed_seconds:.0f} s, "
                    f"before the requested {args.seconds} s."
                )
            if runtime_result.teleport_count > max(
                10, runtime_result.departed_vehicles // 10
            ):
                raise RuntimeError(
                    f"Scenario {name} produced an excessive "
                    f"{runtime_result.teleport_count} teleports."
                )
            result = ScenarioValidationResult(
                scenario=scenario,
                static=static_result,
                runtime=runtime_result,
                warnings=_behavioral_warnings(scenario, runtime_result),
            )
            results.append(result)
            _print_result(result)

        for warning in _cross_scenario_warnings(results):
            print(f"\n[WARNING] {warning}")
        print("\nAll required static and SUMO validations completed successfully.")
        print(SYNTHETIC_DEMAND_STATEMENT)
        return 0
    except Exception as error:
        print(f"[ERROR] Traffic-demand validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Stable XML and metadata writers for synthetic Skopje demand scenarios."""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import Any

from src.config import (
    PROJECT_ROOT,
    SKOPJE_CONFIG_DIR,
    SKOPJE_DEMAND_DIR,
    SKOPJE_INITIAL_VIEW_FILE,
)
from src.demand.network_routes import RouteAssignment
from src.demand.scenarios import TrafficDemandScenario
from src.environment.selected_corridor import SelectedCorridor


GENERATOR_VERSION = "1.0"
SYNTHETIC_DEMAND_STATEMENT = (
    "Synthetic experimental demand; not official or measured Skopje traffic data."
)
_XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"


@dataclass(frozen=True, slots=True)
class ScheduledTrip:
    """One route assignment with a deterministic ID and departure time."""

    vehicle_id: str
    departure_time: float
    assignment: RouteAssignment


@dataclass(frozen=True, slots=True)
class ScenarioOutputFiles:
    """Canonical output locations for one named scenario and seed."""

    trips_file: Path
    route_file: Path
    configuration_file: Path
    metadata_file: Path


@dataclass(frozen=True, slots=True)
class RouteLengthStatistics:
    """Minimum, arithmetic mean, and maximum planned route lengths."""

    minimum_m: float
    mean_m: float
    maximum_m: float


def scenario_output_files(
    scenario_name: str,
    seed: int,
    demand_root: Path = SKOPJE_DEMAND_DIR / "scenarios",
    config_root: Path = SKOPJE_CONFIG_DIR / "scenarios",
) -> ScenarioOutputFiles:
    """Return stable scenario paths without creating any files."""
    scenario_directory = demand_root / scenario_name
    return ScenarioOutputFiles(
        trips_file=scenario_directory / f"seed_{seed}.trips.xml",
        route_file=scenario_directory / f"seed_{seed}.rou.xml",
        configuration_file=config_root / f"{scenario_name}_seed_{seed}.sumocfg",
        metadata_file=scenario_directory / f"seed_{seed}.metadata.json",
    )


def schedule_trips(
    scenario: TrafficDemandScenario,
    assignments: Sequence[RouteAssignment],
    rng: Random,
) -> tuple[ScheduledTrip, ...]:
    """Mix route classes and assign stable, evenly distributed departures."""
    if len(assignments) != scenario.total_vehicle_count:
        raise ValueError(
            f"Scenario {scenario.name} requires {scenario.total_vehicle_count} routes, "
            f"got {len(assignments)}."
        )

    shuffled_assignments = list(assignments)
    rng.shuffle(shuffled_assignments)
    scheduled: list[ScheduledTrip] = []
    for index, assignment in enumerate(shuffled_assignments):
        departure_time = (
            (index + rng.random())
            * scenario.duration_seconds
            / scenario.total_vehicle_count
        )
        scheduled.append(
            ScheduledTrip(
                vehicle_id=f"{scenario.name}_{index:06d}",
                departure_time=departure_time,
                assignment=assignment,
            )
        )
    return tuple(scheduled)


def _format_decimal(value: float, precision: int = 3) -> str:
    """Format a float without unstable trailing zeros."""
    return f"{value:.{precision}f}".rstrip("0").rstrip(".")


def _write_xml_tree(root: ET.Element, output_file: Path) -> None:
    """Write one indented UTF-8 XML document with deterministic line endings."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    with output_file.open("w", encoding="utf-8", newline="\n") as xml_file:
        tree.write(xml_file, encoding="unicode", xml_declaration=True)


def write_trips_file(
    output_file: Path,
    scenario: TrafficDemandScenario,
    trips: Sequence[ScheduledTrip],
) -> None:
    """Write passenger trips in chronological deterministic order."""
    if len(trips) != scenario.total_vehicle_count:
        raise ValueError(
            f"Cannot write {scenario.name}: expected {scenario.total_vehicle_count} "
            f"trips, got {len(trips)}."
        )
    departure_times = [trip.departure_time for trip in trips]
    if departure_times != sorted(departure_times):
        raise ValueError("Scheduled trips must be sorted by departure time.")
    vehicle_ids = [trip.vehicle_id for trip in trips]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise ValueError("Scheduled trip vehicle IDs must be unique.")

    root = ET.Element(
        "routes",
        {
            "xmlns:xsi": _XSI_NAMESPACE,
            "xsi:noNamespaceSchemaLocation": ("http://sumo.dlr.de/xsd/routes_file.xsd"),
        },
    )
    ET.SubElement(
        root,
        "vType",
        {
            "id": scenario.vehicle_type,
            "vClass": "passenger",
        },
    )
    for trip in trips:
        route = trip.assignment.route
        attributes = {
            "id": trip.vehicle_id,
            "type": scenario.vehicle_type,
            "depart": _format_decimal(trip.departure_time),
            "from": route.origin_edge_id,
            "to": route.destination_edge_id,
            "departLane": "best",
            "departSpeed": "max",
        }
        intermediate_edges = route.edge_ids[1:-1]
        if intermediate_edges:
            attributes["via"] = " ".join(intermediate_edges)
        ET.SubElement(
            root,
            "trip",
            attributes,
        )
    _write_xml_tree(root, output_file)


def normalize_duarouter_output(source_file: Path, output_file: Path) -> None:
    """Remove timestamp comments and rewrite duarouter XML stably."""
    try:
        root = ET.parse(source_file).getroot()
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"duarouter output file is missing: {source_file}"
        ) from error
    except ET.ParseError as error:
        raise ValueError(
            f"duarouter produced invalid XML: {source_file}: {error}"
        ) from error
    if root.tag != "routes":
        raise ValueError(f"duarouter output root must be <routes>, got <{root.tag}>.")
    _write_xml_tree(root, output_file)


def _relative_reference(configuration_file: Path, target_file: Path) -> str:
    """Create a forward-slash relative path for a SUMO configuration."""
    relative = os.path.relpath(
        target_file.resolve(), configuration_file.parent.resolve()
    )
    return relative.replace("\\", "/")


def write_scenario_configuration(
    output_file: Path,
    scenario: TrafficDemandScenario,
    network_file: Path,
    route_file: Path,
    polygon_file: Path | None = None,
    view_file: Path | None = SKOPJE_INITIAL_VIEW_FILE,
) -> None:
    """Write a scenario config that uses only generated passenger demand."""
    if not network_file.is_file():
        raise FileNotFoundError(f"Scenario network file is missing: {network_file}")
    if not route_file.is_file():
        raise FileNotFoundError(f"Generated route file is missing: {route_file}")

    root = ET.Element(
        "sumoConfiguration",
        {
            "xmlns:xsi": _XSI_NAMESPACE,
            "xsi:noNamespaceSchemaLocation": (
                "http://sumo.dlr.de/xsd/sumoConfiguration.xsd"
            ),
        },
    )
    input_element = ET.SubElement(root, "input")
    ET.SubElement(
        input_element,
        "net-file",
        {"value": _relative_reference(output_file, network_file)},
    )
    ET.SubElement(
        input_element,
        "route-files",
        {"value": _relative_reference(output_file, route_file)},
    )
    if polygon_file is not None and polygon_file.is_file():
        ET.SubElement(
            input_element,
            "additional-files",
            {"value": _relative_reference(output_file, polygon_file)},
        )

    time_element = ET.SubElement(root, "time")
    ET.SubElement(time_element, "end", {"value": str(scenario.duration_seconds)})

    processing = ET.SubElement(root, "processing")
    ET.SubElement(processing, "ignore-route-errors", {"value": "false"})
    ET.SubElement(processing, "tls.actuated.jam-threshold", {"value": "30"})

    routing = ET.SubElement(root, "routing")
    ET.SubElement(routing, "device.rerouting.adaptation-steps", {"value": "18"})
    ET.SubElement(routing, "device.rerouting.adaptation-interval", {"value": "10"})

    report = ET.SubElement(root, "report")
    ET.SubElement(report, "verbose", {"value": "true"})
    ET.SubElement(report, "duration-log.statistics", {"value": "true"})
    ET.SubElement(report, "no-step-log", {"value": "true"})

    if view_file is not None and view_file.is_file():
        gui_only = ET.SubElement(root, "gui_only")
        ET.SubElement(
            gui_only,
            "gui-settings-file",
            {"value": _relative_reference(output_file, view_file)},
        )
    _write_xml_tree(root, output_file)


def calculate_route_length_statistics(
    assignments: Sequence[RouteAssignment],
) -> RouteLengthStatistics:
    """Calculate stable planned-route length summary values."""
    if not assignments:
        raise ValueError("At least one route assignment is required for statistics.")
    lengths = [assignment.route.length_m for assignment in assignments]
    return RouteLengthStatistics(
        minimum_m=min(lengths),
        mean_m=sum(lengths) / len(lengths),
        maximum_m=max(lengths),
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 checksum for one source file."""
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_generation_metadata(
    scenario: TrafficDemandScenario,
    corridor: SelectedCorridor,
    network_file: Path,
    assignments: Sequence[RouteAssignment],
    corridor_trip_count: int,
    background_trip_count: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build generation metadata with an explicitly non-deterministic timestamp."""
    timestamp = generated_at or datetime.now(UTC)
    statistics = calculate_route_length_statistics(assignments)
    crossing_distribution = Counter(
        len(assignment.route.selected_agents_crossed) for assignment in assignments
    )
    try:
        network_reference = network_file.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        network_reference = network_file.resolve().as_posix()

    return {
        "background_trip_count": background_trip_count,
        "corridor_trip_count": corridor_trip_count,
        "duration_seconds": scenario.duration_seconds,
        "generated_at_utc": timestamp.astimezone(UTC).isoformat(),
        "generated_vehicle_count": len(assignments),
        "generator_version": GENERATOR_VERSION,
        "network_file": network_reference,
        "requested_vehicle_count": scenario.total_vehicle_count,
        "route_length_m": {
            "maximum": round(statistics.maximum_m, 2),
            "mean": round(statistics.mean_m, 2),
            "minimum": round(statistics.minimum_m, 2),
        },
        "scenario": scenario.name,
        "seed": scenario.seed,
        "selected_agent_crossing_distribution": {
            str(count): value for count, value in sorted(crossing_distribution.items())
        },
        "selected_agent_ids": list(corridor.agent_ids),
        "source_network_sha256": sha256_file(network_file),
        "synthetic_demand_notice": SYNTHETIC_DEMAND_STATEMENT,
    }


def write_generation_metadata(output_file: Path, metadata: Mapping[str, Any]) -> None:
    """Write stable, human-readable JSON metadata with sorted keys."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "GENERATOR_VERSION",
    "SYNTHETIC_DEMAND_STATEMENT",
    "RouteLengthStatistics",
    "ScenarioOutputFiles",
    "ScheduledTrip",
    "build_generation_metadata",
    "calculate_route_length_statistics",
    "normalize_duarouter_output",
    "scenario_output_files",
    "schedule_trips",
    "sha256_file",
    "write_generation_metadata",
    "write_scenario_configuration",
    "write_trips_file",
]

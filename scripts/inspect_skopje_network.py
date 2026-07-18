"""Inspect the organized Skopje SUMO network without starting a simulation."""

from __future__ import annotations

import argparse
import csv
import gzip
import importlib
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (  # noqa: E402
    SKOPJE_DIR,
    SKOPJE_INITIAL_CONFIG,
    resolve_sumo_xml_file,
)


POLYGON_FILE = resolve_sumo_xml_file(
    SKOPJE_DIR / "polygons",
    "skopje_initial.poly.xml",
)
PUBLIC_TRANSPORT_ROUTE_FILE = (
    SKOPJE_DIR / "demand" / "skopje_initial.rou.xml"
).resolve()
TRAFFIC_LIGHTS_FILE = (SKOPJE_DIR / "documentation" / "traffic_lights.csv").resolve()
NETWORK_SUMMARY_FILE = (SKOPJE_DIR / "documentation" / "network_summary.md").resolve()


@dataclass(frozen=True, slots=True)
class TrafficLightRecord:
    """Facts about one SUMO traffic-light controller."""

    traffic_light_id: str
    node_ids: tuple[str, ...]
    controlled_lane_count: int
    controlled_link_count: int
    road_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NetworkStats:
    """Summary values extracted from a SUMO network."""

    node_count: int
    edge_count: int
    lane_count: int
    passenger_edge_count: int
    controlled_junction_count: int
    boundary: tuple[float, float, float, float]
    geographic_boundary: tuple[float, float, float, float] | None
    edge_types: tuple[tuple[str, int], ...]
    traffic_lights: tuple[TrafficLightRecord, ...]
    lane_count_distribution: tuple[tuple[int, int], ...] = ()
    speed_limit_distribution: tuple[tuple[float, int], ...] = ()
    named_edge_count: int = 0
    unnamed_edge_count: int = 0
    traffic_light_components: tuple[tuple[str, ...], ...] = ()
    zero_neighbor_traffic_light_ids: tuple[str, ...] = ()


def _load_sumolib() -> ModuleType:
    """Import sumolib from Python or SUMO_HOME with a useful failure message."""
    try:
        return importlib.import_module("sumolib")
    except ImportError as initial_error:
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            tools_directory = Path(sumo_home) / "tools"
            if tools_directory.is_dir() and str(tools_directory) not in sys.path:
                sys.path.insert(0, str(tools_directory))
                try:
                    return importlib.import_module("sumolib")
                except ImportError:
                    pass

        raise RuntimeError(
            "Could not import sumolib. Activate the project environment and "
            "install requirements.txt, or set SUMO_HOME to the SUMO installation."
        ) from initial_error


def _open_network_xml(network_file: Path) -> BinaryIO:
    """Open compressed or uncompressed network XML as a binary stream."""
    if network_file.suffix == ".gz":
        return gzip.open(network_file, "rb")
    return network_file.open("rb")


def read_geographic_boundary(
    network_file: Path,
) -> tuple[float, float, float, float] | None:
    """Read the original longitude and latitude boundary from network XML."""
    with _open_network_xml(network_file) as network_xml:
        for _, element in ET.iterparse(network_xml, events=("start",)):
            if element.tag.rsplit("}", maxsplit=1)[-1] != "location":
                continue

            boundary_text = element.get("origBoundary")
            if not boundary_text:
                return None

            try:
                values = tuple(float(value) for value in boundary_text.split(","))
            except ValueError:
                return None

            if len(values) != 4:
                return None
            return values
    return None


def _traffic_light_records(network: Any) -> tuple[TrafficLightRecord, ...]:
    """Extract deterministic controller inventory records from sumolib."""
    records: list[TrafficLightRecord] = []

    for traffic_light in sorted(
        network.getTrafficLights(),
        key=lambda controller: controller.getID(),
    ):
        connections = traffic_light.getConnections()
        incoming_lanes = {connection[0].getID() for connection in connections}
        node_ids = {
            connection[0].getEdge().getToNode().getID() for connection in connections
        }
        road_names = {
            edge.getName().strip()
            for connection in connections
            for edge in (connection[0].getEdge(), connection[1].getEdge())
            if edge.getName().strip()
        }

        records.append(
            TrafficLightRecord(
                traffic_light_id=traffic_light.getID(),
                node_ids=tuple(sorted(node_ids)),
                controlled_lane_count=len(incoming_lanes),
                controlled_link_count=len(connections),
                road_names=tuple(sorted(road_names)),
            )
        )

    return tuple(records)


def inspect_network(network_file: Path) -> NetworkStats:
    """Load a network with sumolib and return its key structural statistics."""
    if not network_file.is_file():
        raise FileNotFoundError(
            f"Skopje network file is missing: {network_file}\n"
            "Restore the organized scenario under sumo/skopje/network."
        )

    sumolib = _load_sumolib()
    network = sumolib.net.readNet(str(network_file), withPrograms=True)
    nodes = tuple(network.getNodes())
    edges = tuple(network.getEdges())
    traffic_lights = _traffic_light_records(network)
    edge_type_counts = Counter(edge.getType() or "(unspecified)" for edge in edges)
    lane_count_distribution = Counter(len(edge.getLanes()) for edge in edges)
    speed_limit_distribution = Counter(
        round(float(edge.getSpeed()), 2) for edge in edges
    )
    named_edge_count = sum(bool(edge.getName().strip()) for edge in edges)
    controlled_node_ids = {
        node_id
        for traffic_light in traffic_lights
        for node_id in traffic_light.node_ids
    }
    boundary = tuple(float(value) for value in network.getBoundary())

    from scripts.audit_traffic_lights import (
        build_agent_adjacency,
        collect_controller_audits,
        connected_components,
        detect_neighbor_relationships,
    )

    controller_audits = collect_controller_audits(network)
    neighbor_relationships = detect_neighbor_relationships(
        network,
        controller_audits,
    )
    adjacency = build_agent_adjacency(
        controller_audits,
        neighbor_relationships,
    )
    components = connected_components(adjacency)
    audits_by_agent = {audit.agent_id: audit for audit in controller_audits}

    return NetworkStats(
        node_count=len(nodes),
        edge_count=len(edges),
        lane_count=sum(len(edge.getLanes()) for edge in edges),
        passenger_edge_count=sum(edge.allows("passenger") for edge in edges),
        controlled_junction_count=len(controlled_node_ids),
        boundary=boundary,
        geographic_boundary=read_geographic_boundary(network_file),
        edge_types=tuple(sorted(edge_type_counts.items())),
        traffic_lights=traffic_lights,
        lane_count_distribution=tuple(sorted(lane_count_distribution.items())),
        speed_limit_distribution=tuple(sorted(speed_limit_distribution.items())),
        named_edge_count=named_edge_count,
        unnamed_edge_count=len(edges) - named_edge_count,
        traffic_light_components=tuple(
            tuple(audits_by_agent[agent_id].traffic_light_id for agent_id in component)
            for component in components
        ),
        zero_neighbor_traffic_light_ids=tuple(
            audit.traffic_light_id
            for audit in controller_audits
            if not adjacency[audit.agent_id]
        ),
    )


def _project_path(path: Path) -> str:
    """Return a readable project-relative path when possible."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def print_summary(network_file: Path, stats: NetworkStats) -> None:
    """Print a concise human-readable network summary."""
    min_x, min_y, max_x, max_y = stats.boundary
    print("Skopje SUMO network summary")
    print(f"Network file: {_project_path(network_file)}")
    print(f"Nodes: {stats.node_count}")
    print(f"Edges: {stats.edge_count}")
    print(f"Lanes: {stats.lane_count}")
    print(f"Passenger-compatible edges: {stats.passenger_edge_count}")
    print(f"Traffic-light controllers: {len(stats.traffic_lights)}")
    print(f"Traffic-light-controlled junctions: {stats.controlled_junction_count}")
    print(
        "Network boundary (x_min, y_min, x_max, y_max): "
        f"{min_x:.2f}, {min_y:.2f}, {max_x:.2f}, {max_y:.2f}"
    )

    if stats.geographic_boundary is not None:
        min_lon, min_lat, max_lon, max_lat = stats.geographic_boundary
        print(
            "Geographic boundary (lon_min, lat_min, lon_max, lat_max): "
            f"{min_lon:.8f}, {min_lat:.8f}, {max_lon:.8f}, {max_lat:.8f}"
        )

    print("Edge type distribution:")
    for edge_type, count in stats.edge_types:
        print(f"  - {edge_type}: {count}")

    print("Lane-count distribution (lanes per edge):")
    for lane_count, edge_count in stats.lane_count_distribution:
        print(f"  - {lane_count}: {edge_count}")

    print("Speed-limit distribution (m/s per edge):")
    for speed_limit, edge_count in stats.speed_limit_distribution:
        print(f"  - {speed_limit:.2f}: {edge_count}")

    print(f"Named edges: {stats.named_edge_count}")
    print(f"Unnamed edges: {stats.unnamed_edge_count}")

    print("Traffic-light connected components:")
    for component_number, component in enumerate(
        stats.traffic_light_components,
        start=1,
    ):
        print(
            f"  - Component {component_number} ({len(component)}): "
            f"{', '.join(component)}"
        )

    print("Traffic-light controllers with zero detected neighbors:")
    if stats.zero_neighbor_traffic_light_ids:
        for traffic_light_id in stats.zero_neighbor_traffic_light_ids:
            print(f"  - {traffic_light_id}")
    else:
        print("  - None")

    print("Traffic-light IDs:")
    if not stats.traffic_lights:
        print("  - None detected")
    for traffic_light in stats.traffic_lights:
        print(f"  - {traffic_light.traffic_light_id}")


def write_traffic_light_inventory(
    output_file: Path,
    traffic_lights: tuple[TrafficLightRecord, ...],
) -> None:
    """Write one CSV row per real network traffic-light controller."""
    fieldnames = (
        "agent_id",
        "traffic_light_id",
        "node_count",
        "controlled_lane_count",
        "controlled_link_count",
        "neighbor_ids",
        "enabled",
        "notes",
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for agent_number, traffic_light in enumerate(traffic_lights, start=1):
            notes = ""
            if traffic_light.road_names:
                notes = f"Controlled roads: {', '.join(traffic_light.road_names)}"

            writer.writerow(
                {
                    "agent_id": f"A{agent_number}",
                    "traffic_light_id": traffic_light.traffic_light_id,
                    "node_count": len(traffic_light.node_ids),
                    "controlled_lane_count": traffic_light.controlled_lane_count,
                    "controlled_link_count": traffic_light.controlled_link_count,
                    "neighbor_ids": "",
                    "enabled": "true",
                    "notes": notes,
                }
            )


def render_network_summary(
    stats: NetworkStats,
    network_file: Path,
    route_file: Path,
    polygon_file: Path | None,
) -> str:
    """Render reproducible Markdown documentation for the inspected network."""
    polygons_exist = polygon_file is not None and polygon_file.is_file()
    lines = [
        "# Skopje initial network summary",
        "",
        "## Files",
        "",
        f"- Network file used: `{_project_path(network_file)}`.",
        f"- Passenger route input used: `{_project_path(route_file)}`.",
        (
            "- Public-transport route file used: "
            f"`{_project_path(PUBLIC_TRANSPORT_ROUTE_FILE)}`."
        ),
        f"- Polygons exist: {'yes' if polygons_exist else 'no'}.",
        "- The current passenger traffic demand is synthetic.",
        "",
        "## Network statistics",
        "",
        f"- Nodes: {stats.node_count}.",
        f"- Edges: {stats.edge_count}.",
        f"- Lanes: {stats.lane_count}.",
        f"- Traffic-light controllers: {len(stats.traffic_lights)}.",
        f"- Traffic-light-controlled junctions: {stats.controlled_junction_count}.",
        f"- Passenger-compatible edges: {stats.passenger_edge_count}.",
        "",
        "## Traffic-light IDs",
        "",
    ]

    if stats.traffic_lights:
        lines.extend(
            f"- `{traffic_light.traffic_light_id}`"
            for traffic_light in stats.traffic_lights
        )
    else:
        lines.append("- No traffic-light controllers were detected.")

    lines.extend(
        [
            "",
            "## Known limitations",
            "",
            "- OpenStreetMap imports may need manual corrections.",
            "- Traffic-light programs may have been inferred by SUMO during import.",
            "- Synthetic traffic is not real traffic-count data for Skopje.",
            "- Some small roads may need removal from the experiment network.",
            "- Some major intersections need manual inspection in netedit.",
            (
                "- The wizard error log reports missing controlling detectors for "
                "some actuated links and one bus stop that is too short."
            ),
            "",
            "## Next cleanup tasks",
            "",
            "- Inspect major signalized intersections and their phases in netedit.",
            "- Identify small or irrelevant roads that can be removed safely.",
            "- Check inferred signal programs against intersection geometry.",
            "- Define a reduced network before demand modeling and baseline work.",
            "",
        ]
    )
    return "\n".join(lines)


def write_network_summary(
    output_file: Path,
    stats: NetworkStats,
    network_file: Path,
    route_file: Path,
    polygon_file: Path | None,
) -> None:
    """Write the Markdown network summary to disk."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        render_network_summary(stats, network_file, route_file, polygon_file),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    """Parse inspection command-line options."""
    parser = argparse.ArgumentParser(
        description="Inspect the organized Skopje SUMO network."
    )
    parser.add_argument(
        "--write-documentation",
        action="store_true",
        help="regenerate traffic_lights.csv and network_summary.md",
    )
    return parser.parse_args()


def main() -> int:
    """Inspect the network, print statistics, and optionally refresh documentation."""
    args = parse_args()
    try:
        SKOPJE_INITIAL_CONFIG.validate_files()
        stats = inspect_network(SKOPJE_INITIAL_CONFIG.net_file)
        print_summary(SKOPJE_INITIAL_CONFIG.net_file, stats)

        if args.write_documentation:
            write_traffic_light_inventory(TRAFFIC_LIGHTS_FILE, stats.traffic_lights)
            write_network_summary(
                NETWORK_SUMMARY_FILE,
                stats,
                SKOPJE_INITIAL_CONFIG.net_file,
                SKOPJE_INITIAL_CONFIG.route_file,
                POLYGON_FILE,
            )
            print(f"Documentation written to: {_project_path(TRAFFIC_LIGHTS_FILE)}")
            print(f"Documentation written to: {_project_path(NETWORK_SUMMARY_FILE)}")
        return 0
    except Exception as error:
        print(
            f"[ERROR] Network inspection failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

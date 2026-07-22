"""Passenger-compatible route selection on the real Skopje SUMO network."""

from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from random import Random
from types import MappingProxyType
from typing import Any

import sumolib

from src.config import SKOPJE_DIR
from src.demand.scenarios import TrafficDemandScenario
from src.environment.selected_corridor import SELECTED_CORRIDOR, SelectedCorridor


TRAFFIC_LIGHT_AUDIT_FILE = SKOPJE_DIR / "documentation" / "traffic_light_audit.csv"
_BOUNDARY_ZONE_NAMES = ("west", "east", "south", "north")
_BOUNDARY_FRACTION = 0.32


class RouteSelectionError(ValueError):
    """Raised when an origin and destination cannot form a valid demand route."""


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """One validated passenger route between two non-internal network edges."""

    origin_edge_id: str
    destination_edge_id: str
    edge_ids: tuple[str, ...]
    length_m: float
    selected_agents_crossed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteAssignment:
    """A route classified as corridor-focused or wider-network background."""

    route: RouteCandidate
    is_corridor_trip: bool


@dataclass(frozen=True, slots=True)
class RouteGenerationResult:
    """All generated route assignments and bounded-retry diagnostics."""

    assignments: tuple[RouteAssignment, ...]
    corridor_trip_count: int
    background_trip_count: int
    rejected_pair_attempts: int

    @property
    def crossing_distribution(self) -> Mapping[int, int]:
        """Count generated trips by number of selected agents crossed."""
        counts = Counter(
            len(assignment.route.selected_agents_crossed)
            for assignment in self.assignments
        )
        return MappingProxyType(dict(sorted(counts.items())))


def calculate_trip_split(
    total_vehicle_count: int, corridor_share: float
) -> tuple[int, int]:
    """Return deterministic corridor and background vehicle counts."""
    if total_vehicle_count <= 0:
        raise ValueError("total_vehicle_count must be greater than zero.")
    if not 0.0 <= corridor_share <= 1.0:
        raise ValueError("corridor_share must be between 0 and 1.")
    corridor_count = int(total_vehicle_count * corridor_share + 0.5)
    return corridor_count, total_vehicle_count - corridor_count


def load_sumo_network(network_file: Path = SELECTED_CORRIDOR.network_file) -> Any:
    """Load the actual SUMO network through sumolib with a helpful failure."""
    if not network_file.is_file():
        raise FileNotFoundError(f"Skopje SUMO network is missing: {network_file}")
    try:
        return sumolib.net.readNet(str(network_file))
    except Exception as error:
        raise RuntimeError(
            f"Could not load SUMO network {network_file}: {error}"
        ) from error


def is_passenger_compatible_edge(edge: Any) -> bool:
    """Return whether an edge is non-internal and allows passenger vehicles."""
    edge_id = str(edge.getID())
    is_special = bool(edge.isSpecial()) if hasattr(edge, "isSpecial") else False
    return (
        not edge_id.startswith(":")
        and not is_special
        and bool(edge.allows("passenger"))
    )


def passenger_compatible_edges(network: Any) -> tuple[Any, ...]:
    """Return all usable network edges in stable ID order."""
    return tuple(
        sorted(
            (edge for edge in network.getEdges() if is_passenger_compatible_edge(edge)),
            key=lambda edge: edge.getID(),
        )
    )


def load_selected_incoming_edges(
    corridor: SelectedCorridor = SELECTED_CORRIDOR,
    audit_file: Path = TRAFFIC_LIGHT_AUDIT_FILE,
) -> Mapping[str, tuple[str, ...]]:
    """Load selected controlled incoming edges from the existing audit CSV."""
    required_columns = {"agent_id", "incoming_edges"}
    if not audit_file.is_file():
        raise FileNotFoundError(f"Traffic-light audit CSV is missing: {audit_file}")

    selected_agents = set(corridor.agent_ids)
    incoming_edges: dict[str, tuple[str, ...]] = {}
    with audit_file.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = required_columns - set(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Traffic-light audit CSV is missing columns: {missing}")
        for row in reader:
            agent_id = row["agent_id"].strip()
            if agent_id not in selected_agents:
                continue
            edge_ids = tuple(
                edge_id.strip()
                for edge_id in row["incoming_edges"].split(";")
                if edge_id.strip()
            )
            if not edge_ids:
                raise ValueError(
                    f"Selected agent {agent_id} has no audited incoming edges."
                )
            incoming_edges[agent_id] = edge_ids

    missing_agents = [
        agent_id for agent_id in corridor.agent_ids if agent_id not in incoming_edges
    ]
    if missing_agents:
        raise ValueError(
            "Selected agents are missing incoming-edge audit data: "
            f"{', '.join(missing_agents)}."
        )
    return MappingProxyType(
        {agent_id: incoming_edges[agent_id] for agent_id in corridor.agent_ids}
    )


def build_edge_to_agents(
    incoming_edges_by_agent: Mapping[str, Sequence[str]],
) -> Mapping[str, tuple[str, ...]]:
    """Invert audited selected-agent incoming edges in deterministic order."""
    edge_to_agents: dict[str, list[str]] = {}
    for agent_id, edge_ids in incoming_edges_by_agent.items():
        for edge_id in edge_ids:
            edge_to_agents.setdefault(edge_id, []).append(agent_id)
    return MappingProxyType(
        {edge_id: tuple(agent_ids) for edge_id, agent_ids in edge_to_agents.items()}
    )


def selected_agents_crossed(
    route_edge_ids: Sequence[str],
    edge_to_agents: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    """Return selected agents in first-crossed route order without duplicates."""
    crossed: list[str] = []
    seen: set[str] = set()
    for edge_id in route_edge_ids:
        for agent_id in edge_to_agents.get(edge_id, ()):
            if agent_id not in seen:
                crossed.append(agent_id)
                seen.add(agent_id)
    return tuple(crossed)


def calculate_route_length(route_edges: Sequence[Any]) -> float:
    """Return route length as the sum of its real SUMO edge lengths."""
    return sum(float(edge.getLength()) for edge in route_edges)


def _validate_endpoint(edge: Any, endpoint_name: str) -> None:
    """Reject an internal or passenger-incompatible route endpoint."""
    if not is_passenger_compatible_edge(edge):
        raise RouteSelectionError(
            f"{endpoint_name} edge {edge.getID()} is internal or does not allow "
            "passenger vehicles."
        )


def find_valid_shortest_route(
    network: Any,
    origin_edge: Any,
    destination_edge: Any,
    minimum_route_length_m: float,
    minimum_selected_agents_crossed: int,
    edge_to_agents: Mapping[str, Sequence[str]],
) -> RouteCandidate:
    """Find and validate a shortest passenger route for one edge pair."""
    _validate_endpoint(origin_edge, "Origin")
    _validate_endpoint(destination_edge, "Destination")
    origin_id = str(origin_edge.getID())
    destination_id = str(destination_edge.getID())
    if origin_id == destination_id:
        raise RouteSelectionError(
            f"Origin and destination edges must differ, got {origin_id}."
        )

    route_edges, _ = network.getShortestPath(
        origin_edge,
        destination_edge,
        vClass="passenger",
        withInternal=False,
    )
    if not route_edges:
        raise RouteSelectionError(
            f"No passenger route connects {origin_id} to {destination_id}."
        )
    if any(not is_passenger_compatible_edge(edge) for edge in route_edges):
        raise RouteSelectionError(
            f"Route from {origin_id} to {destination_id} contains an invalid edge."
        )

    edge_ids = tuple(str(edge.getID()) for edge in route_edges)
    length_m = calculate_route_length(route_edges)
    if not math.isfinite(length_m) or length_m < minimum_route_length_m:
        raise RouteSelectionError(
            f"Route from {origin_id} to {destination_id} is {length_m:.2f} m, "
            f"below the required {minimum_route_length_m:.2f} m."
        )

    crossed_agents = selected_agents_crossed(edge_ids, edge_to_agents)
    if len(crossed_agents) < minimum_selected_agents_crossed:
        raise RouteSelectionError(
            f"Route from {origin_id} to {destination_id} crosses "
            f"{len(crossed_agents)} selected agents, below the required "
            f"{minimum_selected_agents_crossed}."
        )
    return RouteCandidate(
        origin_edge_id=origin_id,
        destination_edge_id=destination_id,
        edge_ids=edge_ids,
        length_m=length_m,
        selected_agents_crossed=crossed_agents,
    )


def _edge_midpoint(edge: Any) -> tuple[float, float]:
    """Return a stable representative coordinate for an edge."""
    shape = tuple(edge.getShape())
    if not shape:
        from_x, from_y = edge.getFromNode().getCoord()
        to_x, to_y = edge.getToNode().getCoord()
        return (float(from_x + to_x) / 2.0, float(from_y + to_y) / 2.0)
    return (
        sum(float(point[0]) for point in shape) / len(shape),
        sum(float(point[1]) for point in shape) / len(shape),
    )


def boundary_edges_by_zone(
    network: Any,
    edges: Sequence[Any],
    excluded_edge_ids: set[str] | frozenset[str] = frozenset(),
) -> Mapping[str, tuple[Any, ...]]:
    """Group outer-network passenger edges into four geographic boundary zones."""
    minimum_x, minimum_y, maximum_x, maximum_y = map(float, network.getBoundary())
    width = maximum_x - minimum_x
    height = maximum_y - minimum_y
    if width <= 0 or height <= 0:
        raise ValueError("SUMO network boundary must have positive width and height.")

    zones: dict[str, list[Any]] = {name: [] for name in _BOUNDARY_ZONE_NAMES}
    for edge in edges:
        if edge.getID() in excluded_edge_ids:
            continue
        x, y = _edge_midpoint(edge)
        normalized_distances = {
            "west": (x - minimum_x) / width,
            "east": (maximum_x - x) / width,
            "south": (y - minimum_y) / height,
            "north": (maximum_y - y) / height,
        }
        zone_name = min(
            _BOUNDARY_ZONE_NAMES,
            key=lambda name: (
                normalized_distances[name],
                _BOUNDARY_ZONE_NAMES.index(name),
            ),
        )
        if normalized_distances[zone_name] <= _BOUNDARY_FRACTION:
            zones[zone_name].append(edge)

    empty_zones = [
        zone_name for zone_name, zone_edges in zones.items() if not zone_edges
    ]
    if empty_zones:
        raise RouteSelectionError(
            "Could not identify passenger boundary edges for zones: "
            f"{', '.join(empty_zones)}."
        )
    return MappingProxyType(
        {
            zone_name: tuple(sorted(zone_edges, key=lambda edge: edge.getID()))
            for zone_name, zone_edges in zones.items()
        }
    )


def _crossing_occurs_inside_route(
    route: RouteCandidate,
    edge_to_agents: Mapping[str, Sequence[str]],
) -> bool:
    """Check that a corridor route begins before and ends after selected edges."""
    crossing_positions = [
        index
        for index, edge_id in enumerate(route.edge_ids)
        if edge_to_agents.get(edge_id)
    ]
    return bool(
        crossing_positions
        and crossing_positions[0] > 0
        and crossing_positions[-1] < len(route.edge_ids) - 1
    )


def _generate_corridor_assignments(
    network: Any,
    scenario: TrafficDemandScenario,
    rng: Random,
    boundary_edges: Mapping[str, Sequence[Any]],
    edge_to_agents: Mapping[str, Sequence[str]],
    required_count: int,
    used_pairs: set[tuple[str, str]],
    maximum_attempts: int,
) -> tuple[list[RouteAssignment], int]:
    """Generate diverse boundary-to-boundary routes through selected agents."""
    zone_pairs = [
        (source_zone, target_zone)
        for source_zone in _BOUNDARY_ZONE_NAMES
        for target_zone in _BOUNDARY_ZONE_NAMES
        if source_zone != target_zone
    ]
    rng.shuffle(zone_pairs)
    assignments: list[RouteAssignment] = []
    rejected_attempts = 0
    attempts = 0

    while len(assignments) < required_count and attempts < maximum_attempts:
        source_zone, target_zone = zone_pairs[attempts % len(zone_pairs)]
        attempts += 1
        origin_edge = rng.choice(boundary_edges[source_zone])
        destination_edge = rng.choice(boundary_edges[target_zone])
        pair = (str(origin_edge.getID()), str(destination_edge.getID()))
        if pair in used_pairs:
            rejected_attempts += 1
            continue
        try:
            route = find_valid_shortest_route(
                network,
                origin_edge,
                destination_edge,
                scenario.minimum_route_length_m,
                scenario.minimum_selected_agents_crossed,
                edge_to_agents,
            )
        except RouteSelectionError:
            rejected_attempts += 1
            continue
        if not _crossing_occurs_inside_route(route, edge_to_agents):
            rejected_attempts += 1
            continue
        used_pairs.add(pair)
        assignments.append(RouteAssignment(route=route, is_corridor_trip=True))

    if len(assignments) != required_count:
        raise RouteSelectionError(
            f"Generated {len(assignments)} of {required_count} required corridor "
            f"routes after {attempts} bounded attempts."
        )
    return assignments, rejected_attempts


def _generate_background_assignments(
    network: Any,
    scenario: TrafficDemandScenario,
    rng: Random,
    passenger_edges: Sequence[Any],
    edge_to_agents: Mapping[str, Sequence[str]],
    required_count: int,
    used_pairs: set[tuple[str, str]],
    maximum_attempts: int,
) -> tuple[list[RouteAssignment], int]:
    """Generate valid wider-network routes below the corridor classification."""
    assignments: list[RouteAssignment] = []
    rejected_attempts = 0
    attempts = 0
    while len(assignments) < required_count and attempts < maximum_attempts:
        attempts += 1
        origin_edge = rng.choice(passenger_edges)
        destination_edge = rng.choice(passenger_edges)
        pair = (str(origin_edge.getID()), str(destination_edge.getID()))
        if pair in used_pairs:
            rejected_attempts += 1
            continue
        try:
            route = find_valid_shortest_route(
                network,
                origin_edge,
                destination_edge,
                scenario.minimum_route_length_m,
                0,
                edge_to_agents,
            )
        except RouteSelectionError:
            rejected_attempts += 1
            continue
        if (
            len(route.selected_agents_crossed)
            >= scenario.minimum_selected_agents_crossed
        ):
            rejected_attempts += 1
            continue
        used_pairs.add(pair)
        assignments.append(RouteAssignment(route=route, is_corridor_trip=False))

    if len(assignments) != required_count:
        raise RouteSelectionError(
            f"Generated {len(assignments)} of {required_count} required background "
            f"routes after {attempts} bounded attempts."
        )
    return assignments, rejected_attempts


def generate_route_assignments(
    network: Any,
    scenario: TrafficDemandScenario,
    rng: Random,
    incoming_edges_by_agent: Mapping[str, Sequence[str]] | None = None,
) -> RouteGenerationResult:
    """Generate the requested deterministic corridor and background route split."""
    passenger_edges = passenger_compatible_edges(network)
    if not passenger_edges:
        raise RouteSelectionError(
            "The SUMO network contains no non-internal passenger-compatible edges."
        )

    incoming_edges = incoming_edges_by_agent or load_selected_incoming_edges()
    edge_to_agents = build_edge_to_agents(incoming_edges)
    network_edge_ids = {str(edge.getID()) for edge in passenger_edges}
    unknown_controlled_edges = sorted(set(edge_to_agents) - network_edge_ids)
    if unknown_controlled_edges:
        raise RouteSelectionError(
            "Selected controlled incoming edges are missing or passenger-incompatible: "
            f"{', '.join(unknown_controlled_edges)}."
        )

    boundary_edges = boundary_edges_by_zone(
        network,
        passenger_edges,
        frozenset(edge_to_agents),
    )
    corridor_count, background_count = calculate_trip_split(
        scenario.total_vehicle_count,
        scenario.corridor_trip_share,
    )
    used_pairs: set[tuple[str, str]] = set()
    corridor_assignments, corridor_rejections = _generate_corridor_assignments(
        network,
        scenario,
        rng,
        boundary_edges,
        edge_to_agents,
        corridor_count,
        used_pairs,
        max(corridor_count * 40, 5000),
    )
    background_assignments, background_rejections = _generate_background_assignments(
        network,
        scenario,
        rng,
        passenger_edges,
        edge_to_agents,
        background_count,
        used_pairs,
        max(background_count * 40, 5000),
    )
    assignments = (*corridor_assignments, *background_assignments)
    if len(assignments) != scenario.total_vehicle_count:
        raise RouteSelectionError(
            f"Generated {len(assignments)} routes for {scenario.total_vehicle_count} "
            "requested vehicles."
        )
    return RouteGenerationResult(
        assignments=assignments,
        corridor_trip_count=corridor_count,
        background_trip_count=background_count,
        rejected_pair_attempts=corridor_rejections + background_rejections,
    )


__all__ = [
    "RouteAssignment",
    "RouteCandidate",
    "RouteGenerationResult",
    "RouteSelectionError",
    "boundary_edges_by_zone",
    "build_edge_to_agents",
    "calculate_route_length",
    "calculate_trip_split",
    "find_valid_shortest_route",
    "generate_route_assignments",
    "is_passenger_compatible_edge",
    "load_selected_incoming_edges",
    "load_sumo_network",
    "passenger_compatible_edges",
    "selected_agents_crossed",
]

"""Audit Skopje traffic-light controllers and their network relationships."""

from __future__ import annotations

import csv
import heapq
import importlib
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SKOPJE_DIR, SKOPJE_INITIAL_CONFIG  # noqa: E402


AUDIT_FILE = SKOPJE_DIR / "documentation" / "traffic_light_audit.csv"
NEIGHBORS_FILE = SKOPJE_DIR / "documentation" / "traffic_light_neighbors.csv"
CANDIDATES_FILE = SKOPJE_DIR / "documentation" / "corridor_candidates.md"
WIZARD_WARNING_FILE = (
    SKOPJE_DIR / "source" / "wizard_initial" / "trips.trips.xml.errorlog"
)

MAX_NEIGHBOR_DISTANCE_M = 1500.0
COMPLEX_PHASE_COUNT = 10
SHORT_EDGE_LENGTH_M = 5.0
TARGET_CANDIDATE_SIZE = 8
MAX_CANDIDATES = 3

AUDIT_COLUMNS = (
    "agent_id",
    "traffic_light_id",
    "junction_node_ids",
    "x",
    "y",
    "road_names",
    "incoming_edges",
    "outgoing_edges",
    "controlled_lane_count",
    "controlled_link_count",
    "phase_count",
    "phase_durations",
    "neighbor_ids",
    "neighbor_distances",
    "enabled",
    "warnings",
    "notes",
)

NEIGHBOR_COLUMNS = (
    "source_agent_id",
    "source_traffic_light_id",
    "target_agent_id",
    "target_traffic_light_id",
    "network_distance_m",
    "direct_corridor",
    "bidirectional",
    "notes",
)


@dataclass(frozen=True, slots=True)
class PhaseProgramAudit:
    """Phase data from one deterministic SUMO signal program."""

    program_id: str
    program_type: str
    durations: tuple[float, ...]
    states: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ControllerAudit:
    """Computed facts for one SUMO traffic-light controller."""

    agent_id: str
    traffic_light_id: str
    junction_node_ids: tuple[str, ...]
    x: float
    y: float
    road_names: tuple[str, ...]
    incoming_edge_ids: tuple[str, ...]
    outgoing_edge_ids: tuple[str, ...]
    controlled_lane_count: int
    controlled_link_count: int
    program_id: str
    program_type: str
    phase_durations: tuple[float, ...]
    phase_states: tuple[str, ...]
    edge_lane_counts: tuple[tuple[str, int], ...]
    edge_speed_limits: tuple[tuple[str, float], ...]
    warnings: tuple[str, ...]

    @property
    def phase_count(self) -> int:
        """Return the number of phases in the audited program."""
        return len(self.phase_states)

    @property
    def max_edge_lane_count(self) -> int:
        """Return the largest controlled-edge lane count."""
        return max((count for _, count in self.edge_lane_counts), default=0)

    @property
    def max_edge_speed(self) -> float:
        """Return the largest controlled-edge speed limit in meters per second."""
        return max((speed for _, speed in self.edge_speed_limits), default=0.0)


@dataclass(frozen=True, slots=True)
class NeighborRelationship:
    """One directed controller-to-controller network relationship."""

    source_agent_id: str
    source_traffic_light_id: str
    target_agent_id: str
    target_traffic_light_id: str
    network_distance_m: float
    direct_corridor: bool
    bidirectional: bool
    path_edge_ids: tuple[str, ...]
    corridor_road_name: str


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    """One connected controller subset recommended for manual review."""

    name: str
    agent_ids: tuple[str, ...]
    traffic_light_ids: tuple[str, ...]
    direct_corridor_links: int
    mean_neighbor_distance_m: float
    max_edge_lane_count: int
    max_edge_speed: float
    road_names: tuple[str, ...]


def load_sumolib() -> ModuleType:
    """Import sumolib from Python or SUMO_HOME with a useful error."""
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


def agent_sort_key(agent_id: str) -> tuple[int, str]:
    """Sort conventional A-number identifiers numerically and other IDs last."""
    if agent_id.startswith("A") and agent_id[1:].isdigit():
        return int(agent_id[1:]), agent_id
    return sys.maxsize, agent_id


def extract_phase_program(programs: Mapping[str, Any]) -> PhaseProgramAudit:
    """Extract the first program by stable program ID ordering."""
    if not programs:
        return PhaseProgramAudit("", "", (), ())

    program_id = sorted(programs)[0]
    program = programs[program_id]
    phases = tuple(program.getPhases())
    return PhaseProgramAudit(
        program_id=program_id,
        program_type=str(program.getType()),
        durations=tuple(float(phase.duration) for phase in phases),
        states=tuple(str(phase.state) for phase in phases),
    )


def available_road_names(edges: Iterable[Any]) -> tuple[str, ...]:
    """Return only non-empty road names that exist in the SUMO network."""
    names = {
        str(edge.getName()).strip() for edge in edges if str(edge.getName()).strip()
    }
    return tuple(sorted(names))


def read_wizard_controller_warnings(warning_file: Path) -> dict[str, tuple[str, ...]]:
    """Map wizard warnings to controllers when a controller ID is explicit."""
    if not warning_file.is_file():
        return {}

    warning_pattern = re.compile(r"At actuated tlLogic '([^']+)'")
    warnings: dict[str, list[str]] = {}
    for line in warning_file.read_text(encoding="utf-8").splitlines():
        match = warning_pattern.search(line)
        if match:
            warnings.setdefault(match.group(1), []).append(
                "Wizard reported actuated links without a controlling detector."
            )

    return {
        traffic_light_id: tuple(dict.fromkeys(controller_warnings))
        for traffic_light_id, controller_warnings in warnings.items()
    }


def _controller_warnings(
    traffic_light_id: str,
    junction_node_ids: tuple[str, ...],
    controlled_edges: Sequence[Any],
    connections: Sequence[Any],
    programs: Mapping[str, Any],
    phase_program: PhaseProgramAudit,
    external_warnings: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Identify structural or unusual conditions without changing the network."""
    warnings: list[str] = list(external_warnings.get(traffic_light_id, ()))

    if not connections:
        warnings.append("Controller has no controlled links.")
    if not phase_program.states:
        warnings.append("Controller has no signal phases.")
    if len(programs) > 1:
        warnings.append(
            f"Controller has {len(programs)} programs; the audit reports the first ID."
        )
    if len(phase_program.states) > COMPLEX_PHASE_COUNT:
        warnings.append(
            f"Complex phase program with {len(phase_program.states)} phases."
        )
    if phase_program.states and not any(
        "y" in state.lower() for state in phase_program.states
    ):
        warnings.append("Signal program has no yellow state.")
    if any(duration <= 0 for duration in phase_program.durations):
        warnings.append("Signal program contains a non-positive phase duration.")

    if connections and phase_program.states:
        expected_state_length = (
            max(int(connection[2]) for connection in connections) + 1
        )
        observed_lengths = {len(state) for state in phase_program.states}
        if observed_lengths != {expected_state_length}:
            warnings.append(
                "Phase state length does not match the highest controlled link index."
            )

    if len(junction_node_ids) > 1:
        warnings.append(
            f"Controller spans {len(junction_node_ids)} controlled junction nodes."
        )
    if controlled_edges and not available_road_names(controlled_edges):
        warnings.append("Controlled edges have no road names in the network.")

    short_edges = sorted(
        edge.getID()
        for edge in controlled_edges
        if float(edge.getLength()) < SHORT_EDGE_LENGTH_M
    )
    if short_edges:
        warnings.append(
            "Controlled edge shorter than "
            f"{SHORT_EDGE_LENGTH_M:.0f} m: {', '.join(short_edges)}."
        )

    return tuple(dict.fromkeys(warnings))


def collect_controller_audits(
    network: Any,
    external_warnings: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[ControllerAudit, ...]:
    """Collect stable, typed facts for all network traffic-light controllers."""
    warning_map = external_warnings or {}
    audits: list[ControllerAudit] = []
    traffic_lights = sorted(
        network.getTrafficLights(),
        key=lambda controller: controller.getID(),
    )

    for agent_number, traffic_light in enumerate(traffic_lights, start=1):
        connections = tuple(traffic_light.getConnections())
        incoming_edges = {
            connection[0].getEdge().getID(): connection[0].getEdge()
            for connection in connections
        }
        outgoing_edges = {
            connection[1].getEdge().getID(): connection[1].getEdge()
            for connection in connections
        }
        controlled_edges = {
            **incoming_edges,
            **outgoing_edges,
        }
        junction_nodes = {
            connection[0].getEdge().getToNode().getID(): (
                connection[0].getEdge().getToNode()
            )
            for connection in connections
        }
        junction_node_ids = tuple(sorted(junction_nodes))
        coordinates = [node.getCoord() for node in junction_nodes.values()]
        x = (
            sum(float(coord[0]) for coord in coordinates) / len(coordinates)
            if coordinates
            else 0.0
        )
        y = (
            sum(float(coord[1]) for coord in coordinates) / len(coordinates)
            if coordinates
            else 0.0
        )
        phase_program = extract_phase_program(traffic_light.getPrograms())

        audits.append(
            ControllerAudit(
                agent_id=f"A{agent_number}",
                traffic_light_id=traffic_light.getID(),
                junction_node_ids=junction_node_ids,
                x=x,
                y=y,
                road_names=available_road_names(controlled_edges.values()),
                incoming_edge_ids=tuple(sorted(incoming_edges)),
                outgoing_edge_ids=tuple(sorted(outgoing_edges)),
                controlled_lane_count=len(
                    {connection[0].getID() for connection in connections}
                ),
                controlled_link_count=len(connections),
                program_id=phase_program.program_id,
                program_type=phase_program.program_type,
                phase_durations=phase_program.durations,
                phase_states=phase_program.states,
                edge_lane_counts=tuple(
                    sorted(
                        (edge_id, len(edge.getLanes()))
                        for edge_id, edge in controlled_edges.items()
                    )
                ),
                edge_speed_limits=tuple(
                    sorted(
                        (edge_id, float(edge.getSpeed()))
                        for edge_id, edge in controlled_edges.items()
                    )
                ),
                warnings=_controller_warnings(
                    traffic_light.getID(),
                    junction_node_ids,
                    tuple(controlled_edges.values()),
                    connections,
                    traffic_light.getPrograms(),
                    phase_program,
                    warning_map,
                ),
            )
        )

    return tuple(audits)


def _direct_corridor(path_edges: Sequence[Any]) -> tuple[bool, str]:
    """Conservatively identify a named road that is continuous along a path."""
    road_names = tuple(str(edge.getName()).strip() for edge in path_edges)
    if road_names and all(road_names) and len(set(road_names)) == 1:
        return True, road_names[0]
    return False, ""


def _source_neighbor_paths(
    network: Any,
    source: ControllerAudit,
    audits_by_node: Mapping[str, ControllerAudit],
    max_distance_m: float,
) -> dict[str, tuple[float, tuple[str, ...]]]:
    """Find the first different controller reached on each directed path branch."""
    edges_by_id = {edge.getID(): edge for edge in network.getEdges()}
    best_edge_distance: dict[str, float] = {}
    found: dict[str, tuple[float, tuple[str, ...]]] = {}
    queue: list[tuple[float, str, tuple[str, ...]]] = []

    for edge_id in source.outgoing_edge_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None or not edge.allows("passenger"):
            continue
        distance = float(edge.getLength())
        if distance <= max_distance_m:
            heapq.heappush(queue, (distance, edge_id, (edge_id,)))

    while queue:
        distance, edge_id, path_edge_ids = heapq.heappop(queue)
        if distance > best_edge_distance.get(edge_id, float("inf")):
            continue
        best_edge_distance[edge_id] = distance

        edge = edges_by_id[edge_id]
        target = audits_by_node.get(edge.getToNode().getID())
        if target is not None and target.traffic_light_id != source.traffic_light_id:
            previous = found.get(target.traffic_light_id)
            if previous is None or distance < previous[0]:
                found[target.traffic_light_id] = (distance, path_edge_ids)
            continue

        for next_edge in sorted(edge.getOutgoing(), key=lambda item: item.getID()):
            if not next_edge.allows("passenger"):
                continue
            next_distance = distance + float(next_edge.getLength())
            next_edge_id = next_edge.getID()
            if next_distance > max_distance_m:
                continue
            if next_distance >= best_edge_distance.get(next_edge_id, float("inf")):
                continue
            best_edge_distance[next_edge_id] = next_distance
            heapq.heappush(
                queue,
                (next_distance, next_edge_id, (*path_edge_ids, next_edge_id)),
            )

    return found


def detect_neighbor_relationships(
    network: Any,
    audits: Sequence[ControllerAudit],
    max_distance_m: float = MAX_NEIGHBOR_DISTANCE_M,
) -> tuple[NeighborRelationship, ...]:
    """Detect directed neighbors using passenger paths with no intervening controller."""
    audits_by_id = {audit.traffic_light_id: audit for audit in audits}
    audits_by_node = {
        node_id: audit for audit in audits for node_id in audit.junction_node_ids
    }
    edges_by_id = {edge.getID(): edge for edge in network.getEdges()}
    preliminary: list[NeighborRelationship] = []

    for source in audits:
        neighbor_paths = _source_neighbor_paths(
            network,
            source,
            audits_by_node,
            max_distance_m,
        )
        for target_id, (distance, path_edge_ids) in sorted(
            neighbor_paths.items(),
            key=lambda item: agent_sort_key(audits_by_id[item[0]].agent_id),
        ):
            target = audits_by_id[target_id]
            path_edges = [edges_by_id[edge_id] for edge_id in path_edge_ids]
            direct_corridor, road_name = _direct_corridor(path_edges)
            preliminary.append(
                NeighborRelationship(
                    source_agent_id=source.agent_id,
                    source_traffic_light_id=source.traffic_light_id,
                    target_agent_id=target.agent_id,
                    target_traffic_light_id=target.traffic_light_id,
                    network_distance_m=distance,
                    direct_corridor=direct_corridor,
                    bidirectional=False,
                    path_edge_ids=path_edge_ids,
                    corridor_road_name=road_name,
                )
            )

    relationship_keys = {
        (relationship.source_traffic_light_id, relationship.target_traffic_light_id)
        for relationship in preliminary
    }
    relationships = [
        replace(
            relationship,
            bidirectional=(
                relationship.target_traffic_light_id,
                relationship.source_traffic_light_id,
            )
            in relationship_keys,
        )
        for relationship in preliminary
    ]
    return tuple(
        sorted(
            relationships,
            key=lambda relationship: (
                agent_sort_key(relationship.source_agent_id),
                agent_sort_key(relationship.target_agent_id),
            ),
        )
    )


def build_agent_adjacency(
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
) -> dict[str, set[str]]:
    """Build an undirected graph for connectivity and subset selection."""
    adjacency = {audit.agent_id: set() for audit in audits}
    for relationship in relationships:
        adjacency[relationship.source_agent_id].add(relationship.target_agent_id)
        adjacency[relationship.target_agent_id].add(relationship.source_agent_id)
    return adjacency


def connected_components(
    adjacency: Mapping[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    """Return stable connected components, including isolated agents."""
    remaining = set(adjacency)
    components: list[tuple[str, ...]] = []

    while remaining:
        start = min(remaining, key=agent_sort_key)
        stack = [start]
        component: set[str] = set()
        while stack:
            agent_id = stack.pop()
            if agent_id in component:
                continue
            component.add(agent_id)
            stack.extend(sorted(adjacency[agent_id] - component, key=agent_sort_key))
        remaining -= component
        components.append(tuple(sorted(component, key=agent_sort_key)))

    return tuple(
        sorted(
            components,
            key=lambda component: (-len(component), agent_sort_key(component[0])),
        )
    )


def _relationship_lookup(
    relationships: Sequence[NeighborRelationship],
) -> dict[frozenset[str], list[NeighborRelationship]]:
    """Group directed relationships by their undirected agent pair."""
    lookup: dict[frozenset[str], list[NeighborRelationship]] = {}
    for relationship in relationships:
        key = frozenset((relationship.source_agent_id, relationship.target_agent_id))
        lookup.setdefault(key, []).append(relationship)
    return lookup


def _expand_candidate(
    seed: str,
    component: set[str],
    adjacency: Mapping[str, set[str]],
    audits_by_agent: Mapping[str, ControllerAudit],
    relationship_lookup: Mapping[frozenset[str], list[NeighborRelationship]],
    target_size: int,
) -> tuple[str, ...]:
    """Grow one connected candidate with preference for strong road corridors."""
    selected = {seed}
    while len(selected) < target_size:
        frontier = {
            neighbor
            for agent_id in selected
            for neighbor in adjacency[agent_id]
            if neighbor in component and neighbor not in selected
        }
        if not frontier:
            break

        def frontier_score(agent_id: str) -> tuple[float, ...]:
            connecting_pairs = [
                relationship_lookup.get(frozenset((agent_id, selected_id)), [])
                for selected_id in selected
            ]
            relationships = [
                relationship
                for pair_relationships in connecting_pairs
                for relationship in pair_relationships
            ]
            direct_links = len(
                {
                    frozenset(
                        (
                            relationship.source_agent_id,
                            relationship.target_agent_id,
                        )
                    )
                    for relationship in relationships
                    if relationship.direct_corridor
                }
            )
            minimum_distance = min(
                (relationship.network_distance_m for relationship in relationships),
                default=MAX_NEIGHBOR_DISTANCE_M,
            )
            audit = audits_by_agent[agent_id]
            return (
                float(direct_links),
                float(audit.max_edge_lane_count),
                audit.max_edge_speed,
                float(len(adjacency[agent_id])),
                -minimum_distance,
                -float(agent_sort_key(agent_id)[0]),
            )

        selected.add(max(frontier, key=frontier_score))

    return tuple(sorted(selected, key=agent_sort_key))


def select_candidate_groups(
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
    maximum_candidates: int = MAX_CANDIDATES,
) -> tuple[CandidateGroup, ...]:
    """Propose connected 6-to-10-controller groups for manual selection."""
    audits_by_agent = {audit.agent_id: audit for audit in audits}
    adjacency = build_agent_adjacency(audits, relationships)
    components = connected_components(adjacency)
    relationship_lookup = _relationship_lookup(relationships)
    candidate_agent_groups: list[tuple[str, ...]] = []

    eligible_components = [
        set(component) for component in components if len(component) >= 6
    ]
    for component in eligible_components:
        seeds = sorted(
            component,
            key=lambda agent_id: (
                -audits_by_agent[agent_id].max_edge_lane_count,
                -audits_by_agent[agent_id].max_edge_speed,
                -len(adjacency[agent_id]),
                agent_sort_key(agent_id),
            ),
        )
        target_size = min(TARGET_CANDIDATE_SIZE, len(component), 10)
        for seed in seeds:
            candidate = _expand_candidate(
                seed,
                component,
                adjacency,
                audits_by_agent,
                relationship_lookup,
                target_size,
            )
            if len(candidate) >= 6 and candidate not in candidate_agent_groups:
                candidate_agent_groups.append(candidate)
            if len(candidate_agent_groups) >= maximum_candidates:
                break
        if len(candidate_agent_groups) >= maximum_candidates:
            break

    candidates: list[CandidateGroup] = []
    for candidate_number, agent_ids in enumerate(candidate_agent_groups, start=1):
        agent_set = set(agent_ids)
        undirected_pairs = {
            frozenset((relationship.source_agent_id, relationship.target_agent_id))
            for relationship in relationships
            if relationship.source_agent_id in agent_set
            and relationship.target_agent_id in agent_set
        }
        pair_relationships = [
            relationship
            for pair in undirected_pairs
            for relationship in relationship_lookup[pair]
        ]
        distances = [
            min(
                relationship.network_distance_m
                for relationship in relationship_lookup[pair]
            )
            for pair in undirected_pairs
        ]
        direct_pairs = sum(
            any(
                relationship.direct_corridor
                for relationship in relationship_lookup[pair]
            )
            for pair in undirected_pairs
        )
        road_name_counts = Counter(
            relationship.corridor_road_name
            for relationship in pair_relationships
            if relationship.direct_corridor and relationship.corridor_road_name
        )
        road_names = tuple(
            road_name
            for road_name, _ in sorted(
                road_name_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        )
        candidate_audits = [audits_by_agent[agent_id] for agent_id in agent_ids]

        candidates.append(
            CandidateGroup(
                name=f"Candidate {candidate_number}",
                agent_ids=agent_ids,
                traffic_light_ids=tuple(
                    audit.traffic_light_id for audit in candidate_audits
                ),
                direct_corridor_links=direct_pairs,
                mean_neighbor_distance_m=(
                    sum(distances) / len(distances) if distances else 0.0
                ),
                max_edge_lane_count=max(
                    audit.max_edge_lane_count for audit in candidate_audits
                ),
                max_edge_speed=max(audit.max_edge_speed for audit in candidate_audits),
                road_names=road_names,
            )
        )

    return tuple(candidates)


def _format_number(value: float) -> str:
    """Format numeric CSV values without unstable trailing zeros."""
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _controller_notes(audit: ControllerAudit) -> str:
    """Serialize phase states and controlled-edge properties into audit notes."""
    lane_counts = "; ".join(
        f"{edge_id}={lane_count}" for edge_id, lane_count in audit.edge_lane_counts
    )
    speed_limits = "; ".join(
        f"{edge_id}={speed:.2f} m/s" for edge_id, speed in audit.edge_speed_limits
    )
    phase_states = " | ".join(audit.phase_states)
    return (
        f"Program {audit.program_id or '(none)'} ({audit.program_type or 'unknown'}). "
        f"Phase states: {phase_states or '(none)'}. "
        f"Controlled-edge lane counts: {lane_counts or '(none)'}. "
        f"Controlled-edge speed limits: {speed_limits or '(none)'}."
    )


def write_audit_csv(
    output_file: Path,
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
) -> None:
    """Write stable controller facts and outgoing network neighbors."""
    outgoing: dict[str, list[NeighborRelationship]] = {
        audit.traffic_light_id: [] for audit in audits
    }
    for relationship in relationships:
        outgoing[relationship.source_traffic_light_id].append(relationship)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=AUDIT_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        for audit in audits:
            neighbors = sorted(
                outgoing[audit.traffic_light_id],
                key=lambda relationship: agent_sort_key(relationship.target_agent_id),
            )
            writer.writerow(
                {
                    "agent_id": audit.agent_id,
                    "traffic_light_id": audit.traffic_light_id,
                    "junction_node_ids": ";".join(audit.junction_node_ids),
                    "x": f"{audit.x:.2f}",
                    "y": f"{audit.y:.2f}",
                    "road_names": ";".join(audit.road_names),
                    "incoming_edges": ";".join(audit.incoming_edge_ids),
                    "outgoing_edges": ";".join(audit.outgoing_edge_ids),
                    "controlled_lane_count": audit.controlled_lane_count,
                    "controlled_link_count": audit.controlled_link_count,
                    "phase_count": audit.phase_count,
                    "phase_durations": ";".join(
                        _format_number(duration) for duration in audit.phase_durations
                    ),
                    "neighbor_ids": ";".join(
                        relationship.target_traffic_light_id
                        for relationship in neighbors
                    ),
                    "neighbor_distances": ";".join(
                        f"{relationship.target_traffic_light_id}="
                        f"{relationship.network_distance_m:.2f}"
                        for relationship in neighbors
                    ),
                    "enabled": "true",
                    "warnings": "; ".join(audit.warnings),
                    "notes": _controller_notes(audit),
                }
            )


def _neighbor_notes(relationship: NeighborRelationship) -> str:
    """Describe the evidence for one relationship without inventing context."""
    base = (
        f"Passenger path uses {len(relationship.path_edge_ids)} edges and reaches "
        "the target before another traffic-light controller."
    )
    if relationship.direct_corridor:
        return (
            f"{base} Continuous network road name: {relationship.corridor_road_name}."
        )
    return f"{base} Continuous named-road corridor was not established."


def write_neighbors_csv(
    output_file: Path,
    relationships: Sequence[NeighborRelationship],
) -> None:
    """Write stable directed controller relationships and network distances."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=NEIGHBOR_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        for relationship in relationships:
            writer.writerow(
                {
                    "source_agent_id": relationship.source_agent_id,
                    "source_traffic_light_id": (relationship.source_traffic_light_id),
                    "target_agent_id": relationship.target_agent_id,
                    "target_traffic_light_id": (relationship.target_traffic_light_id),
                    "network_distance_m": (f"{relationship.network_distance_m:.2f}"),
                    "direct_corridor": str(relationship.direct_corridor).lower(),
                    "bidirectional": str(relationship.bidirectional).lower(),
                    "notes": _neighbor_notes(relationship),
                }
            )


def _escape_markdown(value: str) -> str:
    """Escape text that would break a compact Markdown table."""
    return value.replace("|", "\\|").replace("\n", " ")


def render_candidate_report(
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
    candidates: Sequence[CandidateGroup],
) -> str:
    """Render computed topology facts separately from subset recommendations."""
    audits_by_agent = {audit.agent_id: audit for audit in audits}
    adjacency = build_agent_adjacency(audits, relationships)
    components = connected_components(adjacency)
    isolated = tuple(
        audit.agent_id for audit in audits if not adjacency[audit.agent_id]
    )
    bidirectional_pairs = {
        frozenset((relationship.source_agent_id, relationship.target_agent_id))
        for relationship in relationships
        if relationship.bidirectional
    }
    direct_pairs = {
        frozenset((relationship.source_agent_id, relationship.target_agent_id))
        for relationship in relationships
        if relationship.direct_corridor
    }
    broken_program_warnings = (
        "Controller has no controlled links.",
        "Controller has no signal phases.",
        "Signal program contains a non-positive phase duration.",
        "Phase state length does not match the highest controlled link index.",
    )
    broken_programs = [
        audit
        for audit in audits
        if any(warning in broken_program_warnings for warning in audit.warnings)
    ]
    complex_programs = [
        audit for audit in audits if audit.phase_count > COMPLEX_PHASE_COUNT
    ]
    phase_counts = [audit.phase_count for audit in audits]

    lines = [
        "# Skopje traffic-light corridor candidates",
        "",
        "This report audits all imported traffic-light controllers without modifying the SUMO network.",
        "No candidate is selected automatically.",
        "",
        "## Computed facts",
        "",
        "### Neighbor-detection method",
        "",
        (
            "- The audit follows directed, passenger-compatible SUMO edge connections "
            "from each controller's outgoing edges."
        ),
        (
            "- A search branch stops when it first reaches a different traffic-light "
            "controller, so a recorded path does not pass through another controller."
        ),
        (
            f"- Searches are limited to {MAX_NEIGHBOR_DISTANCE_M:.0f} m of network "
            "path distance to keep the graph local and avoid long residential detours."
        ),
        (
            "- Network distance is the sum of SUMO edge lengths, not straight-line "
            "distance."
        ),
        (
            "- A relationship is marked as a direct corridor only when every edge "
            "on the path has the same non-empty network road name."
        ),
        (
            "- The x and y audit columns are centroids of controlled junction nodes "
            "in SUMO network coordinates."
        ),
        "",
        "### Graph summary",
        "",
        f"- Audited controllers: {len(audits)}.",
        f"- Directed neighbor relationships: {len(relationships)}.",
        f"- Bidirectional neighbor pairs: {len(bidirectional_pairs)}.",
        f"- Named direct-corridor pairs: {len(direct_pairs)}.",
        f"- Connected components: {len(components)}.",
        f"- Isolated controllers: {len(isolated)}.",
        "",
        "### Phase-program audit",
        "",
        (
            f"- Phase counts range from {min(phase_counts, default=0)} to "
            f"{max(phase_counts, default=0)}."
        ),
        f"- Structurally broken phase programs detected: {len(broken_programs)}.",
        (
            f"- Overly complex programs above {COMPLEX_PHASE_COUNT} phases: "
            f"{len(complex_programs)}."
        ),
        (
            "- Phase states and durations for every controller are stored in the "
            "audit CSV."
        ),
        "",
        "### Connected groups",
        "",
    ]

    for component_number, component in enumerate(components, start=1):
        component_controllers = ", ".join(
            f"{agent_id} (`{audits_by_agent[agent_id].traffic_light_id}`)"
            for agent_id in component
        )
        lines.append(
            f"- Group {component_number} has {len(component)} controllers: "
            f"{component_controllers}."
        )

    lines.extend(["", "### Isolated controllers", ""])
    if isolated:
        for agent_id in isolated:
            lines.append(
                f"- {agent_id} (`{audits_by_agent[agent_id].traffic_light_id}`)."
            )
    else:
        lines.append("- No isolated controllers were detected by the chosen method.")

    lines.extend(
        [
            "",
            "### Controller overview",
            "",
            "| Agent | Traffic-light ID | Nodes | Phases | Max lanes | Max speed | Graph neighbors | Roads | Warnings |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for audit in audits:
        warnings = "; ".join(audit.warnings) or "None"
        road_names = "; ".join(audit.road_names) or "None available"
        lines.append(
            f"| {audit.agent_id} | `{_escape_markdown(audit.traffic_light_id)}` | "
            f"{len(audit.junction_node_ids)} | {audit.phase_count} | "
            f"{audit.max_edge_lane_count} | {audit.max_edge_speed:.2f} m/s | "
            f"{len(adjacency[audit.agent_id])} | {_escape_markdown(road_names)} | "
            f"{_escape_markdown(warnings)} |"
        )

    unusual = [audit for audit in audits if audit.warnings]
    lines.extend(["", "### Program and network warnings", ""])
    if unusual:
        for audit in unusual:
            lines.append(
                f"- {audit.agent_id} (`{audit.traffic_light_id}`): "
                f"{'; '.join(audit.warnings)}"
            )
    else:
        lines.append("- No structural or unusual conditions were detected.")

    lines.extend(
        [
            "",
            "## Recommendations for manual selection",
            "",
            (
                "These candidates are connected graph subsets generated for manual "
                "comparison, not final experiment selections."
            ),
            (
                "The ranking prefers controlled edges with more lanes, higher speed "
                "limits, named direct-corridor links, and stronger graph connectivity."
            ),
            "",
        ]
    )

    if not candidates:
        lines.append(
            "No connected component contains enough controllers for a 6-to-10-agent candidate."
        )

    for candidate in candidates:
        candidate_warning_agents = [
            agent_id
            for agent_id in candidate.agent_ids
            if audits_by_agent[agent_id].warnings
        ]
        lines.extend(
            [
                f"### {candidate.name}",
                "",
                f"- Agents: {', '.join(candidate.agent_ids)}.",
                (
                    "- Traffic-light IDs: "
                    + ", ".join(
                        f"`{traffic_light_id}`"
                        for traffic_light_id in candidate.traffic_light_ids
                    )
                    + "."
                ),
                f"- Named direct-corridor links inside the subset: {candidate.direct_corridor_links}.",
                f"- Mean detected neighbor distance inside the subset: {candidate.mean_neighbor_distance_m:.2f} m.",
                f"- Largest controlled-edge lane count: {candidate.max_edge_lane_count}.",
                f"- Highest controlled-edge speed limit: {candidate.max_edge_speed:.2f} m/s.",
            ]
        )
        if candidate.road_names:
            lines.append(
                "- Repeated direct-corridor road names from the network: "
                f"{', '.join(candidate.road_names)}."
            )
        else:
            lines.append(
                "- No continuous named-road corridor was established inside this subset."
            )
        if candidate_warning_agents:
            lines.append(
                "- Controllers requiring warning review: "
                f"{', '.join(candidate_warning_agents)}."
            )
        else:
            lines.append("- Controllers requiring warning review: none.")
        lines.extend(
            [
                (
                    "- Why it could work for MARL: the controllers form one connected "
                    "neighbor subgraph, allowing local interactions to be studied "
                    "without using all 33 controllers."
                ),
                (
                    "- Manual review needed: verify signal phases, allowed turns, lane "
                    "continuity, queue interactions, and whether the named corridors "
                    "match the intended study area in netedit."
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Decision status",
            "",
            "No final 6-to-10-controller subset has been selected.",
            "Use the manual netedit checklist before accepting or rejecting a candidate.",
            "",
        ]
    )
    return "\n".join(lines)


def write_candidate_report(
    output_file: Path,
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
    candidates: Sequence[CandidateGroup],
) -> None:
    """Write the computed facts and recommendations as Markdown."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        render_candidate_report(audits, relationships, candidates),
        encoding="utf-8",
    )


def print_audit_summary(
    audits: Sequence[ControllerAudit],
    relationships: Sequence[NeighborRelationship],
    candidates: Sequence[CandidateGroup],
) -> None:
    """Print the generated audit summary and proposed candidates."""
    adjacency = build_agent_adjacency(audits, relationships)
    components = connected_components(adjacency)
    isolated = [audit.agent_id for audit in audits if not adjacency[audit.agent_id]]
    warning_controllers = [audit for audit in audits if audit.warnings]
    bidirectional_pairs = {
        frozenset((relationship.source_agent_id, relationship.target_agent_id))
        for relationship in relationships
        if relationship.bidirectional
    }
    direct_pairs = {
        frozenset((relationship.source_agent_id, relationship.target_agent_id))
        for relationship in relationships
        if relationship.direct_corridor
    }

    print("Skopje traffic-light audit summary")
    print(f"Controllers audited: {len(audits)}")
    print(f"Directed neighbor relationships: {len(relationships)}")
    print(f"Bidirectional neighbor pairs: {len(bidirectional_pairs)}")
    print(f"Named direct-corridor pairs: {len(direct_pairs)}")
    print(f"Connected components: {len(components)}")
    print(
        "Connected component sizes: "
        + ", ".join(str(len(component)) for component in components)
    )
    print(f"Isolated controllers: {', '.join(isolated) if isolated else 'none'}")
    print(f"Controllers with warnings: {len(warning_controllers)}")
    print("Proposed corridor candidates:")
    if not candidates:
        print("  - None")
    for candidate in candidates:
        print(
            f"  - {candidate.name}: {', '.join(candidate.agent_ids)} "
            f"({candidate.direct_corridor_links} named direct-corridor links)"
        )


def main() -> int:
    """Audit the organized network and regenerate deterministic documentation."""
    try:
        SKOPJE_INITIAL_CONFIG.validate_files()
        sumolib = load_sumolib()
        network = sumolib.net.readNet(
            str(SKOPJE_INITIAL_CONFIG.net_file),
            withPrograms=True,
        )
        external_warnings = read_wizard_controller_warnings(WIZARD_WARNING_FILE)
        audits = collect_controller_audits(network, external_warnings)
        relationships = detect_neighbor_relationships(network, audits)
        candidates = select_candidate_groups(audits, relationships)

        write_audit_csv(AUDIT_FILE, audits, relationships)
        write_neighbors_csv(NEIGHBORS_FILE, relationships)
        write_candidate_report(CANDIDATES_FILE, audits, relationships, candidates)
        print_audit_summary(audits, relationships, candidates)
        print(f"Audit CSV: {AUDIT_FILE.relative_to(PROJECT_ROOT)}")
        print(f"Neighbor CSV: {NEIGHBORS_FILE.relative_to(PROJECT_ROOT)}")
        print(f"Candidate report: {CANDIDATES_FILE.relative_to(PROJECT_ROOT)}")
        return 0
    except Exception as error:
        print(
            f"[ERROR] Traffic-light audit failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

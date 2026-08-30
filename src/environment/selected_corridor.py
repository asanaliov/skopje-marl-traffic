"""Official selected corridor and validation for the Skopje experiment."""

from __future__ import annotations

import csv
import gzip
import math
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from src.config import SKOPJE_DIR, SKOPJE_INITIAL_SUMO_CONFIG_FILE
from src.environment.corridor_candidates import (
    get_candidate,
    load_agent_traffic_light_mapping,
)


_EXPECTED_CANDIDATE_ID = "1"
_EXPECTED_AGENT_IDS = ("A9", "A18", "A19", "A20", "A24", "A25", "A26", "A29")
_AUDIT_FILE = SKOPJE_DIR / "documentation" / "traffic_light_audit.csv"
_NEIGHBORS_FILE = SKOPJE_DIR / "documentation" / "traffic_light_neighbors.csv"


@dataclass(frozen=True, slots=True)
class SelectedCorridor:
    """Immutable description of the traffic lights selected for future RL control.

    The complete SUMO scenario remains active. This object identifies only the
    controllers that later experiments may expose as learning agents.
    """

    name: str
    candidate_id: str
    description: str
    agent_ids: tuple[str, ...]
    traffic_light_ids: tuple[str, ...]
    junction_node_ids: tuple[str, ...]
    agent_to_traffic_light: Mapping[str, str]
    traffic_light_to_agent: Mapping[str, str]
    road_names_by_agent: Mapping[str, tuple[str, ...]]
    warnings_by_agent: Mapping[str, tuple[str, ...]]
    neighbor_map: Mapping[str, tuple[str, ...]]
    neighbor_distances_m: Mapping[tuple[str, str], float]
    network_file: Path
    route_files: tuple[Path, ...]
    configuration_file: Path


@dataclass(frozen=True, slots=True)
class _AuditRecord:
    """Audit values needed to construct and inspect the selected corridor."""

    traffic_light_id: str
    junction_node_ids: tuple[str, ...]
    road_names: tuple[str, ...]
    warnings: tuple[str, ...]
    phase_count: int | None


def _split_values(value: str) -> tuple[str, ...]:
    """Split a semicolon-separated audit cell while preserving source order."""
    return tuple(item.strip() for item in value.split(";") if item.strip())


@lru_cache(maxsize=None)
def _load_audit_records(audit_file: Path = _AUDIT_FILE) -> Mapping[str, _AuditRecord]:
    """Load typed audit facts without copying controller IDs into source code."""
    audited_mapping = load_agent_traffic_light_mapping(audit_file)
    required_columns = {
        "agent_id",
        "traffic_light_id",
        "junction_node_ids",
        "road_names",
        "warnings",
        "phase_count",
    }

    try:
        csv_file = audit_file.open(encoding="utf-8", newline="")
    except OSError as error:
        raise FileNotFoundError(
            f"Traffic-light audit CSV is unavailable: {audit_file}"
        ) from error

    records: dict[str, _AuditRecord] = {}
    with csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = required_columns - set(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Traffic-light audit CSV is missing columns: {missing}")

        for row in reader:
            agent_id = row["agent_id"].strip()
            if not agent_id:
                raise ValueError("Traffic-light audit contains an empty agent ID.")

            phase_count_text = row["phase_count"].strip()
            try:
                phase_count = int(phase_count_text) if phase_count_text else None
            except ValueError as error:
                raise ValueError(
                    f"Audit phase count for {agent_id} is not an integer: "
                    f"{phase_count_text!r}."
                ) from error

            records[agent_id] = _AuditRecord(
                traffic_light_id=audited_mapping[agent_id],
                junction_node_ids=_split_values(row["junction_node_ids"]),
                road_names=_split_values(row["road_names"]),
                warnings=(row["warnings"].strip(),) if row["warnings"].strip() else (),
                phase_count=phase_count,
            )

    return MappingProxyType(records)


def _configured_paths(configuration_file: Path, option_name: str) -> tuple[Path, ...]:
    """Resolve one comma-separated SUMO input option relative to its config."""
    try:
        root = ET.parse(configuration_file).getroot()
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"SUMO configuration file is missing: {configuration_file}"
        ) from error
    except ET.ParseError as error:
        raise ValueError(
            f"SUMO configuration file is not valid XML: {configuration_file}: {error}"
        ) from error

    option = root.find(f"input/{option_name}")
    if option is None or not option.get("value", "").strip():
        raise ValueError(
            f"SUMO configuration does not define input/{option_name}: "
            f"{configuration_file}"
        )

    return tuple(
        (configuration_file.parent / value.strip()).resolve()
        for value in option.get("value", "").split(",")
        if value.strip()
    )


def _optional_configured_paths(
    configuration_file: Path,
    option_name: str,
) -> tuple[Path, ...]:
    """Resolve an optional comma-separated SUMO input option."""
    root = ET.parse(configuration_file).getroot()
    option = root.find(f"input/{option_name}")
    if option is None:
        return ()
    return tuple(
        (configuration_file.parent / value.strip()).resolve()
        for value in option.get("value", "").split(",")
        if value.strip()
    )


def _load_selected_neighbors(
    agent_ids: tuple[str, ...],
    audited_mapping: Mapping[str, str],
    neighbors_file: Path = _NEIGHBORS_FILE,
) -> tuple[
    Mapping[str, tuple[str, ...]],
    Mapping[tuple[str, str], float],
]:
    """Load directed relationships whose source and target are both selected."""
    required_columns = {
        "source_agent_id",
        "source_traffic_light_id",
        "target_agent_id",
        "target_traffic_light_id",
        "network_distance_m",
    }
    selected_agents = set(agent_ids)
    agent_order = {agent_id: index for index, agent_id in enumerate(agent_ids)}
    rows: list[tuple[str, str, float]] = []
    seen_relationships: set[tuple[str, str]] = set()

    try:
        csv_file = neighbors_file.open(encoding="utf-8", newline="")
    except OSError as error:
        raise FileNotFoundError(
            f"Traffic-light neighbors CSV is unavailable: {neighbors_file}"
        ) from error

    with csv_file:
        reader = csv.DictReader(csv_file)
        missing_columns = required_columns - set(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(
                f"Traffic-light neighbors CSV is missing columns: {missing}"
            )

        for row in reader:
            source = row["source_agent_id"].strip()
            target = row["target_agent_id"].strip()
            if source not in selected_agents or target not in selected_agents:
                continue

            relationship = (source, target)
            if relationship in seen_relationships:
                raise ValueError(
                    f"Duplicate directed neighbor relationship in audit: {source} -> {target}."
                )
            seen_relationships.add(relationship)

            source_traffic_light = row["source_traffic_light_id"].strip()
            target_traffic_light = row["target_traffic_light_id"].strip()
            if source_traffic_light != audited_mapping[source]:
                raise ValueError(
                    f"Neighbor audit maps {source} to {source_traffic_light}, but the "
                    f"traffic-light audit maps it to {audited_mapping[source]}."
                )
            if target_traffic_light != audited_mapping[target]:
                raise ValueError(
                    f"Neighbor audit maps {target} to {target_traffic_light}, but the "
                    f"traffic-light audit maps it to {audited_mapping[target]}."
                )

            distance_text = row["network_distance_m"].strip()
            try:
                distance = float(distance_text)
            except ValueError as error:
                raise ValueError(
                    f"Neighbor distance for {source} -> {target} is not numeric: "
                    f"{distance_text!r}."
                ) from error
            if not math.isfinite(distance) or distance < 0:
                raise ValueError(
                    f"Neighbor distance for {source} -> {target} must be a finite "
                    f"non-negative number, got {distance_text!r}."
                )
            rows.append((source, target, distance))

    rows.sort(key=lambda row: (agent_order[row[0]], agent_order[row[1]]))
    neighbors: dict[str, list[str]] = {agent_id: [] for agent_id in agent_ids}
    distances: dict[tuple[str, str], float] = {}
    for source, target, distance in rows:
        neighbors[source].append(target)
        distances[(source, target)] = distance

    neighbor_map = {agent_id: tuple(neighbors[agent_id]) for agent_id in agent_ids}
    return MappingProxyType(neighbor_map), MappingProxyType(distances)


@lru_cache(maxsize=None)
def _load_network_ids(network_file: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Read traffic-light and junction IDs with a streaming XML parser."""
    opener = gzip.open if network_file.suffix == ".gz" else open
    traffic_light_ids: set[str] = set()
    junction_ids: set[str] = set()

    try:
        with opener(network_file, "rb") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                element_id = element.get("id")
                if element.tag == "tlLogic" and element_id:
                    traffic_light_ids.add(element_id)
                elif element.tag == "junction" and element_id:
                    junction_ids.add(element_id)
                element.clear()
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"SUMO network file is missing: {network_file}"
        ) from error
    except (ET.ParseError, OSError) as error:
        raise ValueError(
            f"Could not read SUMO network file {network_file}: {error}"
        ) from error

    return frozenset(traffic_light_ids), frozenset(junction_ids)


def is_connected(corridor: SelectedCorridor) -> bool:
    """Return whether all selected agents connect in the undirected view."""
    if not corridor.agent_ids:
        return False

    selected_agents = set(corridor.agent_ids)
    adjacency = {agent_id: set() for agent_id in corridor.agent_ids}
    for source, targets in corridor.neighbor_map.items():
        if source not in selected_agents:
            continue
        for target in targets:
            if target in selected_agents:
                adjacency[source].add(target)
                adjacency[target].add(source)

    visited = {corridor.agent_ids[0]}
    pending = deque(visited)
    while pending:
        source = pending.popleft()
        for target in adjacency[source] - visited:
            visited.add(target)
            pending.append(target)
    return visited == selected_agents


def junction_node_ids_by_agent(
    corridor: SelectedCorridor,
) -> Mapping[str, tuple[str, ...]]:
    """Return audited junction IDs grouped by selected agent."""
    records = _load_audit_records()
    return MappingProxyType(
        {
            agent_id: records[agent_id].junction_node_ids
            for agent_id in corridor.agent_ids
        }
    )


def phase_counts_by_agent(
    corridor: SelectedCorridor,
) -> Mapping[str, int | None]:
    """Return audited phase counts for display and inspection."""
    records = _load_audit_records()
    return MappingProxyType(
        {agent_id: records[agent_id].phase_count for agent_id in corridor.agent_ids}
    )


def nearest_neighbor_ids(
    corridor: SelectedCorridor,
    agent_id: str,
    *,
    limit: int | None = None,
    observed_agent_ids: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return one agent's neighbors ordered by network distance, nearest first.

    Spatial observation sharing needs a *bounded* neighborhood: A26 has six
    audited neighbors, and one extra state bit per neighbor multiplies a
    tabular Q-table by two. ``limit`` keeps only the closest neighbors, which
    are also the ones whose queues arrive soonest. ``observed_agent_ids``
    restricts the result to agents a run actually controls, so a corridor
    subset never references a junction nobody is observing.

    Ties in distance are broken by official corridor order, so the result is
    deterministic across runs and machines.
    """
    if agent_id not in corridor.neighbor_map:
        valid = ", ".join(corridor.agent_ids)
        raise ValueError(
            f"Unknown selected agent ID: {agent_id}. Choose from: {valid}."
        )
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise ValueError("limit must be a non-negative integer or None.")

    observed = (
        set(corridor.agent_ids)
        if observed_agent_ids is None
        else set(observed_agent_ids)
    )
    corridor_order = {
        selected_id: index for index, selected_id in enumerate(corridor.agent_ids)
    }
    candidates = sorted(
        (
            neighbor_id
            for neighbor_id in corridor.neighbor_map[agent_id]
            if neighbor_id in observed
        ),
        key=lambda neighbor_id: (
            corridor.neighbor_distances_m[(agent_id, neighbor_id)],
            corridor_order[neighbor_id],
        ),
    )
    return tuple(candidates if limit is None else candidates[:limit])


def _validate_structure(corridor: SelectedCorridor) -> None:
    """Validate identity, mappings, relationships, distances, and connectivity."""
    if corridor.candidate_id != _EXPECTED_CANDIDATE_ID:
        raise ValueError(
            "The selected corridor must represent Candidate 1 "
            f"(candidate_id='1'), got {corridor.candidate_id!r}."
        )
    if len(corridor.agent_ids) != 8:
        raise ValueError(
            f"Candidate 1 must contain exactly eight agents, got {len(corridor.agent_ids)}."
        )
    if len(set(corridor.agent_ids)) != len(corridor.agent_ids):
        raise ValueError("Candidate 1 contains duplicate agent IDs.")
    if corridor.agent_ids != _EXPECTED_AGENT_IDS:
        raise ValueError(
            "Candidate 1 agents must use this deterministic order: "
            f"{', '.join(_EXPECTED_AGENT_IDS)}."
        )
    if len(corridor.traffic_light_ids) != len(corridor.agent_ids):
        raise ValueError("Agent and traffic-light ID counts do not match.")
    if len(set(corridor.traffic_light_ids)) != len(corridor.traffic_light_ids):
        raise ValueError("Candidate 1 contains duplicate traffic-light IDs.")

    expected_agent_keys = set(corridor.agent_ids)
    mapping_keys = set(corridor.agent_to_traffic_light)
    if mapping_keys != expected_agent_keys:
        raise ValueError(
            "Agent-to-traffic-light mapping keys must exactly match the selected agents."
        )
    ordered_mapping = tuple(
        corridor.agent_to_traffic_light[agent_id] for agent_id in corridor.agent_ids
    )
    if ordered_mapping != corridor.traffic_light_ids:
        raise ValueError(
            "Traffic-light IDs do not match the ordered agent-to-controller mapping."
        )
    expected_reverse = {
        traffic_light_id: agent_id
        for agent_id, traffic_light_id in corridor.agent_to_traffic_light.items()
    }
    if dict(corridor.traffic_light_to_agent) != expected_reverse:
        raise ValueError("Traffic-light-to-agent reverse mapping is inconsistent.")

    for mapping_name, mapping in (
        ("road-name", corridor.road_names_by_agent),
        ("warning", corridor.warnings_by_agent),
        ("neighbor", corridor.neighbor_map),
    ):
        if set(mapping) != expected_agent_keys:
            raise ValueError(
                f"The {mapping_name} mapping keys must exactly match selected agents."
            )

    directed_relationships: set[tuple[str, str]] = set()
    for source in corridor.agent_ids:
        targets = corridor.neighbor_map[source]
        if len(targets) != len(set(targets)):
            raise ValueError(f"Agent {source} contains duplicate neighbor references.")
        for target in targets:
            if target == source:
                raise ValueError(
                    f"Agent {source} cannot reference itself as a neighbor."
                )
            if target not in expected_agent_keys:
                raise ValueError(
                    f"Agent {source} references unknown selected neighbor {target}."
                )
            directed_relationships.add((source, target))

    distance_relationships = set(corridor.neighbor_distances_m)
    if distance_relationships != directed_relationships:
        raise ValueError(
            "Directed neighbor distances must exist for exactly the configured "
            "neighbor relationships."
        )
    for (source, target), distance in corridor.neighbor_distances_m.items():
        if not math.isfinite(distance) or distance < 0:
            raise ValueError(
                f"Neighbor distance for {source} -> {target} must be finite and "
                f"non-negative, got {distance!r}."
            )

    if not is_connected(corridor):
        raise ValueError(
            "Candidate 1 agent graph must be connected when treated as undirected."
        )


def _validate_audit_data(corridor: SelectedCorridor) -> None:
    """Confirm every selected value still agrees with the audit source files."""
    records = _load_audit_records()
    missing_agents = [
        agent_id for agent_id in corridor.agent_ids if agent_id not in records
    ]
    if missing_agents:
        raise ValueError(
            "Selected agents are missing from the traffic-light audit: "
            f"{', '.join(missing_agents)}."
        )

    audited_agent_mapping = {
        agent_id: records[agent_id].traffic_light_id for agent_id in corridor.agent_ids
    }
    if dict(corridor.agent_to_traffic_light) != audited_agent_mapping:
        raise ValueError(
            "Selected controller mappings do not match the traffic-light audit."
        )

    expected_junction_ids = tuple(
        junction_id
        for agent_id in corridor.agent_ids
        for junction_id in records[agent_id].junction_node_ids
    )
    if corridor.junction_node_ids != expected_junction_ids:
        raise ValueError("Selected junction IDs do not match the traffic-light audit.")

    expected_roads = {
        agent_id: records[agent_id].road_names for agent_id in corridor.agent_ids
    }
    if dict(corridor.road_names_by_agent) != expected_roads:
        raise ValueError("Selected road names do not match the traffic-light audit.")

    expected_warnings = {
        agent_id: records[agent_id].warnings for agent_id in corridor.agent_ids
    }
    if dict(corridor.warnings_by_agent) != expected_warnings:
        raise ValueError("Selected warnings do not match the traffic-light audit.")

    expected_neighbors, expected_distances = _load_selected_neighbors(
        corridor.agent_ids,
        audited_agent_mapping,
    )
    if dict(corridor.neighbor_map) != dict(expected_neighbors):
        raise ValueError("Selected neighbor relationships do not match the audit.")
    if dict(corridor.neighbor_distances_m) != dict(expected_distances):
        raise ValueError("Selected neighbor distances do not match the audit.")


def _validate_sumo_files(corridor: SelectedCorridor) -> None:
    """Validate scenario inputs and selected IDs against the complete network."""
    required_files = (
        corridor.configuration_file,
        corridor.network_file,
        *corridor.route_files,
    )
    missing_files = [path for path in required_files if not path.is_file()]
    if missing_files:
        details = "\n".join(f"- {path}" for path in missing_files)
        raise FileNotFoundError(
            f"Required selected-corridor files are missing:\n{details}"
        )

    configured_network_files = _configured_paths(
        corridor.configuration_file, "net-file"
    )
    if len(configured_network_files) != 1:
        raise ValueError(
            "The Skopje SUMO configuration must define exactly one network file."
        )
    if corridor.network_file.resolve() != configured_network_files[0]:
        raise ValueError(
            "Selected corridor network does not match the network in the SUMO configuration."
        )

    configured_route_files = _configured_paths(
        corridor.configuration_file, "route-files"
    )
    if tuple(path.resolve() for path in corridor.route_files) != configured_route_files:
        raise ValueError(
            "Selected corridor route files do not match demand files in the SUMO configuration."
        )

    missing_additional_files = [
        path
        for path in _optional_configured_paths(
            corridor.configuration_file,
            "additional-files",
        )
        if not path.is_file()
    ]
    if missing_additional_files:
        details = "\n".join(f"- {path}" for path in missing_additional_files)
        raise FileNotFoundError(
            f"SUMO configuration additional files are missing:\n{details}"
        )

    network_traffic_lights, network_junction_ids = _load_network_ids(
        corridor.network_file
    )
    missing_traffic_lights = sorted(
        set(corridor.traffic_light_ids) - network_traffic_lights
    )
    if missing_traffic_lights:
        raise ValueError(
            "Selected traffic-light controllers are missing from the SUMO network: "
            f"{', '.join(missing_traffic_lights)}."
        )
    missing_junction_ids = sorted(
        set(corridor.junction_node_ids) - network_junction_ids
    )
    if missing_junction_ids:
        raise ValueError(
            "Selected junction IDs are missing from the SUMO network: "
            f"{', '.join(missing_junction_ids)}."
        )


def validate_selected_corridor(corridor: SelectedCorridor) -> None:
    """Raise a readable error unless a corridor is the audited Candidate 1 selection.

    Validation only reads project data. It never writes the SUMO network,
    configuration, demand, polygon, additional, or wizard source files.
    """
    _validate_structure(corridor)
    _validate_audit_data(corridor)
    _validate_sumo_files(corridor)


def _build_selected_corridor() -> SelectedCorridor:
    """Construct Candidate 1 entirely from existing project data."""
    candidate = get_candidate(_EXPECTED_CANDIDATE_ID)
    records = _load_audit_records()
    missing_agents = [
        agent_id for agent_id in candidate.agent_ids if agent_id not in records
    ]
    if missing_agents:
        raise ValueError(
            "Candidate 1 agents are missing from the traffic-light audit: "
            f"{', '.join(missing_agents)}."
        )
    agent_mapping = {
        agent_id: records[agent_id].traffic_light_id for agent_id in candidate.agent_ids
    }
    reverse_mapping = {
        traffic_light_id: agent_id
        for agent_id, traffic_light_id in agent_mapping.items()
    }
    neighbor_map, neighbor_distances = _load_selected_neighbors(
        candidate.agent_ids,
        agent_mapping,
    )
    configuration_file = SKOPJE_INITIAL_SUMO_CONFIG_FILE
    network_files = _configured_paths(configuration_file, "net-file")
    if len(network_files) != 1:
        raise ValueError(
            "The Skopje SUMO configuration must define exactly one network file."
        )

    corridor = SelectedCorridor(
        name="Selected Central Skopje Corridor",
        candidate_id=candidate.candidate_id,
        description=candidate.description,
        agent_ids=candidate.agent_ids,
        traffic_light_ids=tuple(
            agent_mapping[agent_id] for agent_id in candidate.agent_ids
        ),
        junction_node_ids=tuple(
            junction_id
            for agent_id in candidate.agent_ids
            for junction_id in records[agent_id].junction_node_ids
        ),
        agent_to_traffic_light=MappingProxyType(agent_mapping),
        traffic_light_to_agent=MappingProxyType(reverse_mapping),
        road_names_by_agent=MappingProxyType(
            {agent_id: records[agent_id].road_names for agent_id in candidate.agent_ids}
        ),
        warnings_by_agent=MappingProxyType(
            {agent_id: records[agent_id].warnings for agent_id in candidate.agent_ids}
        ),
        neighbor_map=neighbor_map,
        neighbor_distances_m=neighbor_distances,
        network_file=network_files[0],
        route_files=_configured_paths(configuration_file, "route-files"),
        configuration_file=configuration_file,
    )
    validate_selected_corridor(corridor)
    return corridor


SELECTED_CORRIDOR = _build_selected_corridor()


__all__ = [
    "SELECTED_CORRIDOR",
    "SelectedCorridor",
    "is_connected",
    "junction_node_ids_by_agent",
    "nearest_neighbor_ids",
    "phase_counts_by_agent",
    "validate_selected_corridor",
]

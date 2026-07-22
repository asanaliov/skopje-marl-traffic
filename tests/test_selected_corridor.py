"""Tests for the official audited Skopje corridor selection."""

from __future__ import annotations

import gzip
import hashlib
import importlib
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import src.environment.selected_corridor as selected_corridor_module
from src.config import PROJECT_ROOT
from src.environment.corridor_candidates import load_agent_traffic_light_mapping
from src.environment.selected_corridor import (
    SELECTED_CORRIDOR,
    is_connected,
    validate_selected_corridor,
)


EXPECTED_AGENT_IDS = ("A9", "A18", "A19", "A20", "A24", "A25", "A26", "A29")
ORIGINAL_SUMO_DIRECTORIES = (
    PROJECT_ROOT / "sumo" / "skopje" / "network",
    PROJECT_ROOT / "sumo" / "skopje" / "demand",
    PROJECT_ROOT / "sumo" / "skopje" / "config",
    PROJECT_ROOT / "sumo" / "skopje" / "polygons",
    PROJECT_ROOT / "sumo" / "skopje" / "additional",
    PROJECT_ROOT / "sumo" / "skopje" / "source",
)


@pytest.fixture(scope="module")
def network_ids() -> tuple[set[str], set[str]]:
    """Read traffic-light and junction IDs once for network-backed tests."""
    network_file = SELECTED_CORRIDOR.network_file
    opener = gzip.open if network_file.suffix == ".gz" else open
    traffic_light_ids: set[str] = set()
    junction_ids: set[str] = set()

    with opener(network_file, "rb") as xml_file:
        for _, element in ET.iterparse(xml_file, events=("end",)):
            element_id = element.get("id")
            if element.tag == "tlLogic" and element_id:
                traffic_light_ids.add(element_id)
            elif element.tag == "junction" and element_id:
                junction_ids.add(element_id)
            element.clear()
    return traffic_light_ids, junction_ids


def _original_sumo_hashes() -> dict[Path, str]:
    """Hash every organized input and preserved wizard source file."""
    source_files = sorted(
        path
        for directory in ORIGINAL_SUMO_DIRECTORIES
        for path in directory.rglob("*")
        if path.is_file()
    )
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files
    }


def test_exactly_eight_selected_agents() -> None:
    assert len(SELECTED_CORRIDOR.agent_ids) == 8


def test_expected_agent_id_tuple() -> None:
    assert SELECTED_CORRIDOR.candidate_id == "1"
    assert SELECTED_CORRIDOR.agent_ids == EXPECTED_AGENT_IDS


def test_agent_ids_are_unique() -> None:
    assert len(SELECTED_CORRIDOR.agent_ids) == len(set(SELECTED_CORRIDOR.agent_ids))


def test_traffic_light_ids_are_unique() -> None:
    assert len(SELECTED_CORRIDOR.traffic_light_ids) == len(
        set(SELECTED_CORRIDOR.traffic_light_ids)
    )


def test_agent_mappings_match_the_audit() -> None:
    audited_mapping = load_agent_traffic_light_mapping()

    assert dict(SELECTED_CORRIDOR.agent_to_traffic_light) == {
        agent_id: audited_mapping[agent_id] for agent_id in SELECTED_CORRIDOR.agent_ids
    }


def test_traffic_light_to_agent_reverse_mapping() -> None:
    assert dict(SELECTED_CORRIDOR.traffic_light_to_agent) == {
        traffic_light_id: agent_id
        for agent_id, traffic_light_id in SELECTED_CORRIDOR.agent_to_traffic_light.items()
    }


def test_selected_traffic_light_ids_exist_in_network(
    network_ids: tuple[set[str], set[str]],
) -> None:
    traffic_light_ids, _ = network_ids

    assert set(SELECTED_CORRIDOR.traffic_light_ids) <= traffic_light_ids


def test_selected_junction_ids_exist_in_network(
    network_ids: tuple[set[str], set[str]],
) -> None:
    _, junction_ids = network_ids

    assert set(SELECTED_CORRIDOR.junction_node_ids) <= junction_ids


def test_neighbors_are_selected_and_never_self_references() -> None:
    selected_agents = set(SELECTED_CORRIDOR.agent_ids)

    for source, targets in SELECTED_CORRIDOR.neighbor_map.items():
        assert source in selected_agents
        assert source not in targets
        assert set(targets) <= selected_agents


def test_selected_graph_is_connected() -> None:
    assert is_connected(SELECTED_CORRIDOR)


def test_neighbor_distances_are_non_negative() -> None:
    assert all(
        distance >= 0 for distance in SELECTED_CORRIDOR.neighbor_distances_m.values()
    )


def test_selected_corridor_ordering_is_deterministic() -> None:
    agent_order = {
        agent_id: index for index, agent_id in enumerate(SELECTED_CORRIDOR.agent_ids)
    }
    expected_relationship_order = tuple(
        (source, target)
        for source in SELECTED_CORRIDOR.agent_ids
        for target in SELECTED_CORRIDOR.neighbor_map[source]
    )

    assert tuple(SELECTED_CORRIDOR.agent_to_traffic_light) == EXPECTED_AGENT_IDS
    assert tuple(SELECTED_CORRIDOR.traffic_light_to_agent) == (
        SELECTED_CORRIDOR.traffic_light_ids
    )
    assert tuple(SELECTED_CORRIDOR.neighbor_map) == EXPECTED_AGENT_IDS
    assert tuple(SELECTED_CORRIDOR.neighbor_distances_m) == expected_relationship_order
    for targets in SELECTED_CORRIDOR.neighbor_map.values():
        assert list(targets) == sorted(targets, key=agent_order.__getitem__)


def test_required_scenario_files_exist() -> None:
    assert SELECTED_CORRIDOR.network_file.is_file()
    assert SELECTED_CORRIDOR.configuration_file.is_file()
    assert SELECTED_CORRIDOR.route_files
    assert all(route_file.is_file() for route_file in SELECTED_CORRIDOR.route_files)


def test_duplicate_agent_configuration_is_rejected() -> None:
    invalid = replace(
        SELECTED_CORRIDOR,
        agent_ids=(*SELECTED_CORRIDOR.agent_ids[:-1], SELECTED_CORRIDOR.agent_ids[0]),
    )

    with pytest.raises(ValueError, match="duplicate agent IDs"):
        validate_selected_corridor(invalid)


def test_unknown_neighbor_configuration_is_rejected() -> None:
    neighbor_map = dict(SELECTED_CORRIDOR.neighbor_map)
    neighbor_map["A9"] = (*neighbor_map["A9"], "A999")
    distances = dict(SELECTED_CORRIDOR.neighbor_distances_m)
    distances[("A9", "A999")] = 1.0
    invalid = replace(
        SELECTED_CORRIDOR,
        neighbor_map=MappingProxyType(neighbor_map),
        neighbor_distances_m=MappingProxyType(distances),
    )

    with pytest.raises(ValueError, match="unknown selected neighbor A999"):
        validate_selected_corridor(invalid)


def test_disconnected_configuration_is_rejected() -> None:
    invalid = replace(
        SELECTED_CORRIDOR,
        neighbor_map=MappingProxyType(
            {agent_id: () for agent_id in SELECTED_CORRIDOR.agent_ids}
        ),
        neighbor_distances_m=MappingProxyType({}),
    )

    with pytest.raises(ValueError, match="must be connected"):
        validate_selected_corridor(invalid)


def test_import_and_validation_do_not_modify_original_sumo_files() -> None:
    hashes_before = _original_sumo_hashes()

    reloaded_module = importlib.reload(selected_corridor_module)
    reloaded_module.validate_selected_corridor(reloaded_module.SELECTED_CORRIDOR)

    assert _original_sumo_hashes() == hashes_before

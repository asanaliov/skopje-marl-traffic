"""Tests for the organized Skopje scenario and its documentation."""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.inspect_skopje_network import NetworkStats, render_network_summary
from src.config import (
    SKOPJE_CONFIG_DIR,
    SKOPJE_DEMAND_DIR,
    SKOPJE_INITIAL_CONFIG,
    SKOPJE_INITIAL_SUMO_CONFIG_FILE,
    SKOPJE_INITIAL_VIEW_FILE,
    SKOPJE_NETWORK_DIR,
    resolve_sumo_xml_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRAFFIC_LIGHTS_FILE = (
    PROJECT_ROOT / "sumo" / "skopje" / "documentation" / "traffic_lights.csv"
)
EXPECTED_TRAFFIC_LIGHT_COLUMNS = [
    "agent_id",
    "traffic_light_id",
    "node_count",
    "controlled_lane_count",
    "controlled_link_count",
    "neighbor_ids",
    "enabled",
    "notes",
]


@pytest.mark.parametrize(
    "scenario_path",
    (
        SKOPJE_INITIAL_CONFIG.net_file,
        SKOPJE_INITIAL_CONFIG.route_file,
        SKOPJE_INITIAL_SUMO_CONFIG_FILE,
        SKOPJE_INITIAL_VIEW_FILE,
        SKOPJE_NETWORK_DIR,
        SKOPJE_DEMAND_DIR,
        SKOPJE_CONFIG_DIR,
    ),
)
def test_skopje_paths_are_absolute_and_resolved(scenario_path: Path) -> None:
    assert scenario_path.is_absolute()
    assert scenario_path == scenario_path.resolve()


def test_expected_skopje_configuration_files_exist() -> None:
    expected_files = (
        SKOPJE_INITIAL_CONFIG.net_file,
        SKOPJE_INITIAL_CONFIG.route_file,
        SKOPJE_INITIAL_SUMO_CONFIG_FILE,
        SKOPJE_INITIAL_VIEW_FILE,
        SKOPJE_DEMAND_DIR / "skopje_initial.rou.xml",
    )

    for expected_file in expected_files:
        assert expected_file.is_file(), f"Missing scenario file: {expected_file}"


def test_sumocfg_references_existing_relative_files() -> None:
    root = ET.parse(SKOPJE_INITIAL_SUMO_CONFIG_FILE).getroot()
    reference_elements = (
        root.find("input/net-file"),
        root.find("input/route-files"),
        root.find("input/additional-files"),
        root.find("gui_only/gui-settings-file"),
    )

    for element in reference_elements:
        assert element is not None
        value = element.get("value")
        assert value
        for reference in value.split(","):
            referenced_path = Path(reference)
            assert not referenced_path.is_absolute()
            assert "\\" not in reference
            resolved_path = (SKOPJE_INITIAL_SUMO_CONFIG_FILE.parent / reference).resolve()
            assert resolved_path.is_file(), f"Broken SUMO reference: {reference}"


def test_traffic_light_inventory_columns_and_ids_are_unique() -> None:
    with TRAFFIC_LIGHTS_FILE.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = list(reader)

    assert reader.fieldnames == EXPECTED_TRAFFIC_LIGHT_COLUMNS
    assert rows

    agent_ids = [row["agent_id"] for row in rows]
    traffic_light_ids = [row["traffic_light_id"] for row in rows]
    assert len(agent_ids) == len(set(agent_ids))
    assert len(traffic_light_ids) == len(set(traffic_light_ids))
    assert agent_ids == [f"A{index}" for index in range(1, len(rows) + 1)]


def test_network_summary_handles_missing_optional_polygon(tmp_path: Path) -> None:
    stats = NetworkStats(
        node_count=1,
        edge_count=2,
        lane_count=2,
        passenger_edge_count=2,
        controlled_junction_count=0,
        boundary=(0.0, 0.0, 10.0, 10.0),
        geographic_boundary=None,
        edge_types=(("highway.residential", 2),),
        traffic_lights=(),
    )

    summary = render_network_summary(
        stats,
        SKOPJE_INITIAL_CONFIG.net_file,
        SKOPJE_INITIAL_CONFIG.route_file,
        tmp_path / "missing.poly.xml",
    )

    assert "- Polygons exist: no." in summary
    assert "- No traffic-light controllers were detected." in summary


def test_resolve_sumo_xml_file_supports_uncompressed_file(tmp_path: Path) -> None:
    network_file = tmp_path / "example.net.xml"
    network_file.write_text("<net/>", encoding="utf-8")

    assert resolve_sumo_xml_file(tmp_path, network_file.name) == network_file.resolve()


def test_resolve_sumo_xml_file_prefers_compressed_file(tmp_path: Path) -> None:
    uncompressed_file = tmp_path / "example.net.xml"
    compressed_file = tmp_path / "example.net.xml.gz"
    uncompressed_file.write_text("<net/>", encoding="utf-8")
    compressed_file.write_bytes(b"compressed placeholder")

    assert resolve_sumo_xml_file(tmp_path, uncompressed_file.name) == (
        compressed_file.resolve()
    )

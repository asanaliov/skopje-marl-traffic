"""Unit tests for reproducible synthetic Skopje traffic demand."""

from __future__ import annotations

import hashlib
import json
import random
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.config import PROJECT_ROOT
from src.demand.network_routes import (
    RouteAssignment,
    RouteCandidate,
    RouteSelectionError,
    calculate_route_length,
    calculate_trip_split,
    find_valid_shortest_route,
    passenger_compatible_edges,
    selected_agents_crossed,
)
from src.demand.scenarios import (
    HIGH,
    LOW,
    MEDIUM,
    SCENARIOS,
    TrafficDemandScenario,
    get_scenario,
)
from src.demand.xml_writer import (
    SYNTHETIC_DEMAND_STATEMENT,
    build_generation_metadata,
    scenario_output_files,
    schedule_trips,
    write_generation_metadata,
    write_scenario_configuration,
    write_trips_file,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR


class FakeEdge:
    """Small sumolib-edge substitute for route unit tests."""

    def __init__(
        self,
        edge_id: str,
        length: float,
        *,
        allows_passenger: bool = True,
        special: bool = False,
    ) -> None:
        self.edge_id = edge_id
        self.length = length
        self.allows_passenger = allows_passenger
        self.special = special

    def getID(self) -> str:
        return self.edge_id

    def getLength(self) -> float:
        return self.length

    def allows(self, vehicle_class: str) -> bool:
        return vehicle_class == "passenger" and self.allows_passenger

    def isSpecial(self) -> bool:
        return self.special


class FakeNetwork:
    """Small shortest-path network substitute with explicit edge-pair paths."""

    def __init__(
        self,
        edges: tuple[FakeEdge, ...],
        paths: dict[tuple[str, str], tuple[FakeEdge, ...]],
    ) -> None:
        self.edges = edges
        self.paths = paths

    def getEdges(self) -> tuple[FakeEdge, ...]:
        return self.edges

    def getShortestPath(
        self,
        origin: FakeEdge,
        destination: FakeEdge,
        **_: object,
    ) -> tuple[tuple[FakeEdge, ...] | None, float]:
        path = self.paths.get((origin.getID(), destination.getID()))
        if path is None:
            return None, float("inf")
        return path, calculate_route_length(path)


def _scenario(total_vehicle_count: int = 3, seed: int = 42) -> TrafficDemandScenario:
    return TrafficDemandScenario(
        name="fixture",
        duration_seconds=60,
        total_vehicle_count=total_vehicle_count,
        corridor_trip_share=2 / 3,
        minimum_selected_agents_crossed=1,
        minimum_route_length_m=10.0,
        seed=seed,
        vehicle_type="passenger",
    )


def _assignments() -> tuple[RouteAssignment, ...]:
    routes = (
        RouteCandidate(
            "edge-a",
            "edge-b",
            ("edge-a", "edge-mid", "edge-b"),
            100.0,
            ("A9",),
        ),
        RouteCandidate("edge-c", "edge-d", ("edge-c", "edge-d"), 200.0, ("A18",)),
        RouteCandidate("edge-e", "edge-f", ("edge-e", "edge-f"), 300.0, ()),
    )
    return (
        RouteAssignment(routes[0], True),
        RouteAssignment(routes[1], True),
        RouteAssignment(routes[2], False),
    )


def _original_sumo_files() -> tuple[Path, ...]:
    directories = (
        PROJECT_ROOT / "sumo" / "skopje" / "network",
        PROJECT_ROOT / "sumo" / "skopje" / "polygons",
        PROJECT_ROOT / "sumo" / "skopje" / "additional",
        PROJECT_ROOT / "sumo" / "skopje" / "source",
    )
    files = [
        path
        for directory in directories
        for path in directory.rglob("*")
        if path.is_file()
    ]
    files.extend(
        path
        for directory in (
            PROJECT_ROOT / "sumo" / "skopje" / "demand",
            PROJECT_ROOT / "sumo" / "skopje" / "config",
        )
        for path in directory.glob("*")
        if path.is_file()
    )
    return tuple(sorted(files))


def _file_hashes(paths: tuple[Path, ...]) -> dict[Path, str]:
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_canonical_scenario_names_values_and_order() -> None:
    assert tuple(SCENARIOS) == ("low", "medium", "high")
    assert get_scenario("LOW") is LOW
    assert LOW.total_vehicle_count == 900
    assert LOW.corridor_trip_share == 0.70
    assert LOW.minimum_selected_agents_crossed == 1
    assert MEDIUM.total_vehicle_count == 1800
    assert MEDIUM.corridor_trip_share == 0.80
    assert MEDIUM.minimum_selected_agents_crossed == 2
    assert HIGH.total_vehicle_count == 3000
    assert HIGH.corridor_trip_share == 0.85
    assert HIGH.minimum_selected_agents_crossed == 2
    for scenario in SCENARIOS.values():
        assert scenario.duration_seconds == 3600
        assert scenario.minimum_route_length_m == 300.0
        assert scenario.seed == 42
        assert scenario.vehicle_type == "passenger"


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "error_text"),
    (
        ("name", "", "Scenario name"),
        ("duration_seconds", 0, "duration_seconds"),
        ("total_vehicle_count", 0, "total_vehicle_count"),
        ("corridor_trip_share", 0.0, "corridor_trip_share"),
        ("corridor_trip_share", 1.1, "corridor_trip_share"),
        ("minimum_selected_agents_crossed", 0, "minimum_selected_agents_crossed"),
        ("minimum_route_length_m", 0.0, "minimum_route_length_m"),
        ("seed", -1, "seed"),
        ("vehicle_type", "bus", "passenger"),
    ),
)
def test_invalid_scenario_values_are_rejected(
    field_name: str,
    invalid_value: object,
    error_text: str,
) -> None:
    with pytest.raises(ValueError, match=error_text):
        replace(LOW, **{field_name: invalid_value})


def test_low_medium_high_vehicle_counts_increase() -> None:
    assert (
        LOW.total_vehicle_count < MEDIUM.total_vehicle_count < HIGH.total_vehicle_count
    )


def test_corridor_background_split_calculation() -> None:
    assert calculate_trip_split(900, 0.70) == (630, 270)
    assert calculate_trip_split(1800, 0.80) == (1440, 360)
    assert calculate_trip_split(3000, 0.85) == (2550, 450)


def test_passenger_compatible_edge_filtering() -> None:
    valid = FakeEdge("valid", 100)
    internal = FakeEdge(":internal", 10)
    special = FakeEdge("special", 10, special=True)
    bicycle = FakeEdge("bicycle", 100, allows_passenger=False)
    network = FakeNetwork((bicycle, valid, special, internal), {})

    assert passenger_compatible_edges(network) == (valid,)


def test_route_length_and_selected_agent_crossing_detection() -> None:
    edges = (FakeEdge("a", 100), FakeEdge("b", 150), FakeEdge("c", 75))
    edge_to_agents = {"a": ("A9",), "b": ("A18",), "c": ("A9",)}

    assert calculate_route_length(edges) == 325
    assert selected_agents_crossed(("a", "b", "c"), edge_to_agents) == (
        "A9",
        "A18",
    )


def test_disconnected_route_is_rejected() -> None:
    origin = FakeEdge("origin", 100)
    destination = FakeEdge("destination", 100)
    network = FakeNetwork((origin, destination), {})

    with pytest.raises(RouteSelectionError, match="No passenger route"):
        find_valid_shortest_route(network, origin, destination, 100, 0, {})


def test_route_below_minimum_distance_is_rejected() -> None:
    origin = FakeEdge("origin", 40)
    destination = FakeEdge("destination", 50)
    network = FakeNetwork(
        (origin, destination),
        {("origin", "destination"): (origin, destination)},
    )

    with pytest.raises(RouteSelectionError, match="below the required"):
        find_valid_shortest_route(network, origin, destination, 100, 0, {})


def test_seeded_scheduling_is_reproducible() -> None:
    scenario = _scenario()

    first = schedule_trips(scenario, _assignments(), random.Random(42))
    second = schedule_trips(scenario, _assignments(), random.Random(42))

    assert first == second
    assert [trip.vehicle_id for trip in first] == [
        "fixture_000000",
        "fixture_000001",
        "fixture_000002",
    ]
    assert [trip.departure_time for trip in first] == sorted(
        trip.departure_time for trip in first
    )


def test_trip_xml_is_valid_and_same_seed_is_byte_identical(tmp_path: Path) -> None:
    scenario = _scenario()
    first_file = tmp_path / "first.trips.xml"
    second_file = tmp_path / "second.trips.xml"
    first = schedule_trips(scenario, _assignments(), random.Random(42))
    second = schedule_trips(scenario, _assignments(), random.Random(42))

    write_trips_file(first_file, scenario, first)
    write_trips_file(second_file, scenario, second)

    assert first_file.read_bytes() == second_file.read_bytes()
    assert b"\r\n" not in first_file.read_bytes()
    root = ET.parse(first_file).getroot()
    assert root.tag == "routes"
    assert len(root.findall("trip")) == 3
    assert all(trip.get("from") != trip.get("to") for trip in root.findall("trip"))
    assert any(trip.get("via") == "edge-mid" for trip in root.findall("trip"))


def test_different_seeds_produce_different_trip_xml(tmp_path: Path) -> None:
    scenario = _scenario()
    first_file = tmp_path / "first.trips.xml"
    second_file = tmp_path / "second.trips.xml"

    write_trips_file(
        first_file,
        scenario,
        schedule_trips(scenario, _assignments(), random.Random(42)),
    )
    write_trips_file(
        second_file,
        scenario,
        schedule_trips(scenario, _assignments(), random.Random(43)),
    )

    assert first_file.read_bytes() != second_file.read_bytes()


def test_generated_configuration_uses_relative_valid_paths(tmp_path: Path) -> None:
    network_file = tmp_path / "network" / "fixture.net.xml"
    route_file = tmp_path / "demand" / "fixture.rou.xml"
    polygon_file = tmp_path / "polygons" / "fixture.poly.xml"
    view_file = tmp_path / "config" / "fixture.view.xml"
    configuration_file = tmp_path / "config" / "scenarios" / "fixture.sumocfg"
    for path in (network_file, route_file, polygon_file, view_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<fixture />\n", encoding="utf-8")

    write_scenario_configuration(
        configuration_file,
        _scenario(),
        network_file,
        route_file,
        polygon_file,
        view_file,
    )

    assert b"\r\n" not in configuration_file.read_bytes()
    root = ET.parse(configuration_file).getroot()
    for element_path in (
        "input/net-file",
        "input/route-files",
        "input/additional-files",
        "gui_only/gui-settings-file",
    ):
        value = root.find(element_path).get("value", "")  # type: ignore[union-attr]
        assert not Path(value).is_absolute()
        assert (configuration_file.parent / value).resolve().is_file()
    assert root.find("time/end").get("value") == "60"  # type: ignore[union-attr]


def test_scenario_output_paths_are_deterministic(tmp_path: Path) -> None:
    first = scenario_output_files("medium", 42, tmp_path, tmp_path / "configs")
    second = scenario_output_files("medium", 42, tmp_path, tmp_path / "configs")

    assert first == second
    assert first.trips_file == tmp_path / "medium" / "seed_42.trips.xml"
    assert first.route_file == tmp_path / "medium" / "seed_42.rou.xml"


def test_generation_metadata_schema_and_stable_fields(tmp_path: Path) -> None:
    network_file = tmp_path / "fixture.net.xml"
    network_file.write_bytes(b"network")
    generated_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    metadata = build_generation_metadata(
        _scenario(),
        SELECTED_CORRIDOR,
        network_file,
        _assignments(),
        corridor_trip_count=2,
        background_trip_count=1,
        generated_at=generated_at,
    )
    metadata_file = tmp_path / "metadata.json"
    write_generation_metadata(metadata_file, metadata)
    loaded = json.loads(metadata_file.read_text(encoding="utf-8"))

    assert loaded["scenario"] == "fixture"
    assert loaded["seed"] == 42
    assert loaded["requested_vehicle_count"] == 3
    assert loaded["generated_vehicle_count"] == 3
    assert loaded["corridor_trip_count"] == 2
    assert loaded["background_trip_count"] == 1
    assert loaded["selected_agent_ids"] == list(SELECTED_CORRIDOR.agent_ids)
    assert loaded["synthetic_demand_notice"] == SYNTHETIC_DEMAND_STATEMENT
    assert loaded["generated_at_utc"] == "2026-01-02T03:04:00+00:00"


def test_writers_do_not_modify_original_sumo_sources(tmp_path: Path) -> None:
    original_files = _original_sumo_files()
    hashes_before = _file_hashes(original_files)
    scenario = _scenario()
    trips = schedule_trips(scenario, _assignments(), random.Random(42))

    write_trips_file(tmp_path / "fixture.trips.xml", scenario, trips)

    assert _file_hashes(original_files) == hashes_before

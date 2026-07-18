"""Tests for candidate definitions, selections, launchers, and summaries."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.generate_candidate_selections import (
    REVIEW_CRITERIA,
    render_selection,
    review_file_for,
    selection_file_for,
)
from scripts.open_candidate_in_netedit import (
    build_netedit_command,
    parse_args as parse_netedit_args,
)
from scripts.run_candidate_review import (
    build_sumo_command,
    parse_args as parse_review_args,
)
from scripts.summarize_candidates import calculate_candidate_summary
from src.config import (
    SKOPJE_INITIAL_CONFIG,
    SKOPJE_INITIAL_SUMO_CONFIG_FILE,
)
from src.environment.corridor_candidates import (
    CORRIDOR_CANDIDATES,
    CorridorCandidate,
    get_candidate,
    load_agent_traffic_light_mapping,
    validate_candidates,
)


def read_network_ids(network_file: Path) -> tuple[set[str], set[str], set[str]]:
    """Read edge, junction, and traffic-light IDs in one lightweight XML pass."""
    opener = gzip.open if network_file.suffix == ".gz" else open
    edge_ids: set[str] = set()
    junction_ids: set[str] = set()
    traffic_light_ids: set[str] = set()

    with opener(network_file, "rb") as xml_file:
        for _, element in ET.iterparse(xml_file, events=("end",)):
            element_id = element.get("id")
            if element.tag == "edge" and element_id:
                edge_ids.add(element_id)
            elif element.tag == "junction" and element_id:
                junction_ids.add(element_id)
            elif element.tag == "tlLogic" and element_id:
                traffic_light_ids.add(element_id)
            element.clear()
    return edge_ids, junction_ids, traffic_light_ids


def test_candidate_mappings_match_the_audit() -> None:
    mapping = load_agent_traffic_light_mapping()

    validate_candidates(CORRIDOR_CANDIDATES, mapping)
    for candidate in CORRIDOR_CANDIDATES:
        assert candidate.traffic_light_ids == tuple(
            mapping[agent_id] for agent_id in candidate.agent_ids
        )


def test_every_candidate_has_six_to_ten_unique_agents() -> None:
    for candidate in CORRIDOR_CANDIDATES:
        assert 6 <= len(candidate.agent_ids) <= 10
        assert len(candidate.agent_ids) == len(set(candidate.agent_ids))
        assert len(candidate.traffic_light_ids) == len(set(candidate.traffic_light_ids))


def test_no_candidate_references_unknown_network_traffic_lights() -> None:
    _, _, network_traffic_lights = read_network_ids(SKOPJE_INITIAL_CONFIG.net_file)

    for candidate in CORRIDOR_CANDIDATES:
        assert set(candidate.traffic_light_ids) <= network_traffic_lights


def test_selection_rendering_is_deterministic_and_unique() -> None:
    first = render_selection(
        ["junction-b", "junction-a", "junction-a"],
        ["edge-b", "edge-a", "edge-b"],
    )
    second = render_selection(
        ["junction-a", "junction-b"],
        ["edge-a", "edge-b"],
    )

    assert first == second
    assert first.splitlines() == [
        "junction:junction-a",
        "junction:junction-b",
        "edge:edge-a",
        "edge:edge-b",
    ]


def test_generated_selections_reference_valid_network_elements() -> None:
    edge_ids, junction_ids, _ = read_network_ids(SKOPJE_INITIAL_CONFIG.net_file)

    for candidate in CORRIDOR_CANDIDATES:
        selection_file = selection_file_for(candidate)
        assert selection_file.is_file()
        lines = selection_file.read_text(encoding="utf-8").splitlines()
        assert lines
        assert len(lines) == len(set(lines))
        junction_lines = [line for line in lines if line.startswith("junction:")]
        edge_lines = [line for line in lines if line.startswith("edge:")]
        assert lines == [*sorted(junction_lines), *sorted(edge_lines)]
        for line in lines:
            element_type, separator, element_id = line.partition(":")
            assert separator == ":"
            if element_type == "edge":
                assert element_id in edge_ids
            elif element_type == "junction":
                assert element_id in junction_ids
            else:
                pytest.fail(f"Unsupported selection element type: {element_type}")


def test_launcher_command_construction() -> None:
    executable = Path("C:/SUMO/bin/netedit.exe")
    network_file = Path("sumo/skopje/network/skopje_initial.net.xml.gz")
    selection_file = Path("sumo/skopje/selections/candidate_1.txt")

    assert build_netedit_command(executable, network_file, selection_file) == [
        str(executable),
        "--sumo-net-file",
        str(network_file),
        "--selection-file",
        str(selection_file),
    ]
    assert build_sumo_command(Path("sumo"), 600, 42) == [
        "sumo",
        "-c",
        str(SKOPJE_INITIAL_SUMO_CONFIG_FILE),
        "--end",
        "600",
        "--seed",
        "42",
    ]


def test_invalid_candidate_arguments_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown candidate"):
        get_candidate("4")
    with pytest.raises(SystemExit) as netedit_error:
        parse_netedit_args(["--candidate", "4"])
    with pytest.raises(SystemExit) as review_error:
        parse_review_args(["--candidate", "0"])

    assert netedit_error.value.code == 2
    assert review_error.value.code == 2


def test_review_documents_include_all_required_criteria() -> None:
    for candidate in CORRIDOR_CANDIDATES:
        review_file = review_file_for(candidate)
        assert review_file.is_file()
        document = review_file.read_text(encoding="utf-8")
        assert all(agent_id in document for agent_id in candidate.agent_ids)
        assert all(
            traffic_light_id in document
            for traffic_light_id in candidate.traffic_light_ids
        )
        for criterion in REVIEW_CRITERIA:
            assert f"| {criterion} | | |" in document


def test_candidate_summary_calculates_counts_from_small_fixtures() -> None:
    candidate = CorridorCandidate(
        candidate_id="fixture",
        name="Fixture candidate",
        agent_ids=("A1", "A2"),
        traffic_light_ids=("tls-1", "tls-2"),
        description="Test fixture",
    )
    audits = {
        "A1": {"phase_count": "4", "warnings": "", "road_names": "Road"},
        "A2": {"phase_count": "6", "warnings": "Review", "road_names": ""},
    }
    neighbors = [
        {
            "source_agent_id": "A1",
            "target_agent_id": "A2",
            "network_distance_m": "100",
            "direct_corridor": "true",
            "bidirectional": "true",
        },
        {
            "source_agent_id": "A2",
            "target_agent_id": "A1",
            "network_distance_m": "120",
            "direct_corridor": "false",
            "bidirectional": "true",
        },
        {
            "source_agent_id": "A1",
            "target_agent_id": "A3",
            "network_distance_m": "30",
            "direct_corridor": "true",
            "bidirectional": "false",
        },
    ]

    summary = calculate_candidate_summary(candidate, audits, neighbors)

    assert summary.agent_count == 2
    assert summary.directed_neighbor_count == 2
    assert summary.bidirectional_pair_count == 1
    assert summary.direct_corridor_pair_count == 1
    assert summary.average_neighbor_distance_m == 110
    assert summary.maximum_neighbor_distance_m == 120
    assert summary.warning_count == 1
    assert summary.minimum_phase_count == 4
    assert summary.maximum_phase_count == 6
    assert summary.named_road_coverage == "1/2 (50%)"

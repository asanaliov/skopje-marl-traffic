"""Tests for generated traffic-light audit data and small audit helpers."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from scripts.audit_traffic_lights import (
    AUDIT_COLUMNS,
    NEIGHBOR_COLUMNS,
    agent_sort_key,
    available_road_names,
    extract_phase_program,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTATION_DIR = PROJECT_ROOT / "sumo" / "skopje" / "documentation"
AUDIT_FILE = DOCUMENTATION_DIR / "traffic_light_audit.csv"
NEIGHBORS_FILE = DOCUMENTATION_DIR / "traffic_light_neighbors.csv"
CANDIDATES_FILE = DOCUMENTATION_DIR / "corridor_candidates.md"


class FakePhase:
    """Small phase fixture with the attributes used by the audit."""

    def __init__(self, duration: float, state: str) -> None:
        self.duration = duration
        self.state = state


class FakeProgram:
    """Small signal-program fixture for phase extraction."""

    def __init__(self, program_type: str, phases: list[FakePhase]) -> None:
        self._program_type = program_type
        self._phases = phases

    def getType(self) -> str:
        return self._program_type

    def getPhases(self) -> list[FakePhase]:
        return self._phases


class FakeEdge:
    """Small edge fixture for road-name handling."""

    def __init__(self, name: str) -> None:
        self._name = name

    def getName(self) -> str:
        return self._name


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a generated CSV with its ordered field names."""
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return list(reader.fieldnames or ()), list(reader)


def test_audit_csv_columns_and_stable_unique_ids() -> None:
    fieldnames, rows = read_csv(AUDIT_FILE)

    assert fieldnames == list(AUDIT_COLUMNS)
    assert rows
    agent_ids = [row["agent_id"] for row in rows]
    traffic_light_ids = [row["traffic_light_id"] for row in rows]
    assert agent_ids == [f"A{index}" for index in range(1, len(rows) + 1)]
    assert len(agent_ids) == len(set(agent_ids))
    assert len(traffic_light_ids) == len(set(traffic_light_ids))
    assert all("Phase states:" in row["notes"] for row in rows)


def test_neighbor_csv_references_and_distances_are_valid() -> None:
    audit_fields, audit_rows = read_csv(AUDIT_FILE)
    neighbor_fields, neighbor_rows = read_csv(NEIGHBORS_FILE)
    assert audit_fields == list(AUDIT_COLUMNS)
    assert neighbor_fields == list(NEIGHBOR_COLUMNS)

    agents = {row["agent_id"] for row in audit_rows}
    controllers = {row["traffic_light_id"] for row in audit_rows}
    controller_by_agent = {
        row["agent_id"]: row["traffic_light_id"] for row in audit_rows
    }
    for row in neighbor_rows:
        assert row["source_agent_id"] in agents
        assert row["target_agent_id"] in agents
        assert row["source_traffic_light_id"] in controllers
        assert row["target_traffic_light_id"] in controllers
        assert row["source_agent_id"] != row["target_agent_id"]
        assert row["source_traffic_light_id"] != row["target_traffic_light_id"]
        assert (
            row["source_traffic_light_id"]
            == controller_by_agent[row["source_agent_id"]]
        )
        assert (
            row["target_traffic_light_id"]
            == controller_by_agent[row["target_agent_id"]]
        )
        assert float(row["network_distance_m"]) >= 0


def test_bidirectional_neighbor_rows_are_reciprocal() -> None:
    _, rows = read_csv(NEIGHBORS_FILE)
    by_pair = {(row["source_agent_id"], row["target_agent_id"]): row for row in rows}

    for row in rows:
        if row["bidirectional"] == "true":
            reverse = by_pair[(row["target_agent_id"], row["source_agent_id"])]
            assert reverse["bidirectional"] == "true"


def test_generated_rows_use_deterministic_ordering() -> None:
    _, audit_rows = read_csv(AUDIT_FILE)
    _, neighbor_rows = read_csv(NEIGHBORS_FILE)

    audit_order = [agent_sort_key(row["agent_id"]) for row in audit_rows]
    neighbor_order = [
        (
            agent_sort_key(row["source_agent_id"]),
            agent_sort_key(row["target_agent_id"]),
        )
        for row in neighbor_rows
    ]
    assert audit_order == sorted(audit_order)
    assert neighbor_order == sorted(neighbor_order)


def test_missing_road_names_are_ignored_gracefully() -> None:
    edges = [FakeEdge(""), FakeEdge("  "), FakeEdge("Known Road")]

    assert available_road_names(edges) == ("Known Road",)
    assert available_road_names([FakeEdge("")]) == ()


def test_phase_extraction_uses_stable_program_order() -> None:
    programs = {
        "program-b": FakeProgram("static", [FakePhase(10, "Gr")]),
        "program-a": FakeProgram(
            "actuated",
            [FakePhase(30, "GG"), FakePhase(3, "yy")],
        ),
    }

    phase_program = extract_phase_program(programs)

    assert phase_program.program_id == "program-a"
    assert phase_program.program_type == "actuated"
    assert phase_program.durations == (30.0, 3.0)
    assert phase_program.states == ("GG", "yy")


def test_candidate_groups_contain_only_valid_agents() -> None:
    _, audit_rows = read_csv(AUDIT_FILE)
    valid_agents = {row["agent_id"] for row in audit_rows}
    report = CANDIDATES_FILE.read_text(encoding="utf-8")
    candidate_lines = re.findall(r"^- Agents: (.+)\.$", report, flags=re.MULTILINE)

    assert 1 <= len(candidate_lines) <= 3
    for candidate_line in candidate_lines:
        candidate_agents = candidate_line.split(", ")
        assert 6 <= len(candidate_agents) <= 10
        assert set(candidate_agents) <= valid_agents

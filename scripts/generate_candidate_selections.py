"""Generate deterministic Netedit selections and candidate review sheets."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_traffic_lights import (  # noqa: E402
    ControllerAudit,
    NeighborRelationship,
    WIZARD_WARNING_FILE,
    collect_controller_audits,
    detect_neighbor_relationships,
    load_sumolib,
    read_wizard_controller_warnings,
)
from src.config import SKOPJE_DIR, SKOPJE_INITIAL_CONFIG  # noqa: E402
from src.environment.corridor_candidates import (  # noqa: E402
    CORRIDOR_CANDIDATES,
    CorridorCandidate,
)


SELECTION_DIRECTORY = SKOPJE_DIR / "selections"
REVIEW_DIRECTORY = SKOPJE_DIR / "documentation" / "candidate_reviews"
REVIEW_CRITERIA = (
    "Main-road relevance",
    "Geographic continuity",
    "Intersection spacing",
    "Traffic-light quality",
    "Lane and turn correctness",
    "Manageable complexity",
    "Coordination potential",
    "Visual clarity for presentation",
    "Deadlock-free simulation",
    "Overall suitability",
)


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    """The validated network elements selected for one candidate."""

    candidate: CorridorCandidate
    junction_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    corridor_edge_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def selection_file_for(candidate: CorridorCandidate) -> Path:
    """Return the stable selection-file path for a candidate."""
    return SELECTION_DIRECTORY / f"candidate_{candidate.candidate_id}.txt"


def review_file_for(candidate: CorridorCandidate) -> Path:
    """Return the stable Markdown review-sheet path for a candidate."""
    return REVIEW_DIRECTORY / f"candidate_{candidate.candidate_id}_review.md"


def render_selection(
    junction_ids: Sequence[str],
    edge_ids: Sequence[str],
) -> str:
    """Render the official typed SUMO selection-file format deterministically."""
    unique_junctions = sorted(set(junction_ids))
    unique_edges = sorted(set(edge_ids))
    lines = [
        *(f"junction:{junction_id}" for junction_id in unique_junctions),
        *(f"edge:{edge_id}" for edge_id in unique_edges),
    ]
    return "\n".join(lines) + "\n"


def _candidate_connected(
    candidate: CorridorCandidate,
    relationships: Sequence[NeighborRelationship],
) -> bool:
    """Return whether candidate agents form one undirected neighbor component."""
    candidate_agents = set(candidate.agent_ids)
    adjacency = {agent_id: set() for agent_id in candidate.agent_ids}
    for relationship in relationships:
        source_id = relationship.source_agent_id
        target_id = relationship.target_agent_id
        if source_id in candidate_agents and target_id in candidate_agents:
            adjacency[source_id].add(target_id)
            adjacency[target_id].add(source_id)

    visited: set[str] = set()
    stack = [candidate.agent_ids[0]]
    while stack:
        agent_id = stack.pop()
        if agent_id in visited:
            continue
        visited.add(agent_id)
        stack.extend(adjacency[agent_id] - visited)
    return visited == candidate_agents


def build_candidate_selection(
    candidate: CorridorCandidate,
    audits_by_agent: Mapping[str, ControllerAudit],
    relationships: Sequence[NeighborRelationship],
    network: Any,
) -> CandidateSelection:
    """Collect controlled and connecting passenger-compatible network elements."""
    missing_agents = [
        agent_id for agent_id in candidate.agent_ids if agent_id not in audits_by_agent
    ]
    if missing_agents:
        missing = ", ".join(missing_agents)
        raise ValueError(f"{candidate.name} is missing audited agents: {missing}")

    network_edges = {edge.getID(): edge for edge in network.getEdges()}
    network_nodes = {node.getID() for node in network.getNodes()}
    candidate_agents = set(candidate.agent_ids)
    junction_ids: set[str] = set()
    controlled_edge_ids: set[str] = set()
    omitted_non_passenger_edges: set[str] = set()

    for agent_id, expected_traffic_light_id in zip(
        candidate.agent_ids,
        candidate.traffic_light_ids,
        strict=True,
    ):
        audit = audits_by_agent[agent_id]
        if audit.traffic_light_id != expected_traffic_light_id:
            raise ValueError(
                f"{candidate.name} maps {agent_id} to {expected_traffic_light_id}, "
                f"but the live network maps it to {audit.traffic_light_id}."
            )
        junction_ids.update(audit.junction_node_ids)
        for edge_id in (*audit.incoming_edge_ids, *audit.outgoing_edge_ids):
            edge = network_edges.get(edge_id)
            if edge is None:
                raise ValueError(
                    f"Controlled edge {edge_id!r} for {agent_id} is missing."
                )
            if edge.allows("passenger"):
                controlled_edge_ids.add(edge_id)
            else:
                omitted_non_passenger_edges.add(edge_id)

    corridor_edge_ids = {
        edge_id
        for relationship in relationships
        if relationship.source_agent_id in candidate_agents
        and relationship.target_agent_id in candidate_agents
        for edge_id in relationship.path_edge_ids
    }
    invalid_corridor_edges = {
        edge_id
        for edge_id in corridor_edge_ids
        if edge_id not in network_edges
        or not network_edges[edge_id].allows("passenger")
    }
    if invalid_corridor_edges:
        invalid = ", ".join(sorted(invalid_corridor_edges))
        raise ValueError(
            f"{candidate.name} has invalid passenger corridor edges: {invalid}"
        )

    missing_nodes = junction_ids - network_nodes
    if missing_nodes:
        missing = ", ".join(sorted(missing_nodes))
        raise ValueError(f"{candidate.name} has unknown junction IDs: {missing}")

    warnings = [
        "Netedit has no separate traffic-light-controller selection record; "
        "controlled junctions select the candidate controllers.",
    ]
    if omitted_non_passenger_edges:
        warnings.append(
            "Omitted non-passenger controlled edges: "
            + ", ".join(sorted(omitted_non_passenger_edges))
            + "."
        )
    if not corridor_edge_ids:
        warnings.append("No candidate-to-candidate passenger corridor paths found.")
    if not _candidate_connected(candidate, relationships):
        warnings.append(
            "Candidate agents do not form one connected audited neighbor graph."
        )

    return CandidateSelection(
        candidate=candidate,
        junction_ids=tuple(sorted(junction_ids)),
        edge_ids=tuple(sorted(controlled_edge_ids | corridor_edge_ids)),
        corridor_edge_ids=tuple(sorted(corridor_edge_ids)),
        warnings=tuple(warnings),
    )


def write_selection(output_file: Path, selection: CandidateSelection) -> None:
    """Write one candidate selection without touching the SUMO network."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        render_selection(selection.junction_ids, selection.edge_ids),
        encoding="utf-8",
    )


def _markdown_cell(value: str) -> str:
    """Escape text that would otherwise split a Markdown table cell."""
    return value.replace("|", "\\|").replace("\n", " ")


def _candidate_relationships(
    candidate: CorridorCandidate,
    relationships: Sequence[NeighborRelationship],
) -> tuple[NeighborRelationship, ...]:
    """Return stable directed relationships fully inside a candidate."""
    agent_ids = set(candidate.agent_ids)
    return tuple(
        relationship
        for relationship in relationships
        if relationship.source_agent_id in agent_ids
        and relationship.target_agent_id in agent_ids
    )


def render_review_document(
    selection: CandidateSelection,
    audits_by_agent: Mapping[str, ControllerAudit],
    relationships: Sequence[NeighborRelationship],
) -> str:
    """Render a factual, unscored manual-review sheet for one candidate."""
    candidate = selection.candidate
    candidate_relationships = _candidate_relationships(candidate, relationships)
    outgoing = {agent_id: [] for agent_id in candidate.agent_ids}
    for relationship in candidate_relationships:
        outgoing[relationship.source_agent_id].append(relationship)

    lines = [
        f"# {candidate.name} visual review",
        "",
        "This sheet contains computed audit facts and leaves all visual scores blank.",
        "No candidate is selected by this document.",
        "",
        "## Candidate definition",
        "",
        f"- Agents: {', '.join(candidate.agent_ids)}.",
        "- Traffic-light IDs: "
        + ", ".join(f"`{item}`" for item in candidate.traffic_light_ids)
        + ".",
        f"- Description: {candidate.description}",
        "- Selection file: "
        f"`sumo/skopje/selections/candidate_{candidate.candidate_id}.txt`.",
        "",
        "## Controller facts",
        "",
        "| Agent | Traffic-light ID | Junction node IDs | Road names | Phases | Warnings |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for agent_id in candidate.agent_ids:
        audit = audits_by_agent[agent_id]
        road_names = "; ".join(audit.road_names) or "None in network data"
        warnings = "; ".join(audit.warnings) or "None"
        lines.append(
            f"| {agent_id} | `{_markdown_cell(audit.traffic_light_id)}` | "
            f"{_markdown_cell('; '.join(audit.junction_node_ids))} | "
            f"{_markdown_cell(road_names)} | {audit.phase_count} | "
            f"{_markdown_cell(warnings)} |"
        )

    lines.extend(
        [
            "",
            "## Candidate neighbor adjacency",
            "",
        ]
    )
    for agent_id in candidate.agent_ids:
        neighbors = sorted(
            outgoing[agent_id],
            key=lambda relationship: candidate.agent_ids.index(
                relationship.target_agent_id
            ),
        )
        if neighbors:
            targets = ", ".join(
                f"{relationship.target_agent_id} "
                f"({relationship.network_distance_m:.2f} m)"
                for relationship in neighbors
            )
        else:
            targets = "None detected inside this candidate"
        lines.append(f"- {agent_id} -> {targets}.")

    lines.extend(
        [
            "",
            "## Directed neighbor distances",
            "",
            "| Source | Target | Network distance | Direct corridor | Bidirectional |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for relationship in candidate_relationships:
        lines.append(
            f"| {relationship.source_agent_id} | "
            f"{relationship.target_agent_id} | "
            f"{relationship.network_distance_m:.2f} m | "
            f"{'yes' if relationship.direct_corridor else 'no'} | "
            f"{'yes' if relationship.bidirectional else 'no'} |"
        )

    lines.extend(
        [
            "",
            "## Launch commands",
            "",
            "Generate the candidate agent-label POIs:",
            "",
            "```powershell",
            "python scripts/generate_agent_labels.py",
            "```",
            "",
            "Open the complete network with the candidate selection in Netedit:",
            "",
            "```powershell",
            "python scripts/open_candidate_in_netedit.py "
            f"--candidate {candidate.candidate_id}",
            "```",
            "",
            "After Netedit opens, press F9, open the POI visualization settings, enable Show ID, enable constant text size, and increase the text size if labels such as A9 and A18 are too small.",
            "",
            "Observe the original demand and signal programs in SUMO-GUI:",
            "",
            "```powershell",
            "python scripts/run_candidate_review.py "
            f"--candidate {candidate.candidate_id} --seconds 600 --gui",
            "```",
            "",
            "## Manual scoring",
            "",
            "Leave scores blank until the candidate has been reviewed visually.",
            "",
            "| Criterion | Score 1-5 | Notes |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(f"| {criterion} | | |" for criterion in REVIEW_CRITERIA)
    lines.append("")
    return "\n".join(lines)


def write_review_document(
    output_file: Path,
    selection: CandidateSelection,
    audits_by_agent: Mapping[str, ControllerAudit],
    relationships: Sequence[NeighborRelationship],
) -> None:
    """Write one review sheet without erasing recorded manual evidence."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.is_file() and "## Review evidence" in output_file.read_text(
        encoding="utf-8"
    ):
        return
    output_file.write_text(
        render_review_document(selection, audits_by_agent, relationships),
        encoding="utf-8",
    )


def print_selection_summary(selection: CandidateSelection) -> None:
    """Print the requested review scope and warnings for one candidate."""
    print(f"{selection.candidate.name}:")
    print(f"  agent count: {len(selection.candidate.agent_ids)}")
    print(f"  traffic-light count: {len(selection.candidate.traffic_light_ids)}")
    print(f"  selected junction count: {len(selection.junction_ids)}")
    print(f"  selected edge count: {len(selection.edge_ids)}")
    print(f"  corridor edge count: {len(selection.corridor_edge_ids)}")
    print("  warnings:")
    for warning in selection.warnings:
        print(f"    - {warning}")


def main() -> int:
    """Regenerate all candidate selections and review documents."""
    try:
        SKOPJE_INITIAL_CONFIG.validate_files()
        sumolib = load_sumolib()
        network = sumolib.net.readNet(
            str(SKOPJE_INITIAL_CONFIG.net_file),
            withPrograms=True,
        )
        external_warnings = read_wizard_controller_warnings(WIZARD_WARNING_FILE)
        audits = collect_controller_audits(network, external_warnings)
        audits_by_agent = {audit.agent_id: audit for audit in audits}
        relationships = detect_neighbor_relationships(network, audits)

        for candidate in CORRIDOR_CANDIDATES:
            selection = build_candidate_selection(
                candidate,
                audits_by_agent,
                relationships,
                network,
            )
            write_selection(selection_file_for(candidate), selection)
            write_review_document(
                review_file_for(candidate),
                selection,
                audits_by_agent,
                relationships,
            )
            print_selection_summary(selection)
        return 0
    except Exception as error:
        print(
            f"[ERROR] Candidate selection generation failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

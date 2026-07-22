"""Print the audited definition of the official selected Skopje corridor."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.environment.selected_corridor import SelectedCorridor


def _display_path(path: Path) -> Path:
    """Return a stable project-relative path when the file is in the repository."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _configure_utf8_output() -> None:
    """Allow audited Macedonian road names on Windows console streams."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _bidirectional_pair_count(corridor: SelectedCorridor) -> int:
    """Count unordered agent pairs that have both directed relationships."""
    relationships = set(corridor.neighbor_distances_m)
    return sum(
        1
        for source, target in relationships
        if (target, source) in relationships and source < target
    )


def print_corridor(
    corridor: SelectedCorridor,
    junctions_by_agent: Mapping[str, tuple[str, ...]],
    phase_counts: Mapping[str, int | None],
) -> None:
    """Print corridor metadata, controller facts, and graph summaries."""
    from src.environment.selected_corridor import is_connected

    print(f"Corridor name: {corridor.name}")
    print(f"Candidate ID: {corridor.candidate_id}")
    print(f"Description: {corridor.description}")
    print(f"Number of agents: {len(corridor.agent_ids)}")
    print(f"Network file: {_display_path(corridor.network_file)}")
    print(f"Configuration file: {_display_path(corridor.configuration_file)}")
    print("Route files:")
    for route_file in corridor.route_files:
        print(f"  - {_display_path(route_file)}")

    print("\nSelected agents")
    for agent_id in corridor.agent_ids:
        traffic_light_id = corridor.agent_to_traffic_light[agent_id]
        junction_ids = junctions_by_agent[agent_id]
        road_names = corridor.road_names_by_agent[agent_id]
        warnings = corridor.warnings_by_agent[agent_id]
        neighbors = corridor.neighbor_map[agent_id]
        phase_count = phase_counts[agent_id]

        print(f"\n{agent_id}")
        print(f"  SUMO traffic-light controller ID: {traffic_light_id}")
        print(f"  Junction node ID(s): {', '.join(junction_ids) or 'None recorded'}")
        print(f"  Road names: {'; '.join(road_names) or 'None recorded'}")
        print(
            "  Phase count: "
            f"{phase_count if phase_count is not None else 'Not recorded'}"
        )
        print(f"  Warnings: {'; '.join(warnings) or 'None'}")
        print(f"  Neighboring selected agents: {', '.join(neighbors) or 'None'}")
        print("  Directed network distances:")
        if not neighbors:
            print("    None")
        for neighbor_id in neighbors:
            distance = corridor.neighbor_distances_m[(agent_id, neighbor_id)]
            print(f"    {agent_id} -> {neighbor_id}: {distance:.2f} m")

    print("\nAdjacency list")
    for agent_id in corridor.agent_ids:
        neighbors = corridor.neighbor_map[agent_id]
        print(f"  {agent_id}: {', '.join(neighbors) or 'None'}")

    directed_relationship_count = sum(
        len(neighbors) for neighbors in corridor.neighbor_map.values()
    )
    print(f"\nConnected undirected graph: {'yes' if is_connected(corridor) else 'no'}")
    print(f"Total directed neighbor relationships: {directed_relationship_count}")
    print(f"Bidirectional neighbor-pair count: {_bidirectional_pair_count(corridor)}")


def main() -> int:
    """Load, validate, and display the official selected corridor."""
    _configure_utf8_output()
    try:
        from src.environment.selected_corridor import (
            SELECTED_CORRIDOR,
            junction_node_ids_by_agent,
            phase_counts_by_agent,
            validate_selected_corridor,
        )

        validate_selected_corridor(SELECTED_CORRIDOR)
        print_corridor(
            SELECTED_CORRIDOR,
            junction_node_ids_by_agent(SELECTED_CORRIDOR),
            phase_counts_by_agent(SELECTED_CORRIDOR),
        )
        return 0
    except (FileNotFoundError, OSError, ValueError) as error:
        print(
            f"[ERROR] Could not inspect the selected corridor: {error}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

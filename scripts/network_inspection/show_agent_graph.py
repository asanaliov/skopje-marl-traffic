"""Print the generated Skopje traffic-light adjacency list."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_FILE = (
    PROJECT_ROOT / "sumo" / "skopje" / "documentation" / "traffic_light_audit.csv"
)
NEIGHBORS_FILE = (
    PROJECT_ROOT / "sumo" / "skopje" / "documentation" / "traffic_light_neighbors.csv"
)


def agent_sort_key(agent_id: str) -> tuple[int, str]:
    """Sort conventional A-number identifiers numerically."""
    if agent_id.startswith("A") and agent_id[1:].isdigit():
        return int(agent_id[1:]), agent_id
    return sys.maxsize, agent_id


def read_adjacency(
    audit_file: Path,
    neighbors_file: Path,
) -> dict[str, tuple[str, ...]]:
    """Read all agents and their directed neighbors from generated CSV files."""
    if not audit_file.is_file():
        raise FileNotFoundError(
            f"Traffic-light audit CSV is missing: {audit_file}\n"
            "Run python scripts/network_inspection/audit_traffic_lights.py first."
        )
    if not neighbors_file.is_file():
        raise FileNotFoundError(
            f"Traffic-light neighbor CSV is missing: {neighbors_file}\n"
            "Run python scripts/network_inspection/audit_traffic_lights.py first."
        )

    with audit_file.open(encoding="utf-8", newline="") as csv_file:
        agents = [row["agent_id"] for row in csv.DictReader(csv_file)]
    adjacency: dict[str, set[str]] = {agent_id: set() for agent_id in agents}

    with neighbors_file.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            source = row["source_agent_id"]
            target = row["target_agent_id"]
            if source not in adjacency or target not in adjacency:
                raise ValueError(
                    f"Neighbor row references unknown agents: {source} -> {target}"
                )
            adjacency[source].add(target)

    return {
        agent_id: tuple(sorted(neighbors, key=agent_sort_key))
        for agent_id, neighbors in sorted(
            adjacency.items(),
            key=lambda item: agent_sort_key(item[0]),
        )
    }


def main() -> int:
    """Print one deterministic adjacency-list line per audited agent."""
    try:
        adjacency = read_adjacency(AUDIT_FILE, NEIGHBORS_FILE)
        for agent_id, neighbors in adjacency.items():
            neighbor_text = ", ".join(neighbors) if neighbors else "(none)"
            print(f"{agent_id} -> {neighbor_text}")
        return 0
    except Exception as error:
        print(
            f"[ERROR] Could not show agent graph: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

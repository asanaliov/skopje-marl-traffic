"""Print computed comparisons for the three audited Skopje candidates."""

from __future__ import annotations

import csv
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.inspection.audit_traffic_lights import AUDIT_FILE, NEIGHBORS_FILE  # noqa: E402
from src.environment.corridor_candidates import (  # noqa: E402
    CORRIDOR_CANDIDATES,
    CorridorCandidate,
)


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    """Computed comparison fields for one candidate."""

    name: str
    agent_count: int
    directed_neighbor_count: int
    bidirectional_pair_count: int
    direct_corridor_pair_count: int
    average_neighbor_distance_m: float
    maximum_neighbor_distance_m: float
    warning_count: int
    minimum_phase_count: int
    maximum_phase_count: int
    named_road_count: int

    @property
    def named_road_coverage(self) -> str:
        """Format the count and percentage of agents with named network roads."""
        percentage = 100 * self.named_road_count / self.agent_count
        return f"{self.named_road_count}/{self.agent_count} ({percentage:.0f}%)"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read one generated audit CSV with clear missing-file handling."""
    if not path.is_file():
        raise FileNotFoundError(f"Required audit file is missing: {path}")
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def calculate_candidate_summary(
    candidate: CorridorCandidate,
    audits_by_agent: Mapping[str, Mapping[str, str]],
    neighbor_rows: Sequence[Mapping[str, str]],
) -> CandidateSummary:
    """Calculate candidate graph, warning, phase, and road-name facts."""
    missing_agents = [
        agent_id for agent_id in candidate.agent_ids if agent_id not in audits_by_agent
    ]
    if missing_agents:
        missing = ", ".join(missing_agents)
        raise ValueError(f"{candidate.name} is missing audit rows: {missing}")

    agent_ids = set(candidate.agent_ids)
    candidate_neighbors = [
        row
        for row in neighbor_rows
        if row["source_agent_id"] in agent_ids and row["target_agent_id"] in agent_ids
    ]
    distances = [float(row["network_distance_m"]) for row in candidate_neighbors]
    bidirectional_pairs = {
        frozenset((row["source_agent_id"], row["target_agent_id"]))
        for row in candidate_neighbors
        if row["bidirectional"].strip().lower() == "true"
    }
    direct_corridor_pairs = {
        frozenset((row["source_agent_id"], row["target_agent_id"]))
        for row in candidate_neighbors
        if row["direct_corridor"].strip().lower() == "true"
    }
    audit_rows = [audits_by_agent[agent_id] for agent_id in candidate.agent_ids]
    phase_counts = [int(row["phase_count"]) for row in audit_rows]

    return CandidateSummary(
        name=candidate.name,
        agent_count=len(candidate.agent_ids),
        directed_neighbor_count=len(candidate_neighbors),
        bidirectional_pair_count=len(bidirectional_pairs),
        direct_corridor_pair_count=len(direct_corridor_pairs),
        average_neighbor_distance_m=(
            sum(distances) / len(distances) if distances else 0.0
        ),
        maximum_neighbor_distance_m=max(distances, default=0.0),
        warning_count=sum(bool(row["warnings"].strip()) for row in audit_rows),
        minimum_phase_count=min(phase_counts),
        maximum_phase_count=max(phase_counts),
        named_road_count=sum(bool(row["road_names"].strip()) for row in audit_rows),
    )


def render_summary_table(summaries: Sequence[CandidateSummary]) -> str:
    """Render a dependency-free comparison table for terminal output."""
    headers = (
        "Candidate",
        "Agents",
        "Directed",
        "Bidirectional pairs",
        "Direct pairs",
        "Average distance",
        "Maximum distance",
        "Warnings",
        "Phase range",
        "Named roads",
    )
    rows = [
        (
            summary.name,
            str(summary.agent_count),
            str(summary.directed_neighbor_count),
            str(summary.bidirectional_pair_count),
            str(summary.direct_corridor_pair_count),
            f"{summary.average_neighbor_distance_m:.2f} m",
            f"{summary.maximum_neighbor_distance_m:.2f} m",
            str(summary.warning_count),
            f"{summary.minimum_phase_count}-{summary.maximum_phase_count}",
            summary.named_road_coverage,
        )
        for summary in summaries
    ]
    widths = [
        max([len(headers[index]), *(len(row[index]) for row in rows)])
        for index in range(len(headers))
    ]

    def format_row(row: Sequence[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join(
        [format_row(headers), separator, *(format_row(row) for row in rows)]
    )


def build_summaries() -> tuple[CandidateSummary, ...]:
    """Load generated audits and calculate all configured candidate summaries."""
    audit_rows = read_csv_rows(AUDIT_FILE)
    neighbor_rows = read_csv_rows(NEIGHBORS_FILE)
    audits_by_agent = {row["agent_id"]: row for row in audit_rows}
    return tuple(
        calculate_candidate_summary(candidate, audits_by_agent, neighbor_rows)
        for candidate in CORRIDOR_CANDIDATES
    )


def main() -> int:
    """Print the comparison without assigning an overall winner."""
    try:
        print(render_summary_table(build_summaries()))
        print("\nNo overall winner is assigned. Complete the visual review first.")
        return 0
    except Exception as error:
        print(
            f"[ERROR] Candidate summary failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

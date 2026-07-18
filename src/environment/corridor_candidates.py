"""Reviewed Skopje corridor candidates and their audited controller mappings."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.config import SKOPJE_DIR


TRAFFIC_LIGHT_AUDIT_FILE = SKOPJE_DIR / "documentation" / "traffic_light_audit.csv"


@dataclass(frozen=True, slots=True)
class CorridorCandidate:
    """One audited traffic-light subset awaiting visual review."""

    candidate_id: str
    name: str
    agent_ids: tuple[str, ...]
    traffic_light_ids: tuple[str, ...]
    description: str


def load_agent_traffic_light_mapping(
    audit_file: Path = TRAFFIC_LIGHT_AUDIT_FILE,
) -> dict[str, str]:
    """Load the single source of truth for agent-to-controller mappings."""
    if not audit_file.is_file():
        raise FileNotFoundError(f"Traffic-light audit CSV is missing: {audit_file}")

    with audit_file.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"agent_id", "traffic_light_id"}
        missing_columns = required_columns - set(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Traffic-light audit CSV is missing columns: {missing}")

        mapping: dict[str, str] = {}
        traffic_light_ids: set[str] = set()
        for row in reader:
            agent_id = row["agent_id"].strip()
            traffic_light_id = row["traffic_light_id"].strip()
            if not agent_id or not traffic_light_id:
                raise ValueError("Traffic-light audit contains an empty mapping.")
            if agent_id in mapping:
                raise ValueError(f"Duplicate agent ID in audit CSV: {agent_id}")
            if traffic_light_id in traffic_light_ids:
                raise ValueError(
                    f"Duplicate traffic-light ID in audit CSV: {traffic_light_id}"
                )
            mapping[agent_id] = traffic_light_id
            traffic_light_ids.add(traffic_light_id)

    return mapping


def _build_candidate(
    candidate_id: str,
    name: str,
    agent_ids: tuple[str, ...],
    description: str,
    mapping: Mapping[str, str],
) -> CorridorCandidate:
    """Build a candidate from audited IDs instead of repeating TLS mappings."""
    unknown_agents = [agent_id for agent_id in agent_ids if agent_id not in mapping]
    if unknown_agents:
        unknown = ", ".join(unknown_agents)
        raise ValueError(f"{name} references unknown agent IDs: {unknown}")

    return CorridorCandidate(
        candidate_id=candidate_id,
        name=name,
        agent_ids=agent_ids,
        traffic_light_ids=tuple(mapping[agent_id] for agent_id in agent_ids),
        description=description,
    )


def validate_candidates(
    candidates: Iterable[CorridorCandidate],
    mapping: Mapping[str, str],
) -> None:
    """Validate candidate sizes, uniqueness, and audited controller mappings."""
    candidate_ids: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in candidate_ids:
            raise ValueError(f"Duplicate candidate ID: {candidate.candidate_id}")
        candidate_ids.add(candidate.candidate_id)

        if not 6 <= len(candidate.agent_ids) <= 10:
            raise ValueError(f"{candidate.name} must contain between 6 and 10 agents.")
        if len(candidate.agent_ids) != len(set(candidate.agent_ids)):
            raise ValueError(f"{candidate.name} contains duplicate agent IDs.")
        if len(candidate.traffic_light_ids) != len(candidate.agent_ids):
            raise ValueError(
                f"{candidate.name} has mismatched agent and controller counts."
            )
        if len(candidate.traffic_light_ids) != len(set(candidate.traffic_light_ids)):
            raise ValueError(f"{candidate.name} contains duplicate traffic-light IDs.")

        for agent_id, traffic_light_id in zip(
            candidate.agent_ids,
            candidate.traffic_light_ids,
            strict=True,
        ):
            expected_id = mapping.get(agent_id)
            if expected_id is None:
                raise ValueError(
                    f"{candidate.name} references unknown agent ID: {agent_id}"
                )
            if traffic_light_id != expected_id:
                raise ValueError(
                    f"{candidate.name} maps {agent_id} to {traffic_light_id}, "
                    f"but the audit maps it to {expected_id}."
                )


_AUDITED_MAPPING = load_agent_traffic_light_mapping()

CORRIDOR_CANDIDATES = (
    _build_candidate(
        candidate_id="1",
        name="Candidate 1",
        agent_ids=("A9", "A18", "A19", "A20", "A24", "A25", "A26", "A29"),
        description=(
            "Central connected candidate with audited links on several named "
            "multi-lane corridors."
        ),
        mapping=_AUDITED_MAPPING,
    ),
    _build_candidate(
        candidate_id="2",
        name="Candidate 2",
        agent_ids=("A1", "A3", "A19", "A24", "A25", "A29", "A30", "A32"),
        description=(
            "Connected candidate centered on the audited east-west controller "
            "relationships."
        ),
        mapping=_AUDITED_MAPPING,
    ),
    _build_candidate(
        candidate_id="3",
        name="Candidate 3",
        agent_ids=("A1", "A3", "A16", "A22", "A23", "A24", "A25", "A32"),
        description=(
            "Connected candidate spanning audited northern and central controller "
            "relationships."
        ),
        mapping=_AUDITED_MAPPING,
    ),
)

validate_candidates(CORRIDOR_CANDIDATES, _AUDITED_MAPPING)

CANDIDATES_BY_ID = {
    candidate.candidate_id: candidate for candidate in CORRIDOR_CANDIDATES
}


def get_candidate(candidate_id: str | int) -> CorridorCandidate:
    """Return a configured candidate or raise a clear validation error."""
    normalized_id = str(candidate_id)
    try:
        return CANDIDATES_BY_ID[normalized_id]
    except KeyError as error:
        valid_ids = ", ".join(CANDIDATES_BY_ID)
        raise ValueError(
            f"Unknown candidate {normalized_id!r}. Choose one of: {valid_ids}."
        ) from error

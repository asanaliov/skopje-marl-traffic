"""Generate deterministic POI labels for the audited corridor candidates."""

from __future__ import annotations

import csv
import math
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SKOPJE_DIR  # noqa: E402
from src.environment.corridor_candidates import (  # noqa: E402
    CORRIDOR_CANDIDATES,
    TRAFFIC_LIGHT_AUDIT_FILE,
    CorridorCandidate,
)


LABEL_DIRECTORY = SKOPJE_DIR / "labels"
POI_TYPE = "traffic-light-agent"
POI_COLOR = "0,90,220"
POI_LAYER = "1000"
POI_WIDTH = "12"
POI_HEIGHT = "12"


@dataclass(frozen=True, slots=True)
class AgentCoordinate:
    """One finite controller coordinate copied from the traffic-light audit."""

    x: float
    y: float


def agent_label_file_for(candidate: CorridorCandidate) -> Path:
    """Return the stable additional-file path for one candidate."""
    return LABEL_DIRECTORY / (
        f"candidate_{candidate.candidate_id}_agent_labels.add.xml"
    )


def load_audited_coordinates(
    audit_file: Path = TRAFFIC_LIGHT_AUDIT_FILE,
) -> dict[str, AgentCoordinate]:
    """Load and validate agent coordinates from the committed audit CSV."""
    if not audit_file.is_file():
        raise FileNotFoundError(f"Traffic-light audit CSV is missing: {audit_file}")

    with audit_file.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"agent_id", "x", "y"}
        missing_columns = required_columns - set(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"Traffic-light audit CSV is missing columns: {missing}")

        coordinates: dict[str, AgentCoordinate] = {}
        for row in reader:
            agent_id = row["agent_id"].strip()
            if not agent_id:
                raise ValueError("Traffic-light audit contains an empty agent ID.")
            if agent_id in coordinates:
                raise ValueError(f"Duplicate agent ID in audit CSV: {agent_id}")

            try:
                x = float(row["x"])
                y = float(row["y"])
            except ValueError as error:
                raise ValueError(
                    f"Agent {agent_id} has invalid audit coordinates."
                ) from error
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"Agent {agent_id} has non-finite audit coordinates.")
            coordinates[agent_id] = AgentCoordinate(x=x, y=y)

    return coordinates


def _format_coordinate(value: float) -> str:
    """Write stable coordinate text while retaining audit precision."""
    return f"{value:.2f}"


def render_agent_labels(
    candidate: CorridorCandidate,
    coordinates: Mapping[str, AgentCoordinate],
) -> str:
    """Render one valid SUMO additional file in candidate agent order."""
    missing_agents = [
        agent_id for agent_id in candidate.agent_ids if agent_id not in coordinates
    ]
    if missing_agents:
        missing = ", ".join(missing_agents)
        raise ValueError(f"{candidate.name} is missing coordinates for: {missing}")

    if len(candidate.agent_ids) != len(set(candidate.agent_ids)):
        raise ValueError(f"{candidate.name} contains duplicate POI IDs.")

    root = ET.Element("additional")
    for agent_id in candidate.agent_ids:
        coordinate = coordinates[agent_id]
        ET.SubElement(
            root,
            "poi",
            {
                "id": agent_id,
                "name": agent_id,
                "type": POI_TYPE,
                "x": _format_coordinate(coordinate.x),
                "y": _format_coordinate(coordinate.y),
                "color": POI_COLOR,
                "layer": POI_LAYER,
                "width": POI_WIDTH,
                "height": POI_HEIGHT,
            },
        )

    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


def generate_agent_label_files(
    output_directory: Path = LABEL_DIRECTORY,
    candidates: Sequence[CorridorCandidate] = CORRIDOR_CANDIDATES,
    audit_file: Path = TRAFFIC_LIGHT_AUDIT_FILE,
) -> tuple[Path, ...]:
    """Generate every requested label file without touching scenario inputs."""
    coordinates = load_audited_coordinates(audit_file)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_files: list[Path] = []

    for candidate in candidates:
        output_file = output_directory / (
            f"candidate_{candidate.candidate_id}_agent_labels.add.xml"
        )
        output_file.write_bytes(
            render_agent_labels(candidate, coordinates).encode("utf-8")
        )
        output_files.append(output_file)

    return tuple(output_files)


def main() -> int:
    """Regenerate all candidate POI label files and print their counts."""
    try:
        output_files = generate_agent_label_files()
        for candidate, output_file in zip(
            CORRIDOR_CANDIDATES,
            output_files,
            strict=True,
        ):
            print(
                f"{candidate.name}: generated {len(candidate.agent_ids)} labels at "
                f"{output_file.relative_to(PROJECT_ROOT)}"
            )
        return 0
    except Exception as error:
        print(
            f"[ERROR] Agent-label generation failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

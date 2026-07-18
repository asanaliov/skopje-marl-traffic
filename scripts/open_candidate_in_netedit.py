"""Open the complete Skopje network with one candidate selection in Netedit."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_agent_labels import agent_label_file_for  # noqa: E402
from scripts.generate_candidate_selections import selection_file_for  # noqa: E402
from src.config import SKOPJE_INITIAL_CONFIG  # noqa: E402
from src.environment.corridor_candidates import (  # noqa: E402
    CANDIDATES_BY_ID,
    CorridorCandidate,
    get_candidate,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a required candidate number without accepting unknown candidates."""
    parser = argparse.ArgumentParser(
        description=(
            "Open the original Skopje SUMO network with a generated candidate "
            "selection."
        )
    )
    parser.add_argument(
        "--candidate",
        required=True,
        choices=tuple(CANDIDATES_BY_ID),
        help="candidate number to review",
    )
    return parser.parse_args(argv)


def find_netedit_executable() -> Path:
    """Find Netedit on PATH or below SUMO_HOME."""
    executable_path = shutil.which("netedit")
    if executable_path:
        return Path(executable_path)

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_directory = Path(sumo_home) / "bin"
        for candidate in (bin_directory / "netedit", bin_directory / "netedit.exe"):
            if candidate.is_file():
                return candidate

    raise FileNotFoundError(
        "netedit was not found on PATH or under SUMO_HOME. "
        "Install SUMO and make its bin directory available before launching."
    )


def build_netedit_command(
    executable: Path,
    network_file: Path,
    selection_file: Path,
    label_file: Path,
) -> list[str]:
    """Build the shell-free Netedit command with selection and agent POIs."""
    return [
        str(executable),
        "--sumo-net-file",
        str(network_file),
        "--selection-file",
        str(selection_file),
        "--additional-files",
        str(label_file),
    ]


def print_candidate(candidate: CorridorCandidate) -> None:
    """Show exactly which audited controllers will be highlighted."""
    print(f"Opening {candidate.name} in Netedit.")
    print(f"Agents: {', '.join(candidate.agent_ids)}")
    print(f"Traffic-light IDs: {', '.join(candidate.traffic_light_ids)}")


def main(argv: Sequence[str] | None = None) -> int:
    """Validate files and open Netedit without editing the source network."""
    args = parse_args(argv)
    try:
        candidate = get_candidate(args.candidate)
        SKOPJE_INITIAL_CONFIG.validate_files()
        selection_file = selection_file_for(candidate)
        if not selection_file.is_file():
            raise FileNotFoundError(
                f"Candidate selection is missing: {selection_file}. "
                "Run python scripts/generate_candidate_selections.py first."
            )
        label_file = agent_label_file_for(candidate)
        if not label_file.is_file():
            raise FileNotFoundError(
                f"Candidate label file is missing: {label_file}. "
                "Run python scripts/generate_agent_labels.py first."
            )

        executable = find_netedit_executable()
        command = build_netedit_command(
            executable,
            SKOPJE_INITIAL_CONFIG.net_file,
            selection_file,
            label_file,
        )
        print_candidate(candidate)
        print(
            "Press F9, open the POI visualization settings, enable Show ID, "
            "enable constant text size, and increase the text size if labels "
            "are too small."
        )
        subprocess.run(command, check=True)
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(
            f"[ERROR] Netedit launch failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

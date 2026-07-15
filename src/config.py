"""Project paths and shared simulation settings."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMO_DIR = PROJECT_ROOT / "sumo"
BENCHMARK_DIR = SUMO_DIR / "benchmark"
SKOPJE_DIR = SUMO_DIR / "skopje"
RESULTS_DIR = PROJECT_ROOT / "results"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Input files and timing settings for one SUMO simulation."""

    net_file: Path
    route_file: Path
    simulation_seconds: int = 3600
    delta_time: int = 5
    yellow_time: int = 3
    min_green: int = 10
    seed: int = 42
    use_gui: bool = False

    def validate_files(self) -> None:
        """Raise a clear error when a required SUMO input file is missing."""
        missing_files: list[tuple[str, Path]] = []

        if not self.net_file.is_file():
            missing_files.append(("network", self.net_file))
        if not self.route_file.is_file():
            missing_files.append(("route", self.route_file))

        if missing_files:
            details = "\n".join(
                f"- Missing {file_type} file: {path}"
                for file_type, path in missing_files
            )
            raise FileNotFoundError(f"Required SUMO input files are missing:\n{details}")

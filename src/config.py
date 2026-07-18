"""Project paths and shared simulation settings."""

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMO_DIR = (PROJECT_ROOT / "sumo").resolve()
BENCHMARK_DIR = (SUMO_DIR / "benchmark").resolve()
SKOPJE_DIR = (SUMO_DIR / "skopje").resolve()
SKOPJE_NETWORK_DIR = (SKOPJE_DIR / "network").resolve()
SKOPJE_DEMAND_DIR = (SKOPJE_DIR / "demand").resolve()
SKOPJE_CONFIG_DIR = (SKOPJE_DIR / "config").resolve()
RESULTS_DIR = (PROJECT_ROOT / "results").resolve()


def resolve_sumo_xml_file(directory: Path, uncompressed_name: str) -> Path:
    """Resolve a SUMO XML input, preferring its compressed form when present."""
    uncompressed_file = (directory / uncompressed_name).resolve()
    compressed_file = uncompressed_file.with_name(f"{uncompressed_file.name}.gz")

    if compressed_file.is_file():
        return compressed_file
    return uncompressed_file


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


SKOPJE_INITIAL_NETWORK_FILE = resolve_sumo_xml_file(
    SKOPJE_NETWORK_DIR,
    "skopje_initial.net.xml",
)
SKOPJE_INITIAL_ROUTE_FILE = (
    SKOPJE_DEMAND_DIR / "skopje_initial.trips.xml"
).resolve()
SKOPJE_INITIAL_SUMO_CONFIG_FILE = (
    SKOPJE_CONFIG_DIR / "skopje_initial.sumocfg"
).resolve()
SKOPJE_INITIAL_VIEW_FILE = (
    SKOPJE_CONFIG_DIR / "skopje_initial.view.xml"
).resolve()

SKOPJE_INITIAL_CONFIG = SimulationConfig(
    net_file=SKOPJE_INITIAL_NETWORK_FILE,
    route_file=SKOPJE_INITIAL_ROUTE_FILE,
    simulation_seconds=1800,
    delta_time=5,
    yellow_time=3,
    min_green=10,
    seed=42,
    use_gui=False,
)

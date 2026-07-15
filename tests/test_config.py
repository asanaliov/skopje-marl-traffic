"""Tests for project paths and simulation configuration."""

from pathlib import Path

import pytest

from src.config import (
    BENCHMARK_DIR,
    PROJECT_ROOT,
    RESULTS_DIR,
    SKOPJE_DIR,
    SUMO_DIR,
    SimulationConfig,
)


@pytest.mark.parametrize(
    "project_path",
    (PROJECT_ROOT, SUMO_DIR, BENCHMARK_DIR, SKOPJE_DIR, RESULTS_DIR),
)
def test_project_paths_are_absolute(project_path: Path) -> None:
    assert project_path.is_absolute()


def test_simulation_config_defaults() -> None:
    config = SimulationConfig(
        net_file=Path("network.net.xml"),
        route_file=Path("routes.rou.xml"),
    )

    assert config.simulation_seconds == 3600
    assert config.delta_time == 5
    assert config.yellow_time == 3
    assert config.min_green == 10
    assert config.seed == 42
    assert config.use_gui is False


def test_missing_file_validation_reports_both_files(tmp_path: Path) -> None:
    net_file = tmp_path / "missing.net.xml"
    route_file = tmp_path / "missing.rou.xml"
    config = SimulationConfig(net_file=net_file, route_file=route_file)

    with pytest.raises(FileNotFoundError) as error_info:
        config.validate_files()

    error_message = str(error_info.value)
    assert "Missing network file" in error_message
    assert str(net_file) in error_message
    assert "Missing route file" in error_message
    assert str(route_file) in error_message

"""Run the organized Skopje scenario with its original signal programs."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (  # noqa: E402
    SKOPJE_INITIAL_CONFIG,
    SKOPJE_INITIAL_SUMO_CONFIG_FILE,
)


REPORT_EVERY_STEPS = 100


def positive_integer(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error

    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_integer(value: str) -> int:
    """Parse a nonnegative command-line integer."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error

    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def parse_args() -> argparse.Namespace:
    """Parse smoke-test command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the organized Skopje SUMO scenario without controlling its signals."
        )
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        default=SKOPJE_INITIAL_CONFIG.use_gui,
        help="launch sumo-gui instead of running headlessly",
    )
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=SKOPJE_INITIAL_CONFIG.simulation_seconds,
        help=(
            "simulation duration in seconds "
            f"(default: {SKOPJE_INITIAL_CONFIG.simulation_seconds})"
        ),
    )
    parser.add_argument(
        "--seed",
        type=nonnegative_integer,
        default=SKOPJE_INITIAL_CONFIG.seed,
        help=f"SUMO random seed (default: {SKOPJE_INITIAL_CONFIG.seed})",
    )
    return parser.parse_args()


def _load_traci() -> ModuleType:
    """Import TraCI from Python or SUMO_HOME with a useful failure message."""
    try:
        return importlib.import_module("traci")
    except ImportError as initial_error:
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            tools_directory = Path(sumo_home) / "tools"
            if tools_directory.is_dir() and str(tools_directory) not in sys.path:
                sys.path.insert(0, str(tools_directory))
                try:
                    return importlib.import_module("traci")
                except ImportError:
                    pass

        raise RuntimeError(
            "Could not import traci. Activate the project environment and install "
            "requirements.txt, or set SUMO_HOME to the SUMO installation."
        ) from initial_error


def _find_sumo_executable(use_gui: bool) -> Path:
    """Find SUMO on PATH or below SUMO_HOME."""
    executable_name = "sumo-gui" if use_gui else "sumo"
    executable_path = shutil.which(executable_name)
    if executable_path:
        return Path(executable_path)

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_directory = Path(sumo_home) / "bin"
        candidates = (
            bin_directory / executable_name,
            bin_directory / f"{executable_name}.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    raise FileNotFoundError(
        f"{executable_name} was not found on PATH or under SUMO_HOME. "
        "Install SUMO and make its bin directory available before running this script."
    )


def _validate_scenario_files() -> None:
    """Fail before TraCI starts when an organized scenario input is missing."""
    SKOPJE_INITIAL_CONFIG.validate_files()
    if not SKOPJE_INITIAL_SUMO_CONFIG_FILE.is_file():
        raise FileNotFoundError(
            "Skopje SUMO configuration is missing: "
            f"{SKOPJE_INITIAL_SUMO_CONFIG_FILE}"
        )


def _print_step_metrics(
    traci: Any,
    step_count: int,
    departed_total: int,
    arrived_total: int,
) -> None:
    """Print current traffic metrics from the active TraCI connection."""
    vehicle_ids = traci.vehicle.getIDList()
    speeds = [float(traci.vehicle.getSpeed(vehicle_id)) for vehicle_id in vehicle_ids]
    average_speed = sum(speeds) / len(speeds) if speeds else 0.0
    halting_vehicle_count = sum(speed < 0.1 for speed in speeds)

    print(
        f"Step {step_count}: time={traci.simulation.getTime():.0f}s, "
        f"active={len(vehicle_ids)}, departed={departed_total}, "
        f"arrived={arrived_total}, average_speed={average_speed:.2f} m/s, "
        f"halting={halting_vehicle_count}"
    )


def run_simulation(traci: Any, sumo_binary: Path, seconds: int, seed: int) -> None:
    """Start SUMO, advance it without signal actions, and report traffic metrics."""
    command = [
        str(sumo_binary),
        "-c",
        str(SKOPJE_INITIAL_SUMO_CONFIG_FILE),
        "--end",
        str(seconds),
        "--seed",
        str(seed),
    ]
    started = False

    try:
        traci.start(command)
        started = True
        step_count = 0
        departed_total = 0
        arrived_total = 0

        while (
            traci.simulation.getTime() < seconds
            and traci.simulation.getMinExpectedNumber() > 0
        ):
            traci.simulationStep()
            step_count += 1
            departed_total += int(traci.simulation.getDepartedNumber())
            arrived_total += int(traci.simulation.getArrivedNumber())

            if step_count % REPORT_EVERY_STEPS == 0:
                _print_step_metrics(
                    traci,
                    step_count,
                    departed_total,
                    arrived_total,
                )

        if step_count == 0 or step_count % REPORT_EVERY_STEPS != 0:
            _print_step_metrics(
                traci,
                step_count,
                departed_total,
                arrived_total,
            )

        print(
            f"Simulation completed at {traci.simulation.getTime():.0f}s "
            f"after {step_count} steps."
        )
    finally:
        if started:
            traci.close()


def main() -> int:
    """Validate inputs and run the selected headless or GUI SUMO binary."""
    args = parse_args()
    try:
        _validate_scenario_files()
        sumo_binary = _find_sumo_executable(args.gui)
        traci = _load_traci()
        mode = "GUI" if args.gui else "headless"
        print(
            f"Starting {mode} Skopje simulation for {args.seconds}s "
            f"with seed {args.seed}."
        )
        run_simulation(traci, sumo_binary, args.seconds, args.seed)
        return 0
    except Exception as error:
        print(
            f"[ERROR] Simulation failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Observe one candidate while the complete Skopje scenario runs unchanged."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from src.config import (  # noqa: E402
    SKOPJE_INITIAL_CONFIG,
    SKOPJE_INITIAL_SUMO_CONFIG_FILE,
)
from src.environment.corridor_candidates import (  # noqa: E402
    CANDIDATES_BY_ID,
    CorridorCandidate,
    get_candidate,
)


REPORT_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class ControllerTotals:
    """Accumulate only observed review metrics for one controller."""

    queue_sum: float = 0.0
    waiting_time_sum: float = 0.0
    sample_count: int = 0

    def add(self, queue_length: int, average_waiting_time: float) -> None:
        """Add one periodic observation."""
        self.queue_sum += queue_length
        self.waiting_time_sum += average_waiting_time
        self.sample_count += 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse candidate observation options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete Skopje scenario without controlling signals and "
            "report metrics for one candidate."
        )
    )
    parser.add_argument(
        "--candidate",
        required=True,
        choices=tuple(CANDIDATES_BY_ID),
        help="candidate number to observe",
    )
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=SKOPJE_INITIAL_CONFIG.simulation_seconds,
        help="simulation duration in seconds",
    )
    parser.add_argument(
        "--seed",
        type=nonnegative_integer,
        default=SKOPJE_INITIAL_CONFIG.seed,
        help="SUMO random seed",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="launch sumo-gui instead of headless SUMO",
    )
    return parser.parse_args(argv)


def load_traci() -> ModuleType:
    """Import TraCI from Python or SUMO_HOME with a useful error."""
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


def find_sumo_executable(use_gui: bool) -> Path:
    """Find the requested SUMO executable on PATH or below SUMO_HOME."""
    executable_name = "sumo-gui" if use_gui else "sumo"
    executable_path = shutil.which(executable_name)
    if executable_path:
        return Path(executable_path)

    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_directory = Path(sumo_home) / "bin"
        for candidate in (
            bin_directory / executable_name,
            bin_directory / f"{executable_name}.exe",
        ):
            if candidate.is_file():
                return candidate

    raise FileNotFoundError(
        f"{executable_name} was not found on PATH or under SUMO_HOME. "
        "Install SUMO and make its bin directory available before running."
    )


def build_sumo_command(
    executable: Path,
    seconds: int,
    seed: int,
) -> list[str]:
    """Build a command that retains the original scenario and signal programs."""
    return [
        str(executable),
        "-c",
        str(SKOPJE_INITIAL_SUMO_CONFIG_FILE),
        "--end",
        str(seconds),
        "--seed",
        str(seed),
    ]


def controlled_lanes_by_controller(
    traci: Any,
    candidate: CorridorCandidate,
) -> dict[str, tuple[str, ...]]:
    """Read and deduplicate the original controlled lanes from SUMO."""
    available_ids = set(traci.trafficlight.getIDList())
    missing_ids = set(candidate.traffic_light_ids) - available_ids
    if missing_ids:
        missing = ", ".join(sorted(missing_ids))
        raise ValueError(f"Candidate controllers are missing in SUMO: {missing}")

    return {
        traffic_light_id: tuple(
            sorted(set(traci.trafficlight.getControlledLanes(traffic_light_id)))
        )
        for traffic_light_id in candidate.traffic_light_ids
    }


def controller_metrics(
    traci: Any,
    lane_ids: Sequence[str],
) -> tuple[int, float]:
    """Measure queues and current per-vehicle waiting on controlled lanes."""
    queue_length = sum(
        int(traci.lane.getLastStepHaltingNumber(lane_id)) for lane_id in lane_ids
    )
    vehicle_ids = {
        vehicle_id
        for lane_id in lane_ids
        for vehicle_id in traci.lane.getLastStepVehicleIDs(lane_id)
    }
    waiting_times = [
        float(traci.vehicle.getWaitingTime(vehicle_id)) for vehicle_id in vehicle_ids
    ]
    average_waiting_time = (
        sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
    )
    return queue_length, average_waiting_time


def print_periodic_report(
    traci: Any,
    candidate: CorridorCandidate,
    lanes_by_controller: Mapping[str, Sequence[str]],
    arrived_total: int,
    totals: Mapping[str, ControllerTotals],
) -> None:
    """Print and accumulate one candidate-focused 60-second observation."""
    print(f"Time {traci.simulation.getTime():.0f}s")
    print(f"Candidate traffic-light IDs: {', '.join(candidate.traffic_light_ids)}")
    for agent_id, traffic_light_id in zip(
        candidate.agent_ids,
        candidate.traffic_light_ids,
        strict=True,
    ):
        queue_length, average_waiting_time = controller_metrics(
            traci,
            lanes_by_controller[traffic_light_id],
        )
        totals[traffic_light_id].add(queue_length, average_waiting_time)
        print(
            f"  {agent_id} ({traffic_light_id}): queue={queue_length}, "
            f"average_waiting={average_waiting_time:.2f}s"
        )
    print(
        f"  active vehicles={len(traci.vehicle.getIDList())}, "
        f"arrived vehicles={arrived_total}"
    )


def print_final_summary(
    traci: Any,
    candidate: CorridorCandidate,
    arrived_total: int,
    totals: Mapping[str, ControllerTotals],
) -> None:
    """Print aggregate values from the periodic observations only."""
    print(f"Final {candidate.name} review summary")
    print(f"  simulated time: {traci.simulation.getTime():.0f}s")
    print(f"  active vehicles: {len(traci.vehicle.getIDList())}")
    print(f"  arrived vehicles: {arrived_total}")
    for agent_id, traffic_light_id in zip(
        candidate.agent_ids,
        candidate.traffic_light_ids,
        strict=True,
    ):
        controller_totals = totals[traffic_light_id]
        if controller_totals.sample_count:
            mean_queue = controller_totals.queue_sum / controller_totals.sample_count
            mean_waiting = (
                controller_totals.waiting_time_sum / controller_totals.sample_count
            )
            print(
                f"  {agent_id} ({traffic_light_id}): "
                f"mean_sampled_queue={mean_queue:.2f}, "
                f"mean_sampled_waiting={mean_waiting:.2f}s, "
                f"samples={controller_totals.sample_count}"
            )
        else:
            print(
                f"  {agent_id} ({traffic_light_id}): no 60-second samples "
                "were collected"
            )


def run_review(
    traci: Any,
    executable: Path,
    candidate: CorridorCandidate,
    seconds: int,
    seed: int,
) -> None:
    """Run unchanged signals and report only observed candidate metrics."""
    command = build_sumo_command(executable, seconds, seed)
    started = False
    try:
        traci.start(command)
        started = True
        lanes_by_controller = controlled_lanes_by_controller(traci, candidate)
        totals = {
            traffic_light_id: ControllerTotals()
            for traffic_light_id in candidate.traffic_light_ids
        }
        arrived_total = 0
        next_report_time = REPORT_INTERVAL_SECONDS

        while (
            traci.simulation.getTime() < seconds
            and traci.simulation.getMinExpectedNumber() > 0
        ):
            traci.simulationStep()
            arrived_total += int(traci.simulation.getArrivedNumber())
            current_time = float(traci.simulation.getTime())
            if current_time >= next_report_time:
                print_periodic_report(
                    traci,
                    candidate,
                    lanes_by_controller,
                    arrived_total,
                    totals,
                )
                while next_report_time <= current_time:
                    next_report_time += REPORT_INTERVAL_SECONDS

        print_final_summary(traci, candidate, arrived_total, totals)
    finally:
        if started:
            traci.close()


def validate_scenario_files() -> None:
    """Fail before TraCI starts when an organized scenario input is missing."""
    SKOPJE_INITIAL_CONFIG.validate_files()
    if not SKOPJE_INITIAL_SUMO_CONFIG_FILE.is_file():
        raise FileNotFoundError(
            f"Skopje SUMO configuration is missing: {SKOPJE_INITIAL_SUMO_CONFIG_FILE}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run a headless or graphical candidate observation session."""
    args = parse_args(argv)
    try:
        candidate = get_candidate(args.candidate)
        validate_scenario_files()
        executable = find_sumo_executable(args.gui)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(
            f"Reviewing {candidate.name} in {mode} for {args.seconds}s "
            f"with seed {args.seed}."
        )
        print(f"Agents: {', '.join(candidate.agent_ids)}")
        print(f"Traffic-light IDs: {', '.join(candidate.traffic_light_ids)}")
        run_review(traci, executable, candidate, args.seconds, args.seed)
        return 0
    except Exception as error:
        print(
            f"[ERROR] Candidate review failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

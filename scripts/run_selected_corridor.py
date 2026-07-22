"""Run a fixed-program smoke test while observing the selected corridor."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_candidate_review import (  # noqa: E402
    find_sumo_executable,
    load_traci,
)
from scripts.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from src.environment.selected_corridor import (  # noqa: E402
    SELECTED_CORRIDOR,
    SelectedCorridor,
    validate_selected_corridor,
)


DEFAULT_SECONDS = 600
DEFAULT_SEED = 42
DEFAULT_REPORT_INTERVAL = 60
SMOKE_TEST_NOTICE = (
    "This is a pre-RL fixed-program corridor smoke test. "
    "No learning actions were applied."
)


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    """One sampled observation for a selected traffic-light controller."""

    phase_index: int
    queue_length: int
    average_waiting_time: float
    vehicle_count: int


@dataclass(slots=True)
class AgentSamples:
    """Accumulate periodic observations for one selected agent."""

    queue_total: int = 0
    maximum_queue: int = 0
    waiting_time_total: float = 0.0
    maximum_waiting_time: float = 0.0
    sample_count: int = 0

    def add(self, snapshot: ControllerSnapshot) -> None:
        """Include one controller snapshot in the final summary."""
        self.queue_total += snapshot.queue_length
        self.maximum_queue = max(self.maximum_queue, snapshot.queue_length)
        self.waiting_time_total += snapshot.average_waiting_time
        self.maximum_waiting_time = max(
            self.maximum_waiting_time,
            snapshot.average_waiting_time,
        )
        self.sample_count += 1

    @property
    def mean_queue(self) -> float:
        """Return the mean sampled queue, or zero before the first sample."""
        return self.queue_total / self.sample_count if self.sample_count else 0.0

    @property
    def mean_waiting_time(self) -> float:
        """Return the mean sampled waiting time, or zero before sampling."""
        if not self.sample_count:
            return 0.0
        return self.waiting_time_total / self.sample_count


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse fixed-program selected-corridor smoke-test options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the complete original Skopje scenario and observe only the "
            "official eight-controller corridor without applying signal actions."
        )
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="launch sumo-gui instead of headless SUMO",
    )
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=DEFAULT_SECONDS,
        help=f"requested simulation duration (default: {DEFAULT_SECONDS})",
    )
    parser.add_argument(
        "--seed",
        type=nonnegative_integer,
        default=DEFAULT_SEED,
        help=f"SUMO random seed (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--report-interval",
        type=positive_integer,
        default=DEFAULT_REPORT_INTERVAL,
        help=(f"seconds between sampled reports (default: {DEFAULT_REPORT_INTERVAL})"),
    )
    return parser.parse_args(argv)


def _project_relative(path: Path) -> Path:
    """Represent a repository file without a machine-specific absolute path."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def build_sumo_command(
    executable: Path,
    corridor: SelectedCorridor,
    seconds: int,
    seed: int,
) -> list[str]:
    """Build a command that preserves the complete configured SUMO scenario."""
    return [
        str(executable),
        "-c",
        str(_project_relative(corridor.configuration_file)),
        "--end",
        str(seconds),
        "--seed",
        str(seed),
    ]


def _controlled_lanes_by_agent(
    traci: Any,
    corridor: SelectedCorridor,
) -> Mapping[str, tuple[str, ...]]:
    """Read each selected controller's unique incoming lanes from SUMO."""
    available_ids = set(traci.trafficlight.getIDList())
    missing_ids = sorted(set(corridor.traffic_light_ids) - available_ids)
    if missing_ids:
        raise ValueError(
            "Selected traffic-light controllers are unavailable in the running "
            f"SUMO scenario: {', '.join(missing_ids)}."
        )

    return {
        agent_id: tuple(
            sorted(
                set(
                    traci.trafficlight.getControlledLanes(
                        corridor.agent_to_traffic_light[agent_id]
                    )
                )
            )
        )
        for agent_id in corridor.agent_ids
    }


def _controller_snapshot(
    traci: Any,
    traffic_light_id: str,
    lane_ids: Sequence[str],
) -> ControllerSnapshot:
    """Sample phase, queue, waiting, and vehicle counts on incoming lanes."""
    queue_length = sum(
        int(traci.lane.getLastStepHaltingNumber(lane_id)) for lane_id in lane_ids
    )
    vehicle_ids = sorted(
        {
            vehicle_id
            for lane_id in lane_ids
            for vehicle_id in traci.lane.getLastStepVehicleIDs(lane_id)
        }
    )
    waiting_times = [
        float(traci.vehicle.getWaitingTime(vehicle_id)) for vehicle_id in vehicle_ids
    ]
    average_waiting_time = (
        sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
    )
    return ControllerSnapshot(
        phase_index=int(traci.trafficlight.getPhase(traffic_light_id)),
        queue_length=queue_length,
        average_waiting_time=average_waiting_time,
        vehicle_count=len(vehicle_ids),
    )


def _print_periodic_report(
    traci: Any,
    corridor: SelectedCorridor,
    lanes_by_agent: Mapping[str, Sequence[str]],
    departed_total: int,
    arrived_total: int,
    samples_by_agent: Mapping[str, AgentSamples],
) -> None:
    """Print and collect one full-network and selected-agent report."""
    vehicle_ids = sorted(traci.vehicle.getIDList())
    speeds = [float(traci.vehicle.getSpeed(vehicle_id)) for vehicle_id in vehicle_ids]
    average_speed = sum(speeds) / len(speeds) if speeds else 0.0
    halted_vehicle_count = sum(speed < 0.1 for speed in speeds)

    print(f"\nSimulation time: {traci.simulation.getTime():.0f} s")
    print(f"  Departed vehicles: {departed_total}")
    print(f"  Arrived vehicles: {arrived_total}")
    print(f"  Active vehicles: {len(vehicle_ids)}")
    print(f"  Average active-vehicle speed: {average_speed:.2f} m/s")
    print(f"  Total halted vehicles in full network: {halted_vehicle_count}")
    print("  Selected-agent observations:")

    for agent_id in corridor.agent_ids:
        traffic_light_id = corridor.agent_to_traffic_light[agent_id]
        snapshot = _controller_snapshot(
            traci,
            traffic_light_id,
            lanes_by_agent[agent_id],
        )
        samples_by_agent[agent_id].add(snapshot)
        print(
            f"    {agent_id}: phase={snapshot.phase_index}, "
            f"queue={snapshot.queue_length}, "
            f"average_waiting={snapshot.average_waiting_time:.2f} s, "
            f"vehicles={snapshot.vehicle_count}"
        )


def _print_final_summary(
    traci: Any,
    corridor: SelectedCorridor,
    requested_seconds: int,
    departed_total: int,
    arrived_total: int,
    samples_by_agent: Mapping[str, AgentSamples],
) -> None:
    """Print aggregate smoke-test results without writing experiment files."""
    active_vehicles = len(traci.vehicle.getIDList())
    completed_seconds = float(traci.simulation.getTime())

    print("\nSelected corridor smoke-test summary")
    print(f"  Requested simulation time: {requested_seconds} s")
    print(f"  Completed simulation time: {completed_seconds:.0f} s")
    print(f"  Total departed vehicles: {departed_total}")
    print(f"  Total arrived vehicles: {arrived_total}")
    print(f"  Active vehicles remaining: {active_vehicles}")
    print("  Per-agent sampled metrics:")
    print(
        "    Agent | Mean queue | Maximum queue | Mean waiting | "
        "Maximum waiting | Samples"
    )
    for agent_id in corridor.agent_ids:
        samples = samples_by_agent[agent_id]
        print(
            f"    {agent_id} | {samples.mean_queue:.2f} | "
            f"{samples.maximum_queue} | {samples.mean_waiting_time:.2f} s | "
            f"{samples.maximum_waiting_time:.2f} s | {samples.sample_count}"
        )
    print(f"\n{SMOKE_TEST_NOTICE}")


def run_smoke_test(
    traci: Any,
    executable: Path,
    corridor: SelectedCorridor,
    seconds: int,
    seed: int,
    report_interval: int,
) -> None:
    """Advance SUMO without sending any traffic-light control commands."""
    command = build_sumo_command(executable, corridor, seconds, seed)
    started = False
    try:
        traci.start(command)
        started = True
        lanes_by_agent = _controlled_lanes_by_agent(traci, corridor)
        samples_by_agent = {agent_id: AgentSamples() for agent_id in corridor.agent_ids}
        departed_total = 0
        arrived_total = 0
        next_report_time = float(report_interval)

        while (
            float(traci.simulation.getTime()) < seconds
            and int(traci.simulation.getMinExpectedNumber()) > 0
        ):
            traci.simulationStep()
            departed_total += int(traci.simulation.getDepartedNumber())
            arrived_total += int(traci.simulation.getArrivedNumber())
            current_time = float(traci.simulation.getTime())
            if current_time >= next_report_time:
                _print_periodic_report(
                    traci,
                    corridor,
                    lanes_by_agent,
                    departed_total,
                    arrived_total,
                    samples_by_agent,
                )
                while next_report_time <= current_time:
                    next_report_time += report_interval

        _print_final_summary(
            traci,
            corridor,
            seconds,
            departed_total,
            arrived_total,
            samples_by_agent,
        )
    finally:
        if started:
            traci.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the project setup and run the fixed-program smoke test."""
    args = parse_args(argv)
    try:
        validate_selected_corridor(SELECTED_CORRIDOR)
        executable = find_sumo_executable(args.gui)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(SMOKE_TEST_NOTICE)
        print(
            f"Running {SELECTED_CORRIDOR.name} in {mode} for "
            f"{args.seconds} s with seed {args.seed}."
        )
        print(
            f"Configuration: {_project_relative(SELECTED_CORRIDOR.configuration_file)}"
        )
        print(f"Observed agents: {', '.join(SELECTED_CORRIDOR.agent_ids)}")
        run_smoke_test(
            traci,
            executable,
            SELECTED_CORRIDOR,
            args.seconds,
            args.seed,
            args.report_interval,
        )
        return 0
    except Exception as error:
        print(f"[ERROR] Selected corridor smoke test failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

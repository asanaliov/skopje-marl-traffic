"""Run one synthetic traffic-demand scenario without signal-control actions."""

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
    positive_integer,
)
from src.demand.scenarios import SCENARIOS, get_scenario  # noqa: E402
from src.demand.xml_writer import (  # noqa: E402
    SYNTHETIC_DEMAND_STATEMENT,
    scenario_output_files,
)
from src.environment.selected_corridor import (  # noqa: E402
    SELECTED_CORRIDOR,
    SelectedCorridor,
)


DEFAULT_REPORT_INTERVAL_SECONDS = 60


@dataclass(slots=True)
class AgentObservationAccumulator:
    """Collect periodic queue values and continuous traffic coverage."""

    queue_total: int = 0
    maximum_queue: int = 0
    sample_count: int = 0
    received_traffic: bool = False

    def add_queue(self, queue_length: int) -> None:
        """Add one periodic queue observation."""
        self.queue_total += queue_length
        self.maximum_queue = max(self.maximum_queue, queue_length)
        self.sample_count += 1

    @property
    def mean_queue(self) -> float:
        """Return the arithmetic mean of sampled queue lengths."""
        return self.queue_total / self.sample_count if self.sample_count else 0.0


@dataclass(frozen=True, slots=True)
class TrafficScenarioRunResult:
    """Local smoke-test statistics that do not use experiment metrics code."""

    requested_seconds: int
    completed_seconds: float
    departed_vehicles: int
    arrived_vehicles: int
    active_vehicles: int
    teleport_count: int
    final_network_halting_count: int
    agent_observations: Mapping[str, AgentObservationAccumulator]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse manual synthetic-scenario review options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run generated synthetic Skopje demand while retaining every original "
            "SUMO traffic-light program."
        )
    )
    parser.add_argument("--scenario", required=True, choices=tuple(SCENARIOS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seconds", type=positive_integer)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument(
        "--report-interval",
        type=positive_integer,
        default=DEFAULT_REPORT_INTERVAL_SECONDS,
    )
    return parser.parse_args(argv)


def _project_relative(path: Path) -> Path:
    """Represent repository paths without machine-specific absolute strings."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _controlled_lanes_by_agent(
    traci: Any,
    corridor: SelectedCorridor,
) -> Mapping[str, tuple[str, ...]]:
    """Read selected incoming lanes from the running unchanged network."""
    available_ids = set(traci.trafficlight.getIDList())
    missing_ids = sorted(set(corridor.traffic_light_ids) - available_ids)
    if missing_ids:
        raise ValueError(
            "Selected traffic-light controllers are missing in SUMO: "
            f"{', '.join(missing_ids)}."
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


def _lane_vehicle_ids(traci: Any, lane_ids: Sequence[str]) -> tuple[str, ...]:
    """Return unique vehicles currently present on selected incoming lanes."""
    return tuple(
        sorted(
            {
                vehicle_id
                for lane_id in lane_ids
                for vehicle_id in traci.lane.getLastStepVehicleIDs(lane_id)
            }
        )
    )


def _queue_length(traci: Any, lane_ids: Sequence[str]) -> int:
    """Count currently halted vehicles on selected incoming lanes."""
    return sum(
        int(traci.lane.getLastStepHaltingNumber(lane_id)) for lane_id in lane_ids
    )


def _print_report(
    traci: Any,
    corridor: SelectedCorridor,
    lanes_by_agent: Mapping[str, Sequence[str]],
    observations: Mapping[str, AgentObservationAccumulator],
    departed_total: int,
    arrived_total: int,
    teleport_total: int,
) -> None:
    """Print one full-network and selected-agent status report."""
    vehicle_ids = tuple(sorted(traci.vehicle.getIDList()))
    speeds = [float(traci.vehicle.getSpeed(vehicle_id)) for vehicle_id in vehicle_ids]
    average_speed = sum(speeds) / len(speeds) if speeds else 0.0
    halted_count = sum(speed < 0.1 for speed in speeds)
    print(f"\nSimulation time: {traci.simulation.getTime():.0f} s")
    print(
        f"  departed={departed_total}, arrived={arrived_total}, "
        f"active={len(vehicle_ids)}, teleports={teleport_total}, "
        f"average_speed={average_speed:.2f} m/s, halted={halted_count}"
    )

    for agent_id in corridor.agent_ids:
        lane_ids = lanes_by_agent[agent_id]
        selected_vehicle_ids = _lane_vehicle_ids(traci, lane_ids)
        queue_length = _queue_length(traci, lane_ids)
        waiting_times = [
            float(traci.vehicle.getWaitingTime(vehicle_id))
            for vehicle_id in selected_vehicle_ids
        ]
        average_waiting = (
            sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
        )
        observations[agent_id].add_queue(queue_length)
        traffic_light_id = corridor.agent_to_traffic_light[agent_id]
        phase_index = int(traci.trafficlight.getPhase(traffic_light_id))
        print(
            f"  {agent_id}: phase={phase_index}, queue={queue_length}, "
            f"vehicles={len(selected_vehicle_ids)}, "
            f"average_waiting={average_waiting:.2f} s"
        )


def run_scenario(
    traci: Any,
    executable: Path,
    configuration_file: Path,
    corridor: SelectedCorridor,
    seconds: int,
    seed: int,
    report_interval: int,
    print_reports: bool = True,
) -> TrafficScenarioRunResult:
    """Advance a generated scenario without issuing traffic-light actions."""
    command = [
        str(executable),
        "-c",
        str(_project_relative(configuration_file)),
        "--end",
        str(seconds),
        "--seed",
        str(seed),
    ]
    observations = {
        agent_id: AgentObservationAccumulator() for agent_id in corridor.agent_ids
    }
    departed_total = 0
    arrived_total = 0
    teleport_total = 0
    started = False
    try:
        traci.start(command)
        started = True
        lanes_by_agent = _controlled_lanes_by_agent(traci, corridor)
        next_report_time = float(report_interval)

        while (
            float(traci.simulation.getTime()) < seconds
            and int(traci.simulation.getMinExpectedNumber()) > 0
        ):
            traci.simulationStep()
            departed_total += int(traci.simulation.getDepartedNumber())
            arrived_total += int(traci.simulation.getArrivedNumber())
            get_teleports = getattr(traci.simulation, "getStartingTeleportNumber", None)
            if get_teleports is not None:
                teleport_total += int(get_teleports())

            for agent_id, lane_ids in lanes_by_agent.items():
                if not observations[agent_id].received_traffic:
                    observations[agent_id].received_traffic = bool(
                        _lane_vehicle_ids(traci, lane_ids)
                    )

            current_time = float(traci.simulation.getTime())
            if current_time >= next_report_time:
                if print_reports:
                    _print_report(
                        traci,
                        corridor,
                        lanes_by_agent,
                        observations,
                        departed_total,
                        arrived_total,
                        teleport_total,
                    )
                else:
                    for agent_id, lane_ids in lanes_by_agent.items():
                        observations[agent_id].add_queue(_queue_length(traci, lane_ids))
                while next_report_time <= current_time:
                    next_report_time += report_interval

        vehicle_ids = tuple(traci.vehicle.getIDList())
        final_halting_count = sum(
            float(traci.vehicle.getSpeed(vehicle_id)) < 0.1
            for vehicle_id in vehicle_ids
        )
        return TrafficScenarioRunResult(
            requested_seconds=seconds,
            completed_seconds=float(traci.simulation.getTime()),
            departed_vehicles=departed_total,
            arrived_vehicles=arrived_total,
            active_vehicles=len(vehicle_ids),
            teleport_count=teleport_total,
            final_network_halting_count=final_halting_count,
            agent_observations=observations,
        )
    finally:
        if started:
            traci.close()


def print_final_summary(
    scenario_name: str,
    result: TrafficScenarioRunResult,
) -> None:
    """Print one local review summary without writing experiment results."""
    print(f"\nSynthetic {scenario_name} scenario summary")
    print(f"  Requested time: {result.requested_seconds} s")
    print(f"  Completed time: {result.completed_seconds:.0f} s")
    print(f"  Departed vehicles: {result.departed_vehicles}")
    print(f"  Arrived vehicles: {result.arrived_vehicles}")
    print(f"  Active vehicles: {result.active_vehicles}")
    print(f"  Teleports: {result.teleport_count}")
    print(f"  Final network halting count: {result.final_network_halting_count}")
    for agent_id, observation in result.agent_observations.items():
        print(
            f"  {agent_id}: reached={'yes' if observation.received_traffic else 'no'}, "
            f"mean_sampled_queue={observation.mean_queue:.2f}, "
            f"maximum_sampled_queue={observation.maximum_queue}, "
            f"samples={observation.sample_count}"
        )
    print(f"\n{SYNTHETIC_DEMAND_STATEMENT}")
    print("No learning or traffic-light control actions were applied.")


def main(argv: Sequence[str] | None = None) -> int:
    """Load and run one generated synthetic demand configuration."""
    args = parse_args(argv)
    try:
        if args.seed < 0:
            raise ValueError("Seed must be zero or greater.")
        scenario = get_scenario(args.scenario)
        seconds = args.seconds or scenario.duration_seconds
        outputs = scenario_output_files(scenario.name, args.seed)
        if not outputs.configuration_file.is_file():
            raise FileNotFoundError(
                f"Generated scenario configuration is missing: "
                f"{outputs.configuration_file}. Run "
                f"python scripts/generate_traffic_demand.py --scenario "
                f"{scenario.name} --seed {args.seed} first."
            )
        executable = find_sumo_executable(args.gui)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(SYNTHETIC_DEMAND_STATEMENT)
        print(
            f"Running synthetic {scenario.name} demand in {mode} for {seconds} s "
            f"with seed {args.seed}."
        )
        print(f"Configuration: {_project_relative(outputs.configuration_file)}")
        result = run_scenario(
            traci,
            executable,
            outputs.configuration_file,
            SELECTED_CORRIDOR,
            seconds,
            args.seed,
            args.report_interval,
        )
        print_final_summary(scenario.name, result)
        return 0
    except Exception as error:
        print(f"[ERROR] Synthetic traffic scenario failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

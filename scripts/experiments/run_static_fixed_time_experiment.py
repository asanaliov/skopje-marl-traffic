"""Run one static fixed-time baseline experiment and save its metrics.

This is an experimental baseline created for this project (controller
identifier ``static_fixed_time``). It is not a reproduction of any official
City of Skopje signal-timing plan. See
``sumo/skopje/documentation/static_fixed_time_baseline.md``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.inspection.run_candidate_review import (  # noqa: E402
    find_sumo_executable,
    load_traci,
)
from scripts.experiments.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from src.baselines.static_fixed_time import (  # noqa: E402
    CONTROLLER_NAME,
    DEFAULT_DECISION_INTERVAL_SECONDS,
    DEFAULT_FIXED_GREEN_SECONDS,
    StaticFixedTimeConfig,
    StaticFixedTimeController,
)
from src.demand.scenarios import SCENARIOS, TrafficDemandScenario, get_scenario  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402
from src.evaluation.collector import MetricsCollector  # noqa: E402
from src.evaluation.metrics import EpisodeMetrics, PerAgentDiagnostics  # noqa: E402
from src.evaluation.results_writer import DEFAULT_RESULTS_PATH, append_result  # noqa: E402


DEFAULT_COOLDOWN_SECONDS = 600
DEFAULT_REPORT_INTERVAL_SECONDS = 300
BASELINE_NOTICE = (
    "The static fixed-time controller is an experimental baseline created for "
    "this project. It preserves the imported SUMO phase order and transition "
    "states while assigning deterministic durations to green phases. It is "
    "not claimed to reproduce the official traffic-light timings used by the "
    "City of Skopje."
)


def positive_float(value: str) -> float:
    """Parse a strictly positive command-line float."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not number > 0.0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


@dataclass(slots=True)
class _AgentDiagnosticsAccumulator:
    """Accumulate one selected agent's per-run diagnostics from TraCI."""

    controlled_lane_count: int
    queue_sum: int = 0
    queue_max: int = 0
    waiting_time_sum: float = 0.0
    sample_count: int = 0
    observed_vehicle_ids: set[str] = field(default_factory=set)

    def sample(self, traci_conn: Any, lane_ids: Sequence[str]) -> None:
        """Record one step's queue, waiting-time, and observed-vehicle data."""
        vehicle_ids = sorted(
            {
                vehicle_id
                for lane_id in lane_ids
                for vehicle_id in traci_conn.lane.getLastStepVehicleIDs(lane_id)
            }
        )
        queue_length = sum(
            int(traci_conn.lane.getLastStepHaltingNumber(lane_id))
            for lane_id in lane_ids
        )
        waiting_times = [
            float(traci_conn.vehicle.getWaitingTime(vehicle_id))
            for vehicle_id in vehicle_ids
        ]
        self.queue_sum += queue_length
        self.queue_max = max(self.queue_max, queue_length)
        self.waiting_time_sum += (
            sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
        )
        self.sample_count += 1
        self.observed_vehicle_ids.update(vehicle_ids)

    def finalize(
        self,
        agent_id: str,
        final_phase: str | None,
        phase_change_count: int,
    ) -> PerAgentDiagnostics:
        """Build the immutable diagnostics record for one selected agent."""
        return PerAgentDiagnostics(
            agent_id=agent_id,
            controlled_lane_count=self.controlled_lane_count,
            average_queue=(
                self.queue_sum / self.sample_count if self.sample_count else 0.0
            ),
            max_queue=float(self.queue_max),
            average_waiting_time=(
                self.waiting_time_sum / self.sample_count
                if self.sample_count
                else 0.0
            ),
            observed_vehicle_count=len(self.observed_vehicle_ids),
            final_phase=final_phase,
            phase_change_count=phase_change_count,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse single-experiment command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run one static fixed-time baseline experiment for a synthetic "
            "Skopje demand scenario and append its metrics to results/experiments.csv."
        )
    )
    parser.add_argument("--scenario", required=True, choices=tuple(SCENARIOS))
    parser.add_argument("--seed", type=nonnegative_integer, default=42)
    parser.add_argument(
        "--fixed-green-seconds",
        type=positive_float,
        default=DEFAULT_FIXED_GREEN_SECONDS,
        help=f"fixed green duration in seconds (default: {DEFAULT_FIXED_GREEN_SECONDS:.0f})",
    )
    parser.add_argument(
        "--demand-seconds",
        type=positive_integer,
        default=None,
        help=(
            "generated-demand window in seconds; must match the scenario's "
            "generated duration (default: the scenario's own duration)"
        ),
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=nonnegative_integer,
        default=DEFAULT_COOLDOWN_SECONDS,
        help=f"cooldown seconds after demand stops (default: {DEFAULT_COOLDOWN_SECONDS})",
    )
    parser.add_argument(
        "--report-interval",
        type=positive_integer,
        default=DEFAULT_REPORT_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="launch sumo-gui instead of headless SUMO",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help=f"results CSV path (default: {DEFAULT_RESULTS_PATH})",
    )
    return parser.parse_args(argv)


def _project_relative(path: Path) -> Path:
    """Represent a repository file without a machine-specific absolute path."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _resolve_demand_seconds(
    scenario: TrafficDemandScenario,
    requested_demand_seconds: int | None,
) -> int:
    """Require the requested demand window to match the generated scenario.

    The generated trips file spreads vehicle departures evenly across
    ``scenario.duration_seconds``. Running with a different demand window
    would silently break that assumption (either cutting off planned
    departures or leaving the network idle), so we fail fast instead.
    """
    if requested_demand_seconds is None:
        return scenario.duration_seconds
    if requested_demand_seconds != scenario.duration_seconds:
        raise ValueError(
            f"--demand-seconds={requested_demand_seconds} does not match the "
            f"{scenario.name} scenario's generated duration "
            f"({scenario.duration_seconds} s). Regenerate demand with "
            "scripts/demand/generate_traffic_demand.py --duration to change it."
        )
    return requested_demand_seconds


def _build_sumo_command(
    executable: Path,
    configuration_file: Path,
    total_seconds: int,
    seed: int,
) -> list[str]:
    """Build a generated-scenario command overriding only end time and seed."""
    return [
        str(executable),
        "-c",
        str(configuration_file.resolve()),
        "--end",
        str(total_seconds),
        "--seed",
        str(seed),
    ]


def _print_periodic_report(
    traci: Any,
    controller: StaticFixedTimeController,
    lanes_by_agent: Mapping[str, Sequence[str]],
    departed_total: int,
    arrived_total: int,
) -> None:
    """Print one full-network and selected-agent progress report."""
    vehicle_ids = tuple(traci.vehicle.getIDList())
    speeds = [float(traci.vehicle.getSpeed(vid)) for vid in vehicle_ids]
    average_speed = sum(speeds) / len(speeds) if speeds else 0.0

    print(f"\nSimulation time: {traci.simulation.getTime():.0f} s")
    print(
        f"  departed={departed_total}, arrived={arrived_total}, "
        f"active={len(vehicle_ids)}, average_speed={average_speed:.2f} m/s"
    )
    for agent_id, lane_ids in lanes_by_agent.items():
        queue_length = sum(
            int(traci.lane.getLastStepHaltingNumber(lane_id)) for lane_id in lane_ids
        )
        signal = controller.signals[agent_id]
        print(
            f"    {agent_id}: phase={signal.current_phase_index}, "
            f"queue={queue_length}, "
            f"phase_changes={controller.phase_change_counts[agent_id]}"
        )


def run_experiment(
    traci: Any,
    executable: Path,
    configuration_file: Path,
    scenario: TrafficDemandScenario,
    seed: int,
    fixed_green_seconds: float,
    demand_seconds: int,
    cooldown_seconds: int,
    report_interval: int,
    output_path: Path,
    print_reports: bool = True,
) -> EpisodeMetrics:
    """Run one complete static fixed-time episode and save its metrics."""
    total_seconds = demand_seconds + cooldown_seconds
    command = _build_sumo_command(executable, configuration_file, total_seconds, seed)
    started = False
    try:
        traci.start(command)
        started = True

        controller = StaticFixedTimeController(
            traci,
            config=StaticFixedTimeConfig(
                fixed_green_seconds=fixed_green_seconds,
                decision_interval_seconds=DEFAULT_DECISION_INTERVAL_SECONDS,
            ),
            agent_ids=SELECTED_CORRIDOR.agent_ids,
        )
        lanes_by_agent = {
            agent_id: signal.incoming_lane_ids
            for agent_id, signal in controller.signals.items()
        }
        monitored_lanes = sorted(
            {lane_id for lanes in lanes_by_agent.values() for lane_id in lanes}
        )
        collector = MetricsCollector(
            controller=CONTROLLER_NAME,
            scenario=scenario.name,
            seed=seed,
            monitored_lanes=monitored_lanes,
        )
        diagnostics = {
            agent_id: _AgentDiagnosticsAccumulator(
                controlled_lane_count=len(lanes_by_agent[agent_id])
            )
            for agent_id in controller.agent_ids
        }

        departed_total = 0
        arrived_total = 0
        next_report_time = float(report_interval)

        while (
            float(traci.simulation.getTime()) < total_seconds
            and int(traci.simulation.getMinExpectedNumber()) > 0
        ):
            traci.simulationStep()
            current_time = float(traci.simulation.getTime())

            controller.step(current_time)
            collector.record_step(traci)
            for agent_id in controller.agent_ids:
                diagnostics[agent_id].sample(traci, lanes_by_agent[agent_id])

            departed_total += int(traci.simulation.getDepartedNumber())
            arrived_total += int(traci.simulation.getArrivedNumber())

            if print_reports and current_time >= next_report_time:
                _print_periodic_report(
                    traci,
                    controller,
                    lanes_by_agent,
                    departed_total,
                    arrived_total,
                )
                while next_report_time <= current_time:
                    next_report_time += report_interval

        completed_seconds = float(traci.simulation.getTime())
        final_phases = controller.final_phase_by_agent()
        per_agent = tuple(
            diagnostics[agent_id].finalize(
                agent_id,
                final_phases[agent_id],
                controller.phase_change_counts[agent_id],
            )
            for agent_id in controller.agent_ids
        )
        metrics = collector.finalize(
            simulation_seconds=completed_seconds,
            per_agent=per_agent,
        )
        metrics = replace(
            metrics,
            fixed_green_seconds=fixed_green_seconds,
            demand_seconds=float(demand_seconds),
            cooldown_seconds=float(cooldown_seconds),
        )
        append_result(metrics, path=output_path)
        return metrics
    finally:
        if started:
            traci.close()


def _print_final_summary(metrics: EpisodeMetrics) -> None:
    """Print the required per-agent diagnostics and headline metrics."""
    print("\nStatic fixed-time experiment summary")
    print(f"  controller={metrics.controller}")
    print(f"  scenario={metrics.scenario}  seed={metrics.seed}")
    print(f"  fixed_green_seconds={metrics.fixed_green_seconds:.1f}")
    print(f"  demand_seconds={metrics.demand_seconds:.0f}")
    print(f"  cooldown_seconds={metrics.cooldown_seconds:.0f}")
    print(f"  total_simulation_seconds={metrics.simulation_seconds:.0f}")
    print(f"  average_waiting_time={metrics.average_waiting_time:.2f} s")
    print(f"  average_queue_length={metrics.average_queue_length:.2f}")
    print(f"  max_queue_length={metrics.max_queue_length:.0f}")
    print(f"  average_speed={metrics.average_speed:.2f} m/s")
    print(f"  throughput={metrics.throughput}")
    print(f"  departed_vehicles={metrics.departed_vehicles}")
    print(f"  arrived_vehicles={metrics.arrived_vehicles}")
    print(f"  active_vehicles_remaining={metrics.active_vehicles_remaining}")
    print(f"  total_stopped_vehicles={metrics.total_stopped_vehicles}")
    print(f"  teleport_count={metrics.teleport_count}")
    print(f"  total_reward={metrics.total_reward}")
    print("\n  Per-agent diagnostics:")
    print(
        "    agent | lanes | avg_queue | max_queue | avg_wait_s | "
        "vehicles | final_phase | phase_changes"
    )
    for diagnostic in metrics.per_agent:
        print(
            f"    {diagnostic.agent_id:5s} | {diagnostic.controlled_lane_count:5d} | "
            f"{diagnostic.average_queue:9.2f} | {diagnostic.max_queue:9.0f} | "
            f"{diagnostic.average_waiting_time:10.2f} | "
            f"{diagnostic.observed_vehicle_count:8d} | "
            f"{diagnostic.final_phase or '':11s} | "
            f"{diagnostic.phase_change_count:13d}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one static fixed-time baseline experiment from the command line."""
    args = parse_args(argv)
    print(BASELINE_NOTICE)
    try:
        scenario = get_scenario(args.scenario)
        demand_seconds = _resolve_demand_seconds(scenario, args.demand_seconds)
        outputs = scenario_output_files(scenario.name, args.seed)
        if not outputs.configuration_file.is_file():
            raise FileNotFoundError(
                f"Generated scenario configuration is missing: "
                f"{outputs.configuration_file}. Run "
                f"python scripts/demand/generate_traffic_demand.py --scenario "
                f"{scenario.name} --seed {args.seed} first."
            )
        executable = find_sumo_executable(args.gui)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(
            f"Running {CONTROLLER_NAME} on synthetic {scenario.name} demand in "
            f"{mode}: demand={demand_seconds} s, cooldown={args.cooldown_seconds} s, "
            f"fixed_green={args.fixed_green_seconds:.1f} s, seed={args.seed}."
        )
        print(f"Configuration: {_project_relative(outputs.configuration_file)}")
        metrics = run_experiment(
            traci=traci,
            executable=executable,
            configuration_file=outputs.configuration_file,
            scenario=scenario,
            seed=args.seed,
            fixed_green_seconds=args.fixed_green_seconds,
            demand_seconds=demand_seconds,
            cooldown_seconds=args.cooldown_seconds,
            report_interval=args.report_interval,
            output_path=args.output,
        )
        _print_final_summary(metrics)
        print(f"\nSaved result to {args.output}")
        print(f"\n{BASELINE_NOTICE}")
        return 0
    except Exception as error:
        print(f"[ERROR] Static fixed-time experiment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

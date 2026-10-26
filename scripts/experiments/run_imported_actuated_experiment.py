"""Run one imported actuated baseline experiment and save its metrics.

This is a SUMO simulation baseline created for this project (controller
identifier ``imported_actuated``). It evaluates the traffic-light programs
already contained in the imported SUMO network without issuing manual
phase-control actions. See
``sumo/skopje/documentation/imported_actuated_baseline.md``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.inspection.run_candidate_review import load_traci  # noqa: E402
from scripts.experiments.run_skopje_simulation import (  # noqa: E402
    nonnegative_integer,
    positive_integer,
)
from scripts.experiments.run_static_fixed_time_experiment import (  # noqa: E402
    _AgentDiagnosticsAccumulator,
    _project_relative,
    _resolve_demand_seconds,
)
from src.baselines.imported_actuated import (  # noqa: E402
    BASELINE_NOTICE,
    CONTROLLER_NAME,
    DEFAULT_COOLDOWN_SECONDS,
    ImportedActuatedController,
    build_environment_config,
)
from src.demand.scenarios import SCENARIOS, TrafficDemandScenario, get_scenario  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402
from src.environment.multi_agent_environment import (  # noqa: E402
    MultiAgentStepResult,
    MultiAgentTrafficEnvironment,
)
from src.evaluation.collector import MetricsCollector  # noqa: E402
from src.evaluation.metrics import EpisodeMetrics  # noqa: E402
from src.evaluation.results_writer import DEFAULT_RESULTS_PATH, append_result  # noqa: E402


DEFAULT_REPORT_INTERVAL_SECONDS = 300


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse single-experiment command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Run one imported actuated baseline experiment for a synthetic "
            "Skopje demand scenario and append its metrics to "
            "results/experiments.csv."
        )
    )
    parser.add_argument("--scenario", required=True, choices=tuple(SCENARIOS))
    parser.add_argument("--seed", type=nonnegative_integer, default=42)
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
        default=int(DEFAULT_COOLDOWN_SECONDS),
        help=(
            "cooldown seconds after demand stops "
            f"(default: {int(DEFAULT_COOLDOWN_SECONDS)})"
        ),
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


def _print_periodic_report(
    result: MultiAgentStepResult,
) -> None:
    """Print one full-network and selected-agent progress report.

    Reuses the aggregate counts and observations the environment already
    computed for this decision interval instead of re-deriving them from
    raw TraCI calls.
    """
    info = result.info
    print(f"\nSimulation time: {float(info['simulation_time']):.0f} s")
    print(
        f"  departed={info['departed_vehicle_count']}, "
        f"arrived={info['arrived_vehicle_count']}, "
        f"active={info['active_expected_vehicle_count']}, "
        f"halted={info['halted_vehicle_count']}"
    )
    for agent_id, observation in result.observations.items():
        print(
            f"    {agent_id}: phase={observation.current_phase_state}, "
            f"queue={sum(observation.queue_lengths)}"
        )


def run_experiment(
    traci: Any,
    environment: MultiAgentTrafficEnvironment,
    scenario: str,
    seed: int,
    demand_seconds: float,
    cooldown_seconds: float,
    output_path: Path,
    report_interval: int = DEFAULT_REPORT_INTERVAL_SECONDS,
    print_reports: bool = True,
) -> EpisodeMetrics:
    """Run one complete imported actuated episode and save its metrics.

    ``traci`` and ``environment`` are provided separately (rather than
    built internally) so tests can inject a fake TraCI connection and a
    ``MultiAgentTrafficEnvironment`` wired to fake TrafficSignal wrappers,
    exactly like ``tests/test_multi_agent_environment.py`` already does,
    without starting real SUMO.
    """
    controller = ImportedActuatedController(environment)
    try:
        observations = controller.reset()
        lanes_by_agent = {
            agent_id: observation.incoming_lane_ids
            for agent_id, observation in observations.items()
        }
        monitored_lanes = sorted(
            {lane_id for lanes in lanes_by_agent.values() for lane_id in lanes}
        )
        collector = MetricsCollector(
            controller=CONTROLLER_NAME,
            scenario=scenario,
            seed=seed,
            monitored_lanes=monitored_lanes,
        )
        diagnostics = {
            agent_id: _AgentDiagnosticsAccumulator(
                controlled_lane_count=len(lanes_by_agent[agent_id])
            )
            for agent_id in controller.agent_ids
        }

        next_report_time = float(report_interval)
        result: MultiAgentStepResult | None = None
        terminated = False
        truncated = False

        while not (terminated or truncated):
            result = controller.step()
            collector.record_step(traci)
            for agent_id in controller.agent_ids:
                diagnostics[agent_id].sample(traci, lanes_by_agent[agent_id])

            terminated = result.terminated
            truncated = result.truncated

            current_time = float(result.info["simulation_time"])
            if print_reports and current_time >= next_report_time:
                _print_periodic_report(result)
                while next_report_time <= current_time:
                    next_report_time += report_interval

        if result is None:
            raise RuntimeError(
                "Episode ended before any decision interval was advanced."
            )

        completed_seconds = float(result.info["simulation_time"])
        final_phases = {
            agent_id: observation.current_phase_state
            for agent_id, observation in result.observations.items()
        }
        per_agent = tuple(
            diagnostics[agent_id].finalize(
                agent_id,
                final_phases[agent_id],
                0,
            )
            for agent_id in controller.agent_ids
        )
        metrics = collector.finalize(
            simulation_seconds=completed_seconds,
            per_agent=per_agent,
        )
        metrics = replace(
            metrics,
            demand_seconds=float(demand_seconds),
            cooldown_seconds=float(cooldown_seconds),
        )
        append_result(metrics, path=output_path)
        return metrics
    finally:
        controller.close()


def _print_final_summary(metrics: EpisodeMetrics) -> None:
    """Print the required per-agent diagnostics and headline metrics."""
    print("\nImported actuated experiment summary")
    print(f"  controller={metrics.controller}")
    print(f"  scenario={metrics.scenario}  seed={metrics.seed}")
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


def _resolve_scenario_and_demand(
    scenario_name: str,
    requested_demand_seconds: int | None,
    seed: int,
) -> tuple[TrafficDemandScenario, int]:
    """Look up the scenario and require its generated files to exist."""
    scenario = get_scenario(scenario_name)
    demand_seconds = _resolve_demand_seconds(scenario, requested_demand_seconds)
    outputs = scenario_output_files(scenario.name, seed)
    if not outputs.configuration_file.is_file():
        raise FileNotFoundError(
            f"Generated scenario configuration is missing: "
            f"{outputs.configuration_file}. Run "
            f"python scripts/demand/generate_traffic_demand.py --scenario "
            f"{scenario.name} --seed {seed} first."
        )
    return scenario, demand_seconds


def main(argv: list[str] | None = None) -> int:
    """Run one imported actuated baseline experiment from the command line."""
    args = parse_args(argv)
    print(BASELINE_NOTICE)
    try:
        scenario, demand_seconds = _resolve_scenario_and_demand(
            args.scenario, args.demand_seconds, args.seed
        )
        outputs = scenario_output_files(scenario.name, args.seed)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(
            f"Running {CONTROLLER_NAME} on synthetic {scenario.name} demand in "
            f"{mode}: demand={demand_seconds} s, cooldown={args.cooldown_seconds} s, "
            f"seed={args.seed}."
        )
        print(f"Configuration: {_project_relative(outputs.configuration_file)}")

        config = build_environment_config(
            scenario=scenario.name,
            seed=args.seed,
            demand_seconds=float(demand_seconds),
            cooldown_seconds=float(args.cooldown_seconds),
            gui=args.gui,
        )
        environment = MultiAgentTrafficEnvironment(config, traci_connection=traci)
        metrics = run_experiment(
            traci=traci,
            environment=environment,
            scenario=scenario.name,
            seed=args.seed,
            demand_seconds=demand_seconds,
            cooldown_seconds=args.cooldown_seconds,
            output_path=args.output,
            report_interval=args.report_interval,
        )
        _print_final_summary(metrics)
        print(f"\nSaved result to {args.output}")
        print(f"\n{BASELINE_NOTICE}")
        return 0
    except Exception as error:
        print(f"[ERROR] Imported actuated experiment failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

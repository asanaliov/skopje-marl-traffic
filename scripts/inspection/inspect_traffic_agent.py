"""Inspect selected traffic-agent observations in a generated SUMO scenario."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
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
from src.demand.scenarios import SCENARIOS, get_scenario  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402
from src.environment.actions import (  # noqa: E402
    ActionPolicyConfig,
    ActionResult,
    TrafficAction,
)
from src.environment.observations import (  # noqa: E402
    ObservationNormalizationConfig,
    TrafficObservation,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402
from src.environment.traffic_signal import TrafficSignal  # noqa: E402


DEFAULT_SECONDS = 120
DEFAULT_REPORT_INTERVAL_SECONDS = 60
DEMO_NEXT_GREEN_INTERVAL_SECONDS = 30.0
INSPECTION_NOTICE = (
    "This is an agent-interface inspection run. No learning algorithm is active."
)


@dataclass(frozen=True, slots=True)
class InspectionSummary:
    """Small console-only summary for one inspection run."""

    completed_seconds: float
    report_count: int
    action_request_count: int
    phase_switch_count: int
    observed_transition_count: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse traffic-agent inspection options."""
    parser = argparse.ArgumentParser(
        description=(
            "Inspect selected traffic-agent observations without applying "
            "learning actions."
        )
    )
    parser.add_argument("--scenario", required=True, choices=tuple(SCENARIOS))
    parser.add_argument("--seed", type=nonnegative_integer, default=42)
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--agent",
        help="inspect one selected agent, such as A19",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="inspect all eight selected agents",
    )
    parser.add_argument(
        "--seconds",
        type=positive_integer,
        default=DEFAULT_SECONDS,
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
        "--demo-actions",
        action="store_true",
        help=(
            "apply a deterministic KEEP/NEXT_GREEN demonstration schedule; "
            "this is not reinforcement learning"
        ),
    )
    return parser.parse_args(argv)


def _project_relative(path: Path) -> Path:
    """Display repository paths without machine-specific prefixes."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _selected_agent_ids(agent_id: str | None, inspect_all: bool) -> tuple[str, ...]:
    """Resolve and validate the requested selected-agent subset."""
    if inspect_all:
        return SELECTED_CORRIDOR.agent_ids
    if agent_id not in SELECTED_CORRIDOR.agent_to_traffic_light:
        selected = ", ".join(SELECTED_CORRIDOR.agent_ids)
        raise ValueError(
            f"Unknown selected agent {agent_id!r}. Choose one of: {selected}."
        )
    return (str(agent_id),)


def _build_sumo_command(
    executable: Path,
    configuration_file: Path,
    seconds: int,
    seed: int,
) -> list[str]:
    """Build a generated-scenario command without output-file options."""
    return [
        str(executable),
        "-c",
        str(_project_relative(configuration_file)),
        "--end",
        str(seconds),
        "--seed",
        str(seed),
    ]


def _rounded(values: Sequence[float], digits: int = 3) -> tuple[float, ...]:
    """Round console values without changing stored observations."""
    return tuple(round(float(value), digits) for value in values)


def _print_observation(
    signal: TrafficSignal,
    observation: TrafficObservation,
    normalization: ObservationNormalizationConfig,
    phase_switched: bool,
) -> None:
    """Print every required observation and local reward value."""
    normalized = observation.normalized_features(
        phase_count=signal.phase_count,
        config=normalization,
    )
    reward = signal.calculate_local_reward(
        observation,
        phase_switched=phase_switched,
    )
    print(
        f"\nSimulation time: {observation.simulation_time:.0f} s | "
        f"agent={observation.agent_id} | "
        f"traffic_light={observation.traffic_light_id}"
    )
    print(
        f"  phase_index={observation.current_phase_index}, "
        f"phase_state={observation.current_phase_state}, "
        f"elapsed={observation.current_phase_elapsed_seconds:.1f} s, "
        f"green={observation.is_green_phase}, "
        f"transition={observation.is_transition_phase}"
    )
    print(f"  lane_ids={observation.incoming_lane_ids}")
    print(f"  queue_lengths={observation.queue_lengths}")
    print(f"  vehicle_counts={observation.vehicle_counts}")
    print(
        "  mean_waiting_times_seconds="
        f"{_rounded(observation.mean_waiting_times)}"
    )
    print(f"  mean_speeds_mps={_rounded(observation.mean_speeds)}")
    print(f"  normalized_observation={_rounded(normalized, digits=4)}")
    print(
        "  local_reward="
        f"{reward.total_reward:.3f} "
        f"(queue={reward.queue_component:.3f}, "
        f"waiting={reward.waiting_component:.3f}, "
        f"switch={reward.switch_component:.3f})"
    )


def _print_demo_action(
    signal: TrafficSignal,
    action: TrafficAction,
    result: ActionResult,
) -> None:
    """Print one deterministic demonstration action outcome."""
    resulting_state = signal.phase_states[result.resulting_phase_index]
    print(
        f"Demo action at agent={signal.agent_id}: requested={action.name}, "
        f"status={result.status.name}, "
        f"phase={result.previous_phase_index}->{result.resulting_phase_index}, "
        f"state={resulting_state}, "
        f"changed={result.phase_changed}"
    )


def run_inspection(
    traci: Any,
    executable: Path,
    configuration_file: Path,
    agent_ids: tuple[str, ...],
    seconds: int,
    seed: int,
    report_interval: int,
    demo_actions: bool,
) -> InspectionSummary:
    """Run one console-only observation or deterministic action inspection."""
    command = _build_sumo_command(
        executable,
        configuration_file,
        seconds,
        seed,
    )
    started = False
    report_count = 0
    action_request_count = 0
    phase_switch_count = 0
    observed_transition_count = 0
    try:
        traci.start(command)
        started = True
        action_policy = ActionPolicyConfig()
        signals = {
            agent_id: TrafficSignal(
                agent_id=agent_id,
                traffic_light_id=SELECTED_CORRIDOR.agent_to_traffic_light[agent_id],
                traci_connection=traci,
                action_policy=action_policy,
            )
            for agent_id in agent_ids
        }
        normalizations = {
            agent_id: signal.normalization_config()
            for agent_id, signal in signals.items()
        }
        last_phase_indices = {
            agent_id: signal.current_phase_index
            for agent_id, signal in signals.items()
        }
        phase_switched_since_report = dict.fromkeys(agent_ids, False)
        next_report_time = float(report_interval)
        next_decision_time = action_policy.decision_interval_seconds
        next_demo_switch_time = DEMO_NEXT_GREEN_INTERVAL_SECONDS

        for agent_id, signal in signals.items():
            print(
                f"Initialized {agent_id}: "
                f"traffic_light={signal.traffic_light_id}, "
                f"lanes={len(signal.incoming_lane_ids)}, "
                f"phases={signal.phase_count}, "
                f"green_indices={signal.green_phase_indices}"
            )

        while (
            float(traci.simulation.getTime()) < seconds
            and int(traci.simulation.getMinExpectedNumber()) > 0
        ):
            traci.simulationStep()
            current_time = float(traci.simulation.getTime())

            if demo_actions:
                for agent_id, signal in signals.items():
                    signal.synchronize()
                    if signal.current_phase_index != last_phase_indices[agent_id]:
                        state = signal.phase_states[signal.current_phase_index]
                        transition = signal.current_phase_index not in (
                            signal.green_phase_indices
                        )
                        if transition:
                            observed_transition_count += 1
                        print(
                            f"Demo phase change at {current_time:.0f} s: "
                            f"agent={agent_id}, "
                            f"phase={signal.current_phase_index}, "
                            f"state={state}, "
                            f"transition={transition}"
                        )
                        last_phase_indices[agent_id] = signal.current_phase_index

                if current_time >= next_decision_time:
                    action = (
                        TrafficAction.NEXT_GREEN
                        if current_time >= next_demo_switch_time
                        else TrafficAction.KEEP
                    )
                    for agent_id, signal in signals.items():
                        result = signal.apply_action(action)
                        action_request_count += 1
                        if result.phase_changed:
                            phase_switch_count += 1
                            phase_switched_since_report[agent_id] = True
                            if signal.current_phase_index not in (
                                signal.green_phase_indices
                            ):
                                observed_transition_count += 1
                        _print_demo_action(signal, action, result)
                        last_phase_indices[agent_id] = signal.current_phase_index
                    while next_decision_time <= current_time:
                        next_decision_time += action_policy.decision_interval_seconds
                    if action is TrafficAction.NEXT_GREEN:
                        while next_demo_switch_time <= current_time:
                            next_demo_switch_time += (
                                DEMO_NEXT_GREEN_INTERVAL_SECONDS
                            )

            if current_time >= next_report_time:
                for agent_id, signal in signals.items():
                    observation = signal.observe()
                    _print_observation(
                        signal,
                        observation,
                        normalizations[agent_id],
                        phase_switched_since_report[agent_id],
                    )
                    phase_switched_since_report[agent_id] = False
                    report_count += 1
                while next_report_time <= current_time:
                    next_report_time += report_interval

        return InspectionSummary(
            completed_seconds=float(traci.simulation.getTime()),
            report_count=report_count,
            action_request_count=action_request_count,
            phase_switch_count=phase_switch_count,
            observed_transition_count=observed_transition_count,
        )
    finally:
        if started:
            traci.close()


def _print_summary(summary: InspectionSummary, demo_actions: bool) -> None:
    """Print a concise final smoke-test summary."""
    print("\nAgent-interface inspection summary")
    print(f"  completed_seconds={summary.completed_seconds:.0f}")
    print(f"  observation_reports={summary.report_count}")
    print(f"  action_requests={summary.action_request_count}")
    print(f"  initiated_phase_switches={summary.phase_switch_count}")
    print(f"  observed_transition_changes={summary.observed_transition_count}")
    if demo_actions:
        print(
            "  deterministic demonstration actions used the configured "
            "minimum-green, maximum-green, and immediate-transition rules"
        )
    else:
        print("  read-only mode issued no traffic-light action requests")


def main(argv: Sequence[str] | None = None) -> int:
    """Validate inputs, start the scenario, and inspect selected wrappers."""
    args = parse_args(argv)
    print(INSPECTION_NOTICE)
    if args.demo_actions:
        print(
            "Deterministic demonstration actions are active. "
            "Only safe KEEP and NEXT_GREEN requests will be used."
        )
    else:
        print(
            "Read-only observation mode is active. "
            "All original SUMO traffic-light programs remain in control."
        )

    try:
        scenario = get_scenario(args.scenario)
        outputs = scenario_output_files(scenario.name, args.seed)
        if not outputs.configuration_file.is_file():
            raise FileNotFoundError(
                f"Generated scenario configuration is missing: "
                f"{outputs.configuration_file}. Run "
                f"python scripts/demand/generate_traffic_demand.py --scenario "
                f"{scenario.name} --seed {args.seed} first."
            )
        agent_ids = _selected_agent_ids(args.agent, args.all)
        executable = find_sumo_executable(args.gui)
        traci = load_traci()
        mode = "SUMO-GUI" if args.gui else "headless SUMO"
        print(
            f"Inspecting synthetic {scenario.name} demand in {mode} for "
            f"{args.seconds} s with seed {args.seed}."
        )
        print(f"Configuration: {_project_relative(outputs.configuration_file)}")
        summary = run_inspection(
            traci=traci,
            executable=executable,
            configuration_file=outputs.configuration_file,
            agent_ids=agent_ids,
            seconds=args.seconds,
            seed=args.seed,
            report_interval=args.report_interval,
            demo_actions=args.demo_actions,
        )
        _print_summary(summary, args.demo_actions)
        print(f"\n{INSPECTION_NOTICE}")
        return 0
    except Exception as error:
        print(f"[ERROR] Traffic-agent inspection failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

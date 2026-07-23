"""Unit tests for the experiment-metrics package.

None of these tests require SUMO or SUMO-GUI: the collector is tested
against a small in-memory fake that mimics the slice of the TraCI API it
actually uses.
"""

from __future__ import annotations

import pytest

from scripts.summarize_experiments import summarize
from src.evaluation.collector import MetricsCollector
from src.evaluation.metrics import (
    EpisodeMetrics,
    MetricsValidationError,
    PerAgentDiagnostics,
)
from src.evaluation.results_writer import append_result, read_results

# ---------------------------------------------------------------------------
# EpisodeMetrics / PerAgentDiagnostics validation
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides):
    base = {
        "controller": "fixed_time",
        "scenario": "medium",
        "seed": 42,
        "simulation_seconds": 4200.0,
        "average_waiting_time": 12.5,
        "average_queue_length": 3.2,
        "max_queue_length": 9.0,
        "average_speed": 8.1,
        "throughput": 120,
        "departed_vehicles": 130,
        "arrived_vehicles": 120,
        "total_stopped_vehicles": 45,
    }
    base.update(overrides)
    return base


def test_episode_metrics_accepts_valid_values():
    metrics = EpisodeMetrics(**_valid_kwargs())
    assert metrics.controller == "fixed_time"
    assert metrics.total_reward is None
    assert metrics.per_agent == ()


def test_episode_metrics_rejects_negative_values():
    with pytest.raises(MetricsValidationError):
        EpisodeMetrics(**_valid_kwargs(average_waiting_time=-1.0))


def test_episode_metrics_rejects_empty_controller():
    with pytest.raises(MetricsValidationError):
        EpisodeMetrics(**_valid_kwargs(controller=""))


def test_episode_metrics_rejects_nan_reward():
    nan = float("nan")
    with pytest.raises(MetricsValidationError):
        EpisodeMetrics(**_valid_kwargs(total_reward=nan))


def test_episode_metrics_rejects_arrived_over_departed():
    with pytest.raises(MetricsValidationError):
        EpisodeMetrics(
            **_valid_kwargs(departed_vehicles=10, arrived_vehicles=11, throughput=11)
        )


def test_episode_metrics_rejects_stopped_over_departed():
    with pytest.raises(MetricsValidationError):
        EpisodeMetrics(**_valid_kwargs(departed_vehicles=10, total_stopped_vehicles=11))


def test_episode_metrics_as_flat_dict_excludes_per_agent():
    diag = PerAgentDiagnostics(
        agent_id="A9",
        controlled_lane_count=4,
        average_queue=1.0,
        max_queue=3.0,
        average_waiting_time=5.0,
        observed_vehicle_count=20,
    )
    metrics = EpisodeMetrics(**_valid_kwargs(per_agent=(diag,)))
    flat = metrics.as_flat_dict()
    assert "per_agent" not in flat
    assert flat["controller"] == "fixed_time"


def test_per_agent_diagnostics_rejects_negative_queue():
    with pytest.raises(MetricsValidationError):
        PerAgentDiagnostics(
            agent_id="A9",
            controlled_lane_count=4,
            average_queue=-1.0,
            max_queue=3.0,
            average_waiting_time=5.0,
            observed_vehicle_count=20,
        )


def test_per_agent_diagnostics_rejects_empty_agent_id():
    with pytest.raises(MetricsValidationError):
        PerAgentDiagnostics(
            agent_id="",
            controlled_lane_count=4,
            average_queue=1.0,
            max_queue=3.0,
            average_waiting_time=5.0,
            observed_vehicle_count=20,
        )


# ---------------------------------------------------------------------------
# MetricsCollector, exercised against a fake TraCI connection (no SUMO)
# ---------------------------------------------------------------------------


class FakeVehicleAPI:
    def __init__(self, speeds, waiting_times):
        self._speeds = speeds
        self._waiting_times = waiting_times

    def getIDList(self):
        return list(self._speeds.keys())

    def getSpeed(self, vid):
        return self._speeds[vid]

    def getAccumulatedWaitingTime(self, vid):
        return self._waiting_times[vid]


class FakeLaneAPI:
    def __init__(self, halting_by_lane):
        self._halting_by_lane = halting_by_lane

    def getLastStepHaltingNumber(self, lane_id):
        return self._halting_by_lane.get(lane_id, 0)


class FakeSimulationAPI:
    def __init__(self, departed=(), arrived=(), teleports=()):
        self._departed = list(departed)
        self._arrived = list(arrived)
        self._teleports = list(teleports)

    def getDepartedIDList(self):
        return self._departed

    def getArrivedIDList(self):
        return self._arrived

    def getStartingTeleportIDList(self):
        return self._teleports


class FakeTraci:
    """Minimal stand-in for a connected `traci` module."""

    def __init__(self, vehicle, lane, simulation):
        self.vehicle = vehicle
        self.lane = lane
        self.simulation = simulation


def test_collector_handles_step_with_zero_vehicles():
    collector = MetricsCollector(controller="fixed_time", scenario="low", seed=1)
    empty_step = FakeTraci(
        vehicle=FakeVehicleAPI(speeds={}, waiting_times={}),
        lane=FakeLaneAPI({}),
        simulation=FakeSimulationAPI(),
    )
    collector.record_step(empty_step)  # should not raise

    metrics = collector.finalize(simulation_seconds=1.0)
    assert metrics.average_speed == 0.0
    assert metrics.average_queue_length == 0.0
    assert metrics.departed_vehicles == 0
    assert metrics.arrived_vehicles == 0


def test_collector_computes_expected_aggregates_over_two_steps():
    collector = MetricsCollector(
        controller="static_fixed_time",
        scenario="medium",
        seed=42,
        monitored_lanes=["laneA", "laneB"],
        stopped_speed_threshold=0.1,
    )

    step1 = FakeTraci(
        vehicle=FakeVehicleAPI(
            speeds={"v1": 0.0, "v2": 5.0},
            waiting_times={"v1": 2.0, "v2": 0.0},
        ),
        lane=FakeLaneAPI({"laneA": 1, "laneB": 0}),
        simulation=FakeSimulationAPI(departed=["v1", "v2"]),
    )
    step2 = FakeTraci(
        vehicle=FakeVehicleAPI(
            speeds={"v1": 0.0, "v2": 6.0},
            waiting_times={"v1": 3.0, "v2": 0.0},
        ),
        lane=FakeLaneAPI({"laneA": 1, "laneB": 1}),
        simulation=FakeSimulationAPI(arrived=["v2"], teleports=["v1"]),
    )

    collector.record_step(step1)
    collector.record_step(step2)

    metrics = collector.finalize(simulation_seconds=2.0)

    assert metrics.departed_vehicles == 2
    assert metrics.arrived_vehicles == 1
    assert metrics.throughput == 1
    assert metrics.active_vehicles_remaining == 1
    assert metrics.teleport_count == 1
    # queue: step1 = 1+0 = 1, step2 = 1+1 = 2 -> avg 1.5, max 2
    assert metrics.average_queue_length == pytest.approx(1.5)
    assert metrics.max_queue_length == 2
    # v1 stayed stopped both steps, v2 never stopped
    assert metrics.total_stopped_vehicles == 1
    # waiting time is the *last* observed value per vehicle: v1 -> 3.0, v2 -> 0.0
    assert metrics.average_waiting_time == pytest.approx(1.5)
    assert metrics.total_reward is None


def test_collector_add_reward_is_only_set_when_called():
    collector = MetricsCollector(controller="independent_q", scenario="low", seed=7)
    step = FakeTraci(
        vehicle=FakeVehicleAPI(speeds={}, waiting_times={}),
        lane=FakeLaneAPI({}),
        simulation=FakeSimulationAPI(),
    )
    collector.record_step(step)
    collector.add_reward(1.0)
    collector.add_reward(2.5)
    metrics = collector.finalize(simulation_seconds=1.0)
    assert metrics.total_reward == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Results writer (CSV)
# ---------------------------------------------------------------------------


def test_read_results_missing_file_returns_empty_list(tmp_path):
    missing_path = tmp_path / "does_not_exist.csv"
    assert read_results(missing_path) == []


def test_read_results_empty_file_returns_empty_list(tmp_path):
    empty_path = tmp_path / "empty.csv"
    empty_path.touch()
    assert read_results(empty_path) == []


def test_append_result_creates_directory_and_header_once(tmp_path):
    results_path = tmp_path / "nested" / "experiments.csv"
    metrics = EpisodeMetrics(**_valid_kwargs())

    append_result(metrics, path=results_path)
    assert results_path.exists()

    header_line = results_path.read_text().splitlines()[0]
    append_result(metrics, path=results_path)  # append a second row
    lines = results_path.read_text().splitlines()

    assert lines[0] == header_line
    assert lines.count(header_line) == 1  # header written only once
    assert len(lines) == 3  # header + 2 data rows


def test_append_result_preserves_previous_runs_and_column_order(tmp_path):
    results_path = tmp_path / "experiments.csv"

    append_result(EpisodeMetrics(**_valid_kwargs(seed=1)), path=results_path)
    append_result(EpisodeMetrics(**_valid_kwargs(seed=2)), path=results_path)

    rows = read_results(results_path)
    assert len(rows) == 2
    assert [row["seed"] for row in rows] == ["1", "2"]
    assert list(rows[0].keys())[:3] == ["controller", "scenario", "seed"]


# ---------------------------------------------------------------------------
# Summary script
# ---------------------------------------------------------------------------


def test_summarize_groups_by_controller_and_scenario():
    rows = [
        {
            "controller": "fixed_time",
            "scenario": "low",
            "average_waiting_time": "10.0",
            "average_queue_length": "2.0",
            "max_queue_length": "4",
            "average_speed": "9.0",
            "throughput": "100",
        },
        {
            "controller": "fixed_time",
            "scenario": "low",
            "average_waiting_time": "20.0",
            "average_queue_length": "4.0",
            "max_queue_length": "6",
            "average_speed": "7.0",
            "throughput": "90",
        },
        {
            "controller": "static_fixed_time",
            "scenario": "low",
            "average_waiting_time": "5.0",
            "average_queue_length": "1.0",
            "max_queue_length": "2",
            "average_speed": "10.0",
            "throughput": "110",
        },
    ]

    summary = summarize(rows)

    assert summary[("fixed_time", "low")]["run_count"] == 2
    assert summary[("fixed_time", "low")]["mean_average_waiting_time"] == pytest.approx(15.0)
    assert summary[("fixed_time", "low")]["stdev_average_waiting_time"] > 0
    assert summary[("static_fixed_time", "low")]["run_count"] == 1
    assert summary[("static_fixed_time", "low")]["stdev_average_waiting_time"] == 0.0


def test_summarize_handles_missing_and_malformed_values_without_crashing():
    rows = [
        {"controller": "fixed_time", "scenario": "medium"},  # all metrics missing
        {
            "controller": "fixed_time",
            "scenario": "medium",
            "average_waiting_time": "not-a-number",
        },
    ]
    summary = summarize(rows)
    entry = summary[("fixed_time", "medium")]
    assert entry["run_count"] == 2
    assert entry["mean_average_waiting_time"] == 0.0


def test_summarize_empty_input_returns_empty_summary():
    assert summarize([]) == {}

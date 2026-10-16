"""Unit tests for the experiment-metrics package.

None of these tests require SUMO or SUMO-GUI: the collector is tested
against a small in-memory fake that mimics the slice of the TraCI API it
actually uses.
"""

from __future__ import annotations

import pandas
import pytest
from traci import constants as tc

from scripts.analysis.summarize_experiments import summarize
from scripts.analysis.visualize_results import add_series_labels, format_run_length
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
# MetricsCollector batched reads via TraCI subscriptions
# ---------------------------------------------------------------------------


class SubscribingVehicleAPI(FakeVehicleAPI):
    """Vehicle domain with TraCI's real subscription timing.

    A subscription made during a step delivers nothing until the *next*
    step, so `active` holds the ids whose batched rows exist this step --
    the test advances it between steps the way SUMO would. Direct getter
    calls are recorded so the test can prove they only happen as the
    one-step fallback for a vehicle that has just appeared.
    """

    def __init__(self, speeds, waiting_times, active=()):
        super().__init__(speeds, waiting_times)
        self.active = set(active)
        self.subscribe_calls: list[str] = []
        self.getter_calls: list[tuple[str, str]] = []

    def subscribe(self, vid, var_ids):
        self.subscribe_calls.append(vid)

    def getAllSubscriptionResults(self):
        return {
            vid: {
                tc.VAR_SPEED: self._speeds[vid],
                tc.VAR_ACCUMULATED_WAITING_TIME: self._waiting_times[vid],
            }
            for vid in self._speeds
            if vid in self.active
        }

    def getSpeed(self, vid):
        self.getter_calls.append(("speed", vid))
        return super().getSpeed(vid)

    def getAccumulatedWaitingTime(self, vid):
        self.getter_calls.append(("wait", vid))
        return super().getAccumulatedWaitingTime(vid)


class SubscribingLaneAPI(FakeLaneAPI):
    def __init__(self, halting_by_lane, active=()):
        super().__init__(halting_by_lane)
        self.active = set(active)
        self.subscribe_calls: list[str] = []
        self.getter_calls: list[str] = []

    def subscribe(self, lane_id, var_ids):
        self.subscribe_calls.append(lane_id)

    def getAllSubscriptionResults(self):
        return {
            lane_id: {tc.LAST_STEP_VEHICLE_HALTING_NUMBER: count}
            for lane_id, count in self._halting_by_lane.items()
            if lane_id in self.active
        }

    def getLastStepHaltingNumber(self, lane_id):
        self.getter_calls.append(lane_id)
        return super().getLastStepHaltingNumber(lane_id)


_STEP1_SPEEDS = {"v1": 0.0, "v2": 5.0}
_STEP1_WAITS = {"v1": 2.0, "v2": 0.0}
_STEP1_LANES = {"laneA": 1, "laneB": 0}
_STEP2_SPEEDS = {"v1": 0.0, "v2": 6.0}
_STEP2_WAITS = {"v1": 3.0, "v2": 0.0}
_STEP2_LANES = {"laneA": 1, "laneB": 1}


def _collector():
    return MetricsCollector(
        controller="static_fixed_time",
        scenario="medium",
        seed=42,
        monitored_lanes=["laneA", "laneB"],
        stopped_speed_threshold=0.1,
    )


def test_subscription_path_reproduces_getter_path_exactly():
    """Batching changes how values are fetched, never which are counted."""
    legacy = _collector()
    legacy.record_step(
        FakeTraci(
            vehicle=FakeVehicleAPI(_STEP1_SPEEDS, _STEP1_WAITS),
            lane=FakeLaneAPI(_STEP1_LANES),
            simulation=FakeSimulationAPI(departed=["v1", "v2"]),
        )
    )
    legacy.record_step(
        FakeTraci(
            vehicle=FakeVehicleAPI(_STEP2_SPEEDS, _STEP2_WAITS),
            lane=FakeLaneAPI(_STEP2_LANES),
            simulation=FakeSimulationAPI(arrived=["v2"], teleports=["v1"]),
        )
    )

    batched = _collector()
    batched.record_step(
        FakeTraci(
            vehicle=SubscribingVehicleAPI(_STEP1_SPEEDS, _STEP1_WAITS, active=()),
            lane=SubscribingLaneAPI(_STEP1_LANES, active=()),
            simulation=FakeSimulationAPI(departed=["v1", "v2"]),
        )
    )
    batched.record_step(
        FakeTraci(
            vehicle=SubscribingVehicleAPI(
                _STEP2_SPEEDS, _STEP2_WAITS, active={"v1", "v2"}
            ),
            lane=SubscribingLaneAPI(_STEP2_LANES, active={"laneA", "laneB"}),
            simulation=FakeSimulationAPI(arrived=["v2"], teleports=["v1"]),
        )
    )

    assert batched.finalize(2.0) == legacy.finalize(2.0)


def test_subscriptions_are_made_once_and_getters_only_bridge_the_first_step():
    collector = _collector()

    step1_vehicle = SubscribingVehicleAPI(_STEP1_SPEEDS, _STEP1_WAITS, active=())
    step1_lane = SubscribingLaneAPI(_STEP1_LANES, active=())
    collector.record_step(
        FakeTraci(step1_vehicle, step1_lane, FakeSimulationAPI(departed=["v1", "v2"]))
    )

    # Nothing is batched yet, so every value for this step came from a
    # direct getter -- but each vehicle and lane was subscribed for next time.
    assert step1_vehicle.subscribe_calls == ["v1", "v2"]
    assert step1_lane.subscribe_calls == ["laneA", "laneB"]
    assert sorted(step1_vehicle.getter_calls) == [
        ("speed", "v1"),
        ("speed", "v2"),
        ("wait", "v1"),
        ("wait", "v2"),
    ]
    assert step1_lane.getter_calls == ["laneA", "laneB"]

    step2_vehicle = SubscribingVehicleAPI(
        _STEP2_SPEEDS, _STEP2_WAITS, active={"v1", "v2"}
    )
    step2_lane = SubscribingLaneAPI(_STEP2_LANES, active={"laneA", "laneB"})
    collector.record_step(
        FakeTraci(step2_vehicle, step2_lane, FakeSimulationAPI(arrived=["v2"]))
    )

    # Already subscribed: no new subscriptions and no per-object getters at
    # all -- the whole step was served by the two batched reads.
    assert step2_vehicle.subscribe_calls == []
    assert step2_lane.subscribe_calls == []
    assert step2_vehicle.getter_calls == []
    assert step2_lane.getter_calls == []


def test_newly_appearing_vehicle_is_bridged_by_getters_mid_run():
    """A vehicle departing mid-run is read directly for its first step only."""
    collector = _collector()
    collector.record_step(
        FakeTraci(
            SubscribingVehicleAPI({"v1": 1.0}, {"v1": 0.0}, active=()),
            SubscribingLaneAPI({}, active=()),
            FakeSimulationAPI(departed=["v1"]),
        )
    )

    later = SubscribingVehicleAPI(
        {"v1": 1.0, "v9": 0.0}, {"v1": 0.0, "v9": 4.0}, active={"v1"}
    )
    collector.record_step(
        FakeTraci(later, SubscribingLaneAPI({}, active={"laneA", "laneB"}), FakeSimulationAPI(departed=["v9"]))
    )

    assert later.subscribe_calls == ["v9"]
    assert sorted(later.getter_calls) == [("speed", "v9"), ("wait", "v9")]
    metrics = collector.finalize(2.0)
    # v9's first-step observation was counted despite having no batched row.
    assert metrics.total_stopped_vehicles == 1
    assert metrics.average_waiting_time == pytest.approx(2.0)


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
            "demand_seconds": "3600.0",
            "average_waiting_time": "10.0",
            "average_queue_length": "2.0",
            "max_queue_length": "4",
            "average_speed": "9.0",
            "throughput": "100",
        },
        {
            "controller": "fixed_time",
            "scenario": "low",
            "demand_seconds": "3600.0",
            "average_waiting_time": "20.0",
            "average_queue_length": "4.0",
            "max_queue_length": "6",
            "average_speed": "7.0",
            "throughput": "90",
        },
        {
            "controller": "static_fixed_time",
            "scenario": "low",
            "demand_seconds": "3600.0",
            "average_waiting_time": "5.0",
            "average_queue_length": "1.0",
            "max_queue_length": "2",
            "average_speed": "10.0",
            "throughput": "110",
        },
    ]

    summary = summarize(rows)

    fixed_time = summary[("fixed_time", "low", "3600")]
    assert fixed_time["run_count"] == 2
    assert fixed_time["mean_average_waiting_time"] == pytest.approx(15.0)
    assert fixed_time["stdev_average_waiting_time"] > 0
    assert summary[("static_fixed_time", "low", "3600")]["run_count"] == 1
    assert (
        summary[("static_fixed_time", "low", "3600")][
            "stdev_average_waiting_time"
        ]
        == 0.0
    )


def test_summarize_never_averages_runs_of_different_length():
    """A short evaluation and a full one are two experiments, not two runs."""
    rows = [
        {
            "controller": "multi_agent_independent_rl",
            "scenario": "medium",
            "demand_seconds": "600.0",
            "average_waiting_time": "13.18",
        },
        {
            "controller": "multi_agent_independent_rl",
            "scenario": "medium",
            "demand_seconds": "3600.0",
            "average_waiting_time": "7.0",
        },
    ]

    summary = summarize(rows)

    short = summary[("multi_agent_independent_rl", "medium", "600")]
    full = summary[("multi_agent_independent_rl", "medium", "3600")]
    assert short["run_count"] == 1
    assert full["run_count"] == 1
    assert short["mean_average_waiting_time"] == pytest.approx(13.18)
    assert full["mean_average_waiting_time"] == pytest.approx(7.0)


def test_summarize_labels_rows_without_a_demand_period():
    """Rows written before the column existed stay visible as their own group."""
    rows = [{"controller": "fixed_time", "scenario": "low"}]

    summary = summarize(rows)

    assert summary[("fixed_time", "low", "unknown")]["run_count"] == 1


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
    entry = summary[("fixed_time", "medium", "unknown")]
    assert entry["run_count"] == 2
    assert entry["mean_average_waiting_time"] == 0.0


def test_summarize_empty_input_returns_empty_summary():
    assert summarize([]) == {}


# ---------------------------------------------------------------------------
# Visualization script
# ---------------------------------------------------------------------------


def test_plot_series_keep_one_label_while_run_lengths_agree():
    """Consistent results plot exactly as they always did."""
    frame = pandas.DataFrame(
        {
            "controller": ["static_fixed_time", "independent_rl"],
            "demand_seconds": [3600.0, 3600.0],
        }
    )

    labelled = add_series_labels(frame)

    assert list(labelled["series"]) == ["Static Fixed-Time", "Independent Rl"]


def test_plot_series_name_the_run_length_once_it_varies():
    """Mixed run lengths become separate, self-describing plot series."""
    frame = pandas.DataFrame(
        {
            "controller": [
                "multi_agent_independent_rl",
                "multi_agent_independent_rl",
                "static_fixed_time",
            ],
            "demand_seconds": [600.0, 3600.0, 3600.0],
        }
    )

    labelled = add_series_labels(frame)

    assert list(labelled["series"]) == [
        "Multi Agent Independent Rl (600s demand)",
        "Multi Agent Independent Rl (3600s demand)",
        "Static Fixed-Time (3600s demand)",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (3600.0, "3600s demand"),
        ("600", "600s demand"),
        (None, "unknown demand"),
        ("", "unknown demand"),
    ),
)
def test_run_length_labels_tolerate_missing_values(value, expected):
    assert format_run_length(value) == expected

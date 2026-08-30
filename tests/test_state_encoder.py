"""Unit tests for deterministic tabular traffic-state encoding."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from src.agents.state_encoder import (
    DiscreteTrafficState,
    StateEncoderConfig,
    TrafficStateEncoder,
)
from src.environment.observations import TrafficObservation


def make_observation(
    *,
    queue_lengths: tuple[int, ...] = (0, 0),
    waiting_times: tuple[float, ...] = (0.0, 0.0),
    phase_index: int = 0,
    elapsed_seconds: float = 0.0,
    is_green: bool = True,
    is_transition: bool = False,
    agent_id: str = "A19",
    traffic_light_id: str = "cluster_A19",
    simulation_time: float = 0.0,
) -> TrafficObservation:
    """Build one valid observation with aligned lane metrics."""
    lane_count = len(queue_lengths)
    assert len(waiting_times) == lane_count
    lane_ids = tuple(f"lane_{index}" for index in range(lane_count))
    return TrafficObservation(
        agent_id=agent_id,
        traffic_light_id=traffic_light_id,
        simulation_time=simulation_time,
        incoming_lane_ids=lane_ids,
        queue_lengths=queue_lengths,
        vehicle_counts=queue_lengths,
        mean_waiting_times=waiting_times,
        mean_speeds=(0.0,) * lane_count,
        current_phase_index=phase_index,
        current_phase_state="yy" if is_transition else "GG",
        current_phase_elapsed_seconds=elapsed_seconds,
        is_green_phase=is_green,
        is_transition_phase=is_transition,
    )


def test_encoder_output_is_deterministic_and_hashable() -> None:
    """Repeated encoding returns one usable table key."""
    encoder = TrafficStateEncoder(green_phase_indices=(0, 3))
    observation = make_observation(
        queue_lengths=(2, 4),
        waiting_times=(10.0, 20.0),
        phase_index=3,
        elapsed_seconds=25.0,
    )

    first = encoder.encode(observation)
    second = encoder.encode(observation)

    assert first == second
    assert isinstance(first, DiscreteTrafficState)
    assert hash(first) == hash(second)
    assert {first: "stored"}[second] == "stored"


def test_empty_lanes_encode_without_division_errors() -> None:
    """An empty controller observation uses zero-valued traffic buckets."""
    state = TrafficStateEncoder().encode(
        make_observation(queue_lengths=(), waiting_times=())
    )

    assert state.total_queue_bucket == 0
    assert state.maximum_lane_queue_bucket == 0
    assert state.mean_lane_waiting_time_bucket == 0


@pytest.mark.parametrize(
    ("total_queue", "expected_bucket"),
    (
        (0, 0),
        (1, 1),
        (3, 1),
        (4, 2),
        (7, 2),
        (8, 3),
        (15, 3),
        (16, 4),
        (100, 4),
    ),
)
def test_total_queue_bucket_boundaries(
    total_queue: int,
    expected_bucket: int,
) -> None:
    """Total queue follows the documented 0, 1-3, 4-7, 8-15, 16+ bins."""
    state = TrafficStateEncoder().encode(
        make_observation(
            queue_lengths=(total_queue,),
            waiting_times=(0.0,),
        )
    )
    assert state.total_queue_bucket == expected_bucket


@pytest.mark.parametrize(
    ("maximum_queue", "expected_bucket"),
    (
        (0, 0),
        (1, 1),
        (2, 1),
        (3, 2),
        (5, 2),
        (6, 3),
        (10, 3),
        (11, 4),
        (50, 4),
    ),
)
def test_maximum_lane_queue_bucket_boundaries(
    maximum_queue: int,
    expected_bucket: int,
) -> None:
    """Maximum lane queue follows the configured inclusive ranges."""
    state = TrafficStateEncoder().encode(
        make_observation(
            queue_lengths=(0, maximum_queue),
            waiting_times=(0.0, 0.0),
        )
    )
    assert state.maximum_lane_queue_bucket == expected_bucket


@pytest.mark.parametrize(
    ("waiting_time", "expected_bucket"),
    (
        (0.0, 0),
        (4.999, 0),
        (5.0, 1),
        (14.999, 1),
        (15.0, 2),
        (29.999, 2),
        (30.0, 3),
        (59.999, 3),
        (60.0, 4),
        (120.0, 4),
    ),
)
def test_waiting_time_bucket_boundaries(
    waiting_time: float,
    expected_bucket: int,
) -> None:
    """Mean lane waiting uses 5, 15, 30, and 60 second lower boundaries."""
    state = TrafficStateEncoder().encode(
        make_observation(
            queue_lengths=(0,),
            waiting_times=(waiting_time,),
        )
    )
    assert state.mean_lane_waiting_time_bucket == expected_bucket


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected_bucket"),
    (
        (0.0, 0),
        (9.999, 0),
        (10.0, 1),
        (19.999, 1),
        (20.0, 2),
        (39.999, 2),
        (40.0, 3),
        (59.999, 3),
        (60.0, 4),
        (90.0, 4),
    ),
)
def test_elapsed_time_bucket_boundaries(
    elapsed_seconds: float,
    expected_bucket: int,
) -> None:
    """Elapsed phase time uses 10, 20, 40, and 60 second boundaries."""
    state = TrafficStateEncoder().encode(
        make_observation(elapsed_seconds=elapsed_seconds)
    )
    assert state.phase_elapsed_bucket == expected_bucket


def test_known_green_phase_uses_sequence_position() -> None:
    """Controller metadata maps an original phase index to green order."""
    encoder = TrafficStateEncoder(green_phase_indices=(0, 3, 6))
    state = encoder.encode(make_observation(phase_index=3))
    assert state.green_phase_position == 1


def test_missing_green_sequence_uses_raw_phase_index() -> None:
    """Without controller metadata the phase index remains deterministic."""
    state = TrafficStateEncoder().encode(make_observation(phase_index=6))
    assert state.green_phase_position == 6


def test_transition_phase_is_explicit_and_uses_sentinel() -> None:
    """Transitions cannot collide with a known green-phase position."""
    encoder = TrafficStateEncoder(green_phase_indices=(0, 3, 6))
    state = encoder.encode(
        make_observation(
            phase_index=1,
            is_green=False,
            is_transition=True,
        )
    )

    assert state.green_phase_position == -1
    assert state.is_transition_phase is True


def test_identifiers_lane_ids_and_simulation_time_do_not_affect_state() -> None:
    """Episode identity and absolute time stay outside the Q-table key."""
    encoder = TrafficStateEncoder()
    original = make_observation(simulation_time=10.0)
    changed_identity = replace(
        original,
        agent_id="A26",
        traffic_light_id="different_controller",
        simulation_time=999.0,
        incoming_lane_ids=("renamed_0", "renamed_1"),
    )

    assert encoder.encode(original) == encoder.encode(changed_identity)


def test_equivalent_bucketed_observations_share_state() -> None:
    """Different raw lane layouts can represent the same traffic condition."""
    encoder = TrafficStateEncoder()
    first = make_observation(
        queue_lengths=(1, 1),
        waiting_times=(6.0, 8.0),
        elapsed_seconds=11.0,
    )
    second = make_observation(
        queue_lengths=(2,),
        waiting_times=(14.0,),
        elapsed_seconds=19.0,
    )

    assert encoder.encode(first) == encoder.encode(second)


def test_materially_different_traffic_conditions_have_different_states() -> None:
    """Heavy queued traffic must not alias an empty observation."""
    encoder = TrafficStateEncoder()
    empty = make_observation()
    congested = make_observation(
        queue_lengths=(12, 8),
        waiting_times=(70.0, 80.0),
        elapsed_seconds=65.0,
    )

    assert encoder.encode(empty) != encoder.encode(congested)


def test_custom_bucket_configuration_is_frozen_and_used() -> None:
    """Callers can select stable alternative lower boundaries."""
    config = StateEncoderConfig(
        total_queue_thresholds=(2, 5),
        maximum_lane_queue_thresholds=(2, 5),
        mean_waiting_time_thresholds_seconds=(10.0,),
        phase_elapsed_thresholds_seconds=(30.0,),
    )
    state = TrafficStateEncoder(config).encode(
        make_observation(
            queue_lengths=(2,),
            waiting_times=(10.0,),
            elapsed_seconds=30.0,
        )
    )

    assert state.total_queue_bucket == 1
    assert state.maximum_lane_queue_bucket == 1
    assert state.mean_lane_waiting_time_bucket == 1
    assert state.phase_elapsed_bucket == 1
    with pytest.raises(FrozenInstanceError):
        config.total_queue_thresholds = (1,)  # type: ignore[misc]


def test_local_encoder_leaves_neighbor_flags_empty() -> None:
    """A purely local state stays exactly what it was before sharing existed."""
    state = TrafficStateEncoder().encode(make_observation())
    assert state.neighbor_queue_flags == ()


@pytest.mark.parametrize(
    ("neighbor_queue", "expected_flag"),
    ((0, 0), (1, 0), (3, 0), (4, 1), (12, 1)),
)
def test_neighbor_queue_flag_uses_a_two_bucket_threshold(
    neighbor_queue: int,
    expected_flag: int,
) -> None:
    """A neighbor is reported as one congestion bit, not a full bucket."""
    encoder = TrafficStateEncoder(neighbor_ids=("A26",))
    state = encoder.encode(
        make_observation(agent_id="A19"),
        {
            "A26": make_observation(
                agent_id="A26",
                queue_lengths=(neighbor_queue,),
                waiting_times=(0.0,),
            )
        },
    )
    assert state.neighbor_queue_flags == (expected_flag,)


def test_neighbor_flags_follow_configured_neighbor_order() -> None:
    """Flag positions are the encoder's neighbor order, not mapping order."""
    encoder = TrafficStateEncoder(neighbor_ids=("A26", "A9"))
    state = encoder.encode(
        make_observation(agent_id="A19"),
        {
            "A9": make_observation(
                agent_id="A9",
                queue_lengths=(9,),
                waiting_times=(0.0,),
            ),
            "A26": make_observation(
                agent_id="A26",
                queue_lengths=(0,),
                waiting_times=(0.0,),
            ),
        },
    )
    assert encoder.neighbor_ids == ("A26", "A9")
    assert state.neighbor_queue_flags == (0, 1)


def test_unrelated_observations_in_the_snapshot_are_ignored() -> None:
    """Callers may pass a whole corridor snapshot, including the agent itself."""
    encoder = TrafficStateEncoder(neighbor_ids=("A26",))
    local = make_observation(agent_id="A19", queue_lengths=(9,), waiting_times=(0.0,))
    neighbor = make_observation(
        agent_id="A26",
        queue_lengths=(0,),
        waiting_times=(0.0,),
    )
    unrelated = make_observation(
        agent_id="A24",
        queue_lengths=(30,),
        waiting_times=(0.0,),
    )
    snapshot = {"A19": local, "A26": neighbor, "A24": unrelated}

    assert encoder.encode(local, snapshot).neighbor_queue_flags == (0,)


def test_congested_neighbors_produce_distinct_table_keys() -> None:
    """The whole point of sharing: identical local traffic, separable states."""
    encoder = TrafficStateEncoder(neighbor_ids=("A26",))
    local = make_observation(agent_id="A19")
    quiet = encoder.encode(
        local,
        {"A26": make_observation(agent_id="A26", queue_lengths=(0,), waiting_times=(0.0,))},
    )
    busy = encoder.encode(
        local,
        {"A26": make_observation(agent_id="A26", queue_lengths=(12,), waiting_times=(0.0,))},
    )

    assert quiet != busy
    assert hash(quiet) != hash(busy)
    assert {quiet: "quiet", busy: "busy"}[busy] == "busy"


def test_spatial_state_is_never_equal_to_the_local_state_it_extends() -> None:
    """Local and spatial Q-tables must not share keys by accident."""
    local_state = TrafficStateEncoder().encode(make_observation(agent_id="A19"))
    spatial_state = TrafficStateEncoder(neighbor_ids=("A26",)).encode(
        make_observation(agent_id="A19"),
        {"A26": make_observation(agent_id="A26", queue_lengths=(0,), waiting_times=(0.0,))},
    )

    assert spatial_state.neighbor_queue_flags == (0,)
    assert local_state != spatial_state


def test_missing_neighbor_observation_is_rejected() -> None:
    """A dropped neighbor would silently change what a table key means."""
    encoder = TrafficStateEncoder(neighbor_ids=("A26", "A9"))
    with pytest.raises(ValueError, match="missing configured neighbors: A9"):
        encoder.encode(
            make_observation(agent_id="A19"),
            {"A26": make_observation(agent_id="A26")},
        )
    with pytest.raises(ValueError, match="requires neighbor_observations"):
        encoder.encode(make_observation(agent_id="A19"))


def test_neighbor_observations_without_configured_neighbors_are_rejected() -> None:
    """Passing neighbors to a local encoder would be silently ignored data."""
    with pytest.raises(ValueError, match="not configured with neighbor_ids"):
        TrafficStateEncoder().encode(
            make_observation(agent_id="A19"),
            {"A26": make_observation(agent_id="A26")},
        )


@pytest.mark.parametrize(
    "neighbor_ids",
    ((), ("A26", "A26"), ("",), "A26", (7,)),
)
def test_invalid_neighbor_ids_are_rejected(neighbor_ids) -> None:
    with pytest.raises(ValueError):
        TrafficStateEncoder(neighbor_ids=neighbor_ids)


def test_neighbor_threshold_is_configurable_and_validated() -> None:
    encoder = TrafficStateEncoder(
        StateEncoderConfig(neighbor_total_queue_threshold=10),
        neighbor_ids=("A26",),
    )
    state = encoder.encode(
        make_observation(agent_id="A19"),
        {
            "A26": make_observation(
                agent_id="A26",
                queue_lengths=(9,),
                waiting_times=(0.0,),
            )
        },
    )
    assert state.neighbor_queue_flags == (0,)
    with pytest.raises(ValueError, match="neighbor_total_queue_threshold"):
        StateEncoderConfig(neighbor_total_queue_threshold=0)

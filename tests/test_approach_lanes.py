"""Tests for the upstream approach lanes built from the SUMO network."""

from __future__ import annotations

import pytest

from src.config import SKOPJE_INITIAL_NETWORK_FILE
from src.environment.approach_lanes import _read_net, build_approach_lanes
from src.environment.selected_corridor import SELECTED_CORRIDOR

pytest.importorskip("sumolib")


def _controlled_lanes(agent_id: str) -> list[str]:
    tls = _read_net(str(SKOPJE_INITIAL_NETWORK_FILE)).getTLS(
        SELECTED_CORRIDOR.agent_to_traffic_light[agent_id]
    )
    return list(dict.fromkeys(c[0].getID() for c in tls.getConnections()))


def test_zero_range_keeps_the_controlled_lanes_only():
    assert build_approach_lanes(SKOPJE_INITIAL_NETWORK_FILE, _controlled_lanes("A19"), 0) == {}


def test_every_upstream_lane_belongs_to_one_controlled_lane_and_is_cut_at_range():
    net = _read_net(str(SKOPJE_INITIAL_NETWORK_FILE))
    lanes = _controlled_lanes("A20")
    approaches = build_approach_lanes(SKOPJE_INITIAL_NETWORK_FILE, lanes, 150.0)
    assert set(approaches) == set(lanes)
    upstream = [lane for pairs in approaches.values() for lane, _ in pairs]
    assert len(upstream) == len(set(upstream))
    assert not set(upstream) & set(lanes)
    for pairs in approaches.values():
        for lane_id, start in pairs:
            assert 0.0 <= start <= net.getLane(lane_id).getLength()
    assert upstream, "a 150 m range must reach past the short stop-line lanes"


def test_walk_stops_at_other_agents():
    others = [
        tls for agent, tls in SELECTED_CORRIDOR.agent_to_traffic_light.items() if agent != "A19"
    ]
    lanes = _controlled_lanes("A19")
    free = build_approach_lanes(SKOPJE_INITIAL_NETWORK_FILE, lanes, 2000.0)
    stopped = build_approach_lanes(SKOPJE_INITIAL_NETWORK_FILE, lanes, 2000.0, others)
    count = lambda approaches: sum(len(pairs) for pairs in approaches.values())  # noqa: E731
    assert count(stopped) < count(free)

"""Upstream lanes that extend each controlled lane into a full approach.

Most controlled lanes on the Skopje network are the last few metres before
the stop line (median ~18 m, about three cars), so a queue longer than that is
invisible to the agent. Walking upstream to a fixed range gives the agent the
whole queue, like a detector placed further back.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

import sumolib


@lru_cache(maxsize=4)
def _read_net(net_file: str):
    return sumolib.net.readNet(net_file, withPrograms=True)


def build_approach_lanes(
    net_file: Path,
    controlled_lane_ids: Iterable[str],
    range_m: float,
    stop_traffic_light_ids: Iterable[str] = (),
) -> Mapping[str, tuple[tuple[str, float], ...]]:
    """Map each controlled lane to ``(upstream lane, start position)`` pairs.

    Only vehicles at or past the start position are within ``range_m`` of the
    stop line, so a long upstream lane is cut off at the range.

    The walk crosses unsignalized junctions and other lights but stops at the
    nodes of ``stop_traffic_light_ids`` (the other agents), whose queues belong
    to them. A lane reachable from several controlled lanes is given to the
    closest one, so no vehicle is counted twice.
    """
    if range_m <= 0:
        return {}
    net = _read_net(str(net_file))
    stop_nodes = {
        connection[0].getEdge().getToNode().getID()
        for tls_id in stop_traffic_light_ids
        for connection in net.getTLS(tls_id).getConnections()
    }
    controlled = tuple(dict.fromkeys(controlled_lane_ids))
    claimed: dict[str, tuple[float, str]] = {lane_id: (0.0, lane_id) for lane_id in controlled}
    frontier = []
    for lane_id in controlled:
        lane = net.getLane(lane_id)
        frontier.append((lane.getLength(), lane, lane_id))
    while frontier:
        frontier.sort(key=lambda item: item[0])
        distance, lane, owner = frontier.pop(0)
        if distance >= range_m:
            continue
        if lane.getEdge().getFromNode().getID() in stop_nodes:
            continue
        for upstream in lane.getIncoming():
            upstream_id = upstream.getID()
            if upstream_id.startswith(":") or upstream_id in claimed:
                continue
            claimed[upstream_id] = (distance, owner)
            frontier.append((distance + upstream.getLength(), upstream, owner))
    approaches: dict[str, list[tuple[str, float]]] = {lane_id: [] for lane_id in controlled}
    for lane_id, (distance, owner) in claimed.items():
        if lane_id != owner:
            length = net.getLane(lane_id).getLength()
            approaches[owner].append((lane_id, max(0.0, length - (range_m - distance))))
    return {lane_id: tuple(lanes) for lane_id, lanes in approaches.items()}

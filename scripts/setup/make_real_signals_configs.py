"""Create SUMO configs for the real-signals network from the original ones.

The real-signals variant (SKOPJE_NETWORK=real_signals) uses the same demand as
the original network but a different net file, so its configs are copies of the
original configs with the ``net-file`` reference changed. The site-checked road
fixes removed two slip roads and split one edge, so routes that used them are
repaired (removed edges dropped, gaps filled with the shortest connecting path;
departures, origins and destinations unchanged) into
``demand/scenarios_real_signals/`` and only those configs point there.
Re-run after rebuilding the network or adding demand (for example ``peak``)::

    python scripts/setup/make_real_signals_configs.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SKOPJE_DIR = Path(__file__).resolve().parents[2] / "sumo" / "skopje"
CONFIG_DIR = SKOPJE_DIR / "config"
ORIGINAL_NET = "skopje_initial.net.xml.gz"
VARIANT_NET = "skopje_real_signals.net.xml.gz"
ORIGINAL_DEMAND = "demand/scenarios/"
VARIANT_DEMAND = "demand/scenarios_real_signals/"


def load_net():
    sumo_home = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo"))
    sys.path.insert(0, str(sumo_home / "tools"))
    import sumolib

    return sumolib.net.readNet(str(SKOPJE_DIR / "network" / VARIANT_NET))


def repair_route(edges: list[str], net) -> list[str]:
    kept = [e for e in edges if net.hasEdge(e)]
    repaired = kept[:1]
    for edge_id in kept[1:]:
        previous, edge = net.getEdge(repaired[-1]), net.getEdge(edge_id)
        if edge not in previous.getOutgoing():
            path, _ = net.getShortestPath(previous, edge, vClass="passenger")
            if path is None:
                continue  # only reachable through a removed edge: drop it like the removed one
            repaired += [e.getID() for e in path[1:-1]]
        repaired.append(edge_id)
    if repaired[-1] != kept[-1]:
        raise ValueError(f"route to {kept[-1]} cannot reach its destination any more")
    return repaired


def repair_routes(source: Path, target: Path, net) -> int:
    """Write repaired routes to target; return how many changed (0 writes nothing)."""
    changed = 0

    def fix(match: re.Match) -> str:
        nonlocal changed
        edges = match.group(1).split()
        repaired = repair_route(edges, net)
        if repaired == edges:
            return match.group(0)
        changed += 1
        return f'<route edges="{" ".join(repaired)}"'

    text = re.sub(r'<route edges="([^"]+)"', fix, source.read_text(encoding="utf-8"))
    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return changed


def convert(source: Path, target: Path, net) -> str:
    text = source.read_text(encoding="utf-8")
    if ORIGINAL_NET not in text:
        raise ValueError(f"{source} does not reference {ORIGINAL_NET}.")
    text = text.replace(ORIGINAL_NET, VARIANT_NET)
    note = ""
    route = re.search(r'<route-files value="([^"]+)"', text)
    if route and ORIGINAL_DEMAND in route.group(1):
        original_routes = (source.parent / route.group(1)).resolve()
        variant_value = route.group(1).replace(ORIGINAL_DEMAND, VARIANT_DEMAND)
        changed = repair_routes(original_routes, (target.parent / variant_value).resolve(), net)
        if changed:
            text = text.replace(route.group(1), variant_value)
            note = f" ({changed} routes repaired)"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return note


def main() -> int:
    net = load_net()
    convert(CONFIG_DIR / "skopje_initial.sumocfg", CONFIG_DIR / "skopje_initial_real_signals.sumocfg", net)
    count = 1
    for source in sorted((CONFIG_DIR / "scenarios").glob("*.sumocfg")):
        note = convert(source, CONFIG_DIR / "scenarios_real_signals" / source.name, net)
        print(f"{source.name}{note}")
        count += 1
    print(f"Wrote {count} real-signals configs under {CONFIG_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

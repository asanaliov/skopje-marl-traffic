"""Rebuild skopje_real_signals.net.xml.gz from the #72 recode and the site-checked patches.

    python scripts/setup/build_real_signals_network.py

An edge patch alone keeps the old lane-to-lane connections and leaves dead lanes,
so every edge whose lanes change, and every edge feeding it, gets its connections
re-guessed. Approaches whose turns were checked on site get explicit connections.
Signal programs are regenerated only for lights whose links changed: agents keep
the one-approach-per-phase rule of the #72 recode, pedestrian-only lights stop
just the boulevard through lanes. The net is written only if every check passes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NETWORK_DIR = PROJECT_ROOT / "sumo" / "skopje" / "network"
PATCHES = NETWORK_DIR / "real_signals_patches"
BASE = PATCHES / "base.net.xml.gz"
OUTPUT = NETWORK_DIR / "skopje_real_signals.net.xml.gz"

# lights whose links are expected to change; anything else changing fails the build
AGENT_LIGHTS = {
    "GS_cluster_170640546_170645388_170684654_170684655",  # a19 soboren
    "GS_cluster_1839000563_1839000611_1839000738_365292561",  # a24 finki-makpetrol
    "GS_cluster_2414241934_2593819789",  # a25 ruzvelt
    "GS_cluster_170712177_1848310997",  # a21 kliment ohridski x ilinden
}
PEDESTRIAN_LIGHTS = {
    "cluster_12549999855_4127480432_4537363482_4537363483_#2more",  # a29
    "cluster_12549999856_2458486828_3830563710_6206171929_#3more",  # leninova
    "cluster_287496085_3830563709_6221854337_6221854340_#2more",  # silbo
}
# right-turn arrow that also runs in a non-conflicting phase: (light, from edge, to edge)
OVERLAPS = [("GS_cluster_170712177_1848310997", "671643167#0", "42875018#0")]
GREEN = '<phase duration="20" state="{}" minDur="5" maxDur="50"/>'
YELLOW = '<phase duration="3" state="{}"/>'


SUMO_HOME = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo"))
# the seven junctions recoded in #72; the approach rule must reproduce them
RECODED = {
    "GS_12432953582", "GS_cluster_170638629_170642149_170723177_418949594",
    "GS_cluster_170640546_170645388_170684654_170684655", "GS_cluster_170664726_3563678918",
    "GS_cluster_1839000563_1839000611_1839000738_365292561", "GS_cluster_2414241934_2593819789",
    "GS_cluster_511207145_8301921419",
}


def sumo_tools() -> None:
    sys.path.insert(0, str(SUMO_HOME / "tools"))


def netconvert(*args: str) -> None:
    result = subprocess.run([str(SUMO_HOME / "bin" / "netconvert"), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip().splitlines()[-1])


def tls_links(net) -> dict[str, list]:
    """Controlled connections per light, ordered by link index."""
    links = {}
    for tls in net.getTrafficLights():
        links[tls.getID()] = sorted(tls.getConnections(), key=lambda c: c[2])
    return links


def link_key(link) -> tuple:
    in_lane, out_lane, _ = link
    return (in_lane.getEdge().getID(), in_lane.getIndex(), out_lane.getEdge().getID(), out_lane.getIndex())


def approach_phases(links: list) -> list[str]:
    """One green and one yellow per approach, approaches in link order (the #72 rule)."""
    approaches: dict[str, list[int]] = {}
    for position, (in_lane, _, _) in enumerate(links):
        approaches.setdefault(in_lane.getEdge().getID(), []).append(position)
    phases = []
    for members in approaches.values():
        green = ["r"] * len(links)
        for i in members:
            green[i] = "G"
        phases += ["".join(green), "".join(green).replace("G", "y")]
    return phases


def add_overlap(net, links: list, phases: list[str], from_edge: str, to_edge: str) -> list[str]:
    """Also give a turn green in the first other green phase where it has no conflicts."""
    turn = next(i for i, link in enumerate(links)
                if link[0].getEdge().getID() == from_edge and link[1].getEdge().getID() == to_edge)
    node = links[turn][0].getEdge().getToNode()

    def conn(link):
        return next(c for c in link[0].getEdge().getConnections(link[1].getEdge())
                    if c.getFromLane() == link[0] and c.getToLane() == link[1])

    turn_index = node.getLinkIndex(conn(links[turn]))
    for p in range(0, len(phases), 2):
        greens = [i for i, s in enumerate(phases[p]) if s == "G"]
        if turn in greens:
            continue
        if not any(node.areFoes(turn_index, node.getLinkIndex(conn(links[i])))
                   or node.areFoes(node.getLinkIndex(conn(links[i])), turn_index) for i in greens):
            phases[p] = phases[p][:turn] + "G" + phases[p][turn + 1:]
            phases[p + 1] = phases[p + 1][:turn] + "y" + phases[p + 1][turn + 1:]
            return phases
    raise RuntimeError(f"no conflict-free phase for the {from_edge} -> {to_edge} overlap")


def tll_entry(light: str, phases: list[str], links: list, actuated_bounds: dict | None = None) -> list[str]:
    lines = [f'    <tlLogic id="{light}" type="actuated" programID="0" offset="0">']
    for state in phases:
        if actuated_bounds:
            lines.append("        " + actuated_bounds[state[0] if "G" not in state else "G"].format(state))
        else:
            lines.append("        " + (GREEN if "G" in state else YELLOW).format(state))
    lines.append("    </tlLogic>")
    for index, link in enumerate(links):
        frm, from_lane, to, to_lane = link_key(link)
        lines.append(f'    <connection from="{frm}" to="{to}" fromLane="{from_lane}" '
                     f'toLane="{to_lane}" tl="{light}" linkIndex="{index}"/>')
    return lines


def pedestrian_phases(links: list) -> list[str]:
    n = len(links)
    return ["G" * n, "y" * n, "r" * n]


PEDESTRIAN_BOUNDS = {
    "G": '<phase duration="50" state="{}" minDur="5" maxDur="50"/>',
    "y": '<phase duration="3" state="{}"/>',
    "r": '<phase duration="10" state="{}" minDur="5" maxDur="15"/>',
}


def main() -> int:
    sumo_tools()
    import sumolib

    base = sumolib.net.readNet(str(BASE), withPrograms=True)
    base_links = tls_links(base)
    lanes_text = (PATCHES / "lanes.edg.xml").read_text(encoding="utf-8")
    changed = re.findall(r'<edge id="([^"]+)" numLanes', lanes_text)
    deleted = re.findall(r'<delete id="([^"]+)"', lanes_text)
    explicit_text = (PATCHES / "approach_turns.con.xml").read_text(encoding="utf-8")
    explicit = set(re.findall(r'<connection from="([^"]+)"', explicit_text))

    # the #72 rule must reproduce the existing agent programs before it is trusted
    for light in sorted(RECODED):
        states = [p.state for p in base.getTLS(light).getPrograms()["0"].getPhases()]
        if states != approach_phases(base_links[light]):
                raise RuntimeError(f"approach rule does not reproduce {light}")

    reset = set(changed)
    for edge_id in changed + deleted:
        from_node = base.getEdge(edge_id).getFromNode()
        if not from_node.getType().startswith("traffic_light"):
            reset.update(e.getID() for e in from_node.getIncoming() if e.getID() not in deleted)
    reset -= explicit

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        resets = tmp / "resets.con.xml"
        resets.write_text("<connections>\n" + "".join(
            f'    <connection from="{e}" reset="true"/>\n' for e in sorted(reset)) + "</connections>\n")
        netconvert("-s", str(BASE), "-e", str(PATCHES / "lanes.edg.xml"),
                   "-x", f"{resets},{PATCHES / 'pedestrian_turns.con.xml'}", "-o", str(tmp / "p1.net.xml.gz"))

        p1 = sumolib.net.readNet(str(tmp / "p1.net.xml.gz"))
        deletes = tmp / "deletes.con.xml"
        deletes.write_text("<connections>\n" + "".join(
            f'    <delete from="{e}" to="{to.getID()}"/>\n'
            for e in sorted(explicit) for to in p1.getEdge(e).getOutgoing()) + "</connections>\n")
        netconvert("-s", str(tmp / "p1.net.xml.gz"), "-x", str(deletes), "-o", str(tmp / "p2.net.xml.gz"))
        netconvert("-s", str(tmp / "p2.net.xml.gz"), "-x", str(PATCHES / "approach_turns.con.xml"),
                   "-o", str(tmp / "p3.net.xml.gz"))

        p3 = sumolib.net.readNet(str(tmp / "p3.net.xml.gz"), withPrograms=True)
        p3_links = tls_links(p3)
        moved = {t for t in base_links if [link_key(l) for l in base_links[t]] != [link_key(l) for l in p3_links.get(t, [])]}
        if moved != AGENT_LIGHTS | PEDESTRIAN_LIGHTS:
            raise RuntimeError(f"unexpected lights changed: {sorted(moved ^ (AGENT_LIGHTS | PEDESTRIAN_LIGHTS))}")

        tll = ["<tlLogics>"]
        for light in sorted(AGENT_LIGHTS):
            phases = approach_phases(p3_links[light])
            for overlap_light, frm, to in OVERLAPS:
                if overlap_light == light:
                    phases = add_overlap(p3, p3_links[light], phases, frm, to)
            tll += tll_entry(light, phases, p3_links[light])
        for light in sorted(PEDESTRIAN_LIGHTS):
            tll += tll_entry(light, pedestrian_phases(p3_links[light]), p3_links[light], PEDESTRIAN_BOUNDS)
        tll.append("</tlLogics>")
        (tmp / "programs.tll.xml").write_text("\n".join(tll) + "\n", encoding="utf-8")
        netconvert("-s", str(tmp / "p3.net.xml.gz"), "--tllogic-files", str(tmp / "programs.tll.xml"),
                   "-o", str(tmp / "final.net.xml.gz"))

        final = sumolib.net.readNet(str(tmp / "final.net.xml.gz"), withPrograms=True)
        problems = check(final, base, base_links)
        if problems:
            print("not written:\n  " + "\n  ".join(problems))
            return 1
        OUTPUT.write_bytes((tmp / "final.net.xml.gz").read_bytes())
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)}: {len(changed)} edges re-laned, "
          f"{len(reset)} re-guessed, {len(explicit)} approaches set by hand, "
          f"{len(AGENT_LIGHTS)} agent and {len(PEDESTRIAN_LIGHTS)} pedestrian programs regenerated")
    return 0


def dead_lanes(net) -> set[str]:
    """Passenger lanes with no way out, except at the network boundary."""
    dead = set()
    for edge in net.getEdges():
        if edge.getFunction() == "internal" or not edge.allows("passenger"):
            continue
        if not [o for o in edge.getToNode().getOutgoing() if o.allows("passenger")]:
            continue
        dead.update(l.getID() for l in edge.getLanes() if l.allows("passenger") and not l.getOutgoing())
    return dead


def check(final, base, base_links) -> list[str]:
    problems = [f"new dead lane {lane}" for lane in sorted(dead_lanes(final) - dead_lanes(base))]
    for tls in final.getTrafficLights():
        links = sorted(tls.getConnections(), key=lambda c: c[2])
        if [c[2] for c in links] != list(range(len(links))):
            problems.append(f"{tls.getID()}: link indices not contiguous")
        for program in tls.getPrograms().values():
            if any(len(p.state) != len(links) for p in program.getPhases()):
                problems.append(f"{tls.getID()}: phase state length != {len(links)} links")
        light = tls.getID()
        if light not in AGENT_LIGHTS | PEDESTRIAN_LIGHTS:
            before = [p.state for p in base.getTLS(light).getPrograms()["0"].getPhases()]
            after = [p.state for p in tls.getPrograms()["0"].getPhases()]
            if before != after or [link_key(l) for l in base_links[light]] != [link_key(l) for l in links]:
                problems.append(f"{light}: changed but should not have")
    return problems


if __name__ == "__main__":
    raise SystemExit(main())

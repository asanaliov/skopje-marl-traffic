"""Compute Webster fixed-time plans for the eight agent lights, per scenario.

A fixed-time baseline a traffic engineer would set up: each scenario's plan is
computed once from its seed-42 demand (the "historical counts") with SUMO's
``tlsCycleAdaptation.py`` (Webster's method) and then used unchanged on every
seed. Greens are at least 7 s, as for actuated control and the rl agents.

    $env:SKOPJE_NETWORK="real_signals"
    python scripts/setup/make_webster_plans.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import SKOPJE_INITIAL_CONFIG, WEBSTER_PLAN_DIR  # noqa: E402
from src.environment.selected_corridor import SELECTED_CORRIDOR  # noqa: E402
from src.demand.scenarios import SCENARIOS  # noqa: E402
from src.demand.xml_writer import scenario_output_files  # noqa: E402

SUMO_HOME = Path(os.environ.get("SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo"))
PROGRAM_ID = "webster"
MIN_GREEN_SECONDS = 7
YELLOW_SECONDS = 3
MIN_CYCLE_SECONDS = 30
MAX_CYCLE_SECONDS = 120


def route_file(scenario: str) -> Path:
    config = ET.parse(scenario_output_files(scenario, 42).configuration_file).getroot()
    value = config.find("input/route-files").get("value")
    return (scenario_output_files(scenario, 42).configuration_file.parent / value).resolve()


def make_plan(scenario: str) -> Path:
    agent_lights = set(SELECTED_CORRIDOR.agent_to_traffic_light.values())
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "plan.add.xml"
        subprocess.run(
            [
                sys.executable, str(SUMO_HOME / "tools" / "tlsCycleAdaptation.py"),
                "-n", str(SKOPJE_INITIAL_CONFIG.net_file),
                "-r", str(route_file(scenario)),
                "-o", str(raw),
                "-b", "0",
                "-y", str(YELLOW_SECONDS),
                "-g", str(MIN_GREEN_SECONDS),
                "--min-cycle", str(MIN_CYCLE_SECONDS),
                "--max-cycle", str(MAX_CYCLE_SECONDS),
            ],
            check=True,
            capture_output=True,
        )
        root = ET.parse(raw).getroot()
    for logic in list(root):
        if logic.get("id") not in agent_lights:
            root.remove(logic)
            continue
        logic.set("type", "static")
        logic.set("programID", PROGRAM_ID)
    missing = agent_lights - {logic.get("id") for logic in root}
    if missing:
        raise RuntimeError(f"no webster plan for {sorted(missing)}")
    target = WEBSTER_PLAN_DIR / f"{scenario}.add.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return target


def main() -> int:
    for scenario in SCENARIOS:
        target = make_plan(scenario)
        cycles = [
            sum(float(phase.get("duration")) for phase in logic)
            for logic in ET.parse(target).getroot()
        ]
        print(f"{target.relative_to(PROJECT_ROOT)}: cycles {min(cycles):.0f}-{max(cycles):.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

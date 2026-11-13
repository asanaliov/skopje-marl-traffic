"""Webster fixed-time baseline (controller identifier ``webster_fixed_time``).

The optimised fixed-time plan a traffic engineer would set from historical
counts: ``scripts/setup/make_webster_plans.py`` computes one plan per scenario
from its seed-42 demand with Webster's method. Here the eight agent lights run
that plan unchanged on every seed; every other light keeps its imported
program, exactly as in ``imported_actuated``. The naive ``static_fixed_time``
baseline (30 s greens everywhere) stays as the weaker reference.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from src.baselines.imported_actuated import ImportedActuatedController
from src.config import WEBSTER_PLAN_DIR


CONTROLLER_NAME = "webster_fixed_time"


def plan_file(scenario: str) -> Path:
    """Return the Webster plan for ``scenario`` or explain how to create it."""
    path = WEBSTER_PLAN_DIR / f"{scenario}.add.xml"
    if not path.is_file():
        raise FileNotFoundError(
            f"No Webster plan at {path}; run scripts/setup/make_webster_plans.py."
        )
    return path


class WebsterFixedTimeController(ImportedActuatedController):
    """Run the agent lights on fixed Webster plans, issuing no actions."""

    controller_name: str = CONTROLLER_NAME

    def reset(self):
        """Restart the episode, then switch the agent lights to their plan."""
        observations = super().reset()
        traci = self.environment._traci
        root = ET.parse(plan_file(self.environment.config.scenario)).getroot()
        for logic in root.iter("tlLogic"):
            phases = [
                traci.trafficlight.Phase(float(phase.get("duration")), phase.get("state"))
                for phase in logic.iter("phase")
            ]
            program = logic.get("programID")
            traci.trafficlight.setProgramLogic(
                logic.get("id"), traci.trafficlight.Logic(program, 0, 0, phases)
            )
            traci.trafficlight.setProgram(logic.get("id"), program)
        return observations


__all__ = ["CONTROLLER_NAME", "WebsterFixedTimeController", "plan_file"]

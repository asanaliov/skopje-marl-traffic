"""Tests for the Webster fixed-time plans of the real_signals network."""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.baselines.webster_fixed_time import CONTROLLER_NAME, WebsterFixedTimeController

SKOPJE = Path(__file__).resolve().parents[1] / "sumo" / "skopje"
PLANS = SKOPJE / "network" / "webster_real_signals"


def agent_lights() -> set[str]:
    audit = SKOPJE / "documentation" / "traffic_light_audit_real_signals.csv"
    agents = {"A9", "A18", "A19", "A20", "A21", "A24", "A25", "A26"}
    with audit.open(encoding="utf-8", newline="") as file:
        return {row["traffic_light_id"] for row in csv.DictReader(file) if row["agent_id"] in agents}


@pytest.mark.parametrize("scenario", ["low", "medium", "high", "peak", "stress"])
def test_plan_covers_every_agent_light_with_static_7s_greens(scenario):
    root = ET.parse(PLANS / f"{scenario}.add.xml").getroot()
    logics = list(root.iter("tlLogic"))
    assert {logic.get("id") for logic in logics} == agent_lights()
    for logic in logics:
        assert logic.get("type") == "static"
        greens = [p for p in logic.iter("phase") if "G" in p.get("state")]
        assert greens and all(float(p.get("duration")) >= 7 for p in greens)


def test_webster_controller_has_its_own_label():
    assert CONTROLLER_NAME == WebsterFixedTimeController.controller_name == "webster_fixed_time"

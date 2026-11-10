"""The original and real-signals networks must never share state.

Observation sizes depend on each light's phase count, so results, checkpoints,
audits and SUMO configs are kept apart per variant (SKOPJE_NETWORK).
"""

from __future__ import annotations

import csv
import gzip
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKOPJE = PROJECT_ROOT / "sumo" / "skopje"
AGENTS = ("A9", "A18", "A19", "A20", "A24", "A25", "A26", "A29")
REAL_SIGNAL_AGENTS = {
    "A9": 6, "A18": 6, "A19": 8, "A20": 8, "A24": 8, "A25": 8, "A26": 8, "A29": 3,
}
ORIGINAL_AGENTS = {
    "A9": 4, "A18": 4, "A19": 9, "A20": 8, "A24": 8, "A25": 4, "A26": 9, "A29": 4,
}


def _config_values(variant: str) -> dict[str, str]:
    code = (
        "import src.config as c;"
        "print(c.RESULTS_FILE.as_posix());print(c.CHECKPOINT_DIR.as_posix());"
        "print(c.SKOPJE_AUDIT_FILE.name);print(c.SKOPJE_INITIAL_NETWORK_FILE.name);"
        "print(c.SKOPJE_SCENARIO_CONFIG_DIR.name)"
    )
    environment = {**os.environ, "SKOPJE_NETWORK": variant}
    output = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,r'{PROJECT_ROOT}');{code}"],
        capture_output=True, text=True, check=True, env=environment,
    ).stdout.split()
    return dict(zip(("results", "checkpoints", "audit", "net", "configs"), output))


def test_original_variant_keeps_existing_locations() -> None:
    assert _config_values("original") == {
        "results": "results/experiments.csv",
        "checkpoints": "checkpoints",
        "audit": "traffic_light_audit.csv",
        "net": "skopje_initial.net.xml.gz",
        "configs": "scenarios",
    }


def test_real_signals_variant_is_fully_separate() -> None:
    assert _config_values("real_signals") == {
        "results": "results/real_signals/experiments.csv",
        "checkpoints": "checkpoints/real_signals",
        "audit": "traffic_light_audit_real_signals.csv",
        "net": "skopje_real_signals.net.xml.gz",
        "configs": "scenarios_real_signals",
    }


def test_unknown_variant_is_rejected() -> None:
    environment = {**os.environ, "SKOPJE_NETWORK": "bogus"}
    result = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,r'{PROJECT_ROOT}');import src.config"],
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode != 0
    assert "SKOPJE_NETWORK" in result.stderr


def test_audit_phase_counts_match_each_network() -> None:
    def phase_counts(audit: str, net: str) -> dict[str, int]:
        audit_rows = {
            row["agent_id"]: row
            for row in csv.DictReader(open(SKOPJE / "documentation" / audit, encoding="utf-8"))
        }
        text = gzip.open(SKOPJE / "network" / net, "rt", encoding="utf-8").read()
        counts = {}
        for agent in AGENTS:
            light = audit_rows[agent]["traffic_light_id"]
            block = re.search(
                rf'<tlLogic id="{re.escape(light)}".*?</tlLogic>', text, re.S
            ).group(0)
            counts[agent] = block.count("<phase ")
            assert int(audit_rows[agent]["phase_count"]) == counts[agent]
        return counts

    original = phase_counts("traffic_light_audit.csv", "skopje_initial.net.xml.gz")
    real = phase_counts(
        "traffic_light_audit_real_signals.csv", "skopje_real_signals.net.xml.gz"
    )
    assert real == REAL_SIGNAL_AGENTS
    assert original != real


def test_real_signal_programs_use_one_approach_per_phase() -> None:
    text = gzip.open(
        SKOPJE / "network" / "skopje_real_signals.net.xml.gz", "rt", encoding="utf-8"
    ).read()
    for light in (
        "GS_12432953582",
        "GS_cluster_170638629_170642149_170723177_418949594",
        "GS_cluster_170664726_3563678918",
        "GS_cluster_511207145_8301921419",
    ):
        block = re.search(rf'<tlLogic id="{light}".*?</tlLogic>', text, re.S).group(0)
        states = re.findall(r'state="([^"]+)"', block)
        green = [state for state in states if "G" in state]
        assert len(green) * 2 == len(states)
        assert all(set(state) <= {"G", "r"} for state in green)
        assert all("g" not in state for state in states)


def test_real_signals_configs_only_differ_in_the_network() -> None:
    for original in sorted((SKOPJE / "config" / "scenarios").glob("*_seed_42.sumocfg")):
        variant = SKOPJE / "config" / "scenarios_real_signals" / original.name
        assert variant.read_text(encoding="utf-8") == original.read_text(
            encoding="utf-8"
        ).replace("skopje_initial.net.xml.gz", "skopje_real_signals.net.xml.gz")


@pytest.mark.parametrize("variant", ("original", "real_signals"))
def test_corridor_loads_in_each_variant(variant: str) -> None:
    code = (
        f"import sys;sys.path.insert(0,r'{PROJECT_ROOT}');"
        "from src.environment.gym_wrapper import audited_space_specs as a;"
        "print({k:v.phase_count for k,v in a().items()})"
    )
    output = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True, text=True, check=True,
        env={**os.environ, "SKOPJE_NETWORK": variant},
    ).stdout
    expected = REAL_SIGNAL_AGENTS if variant == "real_signals" else ORIGINAL_AGENTS
    assert str(expected) in output

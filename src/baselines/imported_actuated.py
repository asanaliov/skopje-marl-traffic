"""Imported SUMO actuated baseline controller.

This is a SUMO simulation baseline created for this project (controller
identifier ``imported_actuated``). It evaluates the traffic-light control
programs already contained in the imported Skopje SUMO network without
issuing any manual phase-control actions. It is not claimed to reproduce
the official operational traffic-control system of the City of Skopje. See
``sumo/skopje/documentation/imported_actuated_baseline.md`` for the full
wording.

Design note: unlike the static fixed-time baseline
(``src/baselines/static_fixed_time.py``), which drives every selected
agent's phases directly through the safe ``TrafficSignal`` action wrapper,
this baseline never calls ``TrafficSignal.apply_action`` at all. It reuses
``MultiAgentTrafficEnvironment`` exactly as-is and always advances with
``environment.step(None)``, which the environment already treats as an
observation-only decision round -- no action validation runs and no
wrapper is mutated (see ``MultiAgentTrafficEnvironment.step`` and
``MultiAgentTrafficEnvironment._validate_actions``, which is skipped
entirely when ``actions is None``). The imported SUMO actuated programs
already attached to every selected traffic light therefore keep making
every phase decision, for the complete Skopje network.
"""

from __future__ import annotations

from src.environment.multi_agent_environment import (
    MultiAgentEnvironmentConfig,
    MultiAgentStepResult,
    MultiAgentTrafficEnvironment,
)
from src.environment.selected_corridor import SELECTED_CORRIDOR


CONTROLLER_NAME = "imported_actuated"

# Values likely to be confused with an authoritative source; never use these
# as the controller identifier for this baseline.
_FORBIDDEN_CONTROLLER_NAMES = (
    "skopje_official",
    "official_skopje",
    "original_skopje_controller",
)

DEFAULT_DEMAND_SECONDS = 3600.0
DEFAULT_COOLDOWN_SECONDS = 600.0

# MetricsCollector and the per-agent diagnostics accumulator both read
# TraCI's "since the last simulationStep() call" snapshot methods
# (simulation.getDepartedIDList/getArrivedIDList, lane.getLastStepVehicleIDs,
# ...). This baseline's runner calls collector.record_step() exactly once
# per environment.step(None) call, so decision_interval_seconds must equal
# sumo_step_length_seconds -- otherwise each environment.step() call would
# advance multiple raw SUMO steps internally (MultiAgentTrafficEnvironment.
# _advance_simulation) while metrics are only sampled once, silently
# dropping every vehicle that departed or arrived on the skipped
# intermediate steps. Do not change this default without also sampling
# metrics once per raw SUMO step.
DEFAULT_DECISION_INTERVAL_SECONDS = 1.0

BASELINE_NOTICE = (
    "The imported actuated baseline evaluates the traffic-light programs "
    "contained in the imported SUMO network without issuing manual "
    "phase-control actions. These programs are used as a simulation "
    "baseline and are not claimed to reproduce the official operational "
    "traffic-control system of the City of Skopje."
)


def _validate_controller_name(controller_name: str) -> None:
    """Guard against accidentally relabeling this baseline as official."""
    if controller_name != CONTROLLER_NAME:
        raise ValueError(
            f"This baseline must be labeled {CONTROLLER_NAME!r}, "
            f"got {controller_name!r}."
        )
    if controller_name.strip().lower() in _FORBIDDEN_CONTROLLER_NAMES:
        raise ValueError(
            f"{controller_name!r} falsely implies an official Skopje timing "
            "plan and must never be used as a controller identifier."
        )


def build_environment_config(
    scenario: str,
    seed: int,
    demand_seconds: float = DEFAULT_DEMAND_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    **overrides: object,
) -> MultiAgentEnvironmentConfig:
    """Build the full eight-agent environment config for this baseline.

    Always configures every selected corridor agent
    (``SELECTED_CORRIDOR.agent_ids``) so the complete Skopje network stays
    active with all eight imported traffic-light programs in control.
    ``decision_interval_seconds`` defaults to
    ``DEFAULT_DECISION_INTERVAL_SECONDS`` (one raw SUMO second) so that a
    caller sampling metrics once per ``environment.step(None)`` call -- as
    ``scripts/experiments/run_imported_actuated_experiment.py`` does -- stays aligned
    with SUMO's own per-step reporting; see that constant's docstring.
    ``**overrides`` may set any other ``MultiAgentEnvironmentConfig`` field
    (for example ``gui``) without letting a caller narrow the configured
    agent set.
    """
    overrides.pop("agent_ids", None)
    overrides.setdefault(
        "decision_interval_seconds", DEFAULT_DECISION_INTERVAL_SECONDS
    )
    return MultiAgentEnvironmentConfig(
        scenario=scenario,
        seed=seed,
        agent_ids=SELECTED_CORRIDOR.agent_ids,
        demand_seconds=demand_seconds,
        cooldown_seconds=cooldown_seconds,
        **overrides,
    )


class ImportedActuatedController:
    """Advance ``MultiAgentTrafficEnvironment`` while issuing zero actions.

    Owns no SUMO/TraCI lifecycle of its own beyond forwarding to the
    injected environment: the caller (typically inside a try/finally block)
    builds the ``MultiAgentTrafficEnvironment`` and calls ``reset()`` /
    ``step()`` / ``close()`` here, which simply forward to the same-named
    environment methods. ``step()`` always calls ``environment.step(None)``,
    so it can never request ``TrafficAction.KEEP`` or
    ``TrafficAction.NEXT_GREEN`` for any agent.
    """

    controller_name: str = CONTROLLER_NAME

    def __init__(self, environment: MultiAgentTrafficEnvironment) -> None:
        _validate_controller_name(self.controller_name)
        if not isinstance(environment, MultiAgentTrafficEnvironment):
            raise TypeError(
                "ImportedActuatedController requires a "
                "MultiAgentTrafficEnvironment."
            )
        if tuple(environment.agent_ids) != tuple(SELECTED_CORRIDOR.agent_ids):
            raise ValueError(
                "imported_actuated must configure all eight selected "
                f"agents {SELECTED_CORRIDOR.agent_ids}; got "
                f"{tuple(environment.agent_ids)}."
            )
        self.environment = environment

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Return the configured agents in official corridor order."""
        return self.environment.agent_ids

    def reset(self):
        """Restart the episode and return the initial observations."""
        return self.environment.reset()

    def step(self) -> MultiAgentStepResult:
        """Advance one decision interval, issuing zero manual actions."""
        return self.environment.step(None)

    def close(self) -> None:
        """Close the underlying environment's TraCI connection safely."""
        self.environment.close()


__all__ = [
    "BASELINE_NOTICE",
    "CONTROLLER_NAME",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_DECISION_INTERVAL_SECONDS",
    "DEFAULT_DEMAND_SECONDS",
    "ImportedActuatedController",
    "build_environment_config",
]

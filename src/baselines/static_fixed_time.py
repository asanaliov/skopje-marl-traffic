"""Deterministic static fixed-time baseline controller.

This is an experimental baseline created for this project. It is not a
reproduction of any official City of Skopje signal-timing plan -- we do not
have verified official Skopje signal timings, detector logic, offsets, or
time-of-day plans. See
``sumo/skopje/documentation/static_fixed_time_baseline.md`` for the full
wording.

Design note: the controller reuses ``TrafficSignal``, the same safe
KEEP/NEXT_GREEN action wrapper already used for the (future) learning
agents. ``TrafficSignal.apply_action`` already guarantees, for every
selected agent:

- the original phase order is preserved (it only ever advances to the
  immediate next phase in the active program);
- original phase-state strings are preserved (phases are read from SUMO,
  never invented);
- a requested switch away from green is rejected until the configured
  minimum green time has elapsed, and forced once the configured maximum
  green time is reached;
- the immediate next phase must be a yellow or all-red transition state,
  or the switch is refused -- so it can never jump directly from one green
  phase to another.

Setting ``minimum_green_seconds == maximum_green_seconds == fixed_green_seconds``
on that same wrapper turns it into a deterministic fixed-time controller:
every original green phase runs for exactly ``fixed_green_seconds`` before
the wrapper enters the next original transition phase, and that transition
is given its own original SUMO duration untouched (see
``TrafficSignal._transition_to_immediate_next_phase``, which sets the
transition's duration from the original program logic, not from this
baseline's configuration). This baseline never calls ``TrafficAction.KEEP``
and never sets a green phase's duration directly -- it only requests
``NEXT_GREEN`` on a fixed schedule and lets the safe wrapper enforce timing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.environment.actions import ActionPolicyConfig, TrafficAction
from src.environment.selected_corridor import SELECTED_CORRIDOR
from src.environment.traffic_signal import TrafficSignal


CONTROLLER_NAME = "static_fixed_time"

# Values likely to be confused with an authoritative source; never use these
# as the controller identifier for this baseline.
_FORBIDDEN_CONTROLLER_NAMES = (
    "skopje_official",
    "official_skopje",
    "original_skopje_controller",
)

DEFAULT_FIXED_GREEN_SECONDS = 30.0
DEFAULT_DECISION_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class StaticFixedTimeConfig:
    """Configurable timing policy for the static fixed-time baseline.

    ``fixed_green_seconds`` is the only timing knob controller logic reads.
    Change it here to run a different fixed-time policy later without
    editing ``StaticFixedTimeController``.

    ``decision_interval_seconds`` only controls how often the controller
    polls TraCI to check whether it is time to switch; it never changes how
    long a green phase actually runs (that is fixed_green_seconds, enforced
    by the safe action wrapper's minimum/maximum green equality below).
    """

    fixed_green_seconds: float = DEFAULT_FIXED_GREEN_SECONDS
    decision_interval_seconds: float = DEFAULT_DECISION_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        """Reject unusable timing settings early, before SUMO starts."""
        if not math.isfinite(self.fixed_green_seconds):
            raise ValueError("fixed_green_seconds must be finite.")
        if self.fixed_green_seconds <= 0.0:
            raise ValueError("fixed_green_seconds must be greater than zero.")
        if not math.isfinite(self.decision_interval_seconds):
            raise ValueError("decision_interval_seconds must be finite.")
        if self.decision_interval_seconds <= 0.0:
            raise ValueError("decision_interval_seconds must be greater than zero.")

    def action_policy(self) -> ActionPolicyConfig:
        """Build the safe-action policy that enforces this fixed timing.

        Minimum and maximum green are both set to ``fixed_green_seconds``,
        so ``TrafficSignal.apply_action(NEXT_GREEN)`` can only succeed once
        exactly that much time has elapsed on the current green phase --
        there is no other way to reach fixed-duration greens through the
        existing safe wrapper without duplicating its transition logic.
        """
        decision_interval = min(
            self.decision_interval_seconds,
            self.fixed_green_seconds,
        )
        return ActionPolicyConfig(
            minimum_green_seconds=self.fixed_green_seconds,
            maximum_green_seconds=self.fixed_green_seconds,
            decision_interval_seconds=decision_interval,
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


class StaticFixedTimeController:
    """Drives every selected agent with deterministic fixed green durations.

    Owns no SUMO/TraCI lifecycle: the caller starts and closes the
    connection (typically in a try/finally block) and calls ``step`` once
    per simulation step, passing the current simulation time.
    """

    controller_name: str = CONTROLLER_NAME

    def __init__(
        self,
        traci_connection: Any,
        config: StaticFixedTimeConfig | None = None,
        agent_ids: tuple[str, ...] = SELECTED_CORRIDOR.agent_ids,
    ) -> None:
        _validate_controller_name(self.controller_name)
        self.config = config or StaticFixedTimeConfig()
        self.agent_ids = tuple(agent_ids)
        if not self.agent_ids:
            raise ValueError("StaticFixedTimeController requires at least one agent.")

        policy = self.config.action_policy()
        self.decision_interval_seconds = policy.decision_interval_seconds
        self.signals: dict[str, TrafficSignal] = {
            agent_id: TrafficSignal(
                agent_id=agent_id,
                traffic_light_id=SELECTED_CORRIDOR.agent_to_traffic_light[agent_id],
                traci_connection=traci_connection,
                action_policy=policy,
            )
            for agent_id in self.agent_ids
        }
        self.phase_change_counts: dict[str, int] = dict.fromkeys(self.agent_ids, 0)
        self._next_decision_time = self.decision_interval_seconds

    def step(self, simulation_time: float) -> bool:
        """Request NEXT_GREEN for every agent when a decision is due.

        Returns whether a decision round was issued this call. Safe to call
        every simulation step; it only acts once every
        ``decision_interval_seconds`` of simulated time, matching the
        polling pattern already used elsewhere in this project's agent
        inspection tooling.
        """
        if simulation_time < self._next_decision_time:
            return False

        for agent_id, signal in self.signals.items():
            result = signal.apply_action(TrafficAction.NEXT_GREEN)
            if result.phase_changed:
                self.phase_change_counts[agent_id] += 1

        while self._next_decision_time <= simulation_time:
            self._next_decision_time += self.decision_interval_seconds
        return True

    def final_phase_by_agent(self) -> dict[str, str]:
        """Return each selected agent's most recently synchronized phase state."""
        return {
            agent_id: signal.phase_states[signal.current_phase_index]
            for agent_id, signal in self.signals.items()
        }


__all__ = [
    "CONTROLLER_NAME",
    "DEFAULT_DECISION_INTERVAL_SECONDS",
    "DEFAULT_FIXED_GREEN_SECONDS",
    "StaticFixedTimeConfig",
    "StaticFixedTimeController",
]

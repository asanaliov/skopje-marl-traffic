"""Canonical synthetic traffic-demand scenarios for the Skopje network."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from types import MappingProxyType


_SCENARIO_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True, slots=True)
class TrafficDemandScenario:
    """One reproducible synthetic passenger-demand load level.

    Vehicle counts are initial experimental calibration values.
    They are not official or measured Skopje traffic counts.

    ``departure_profile`` splits the duration into equal intervals and gives
    each interval a relative departure weight. The default single weight
    spreads departures evenly across the whole duration.

    ``street_weights`` biases corridor routes by street name. A route is kept
    with probability (highest weight above 1 among its streets, or 1) times
    (product of its weights below 1), divided by the highest weight listed: it is
    favoured if it uses any favoured street and avoided per avoided street.

    ``rerouting_probability`` is the share of vehicles that pick the fastest
    route under current traffic when they depart, written into the scenario's
    SUMO config. 0 keeps every vehicle on its pre-computed route.

    ``extra_corridor_agents`` are traffic lights that count as selected agents
    when deciding which trips are corridor trips, e.g. A21, an agent only on the
    real_signals network, so demand also loads it.
    """

    name: str
    duration_seconds: int
    total_vehicle_count: int
    corridor_trip_share: float
    minimum_selected_agents_crossed: int
    minimum_route_length_m: float
    seed: int
    vehicle_type: str
    departure_profile: tuple[float, ...] = (1.0,)
    street_weights: tuple[tuple[str, float], ...] = ()
    rerouting_probability: float = 0.0
    extra_corridor_agents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject invalid scenario values when a definition is constructed."""
        validate_scenario(self)


def validate_scenario(scenario: TrafficDemandScenario) -> None:
    """Raise a clear error unless every scenario setting is usable."""
    if not _SCENARIO_NAME_PATTERN.fullmatch(scenario.name):
        raise ValueError(
            "Scenario name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, underscores, or hyphens."
        )
    if scenario.duration_seconds <= 0:
        raise ValueError("Scenario duration_seconds must be greater than zero.")
    if scenario.total_vehicle_count <= 0:
        raise ValueError("Scenario total_vehicle_count must be greater than zero.")
    if not 0.0 < scenario.corridor_trip_share <= 1.0:
        raise ValueError(
            "Scenario corridor_trip_share must be greater than 0 and at most 1."
        )
    if scenario.minimum_selected_agents_crossed < 1:
        raise ValueError("Scenario minimum_selected_agents_crossed must be at least 1.")
    if scenario.minimum_selected_agents_crossed > 8:
        raise ValueError(
            "Scenario minimum_selected_agents_crossed cannot exceed the eight "
            "selected corridor agents."
        )
    if scenario.minimum_route_length_m <= 0:
        raise ValueError("Scenario minimum_route_length_m must be greater than zero.")
    if scenario.seed < 0:
        raise ValueError("Scenario seed must be zero or greater.")
    if not scenario.departure_profile:
        raise ValueError("Scenario departure_profile must contain at least one weight.")
    if any(weight <= 0 for weight in scenario.departure_profile):
        raise ValueError("Scenario departure_profile weights must be greater than zero.")
    if any(weight <= 0 for _, weight in scenario.street_weights):
        raise ValueError("Scenario street_weights must be greater than zero.")
    if not 0.0 <= scenario.rerouting_probability <= 1.0:
        raise ValueError("Scenario rerouting_probability must be between 0 and 1.")
    if any(not re.fullmatch(r"A\d+", agent_id) for agent_id in scenario.extra_corridor_agents):
        raise ValueError("Scenario extra_corridor_agents must be agent ids like 'A21'.")
    if scenario.vehicle_type != "passenger":
        raise ValueError(
            "Traffic-demand scenarios currently support only vehicle_type='passenger'."
        )


LOW = TrafficDemandScenario(
    name="low",
    duration_seconds=3600,
    total_vehicle_count=900,
    corridor_trip_share=0.70,
    minimum_selected_agents_crossed=1,
    minimum_route_length_m=300.0,
    seed=42,
    vehicle_type="passenger",
)

MEDIUM = TrafficDemandScenario(
    name="medium",
    duration_seconds=3600,
    total_vehicle_count=1800,
    corridor_trip_share=0.80,
    minimum_selected_agents_crossed=2,
    minimum_route_length_m=300.0,
    seed=42,
    vehicle_type="passenger",
)

HIGH = TrafficDemandScenario(
    name="high",
    duration_seconds=3600,
    total_vehicle_count=3000,
    corridor_trip_share=0.85,
    minimum_selected_agents_crossed=2,
    minimum_route_length_m=300.0,
    seed=42,
    vehicle_type="passenger",
)

# Weekday rush hour on the central boulevards. The four weights are the
# quarter-hour shares of the hour's departures (22/27/30/21 %), which gives a
# peak hour factor of 1 / (4 * 0.30) ~= 0.83, a sharper peak than the HCM
# urban default of 0.92. Corridor routes are steered onto Partizanski odredi
# (3 lanes per direction) and Ilinden (loads A21) and away from Vodnjanska
# (mostly 2), A21 counts toward the corridor rule, and half of the drivers
# reroute around congestion when they depart. 4,600 is the highest volume at
# which every seed clears on the real_signals network. See traffic_demand.md
# for the rationale, the tuning runs and the caveats.
PEAK = TrafficDemandScenario(
    name="peak",
    duration_seconds=3600,
    total_vehicle_count=4600,
    corridor_trip_share=0.88,
    minimum_selected_agents_crossed=2,
    minimum_route_length_m=300.0,
    seed=42,
    vehicle_type="passenger",
    departure_profile=(0.22, 0.27, 0.30, 0.21),
    street_weights=(
        ("Булевар Партизански одреди", 8.0),
        ("Илинден", 8.0),
        ("Булевар Водњанска", 0.05),
    ),
    rerouting_probability=0.5,
    extra_corridor_agents=("A21",),
)

# Peak pushed past what the network clears in the cooldown (5,000+ on the
# real_signals network): soboren itself gridlocks, but most breakdowns are on
# streets no agent controls. A robustness test, not the main benchmark; report
# teleports at the agents separately from the rest.
STRESS = replace(PEAK, name="stress", total_vehicle_count=5400)


SCENARIOS = MappingProxyType(
    {
        scenario.name: scenario
        for scenario in (
            LOW,
            MEDIUM,
            HIGH,
            PEAK,
            STRESS,
        )
    }
)


def get_scenario(name: str) -> TrafficDemandScenario:
    """Return a canonical scenario by name or raise a readable error."""
    normalized_name = name.strip().lower()
    try:
        return SCENARIOS[normalized_name]
    except KeyError as error:
        valid_names = ", ".join(SCENARIOS)
        raise ValueError(
            f"Unknown traffic-demand scenario {name!r}. Choose one of: {valid_names}."
        ) from error


__all__ = [
    "HIGH",
    "LOW",
    "MEDIUM",
    "PEAK",
    "STRESS",
    "SCENARIOS",
    "TrafficDemandScenario",
    "get_scenario",
    "validate_scenario",
]

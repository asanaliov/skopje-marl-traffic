"""JSON encoding of tabular Q-learning state keys.

Shared by the single-agent runner (``independent_q_learning``) and the
multi-agent runner (``multi_agent_q_learning``) so both write the same
inspectable state shape into their checkpoints, and so a state encoded by
one runner always reads back identically in the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from src.agents.state_encoder import DiscreteTrafficState


def state_to_json(state: Any) -> dict[str, Any]:
    """Convert one Q-table state key into a JSON-serializable object."""
    if isinstance(state, DiscreteTrafficState):
        return {"type": "DiscreteTrafficState", **asdict(state)}
    if is_dataclass(state):
        return {"type": type(state).__name__, **asdict(state)}
    if isinstance(state, (str, int, float, bool)) or state is None:
        return {"type": "primitive", "value": state}
    if isinstance(state, tuple):
        return {"type": "tuple", "value": list(state)}
    raise TypeError(f"Unsupported checkpoint state type: {type(state).__name__}")


def state_from_json(value: Mapping[str, Any]) -> Any:
    """Rebuild one Q-table state key from its checkpoint representation."""
    state_type = value.get("type")
    if state_type == "DiscreteTrafficState":
        fields = {
            field: value[field]
            for field in (
                "total_queue_bucket",
                "maximum_lane_queue_bucket",
                "mean_lane_waiting_time_bucket",
                "green_phase_position",
                "phase_elapsed_bucket",
                "is_transition_phase",
            )
        }
        return DiscreteTrafficState(**fields)
    if state_type == "primitive":
        return value.get("value")
    if state_type == "tuple":
        return tuple(value.get("value", ()))
    raise ValueError(f"Unsupported checkpoint state type: {state_type!r}.")


__all__ = ["state_from_json", "state_to_json"]

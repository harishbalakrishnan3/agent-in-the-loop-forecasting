"""Serializable LangGraph state (promoted from ``pocs/changepoint/graph/state.py``).

Plain dicts/lists only — no toggles, no registry, no emitter, no model handles, no full diagnostics
bundle (those live on ``RunContext``). ``diagnostics`` here is the FILTERED agent-facing view. This
module is import-clean of langgraph (FR-003).
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _take_right(_left: Any, right: Any) -> Any:
    """Reducer for branch joins: later write wins (concurrent visual/diagnostics fan-out)."""
    return right


class AgentState(TypedDict, total=False):
    """Graph state — plain serializable values; runtime objects are passed via RunContext."""

    scenario_id: str
    image_path: str
    seasonal_period: int

    # Concurrent branch outputs (each written by exactly one branch).
    visual: Annotated[dict[str, Any], _take_right]
    diagnostics: Annotated[dict[str, Any], _take_right]  # FILTERED agent-facing view

    # Decision/validation loop.
    naive_summary: dict[str, Any]
    iterations: list[dict[str, Any]]
    rejected_signatures: list[str]
    accepted: dict[str, Any] | None
    final_candidate: dict[str, Any]
    final_case: str
    _final_eval: dict[str, Any]  # forecasts + test metrics for artifacts (not agent-facing)

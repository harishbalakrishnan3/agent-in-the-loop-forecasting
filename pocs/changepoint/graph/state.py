"""Serializable LangGraph state + LLM output schemas (T019, data-model.md).

Test values never enter this state until the final-evaluation node populates test metrics.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


def _take_right(_left: Any, right: Any) -> Any:
    """Reducer for branch joins: later write wins (used for fields written by one branch)."""
    return right


class VisualInspectionResult(BaseModel):
    """Structured output of the visual node (FR-016) — no intervention field."""

    observations: list[str] = Field(description="Concrete things seen in the training-only chart")
    pattern_summary: str = Field(description="One sentence naming the dominant pattern")
    hypotheses: list[str] = Field(description="Plausible failure modes for a naive recent-window forecast")
    uncertainties: list[str] = Field(description="What the image alone cannot determine")


class InterventionChoice(BaseModel):
    """Structured output of the ReAct decision node (FR-018)."""

    tool: str = Field(description="One of the six bounded intervention tool names")
    params: dict[str, Any] = Field(default_factory=dict, description="Bounded parameters for the tool")
    visual_first_rationale: str = Field(description="Rationale citing visual observations BEFORE numeric diagnostics")
    expected_effect: str = Field(description="What this intervention is expected to fix")


class AgentState(TypedDict, total=False):
    """Graph state. Plain serializable values; objects are passed by reference for compute only."""

    # Inputs (set before invoke)
    scenario_id: str
    image_path: str
    seasonal_period: int

    # Concurrent branch outputs (each written by exactly one branch)
    visual: Annotated[dict[str, Any], _take_right]
    diagnostics: Annotated[dict[str, Any], _take_right]

    # Decision/validation loop
    naive_summary: dict[str, Any]
    iterations: list[dict[str, Any]]
    rejected_signatures: list[str]
    accepted: dict[str, Any] | None
    final_candidate: dict[str, Any]
    final_case: str
    _final_eval: dict[str, Any]  # forecasts + test metrics for artifact writing (not agent-facing)

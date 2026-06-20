"""LLM structured-output schemas for the changepoint agent (pydantic — LLM I/O only).

Promoted from ``pocs/changepoint/graph/state.py``. These are the ONLY pydantic models in the
pipeline; everything else on the serializable boundary is a frozen dataclass (research Decision 16).
They stay pipeline-side because ``InterventionChoice.tool`` enumerates changepoint tools and the
rationale is changepoint-prompt-coupled (SC-002).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VisualInspectionResult(BaseModel):
    """Structured output of the visual node (FR-016) — no intervention field."""

    observations: list[str] = Field(description="Concrete things seen in the training-only chart")
    pattern_summary: str = Field(description="One sentence naming the dominant pattern")
    hypotheses: list[str] = Field(description="Plausible failure modes for a naive recent-window forecast")
    uncertainties: list[str] = Field(description="What the image alone cannot determine")


class InterventionChoice(BaseModel):
    """Structured output of the decision node (FR-018)."""

    tool: str = Field(description="One of the bounded intervention tool names from the menu")
    params: dict[str, Any] = Field(default_factory=dict, description="Bounded parameters for the tool")
    rationale: str = Field(
        description="Why this intervention — citing visual observations first when visual analysis "
        "is enabled, otherwise the numeric diagnostics"
    )
    expected_effect: str = Field(description="What this intervention is expected to fix")

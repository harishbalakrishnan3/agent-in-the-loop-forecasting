"""RunContext — all non-serializable handles + per-run resolved config (research Decision 5).

Carries everything the node closures need that must NOT enter the serializable ``AgentState``:
model wrappers, the FULL diagnostics bundle (for tools/gate), the naive result, the projected tool
registry, the toggles, the emitter, and the resolved split. Import-clean of langgraph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunContext:
    run_id: str
    scenario_id: str
    visual_model: Any  # ModelWrapper | FakeModelWrapper (duck-typed)
    decision_model: Any
    visual_model_id: str
    decision_model_id: str
    split: Any  # SeriesSplit (pipeline)
    full_diagnostics: Any  # DiagnosticsBundle (pipeline) — tools/gate see the full bundle
    naive: Any  # NaiveWorkflowResult
    tool_registry: Any  # ToolRegistry (already the for_run projection)
    visual_enabled: bool
    enabled_diagnostics: frozenset[str]
    image_path: Path | None
    emitter: Any  # EventEmitter | NullEmitter
    decision_prompt: str  # the loaded, menu-filled decision prompt text
    visual_prompt: str | None  # the loaded visual prompt text (when visual_enabled)
    visual_schema: Any = None  # pydantic schema for the visual node's structured output
    decision_schema: Any = None  # pydantic schema for the decision node's structured output
    prompt_ids: dict[str, str] = field(default_factory=dict)
    max_iterations: int = 5

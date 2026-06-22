"""Model-choice catalog for the UI's two role selectors (data-model §5, FR-012).

Friendly labels map to Bedrock-form model ids. The backend translates these to native Anthropic
ids when the active provider is the Anthropic API (``resolve._to_anthropic_model_id``), so the UI
never needs to know which provider is active — it always emits Bedrock-form ids.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelChoice:
    """One offered model: a friendly label shown in the UI and the Bedrock-form id it maps to."""

    label: str
    model_id: str  # Bedrock cross-region inference id (translated for the Anthropic provider)


# The fixed catalog of valid choices for both the visual and reasoning roles. Add new tiers here;
# ids must exist in resolve._BEDROCK_TO_ANTHROPIC_MODEL_ID or follow its us.anthropic.* heuristic.
MODEL_CHOICES: tuple[ModelChoice, ...] = (
    ModelChoice(label="Claude Opus 4.8", model_id="us.anthropic.claude-opus-4-8"),
    ModelChoice(label="Claude Sonnet 4.6", model_id="us.anthropic.claude-sonnet-4-6"),
)

# Defaults match config.yaml: visual=Opus 4.8 (stronger vision), reasoning=Sonnet 4.6 (faster).
DEFAULT_VISUAL_MODEL_ID = "us.anthropic.claude-opus-4-8"
DEFAULT_REASONING_MODEL_ID = "us.anthropic.claude-sonnet-4-6"


def labels() -> list[str]:
    """Friendly labels for a selectbox, in catalog order."""
    return [c.label for c in MODEL_CHOICES]


def model_id_for_label(label: str) -> str:
    """Resolve a friendly label to its Bedrock-form model id."""
    for c in MODEL_CHOICES:
        if c.label == label:
            return c.model_id
    raise KeyError(f"unknown model label {label!r}; valid: {labels()}")


def label_for_model_id(model_id: str) -> str:
    """Reverse lookup — the friendly label for a Bedrock-form id (for default selection)."""
    for c in MODEL_CHOICES:
        if c.model_id == model_id:
            return c.label
    raise KeyError(f"unknown model id {model_id!r}")

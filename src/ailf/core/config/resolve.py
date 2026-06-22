"""Config resolution: merge a per-run override onto defaults, validate, lockstep-check (FR-009..012).

``resolve_config`` performs MERGE → VALIDATE → return ``EffectiveConfig``. Merge rules
(contracts/config_schema.md): scalars replace-if-present; ``diagnostics``/``agent_tools`` merge
KEY-WISE (partial overrides allowed, no NEW keys); the ``split`` block REPLACES as a unit.

The pipeline injects its own symbol sets (the 13 ``DiagnosticsBundle`` field names + the 5
structural tool names) so this core module holds zero changepoint symbols (FR-011/FR-012, SC-002).
"""

from __future__ import annotations

import os
from typing import Any

from ailf.core.config.schema import (
    ConfigOverride,
    EffectiveConfig,
    ModelConfig,
    SplitSpec,
)

# ---------------------------------------------------------------------------
# Bedrock cross-region inference profile ID → native Anthropic model ID.
# Used when the Anthropic direct-API provider is selected.
# ---------------------------------------------------------------------------
_BEDROCK_TO_ANTHROPIC_MODEL_ID: dict[str, str] = {
    "us.anthropic.claude-opus-4-8":           "claude-opus-4-8",
    "us.anthropic.claude-sonnet-4-6":         "claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-5-20251002-v1:0": "claude-sonnet-4-5-20250929",
    "us.anthropic.claude-opus-4-5":           "claude-opus-4-5-20251101",
    "us.anthropic.claude-haiku-3-5":          "claude-haiku-3-5-20241022",
}


def _to_anthropic_model_id(bedrock_id: str) -> str:
    """Convert a Bedrock model id to a native Anthropic API model id.

    Falls back to stripping the ``us.`` prefix for unknown IDs — handles most
    cross-region inference profiles without explicit enumeration.
    """
    if bedrock_id in _BEDROCK_TO_ANTHROPIC_MODEL_ID:
        return _BEDROCK_TO_ANTHROPIC_MODEL_ID[bedrock_id]
    # Heuristic: "us.anthropic.X" → "anthropic.X" → strip vendor prefix → "X"
    stripped = bedrock_id.removeprefix("us.").removeprefix("anthropic.")
    return stripped


# Sentinel for "no LLM provider credentials present". Config resolution stays pure and never
# fails on this — the clear fail-fast happens only when a pipeline is about to build REAL model
# clients (run_scenario with model_wrappers=None); injected fakes never need a provider.
LLM_PROVIDER_UNCONFIGURED = "unconfigured"

NO_PROVIDER_MESSAGE = (
    "No LLM provider configured: set ANTHROPIC_API_KEY (preferred) or AWS_ACCESS_KEY_ID "
    "(for AWS Bedrock) in your .env or environment before running."
)


def _detect_llm_provider() -> str:
    """Return 'anthropic' if ANTHROPIC_API_KEY is set, else 'bedrock' if AWS_ACCESS_KEY_ID is set.

    The Anthropic API is PREFERRED when both are configured (feature 006, FR-027). When NEITHER is
    configured, return the ``LLM_PROVIDER_UNCONFIGURED`` sentinel (never raises) so config
    resolution stays side-effect-free for the deterministic test suite; the clear fail-fast for a
    real run lives in the pipeline (FR-029). Whitespace-only values are treated as unset.
    """
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("AWS_ACCESS_KEY_ID", "").strip():
        return "bedrock"
    return LLM_PROVIDER_UNCONFIGURED

# The always-on fallback tool: present in agent_tools with enabled:true, MAY NOT be disabled,
# and is EXCLUDED from the structural-tool lockstep exact-match (FR-016).
FALLBACK_TOOL = "full_history_default"


class ConfigError(RuntimeError):
    """Raised on any invalid configuration — names the offending field; never a silent default."""


def _merge_bool_map(name: str, defaults: dict[str, bool], override: dict[str, Any] | None) -> dict[str, bool]:
    """Key-wise merge for diagnostics/agent_tools — an override may not introduce a new key."""
    merged = dict(defaults)
    if override is None:
        return merged
    for key, value in override.items():
        if key not in defaults:
            raise ConfigError(
                f"unknown {name} key {key!r} in override; allowed keys: {sorted(defaults)}"
            )
        if not isinstance(value, bool):
            raise ConfigError(f"{name}.{key} must be a boolean, got {type(value).__name__}")
        merged[key] = value
    return merged


def assert_config_in_lockstep(
    diagnostics_field_names: set[str],
    structural_tool_names: set[str],
    cfg_diagnostics: dict[str, bool],
    cfg_tools: dict[str, bool],
) -> None:
    """Fail if the config surface drifts from the live bundle/registry (FR-011/FR-012, SC-003).

    ``diagnostics`` keys must equal the bundle field names exactly. ``agent_tools`` keys must equal
    the structural tool names PLUS the always-on fallback (the fallback is excluded from the
    structural exact-match but must be present and enabled).
    """
    diag_keys = set(cfg_diagnostics)
    if diag_keys != diagnostics_field_names:
        missing = diagnostics_field_names - diag_keys
        unknown = diag_keys - diagnostics_field_names
        raise ConfigError(
            f"diagnostics config out of lockstep with DiagnosticsBundle: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )

    tool_keys = set(cfg_tools)
    expected_tools = structural_tool_names | {FALLBACK_TOOL}
    if tool_keys != expected_tools:
        missing = expected_tools - tool_keys
        unknown = tool_keys - expected_tools
        raise ConfigError(
            f"agent_tools config out of lockstep with the tool registry: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )


def resolve_config(
    defaults: dict[str, Any],
    override: ConfigOverride | None,
    *,
    diagnostics_field_names: set[str],
    structural_tool_names: set[str],
    anthropic_api_key: str | None = None,
) -> EffectiveConfig:
    """Merge ``override`` onto ``defaults``, validate + lockstep-check, return ``EffectiveConfig``.

    When ``anthropic_api_key`` is provided (a bring-your-own-key session), the provider is forced to
    ``anthropic`` regardless of server env, so a hosted/public deployment never needs its own
    credentials in the process environment.
    """
    override = override or ConfigOverride()

    # --- models (scalar replace within the block) ---
    base_models = dict(defaults.get("models") or {})
    if override.models:
        base_models.update(override.models)
    region = override.models.get("aws_region") if override.models else None
    region = region or defaults.get("aws_region")
    visual_id = base_models.get("visual_model_id", "")
    decision_id = base_models.get("decision_model_id", "")
    if not visual_id:
        raise ConfigError("models.visual_model_id is required and must be non-empty")
    if not decision_id:
        raise ConfigError("models.decision_model_id is required and must be non-empty")
    if not region:
        raise ConfigError("aws_region is required and must be non-empty")

    # An explicit BYO key forces the Anthropic provider; otherwise detect from env.
    llm_provider = "anthropic" if (anthropic_api_key and anthropic_api_key.strip()) else _detect_llm_provider()
    if llm_provider == "anthropic":
        visual_id = _to_anthropic_model_id(visual_id)
        decision_id = _to_anthropic_model_id(decision_id)

    models = ModelConfig(
        visual_model_id=visual_id,
        decision_model_id=decision_id,
        aws_region=region,
        llm_provider=llm_provider,
    )

    # --- visual switch (scalar) ---
    visual_enabled = (
        override.visual_analysis_enabled
        if override.visual_analysis_enabled is not None
        else bool(defaults.get("visual_analysis_enabled", True))
    )

    # --- diagnostics / agent_tools (key-wise) ---
    diagnostics = _merge_bool_map("diagnostics", dict(defaults.get("diagnostics") or {}), override.diagnostics)
    agent_tools = _merge_bool_map("agent_tools", dict(defaults.get("agent_tools") or {}), override.agent_tools)

    # Lockstep BEFORE the fallback guard so an out-of-lockstep config fails first with a clear msg.
    assert_config_in_lockstep(diagnostics_field_names, structural_tool_names, diagnostics, agent_tools)

    if not agent_tools.get(FALLBACK_TOOL, False):
        raise ConfigError(
            f"{FALLBACK_TOOL!r} is the guaranteed-valid fallback and may not be disabled (FR-016)"
        )

    # --- split (replace as a unit) ---
    if override.split is not None:
        split = SplitSpec.from_dict(override.split)
    else:
        split = SplitSpec.from_dict(defaults.get("split") or {"units": "golden"})

    seed = override.seed if override.seed is not None else int(defaults.get("seed", 1729))

    return EffectiveConfig(
        models=models,
        visual_analysis_enabled=visual_enabled,
        diagnostics=diagnostics,
        agent_tools=agent_tools,
        split=split,
        seed=seed,
    )

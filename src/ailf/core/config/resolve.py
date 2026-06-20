"""Config resolution: merge a per-run override onto defaults, validate, lockstep-check (FR-009..012).

``resolve_config`` performs MERGE → VALIDATE → return ``EffectiveConfig``. Merge rules
(contracts/config_schema.md): scalars replace-if-present; ``diagnostics``/``agent_tools`` merge
KEY-WISE (partial overrides allowed, no NEW keys); the ``split`` block REPLACES as a unit.

The pipeline injects its own symbol sets (the 13 ``DiagnosticsBundle`` field names + the 5
structural tool names) so this core module holds zero changepoint symbols (FR-011/FR-012, SC-002).
"""

from __future__ import annotations

from typing import Any

from ailf.core.config.schema import (
    ConfigOverride,
    EffectiveConfig,
    ModelConfig,
    SplitSpec,
)

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
) -> EffectiveConfig:
    """Merge ``override`` onto ``defaults``, validate + lockstep-check, return ``EffectiveConfig``."""
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
    models = ModelConfig(visual_model_id=visual_id, decision_model_id=decision_id, aws_region=region)

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

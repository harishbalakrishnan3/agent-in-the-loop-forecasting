"""T020/T050/T052 — config loader + override merge + lockstep + validation errors."""

from __future__ import annotations

import pytest

from ailf.core.config.loader import load_config_yaml
from ailf.core.config.resolve import ConfigError, resolve_config
from ailf.core.config.schema import ConfigOverride

_DIAG = {"d1", "d2", "d3"}
_TOOLS = {"t1", "t2"}


def _defaults() -> dict:
    return {
        "models": {"visual_model_id": "vis", "decision_model_id": "dec"},
        "aws_region": "us-west-2",
        "visual_analysis_enabled": True,
        "diagnostics": {"d1": True, "d2": True, "d3": True},
        "agent_tools": {"t1": True, "t2": True, "full_history_default": True},
        "split": {"source": "golden"},
        "seed": 1729,
    }


def _resolve(defaults=None, override=None):
    return resolve_config(
        defaults or _defaults(),
        override,
        diagnostics_field_names=_DIAG,
        structural_tool_names=_TOOLS,
    )


def test_resolve_defaults_no_override():
    cfg = _resolve()
    assert cfg.models.visual_model_id == "vis"
    assert cfg.models.aws_region == "us-west-2"
    assert cfg.visual_analysis_enabled is True
    assert cfg.enabled_diagnostics == frozenset({"d1", "d2", "d3"})
    assert cfg.seed == 1729


def test_scalar_override_replaces():
    cfg = _resolve(override=ConfigOverride(visual_analysis_enabled=False, seed=42))
    assert cfg.visual_analysis_enabled is False
    assert cfg.seed == 42


def test_diagnostics_partial_keywise_merge():
    cfg = _resolve(override=ConfigOverride(diagnostics={"d2": False}))
    assert cfg.diagnostics == {"d1": True, "d2": False, "d3": True}
    assert cfg.enabled_diagnostics == frozenset({"d1", "d3"})


def test_tool_partial_keywise_merge():
    cfg = _resolve(override=ConfigOverride(agent_tools={"t1": False}))
    assert cfg.agent_tools["t1"] is False
    assert cfg.agent_tools["full_history_default"] is True


def test_split_replace_as_unit():
    cfg = _resolve(
        override=ConfigOverride(
            split={"units": "ratios", "train_ratio": 0.8, "val_ratio": 0.1, "test_ratio": 0.1}
        )
    )
    assert cfg.split.units == "ratios"
    assert cfg.split.train_ratio == 0.8


# --- validation errors (FR-010 / SC-008) ---

def test_unknown_diagnostic_key_raises():
    with pytest.raises(ConfigError, match="unknown diagnostics key 'nope'"):
        _resolve(override=ConfigOverride(diagnostics={"nope": False}))


def test_unknown_tool_key_raises():
    with pytest.raises(ConfigError, match="unknown agent_tools key"):
        _resolve(override=ConfigOverride(agent_tools={"ghost": False}))


def test_malformed_bool_value_raises():
    with pytest.raises(ConfigError, match="must be a boolean"):
        _resolve(override=ConfigOverride(diagnostics={"d1": "yes"}))


def test_disabling_fallback_raises():
    with pytest.raises(ConfigError, match="may not be disabled"):
        _resolve(override=ConfigOverride(agent_tools={"full_history_default": False}))


def test_missing_model_id_raises():
    d = _defaults()
    d["models"]["visual_model_id"] = ""
    with pytest.raises(ConfigError, match="visual_model_id"):
        _resolve(defaults=d)


# --- lockstep (FR-011/FR-012, SC-003) ---

def test_lockstep_missing_diagnostic_key_raises():
    d = _defaults()
    del d["diagnostics"]["d3"]
    with pytest.raises(ConfigError, match="diagnostics config out of lockstep"):
        _resolve(defaults=d)


def test_lockstep_extra_tool_key_raises():
    d = _defaults()
    d["agent_tools"]["t_extra"] = True
    with pytest.raises(ConfigError, match="agent_tools config out of lockstep"):
        _resolve(defaults=d)


def test_load_config_yaml_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config_yaml(tmp_path / "absent.yaml")

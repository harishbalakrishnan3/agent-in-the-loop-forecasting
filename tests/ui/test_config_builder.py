"""T004 — UI config-override builder (contracts/run_invocation.md, data-model §1/§5).

Asserts ``to_override_dict`` emits the exact lockstep-valid shape and that it round-trips through
``ConfigOverride.from_dict`` + ``resolve_config`` against the real changepoint defaults.
"""

from __future__ import annotations

from pathlib import Path

from ailf.core.config.loader import load_config_yaml
from ailf.core.config.resolve import resolve_config
from ailf.core.config.schema import ConfigOverride
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle
from ailf.pipelines.changepoint.interventions import structural_tool_names

from ailf.ui import config_builder as cb

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "ailf" / "pipelines" / "changepoint" / "config.yaml"
)


def _base_override():
    return cb.to_override_dict(
        visual_model_id="us.anthropic.claude-opus-4-8",
        decision_model_id="us.anthropic.claude-sonnet-4-6",
        visual_analysis_enabled=True,
        diagnostics_enabled=cb.default_diagnostics_enabled(),
        tools_enabled=cb.default_tools_enabled(),
    )


def test_models_are_bedrock_form_ids():
    ov = _base_override()
    assert ov["models"]["visual_model_id"] == "us.anthropic.claude-opus-4-8"
    assert ov["models"]["decision_model_id"] == "us.anthropic.claude-sonnet-4-6"


def test_diagnostics_keys_equal_bundle_fields_exactly():
    ov = _base_override()
    assert set(ov["diagnostics"]) == set(DiagnosticsBundle.field_names())


def test_agent_tools_keys_equal_structural_plus_fallback_and_fallback_forced_true():
    ov = _base_override()
    expected = set(structural_tool_names()) | {"full_history_default"}
    assert set(ov["agent_tools"]) == expected
    assert ov["agent_tools"]["full_history_default"] is True


def test_fallback_stays_true_even_if_caller_tries_to_disable_it():
    ov = cb.to_override_dict(
        visual_model_id="us.anthropic.claude-opus-4-8",
        decision_model_id="us.anthropic.claude-sonnet-4-6",
        visual_analysis_enabled=False,
        diagnostics_enabled={k: False for k in DiagnosticsBundle.field_names()},
        tools_enabled={"full_history_default": False},  # ignored — fallback is always-on
    )
    assert ov["agent_tools"]["full_history_default"] is True
    assert ov["visual_analysis_enabled"] is False


def test_no_split_block_emitted():
    assert "split" not in _base_override()


def test_round_trips_through_resolve_config_lockstep():
    defaults = load_config_yaml(_CONFIG_PATH)
    override = ConfigOverride.from_dict(_base_override())
    cfg = resolve_config(
        defaults,
        override,
        diagnostics_field_names=set(DiagnosticsBundle.field_names()),
        structural_tool_names=set(structural_tool_names()),
    )
    # All 13 diagnostics enabled, all 5 structural tools + fallback enabled.
    assert cfg.enabled_diagnostics == frozenset(DiagnosticsBundle.field_names())
    assert "full_history_default" in cfg.enabled_tools
    assert cfg.seed == cb.DEFAULT_SEED


def test_diagnostic_meta_and_groups_cover_every_key_exactly_once():
    keys = set(cb.DIAGNOSTIC_KEYS)
    # Metadata covers exactly the 13 canonical diagnostics.
    assert set(cb.DIAGNOSTIC_META) == keys
    # Groups partition the same keys (each appears in exactly one umbrella).
    grouped = [k for _, ks in cb.DIAGNOSTIC_GROUPS for k in ks]
    assert sorted(grouped) == sorted(keys)
    assert len(grouped) == len(set(grouped))  # no key in two groups
    # Every item has a non-empty human label + help.
    for m in cb.DIAGNOSTIC_META.values():
        assert m.label.strip() and m.help.strip()


def test_tool_meta_and_groups_cover_structural_plus_fallback_exactly_once():
    keys = set(cb.STRUCTURAL_TOOL_KEYS) | {cb.FALLBACK_TOOL_KEY}
    assert set(cb.TOOL_META) == keys
    grouped = [k for _, ks in cb.TOOL_GROUPS for k in ks]
    assert sorted(grouped) == sorted(keys)
    assert len(grouped) == len(set(grouped))
    for m in cb.TOOL_META.values():
        assert m.label.strip() and m.help.strip()


def test_disabled_diagnostics_and_tools_reflected_after_resolve():
    defaults = load_config_yaml(_CONFIG_PATH)
    diags = cb.default_diagnostics_enabled()
    diags["segment_stats"] = False
    tools = cb.default_tools_enabled()
    tools["recent_window"] = False
    override = ConfigOverride.from_dict(
        cb.to_override_dict(
            visual_model_id="us.anthropic.claude-opus-4-8",
            decision_model_id="us.anthropic.claude-sonnet-4-6",
            visual_analysis_enabled=True,
            diagnostics_enabled=diags,
            tools_enabled=tools,
        )
    )
    cfg = resolve_config(
        defaults,
        override,
        diagnostics_field_names=set(DiagnosticsBundle.field_names()),
        structural_tool_names=set(structural_tool_names()),
    )
    assert "segment_stats" not in cfg.enabled_diagnostics
    assert "recent_window" not in cfg.enabled_tools

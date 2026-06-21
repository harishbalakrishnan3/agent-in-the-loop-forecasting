"""T053 — the committed config.yaml is in lockstep with the live bundle + registry (SC-003).

Reflects ``DiagnosticsBundle.field_names()`` and the registry's structural tool names (live symbols,
not literal lists) so the test cannot rot when a field/tool is added without updating config.yaml.
"""

from __future__ import annotations

from pathlib import Path

from ailf.core.config.loader import load_config_yaml
from ailf.core.config.resolve import FALLBACK_TOOL, assert_config_in_lockstep
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle
from ailf.pipelines.changepoint.interventions import structural_tool_names

_CONFIG = Path("src/ailf/pipelines/changepoint/config.yaml")


def test_committed_config_in_lockstep():
    cfg = load_config_yaml(_CONFIG)
    # Should not raise.
    assert_config_in_lockstep(
        set(DiagnosticsBundle.field_names()),
        set(structural_tool_names()),
        cfg["diagnostics"],
        cfg["agent_tools"],
    )


def test_config_diagnostics_keys_equal_bundle_fields():
    cfg = load_config_yaml(_CONFIG)
    assert set(cfg["diagnostics"]) == set(DiagnosticsBundle.field_names())


def test_config_tool_keys_equal_structural_plus_fallback():
    cfg = load_config_yaml(_CONFIG)
    assert set(cfg["agent_tools"]) == set(structural_tool_names()) | {FALLBACK_TOOL}

"""T049 — end-to-end single-scenario smoke test with a FakeModelWrapper (no Bedrock).

Runs the wired pipeline and asserts the full per-run artifact set is produced and internally
consistent. Also covers the visual-off arm (US3) and a tool-removed override (US2/SC-005).
"""

from __future__ import annotations

import json

import pytest

from ailf.core.config.schema import ConfigOverride
from ailf.pipelines.changepoint.pipeline import run_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice, VisualInspectionResult

_SID = "level_shift_loses_seasonality"


class _Fake:
    def __init__(self, responses):
        self._responses = list(responses)
        self.model_id = "fake"
        self.calls = []

    def invoke_structured_text(self, *, prompt, schema):
        self.calls.append(("text", prompt))
        return self._responses.pop(0)

    def invoke_structured_with_image(self, *, prompt, image_path, schema):
        self.calls.append(("image", prompt))
        return self._responses.pop(0)


def _models(*, visual_enabled, tool="full_history_default"):
    visual = _Fake(
        [VisualInspectionResult(observations=["o"], pattern_summary="p", hypotheses=["h"], uncertainties=["u"])]
        if visual_enabled else []
    )
    # supply enough decision responses for up to 5 iterations
    decision = _Fake(
        [InterventionChoice(tool=tool, params={}, rationale="r", expected_effect="e") for _ in range(5)]
    )
    return visual, decision


def test_visual_on_run_produces_full_artifact_set(tmp_path):
    report = run_scenario(
        _SID, model_wrappers=_models(visual_enabled=True), reports_root=tmp_path
    )
    run_dir = tmp_path / f"{_SID}-1729"
    for name in ["effective_config.json", "metrics.json", "agent_trace.json", "report.md",
                 "agent_context.png", "forecast_comparison.png"]:
        assert (run_dir / name).exists(), f"missing artifact: {name}"
    assert report["winner"] in {"full_history_prophet", "naive_workflow", "agent"}
    trace = json.loads((run_dir / "agent_trace.json").read_text())
    assert trace["visual_analysis_enabled"] is True
    assert trace["visual"]["pattern_summary"] == "p"


def test_visual_off_run_produces_no_image(tmp_path):
    run_scenario(
        _SID,
        override=ConfigOverride(visual_analysis_enabled=False),
        model_wrappers=_models(visual_enabled=False),
        reports_root=tmp_path,
    )
    run_dir = tmp_path / f"{_SID}-1729"
    assert not (run_dir / "agent_context.png").exists()  # no image when visual off (SC-006)
    assert (run_dir / "metrics.json").exists()
    trace = json.loads((run_dir / "agent_trace.json").read_text())
    assert trace["visual_analysis_enabled"] is False
    assert trace["prompt_ids"]["decision"] == "react_decision_diagnostics_only_v1"


def test_removed_tool_recorded_in_trace(tmp_path):
    run_scenario(
        _SID,
        override=ConfigOverride(agent_tools={"full_history_step_regressor": False}),
        model_wrappers=_models(visual_enabled=True),
        reports_root=tmp_path,
    )
    trace = json.loads((tmp_path / f"{_SID}-1729" / "agent_trace.json").read_text())
    assert "full_history_step_regressor" in trace["removed_tools"]


def test_real_run_without_provider_fails_fast(tmp_path, monkeypatch):
    """A REAL run (no injected model_wrappers) with neither provider configured must raise a clear
    ConfigError before any model call (FR-029) — not a cryptic deferred failure."""
    from ailf.core.config.resolve import ConfigError

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    with pytest.raises(ConfigError, match="No LLM provider configured"):
        run_scenario(_SID, reports_root=tmp_path)  # model_wrappers=None → real-client path

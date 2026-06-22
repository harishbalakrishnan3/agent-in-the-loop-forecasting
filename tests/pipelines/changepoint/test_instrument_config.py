"""T028 — instrument configuration reflected in the streamed run (FR-013/014/015, SC-004).

Disabling diagnostics/tools and turning visual analysis off must show up in the event stream:
hidden diagnostics under config_resolved.hidden_diagnostics, disabled tools under removed_tools and
absent from the decision menu (fallback retained), and NO visual_inspection event.
"""

from __future__ import annotations

import json

from ailf.core.config.schema import ConfigOverride
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle
from ailf.pipelines.changepoint.interventions import structural_tool_names
from ailf.pipelines.changepoint.pipeline import run_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice

_SID = "level_shift_loses_seasonality"


class _Fake:
    def __init__(self, responses):
        self._r = list(responses)
        self.model_id = "fake"

    def invoke_structured_text(self, *, prompt, schema):
        return self._r.pop(0)

    def invoke_structured_with_image(self, *, prompt, image_path, schema):
        return self._r.pop(0)


def _run_dir(tmp_path):
    return tmp_path / f"{_SID}-1729"


def _read_stream(tmp_path):
    path = _run_dir(tmp_path) / "events.jsonl"
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


def _resolve_payload(tmp_path, event):
    """Return the event payload, loading the sidecar file if it was offloaded ($ref)."""
    payload = event.get("payload", {})
    if isinstance(payload, dict) and "$ref" in payload:
        ref = _run_dir(tmp_path) / payload["$ref"].split("/", 1)[1]
        return json.loads(ref.read_text())
    return payload


def test_disabled_instruments_and_visual_off_reflected(tmp_path):
    # Disable two diagnostics and two structural tools; turn visual analysis off.
    all_diags = list(DiagnosticsBundle.field_names())
    diag_override = {d: True for d in all_diags}
    diag_override["segment_stats"] = False
    diag_override["transient_event_score"] = False

    all_tools = list(structural_tool_names())
    tool_override = {t: True for t in all_tools}
    tool_override["recent_window"] = False
    tool_override["full_history_clean_event"] = False
    tool_override["full_history_default"] = True  # fallback always on

    override = ConfigOverride(
        visual_analysis_enabled=False,
        diagnostics=diag_override,
        agent_tools=tool_override,
    )
    decision = _Fake(
        [InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e")
         for _ in range(5)]
    )
    run_scenario(_SID, override=override, model_wrappers=(_Fake([]), decision), reports_root=tmp_path)
    events = _read_stream(tmp_path)

    def _complete(stage):
        return next(e for e in events if e["stage"] == stage and e["status"] == "complete")

    # config_resolved lists the disabled diagnostics + removed tools.
    cfg_payload = _resolve_payload(tmp_path, _complete("config_resolved"))
    assert set(cfg_payload["hidden_diagnostics"]) == {"segment_stats", "transient_event_score"}
    assert set(cfg_payload["removed_tools"]) == {"recent_window", "full_history_clean_event"}
    assert cfg_payload["visual_analysis_enabled"] is False

    # diagnostics_computed exposes only the enabled diagnostics.
    exposed = set(_resolve_payload(tmp_path, _complete("diagnostics_computed"))["diagnostics"])
    assert "segment_stats" not in exposed and "transient_event_score" not in exposed

    # decision menu omits disabled tools but keeps the always-on fallback.
    menu = _resolve_payload(tmp_path, _complete("decision_iteration"))["menu"]
    assert "recent_window" not in menu and "full_history_clean_event" not in menu
    assert "full_history_default" in menu

    # No visual_inspection event when visual analysis is off.
    assert all(e["stage"] != "visual_inspection" for e in events)

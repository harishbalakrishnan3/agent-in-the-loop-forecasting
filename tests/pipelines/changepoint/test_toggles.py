"""T057/T062 — toggle integration: disabled diagnostic hidden-but-computed; disabled tool removed;
visual on/off (US2/US3, FR-013/FR-014/SC-004/SC-005/SC-006).

End-to-end through run_scenario with a FakeModelWrapper; inspects the recorded trace.
"""

from __future__ import annotations

import json

from ailf.core.config.schema import ConfigOverride
from ailf.pipelines.changepoint.pipeline import run_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice, VisualInspectionResult

_SID = "level_shift_loses_seasonality"


class _Fake:
    def __init__(self, responses):
        self._responses = list(responses)
        self.model_id = "fake"

    def invoke_structured_text(self, *, prompt, schema):
        self._last_prompt = prompt
        return self._responses.pop(0)

    def invoke_structured_with_image(self, *, prompt, image_path, schema):
        return self._responses.pop(0)


def _models(visual_enabled=True):
    v = _Fake([VisualInspectionResult(observations=["o"], pattern_summary="p", hypotheses=["h"], uncertainties=["u"])]
              if visual_enabled else [])
    d = _Fake([InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e")
               for _ in range(5)])
    return v, d


def _trace(tmp_path):
    return json.loads((tmp_path / f"{_SID}-1729" / "agent_trace.json").read_text())


def test_disabled_diagnostic_hidden_from_agent_but_present_in_full_trace(tmp_path):
    v, d = _models(visual_enabled=True)
    run_scenario(
        _SID,
        override=ConfigOverride(diagnostics={"recurring_event_summary": False}),
        model_wrappers=(v, d),
        reports_root=tmp_path,
    )
    trace = _trace(tmp_path)
    # Recorded as hidden:
    assert "recurring_event_summary" in trace["hidden_diagnostics"]
    # The FULL bundle in the trace still has it (still computed):
    assert "recurring_event_summary" in trace["diagnostics"]
    # The agent's decision input excluded it from the serialized diagnostics DATA block. The prompt
    # PROSE mentions the field name in its decision rules, so assert on the JSON key form, which only
    # appears in the embedded data, and confirm an enabled field's JSON key IS present.
    assert '"recurring_event_summary":' not in d._last_prompt
    assert '"permanent_shift_magnitude":' in d._last_prompt


def test_disabled_tool_removed_and_never_accepted(tmp_path):
    v, d = _models(visual_enabled=True)
    run_scenario(
        _SID,
        override=ConfigOverride(agent_tools={"full_history_ramp_regressor": False}),
        model_wrappers=(v, d),
        reports_root=tmp_path,
    )
    trace = _trace(tmp_path)
    assert "full_history_ramp_regressor" in trace["removed_tools"]
    # the removed tool is not advertised in the decision prompt menu
    assert "full_history_ramp_regressor" not in d._last_prompt
    chosen = trace["final_candidate"]["tool"]
    assert chosen != "full_history_ramp_regressor"


def test_visual_off_uses_diagnostics_only_prompt(tmp_path):
    v, d = _models(visual_enabled=False)
    run_scenario(
        _SID,
        override=ConfigOverride(visual_analysis_enabled=False),
        model_wrappers=(v, d),
        reports_root=tmp_path,
    )
    trace = _trace(tmp_path)
    assert trace["visual_analysis_enabled"] is False
    assert trace["prompt_ids"]["decision"] == "react_decision_diagnostics_only_v1"
    assert not trace["visual"]  # no visual result recorded

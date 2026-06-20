"""T077/T076 — end-to-end event stream (SC-010) + leakage (FR-029).

Runs a full scenario with a FakeModelWrapper + FileEventSink, then asserts events.jsonl is the
complete, in-order stream conforming to the documented per-stage shapes, with no pre-final leakage.
"""

from __future__ import annotations

import json

from ailf.core.config.schema import ConfigOverride
from ailf.core.events.leakage import assert_no_leakage
from ailf.pipelines.changepoint.pipeline import run_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice, VisualInspectionResult

_SID = "level_shift_loses_seasonality"


class _Fake:
    def __init__(self, responses):
        self._responses = list(responses)
        self.model_id = "fake"

    def invoke_structured_text(self, *, prompt, schema):
        return self._responses.pop(0)

    def invoke_structured_with_image(self, *, prompt, image_path, schema):
        return self._responses.pop(0)


def _models(visual_enabled=True):
    v = _Fake([VisualInspectionResult(observations=["o"], pattern_summary="p", hypotheses=["h"], uncertainties=["u"])]
              if visual_enabled else [])
    d = _Fake([InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e")
               for _ in range(5)])
    return v, d


def _read_stream(tmp_path):
    path = tmp_path / f"{_SID}-1729" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


def test_stream_has_expected_stages_in_causal_order(tmp_path):
    run_scenario(_SID, model_wrappers=_models(True), reports_root=tmp_path)
    events = _read_stream(tmp_path)
    # seq strictly increasing
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    stages = [e["stage"] for e in events if e["status"] == "complete"]
    # prelude appears, in causal order, before the agent stages
    prelude = ["config_resolved", "split_built", "changepoint_detection",
               "baseline_full_history_prophet", "baseline_naive_workflow", "diagnostics_computed"]
    idx = [stages.index(s) for s in prelude]
    assert idx == sorted(idx), stages
    # visual present (visual on), and final/run_complete last
    assert "visual_inspection" in stages
    assert stages[-2:] == ["final_evaluation", "run_complete"]
    # at least one decision + validation pair
    assert "decision_iteration" in stages and "validation_outcome" in stages


def test_visual_diagnostics_concurrency_group_marked(tmp_path):
    run_scenario(_SID, model_wrappers=_models(True), reports_root=tmp_path)
    events = _read_stream(tmp_path)
    visual = [e for e in events if e["stage"] == "visual_inspection"]
    assert visual and all(e["concurrency_group"] == "visual_diagnostics" for e in visual)


def test_visual_off_stream_has_no_visual_stage(tmp_path):
    run_scenario(_SID, override=ConfigOverride(visual_analysis_enabled=False),
                 model_wrappers=_models(False), reports_root=tmp_path)
    stages = {e["stage"] for e in _read_stream(tmp_path)}
    assert "visual_inspection" not in stages
    assert "diagnostics_computed" in stages


def test_no_prefinal_event_leaks_test_or_audit(tmp_path):
    run_scenario(_SID, model_wrappers=_models(True), reports_root=tmp_path)
    events = _read_stream(tmp_path)
    for e in events:
        if e["stage"] in ("final_evaluation", "run_complete"):
            continue
        assert_no_leakage(e["payload"])  # raises LeakageError on any forbidden key
        # validation_outcome must not carry val_metrics
        if e["stage"] == "validation_outcome":
            assert "val_metrics" not in e["payload"]


def test_test_metrics_first_appear_at_final_evaluation(tmp_path):
    run_scenario(_SID, model_wrappers=_models(True), reports_root=tmp_path)
    events = _read_stream(tmp_path)
    for e in events:
        blob = json.dumps(e["payload"])
        if e["stage"] in ("final_evaluation", "run_complete"):
            continue
        assert "test_metrics" not in blob, f"{e['stage']} leaked test_metrics"

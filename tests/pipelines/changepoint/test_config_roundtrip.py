"""T079 — SC-007: re-ingesting a recorded effective_config reproduces metrics + stable provenance.

Runs a scenario, reads the recorded effective_config.json, re-runs with it as the override, and
asserts identical deterministic metrics + stable split provenance.
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
        return self._responses.pop(0)

    def invoke_structured_with_image(self, *, prompt, image_path, schema):
        return self._responses.pop(0)


def _models():
    v = _Fake([VisualInspectionResult(observations=["o"], pattern_summary="p", hypotheses=["h"], uncertainties=["u"])])
    d = _Fake([InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e") for _ in range(5)])
    return v, d


def test_golden_run_roundtrip_reproduces_and_keeps_golden_provenance(tmp_path):
    first = run_scenario(_SID, model_wrappers=_models(), reports_root=tmp_path)
    recorded = json.loads((tmp_path / f"{_SID}-1729" / "effective_config.json").read_text())
    assert recorded["split_provenance"]["source"] == "golden"

    # Re-ingest the recorded effective_config as the override.
    override = ConfigOverride.from_dict(recorded["effective_config"])
    second = run_scenario(_SID, override=override, model_wrappers=_models(), reports_root=tmp_path / "rerun")
    rec2 = json.loads((tmp_path / "rerun" / f"{_SID}-1729" / "effective_config.json").read_text())

    # Provenance stays golden; deterministic baseline metrics reproduce.
    assert rec2["split_provenance"]["source"] == "golden"
    assert first["methods"]["full_history_prophet"]["mae"] == second["methods"]["full_history_prophet"]["mae"]
    assert first["methods"]["naive_workflow"]["mae"] == second["methods"]["naive_workflow"]["mae"]

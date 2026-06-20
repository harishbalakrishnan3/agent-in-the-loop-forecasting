"""T028 — diagnostics: 13 fields, compute-but-hide filtering, golden byte-identity vs the POC."""

from __future__ import annotations

import pytest

from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle, compute_diagnostics
from ailf.pipelines.changepoint.scenarios import load_scenario
from pocs.changepoint.diagnostics import compute_diagnostics as poc_compute
from pocs.changepoint.detector import detect_changepoints as poc_detect
from pocs.changepoint.scenarios import load_scenario as poc_load

_SID = "level_shift_loses_seasonality"

_EXPECTED_FIELDS = {
    "detected_changepoints",
    "latest_changepoint",
    "primary_changepoint",
    "post_changepoint_history_len",
    "post_changepoint_shorter_than_season",
    "seasonal_period",
    "segment_stats",
    "candidate_event_blocks",
    "recurring_event_summary",
    "local_boundary_jumps",
    "candidate_drift_intervals",
    "transient_event_score",
    "permanent_shift_magnitude",
}


@pytest.fixture(scope="module")
def bundle() -> DiagnosticsBundle:
    sc = load_scenario(_SID)
    cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    return compute_diagnostics(sc.split.train_df, changepoints=cps, seasonal_period=sc.seasonal_period)


def test_bundle_has_exactly_13_fields():
    assert set(DiagnosticsBundle.field_names()) == _EXPECTED_FIELDS
    assert len(DiagnosticsBundle.field_names()) == 13


def test_all_enabled_view_is_full(bundle):
    assert set(bundle.to_agent_dict()) == _EXPECTED_FIELDS


def test_disabled_diagnostic_hidden_but_full_still_computed(bundle):
    enabled = _EXPECTED_FIELDS - {"recurring_event_summary"}
    view = bundle.to_agent_dict(enabled)
    assert "recurring_event_summary" not in view
    # Still computed on the full bundle (dependents unaffected):
    assert bundle.recurring_event_summary is not None
    assert "recurring_event_summary" in bundle.to_agent_dict()


def test_golden_byte_identity_with_poc(bundle):
    # SC-001 parity guard: the all-enabled filtered view equals the POC's to_agent_dict output.
    psc = poc_load(_SID)
    pcps = poc_detect(psc.split.train_df, n_changepoints_to_detect=psc.n_changepoints_to_detect)
    pbundle = poc_compute(psc.split.train_df, changepoints=pcps, seasonal_period=psc.seasonal_period)
    assert bundle.to_agent_dict() == pbundle.to_agent_dict()

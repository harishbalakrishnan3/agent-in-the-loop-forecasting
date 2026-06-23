"""Test-first (Principle II) — changepoint GT decode + schema-1.1 record builder.

decode branches per family; build_golden_record over a synthetic run dir produces a self-contained
schema-1.1 record with judged_iteration (gated iteration selected over [0] when a prophet_tuned
proposal exists) and NO trace_path; train_end mismatch raises.
"""

from __future__ import annotations

import json

from ailf.pipelines.changepoint.eval.record import (
    build_golden_record,
    decode_ground_truth_events,
    _normalize_drift_intervals,
    _normalize_event_blocks,
)


def test_decode_per_family():
    assert decode_ground_truth_events("full_history_step_regressor", [610, 700]) == [
        {"kind": "point", "index": 610}, {"kind": "point", "index": 700}]
    assert decode_ground_truth_events("full_history_ramp_regressor", [540, 720]) == [
        {"kind": "interval", "start": 540, "end": 720, "interval_type": "drift"}]
    ev = decode_ground_truth_events("full_history_clean_event", [250, 268, 420, 444])
    assert len(ev) == 2 and ev[0] == {"kind": "interval", "start": 250, "end": 268, "interval_type": "event"}
    assert decode_ground_truth_events("fallback", []) == []


def test_normalize_intervals():
    assert _normalize_drift_intervals([{"start": 100, "end": 199}])[0]["end"] == 200   # inclusive -> +1
    assert _normalize_event_blocks([{"start": 10, "end": 20}])[0]["end"] == 20          # already exclusive


def _write_run_dir(tmp_path, *, iterations, family="full_history_clean_event", train_end=880):
    d = tmp_path / "scen-1729"
    d.mkdir()
    trace = {
        "scenario_id": "scen", "seed": 1729,
        "split_provenance": {"derived": {"train_end": train_end, "fit_end": train_end - 120}},
        "diagnostics": {"detected_changepoints": [{"index": 5}], "candidate_event_blocks": [],
                        "candidate_drift_intervals": [], "recurring_event_summary": {"is_calendar_recurring": False},
                        "transient_event_score": 1.0, "permanent_shift_magnitude": 2.0},
        "final_candidate": {"tool": family, "params": {}},
        "final_case": "accepted_beat_naive", "iterations": iterations,
    }
    (d / "agent_trace.json").write_text(json.dumps(trace))
    (d / "metrics.json").write_text(json.dumps({
        "winner": "agent", "horizon": 120,
        "methods": {"agent": {"mae": 1.0, "rmse": 1, "wape": 1, "smape": 1},
                    "naive_workflow": {"mae": 5.0, "rmse": 5, "wape": 5, "smape": 5},
                    "full_history_prophet": {"mae": 5.0, "rmse": 5, "wape": 5, "smape": 5}}}))
    return d


def _gt(_sid):
    return {"expected_intervention_family": "full_history_clean_event", "true_injected_boundaries": [10, 20],
            "note": "n", "train_end": 880, "n_changepoints_to_detect": 2, "seasonal_period": 365}


def test_build_record_schema_1_1_no_trace_path(tmp_path):
    d = _write_run_dir(tmp_path, iterations=[
        {"proposal": {"tool": "full_history_clean_event", "rationale": "R0"}}])
    rec = build_golden_record(d, gt_loader=_gt)
    assert rec["record_schema_version"] == "1.1"
    assert "trace_path" not in rec
    assert rec["judged_iteration"]["rationale"] == "R0"   # only one iteration
    assert rec["outcome"]["beat_naive"] is True


def test_build_record_picks_gated_iteration_not_first(tmp_path):
    # iteration[0] is recent_window; the GATED tuned-holidays iteration is at index 1 -> judge it
    d = _write_run_dir(tmp_path, iterations=[
        {"proposal": {"tool": "recent_window", "rationale": "R0"}},
        {"proposal": {"tool": "full_history_prophet_tuned_holidays", "rationale": "R-GATED"}}])
    rec = build_golden_record(d, gt_loader=_gt)
    assert rec["judged_iteration"]["rationale"] == "R-GATED"
    assert rec["judged_iteration"]["tool_argued_for"] == "full_history_prophet_tuned_holidays"


def test_build_record_train_end_mismatch_raises(tmp_path):
    import pytest
    d = _write_run_dir(tmp_path, iterations=[{"proposal": {"tool": "x", "rationale": "r"}}], train_end=999)
    with pytest.raises(ValueError):
        build_golden_record(d, gt_loader=_gt)   # gt train_end=880 != trace 999

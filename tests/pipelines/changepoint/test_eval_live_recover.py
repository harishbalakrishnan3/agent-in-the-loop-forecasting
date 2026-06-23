"""Test-first (Principle II) — the deterministic crash-recovery in eval/live.py (no Bedrock).

_recover_from_events reconstructs proposals + the repeated_blocked_tool signal from a synthetic
events.jsonl; build_crash_record wraps it into a self-contained crash record the classifier reads.
"""

from __future__ import annotations

import json

from ailf.pipelines.changepoint.eval.live import _recover_from_events, build_crash_record
from ailf.pipelines.changepoint.eval.failure_modes import classify_record


def _events(tmp_path, rows):
    d = tmp_path / "scen-1729"
    d.mkdir()
    (d / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    return d


def test_recover_detects_repeated_blocked_tool(tmp_path):
    rows = [
        {"stage": "split_built", "payload": {"provenance": {"derived": {"train_end": 1610, "fit_end": 1490}}}},
        {"stage": "decision_iteration", "payload": {"i": 1, "proposal": {"tool": "full_history_prophet_tuned_holidays", "params": {"a": 1}}}},
        {"stage": "validation_outcome", "payload": {"i": 1, "rejected_reason": "precondition failed: not calendar-recurring"}},
        {"stage": "decision_iteration", "payload": {"i": 2, "proposal": {"tool": "full_history_prophet_tuned_holidays", "params": {"a": 2}}}},
        {"stage": "validation_outcome", "payload": {"i": 2, "rejected_reason": "precondition failed: not calendar-recurring"}},
    ]
    rec = _recover_from_events(_events(tmp_path, rows))
    assert rec["n_iterations"] == 2
    assert rec["repeated_blocked_tool"] is True          # same tool 2x, both precondition-rejected
    assert rec["split"] == {"train_end": 1610, "fit_end": 1490}


def test_recover_no_events_returns_empty(tmp_path):
    d = tmp_path / "scen-1729"; d.mkdir()
    rec = _recover_from_events(d)
    assert rec["n_iterations"] == 0 and rec["repeated_blocked_tool"] is False


def test_build_crash_record_indexerror_classifies_pipeline(tmp_path):
    d = _events(tmp_path, [{"stage": "decision_iteration", "payload": {"i": 1, "proposal": {"tool": "full_history_ramp_regressor"}}}])
    gt = {"expected_intervention_family": "fallback", "true_injected_boundaries": [],
          "note": "", "n_changepoints_to_detect": 2, "seasonal_period": 365}
    rec = build_crash_record("scen", IndexError("single positional indexer is out-of-bounds"), d, gt)
    assert rec["record_schema_version"] == "1.0-crash"
    assert rec["crash_info"]["exception_type"] == "IndexError"
    assert rec["crash_info"]["crash_stage"] == "validation"
    assert rec["outcome"]["beat_naive"] is False
    # the classifier reads it as a pipeline-class crash
    assert classify_record(rec)["failure_mode_labels"] == ["crashed_indexerror"]

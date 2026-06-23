"""Test-first (Principle II) — the changepoint failure-mode taxonomy classifier.

Every taxonomy predicate against synthetic records with KNOWN labels, incl. the 3 crash modes
(keyed on crash_info) and the suppression of outcome-modes on crash records.
"""

from __future__ import annotations

from ailf.pipelines.changepoint.eval.failure_modes import classify_record, classify_corpus


def _rec(family, chosen, amae, nmae, *, events=None, blocks=None, drifts=None, crash=None):
    fc = ("interval" if family in ("full_history_ramp_regressor", "full_history_clean_event")
          else ("point" if family in ("full_history_step_regressor", "full_history_prophet_tuned_holidays")
                else "none"))
    rec = {
        "scenario_id": "t",
        "ground_truth": {"expected_intervention_family": family, "family_channel": fc,
                         "ground_truth_events": events or [], "intended_failure_lever": "x"},
        "prediction": {"chosen_tool": chosen, "candidate_event_blocks": blocks or [],
                       "candidate_drift_intervals": drifts or []},
        "outcome": {"beat_naive": amae < nmae, "winner": "agent" if amae < nmae else "naive_workflow"},
    }
    if crash:
        rec["crash_info"] = crash
    return rec


def test_clean_success():
    r = classify_record(_rec("full_history_clean_event", "full_history_clean_event", 1, 10,
                             events=[{"kind": "interval", "start": 10, "end": 20, "interval_type": "event"}],
                             blocks=[{"start": 10, "end": 20}]))
    assert "clean_success" in r["failure_mode_labels"] and not r["is_behavioral_failure"]


def test_capability_gap_not_a_bug():
    r = classify_record(_rec("fallback", "recent_window", 12, 10))
    assert r["is_capability_gap"] and not r["is_behavioral_failure"]


def test_no_proposal_beat_naive_behavioral():
    r = classify_record(_rec("full_history_ramp_regressor", "full_history_step_regressor", 12, 10))
    assert "no_proposal_beat_naive" in r["failure_mode_labels"] and r["is_behavioral_failure"]


def test_wrong_family_but_won():
    r = classify_record(_rec("full_history_ramp_regressor", "full_history_clean_event", 1, 10))
    assert "wrong_family_but_won" in r["failure_mode_labels"]


def test_crash_indexerror_pipeline_class():
    r = classify_record(_rec("fallback", None, 0, 0,
                             crash={"exception_type": "IndexError", "crash_stage": "validation",
                                    "repeated_blocked_tool": False}))
    assert r["failure_mode_labels"] == ["crashed_indexerror"]
    assert r["is_pipeline_blindness"] and not r["is_capability_gap"]


def test_crash_loop_then_final_two_labels_behavioral():
    r = classify_record(_rec("fallback", None, 0, 0,
                             crash={"exception_type": "ToolBoundsError", "crash_stage": "final_eval",
                                    "repeated_blocked_tool": True}))
    assert set(r["failure_mode_labels"]) == {"looped_on_blocked_tool", "crashed_at_final_eval"}
    assert r["is_behavioral_failure"]


def test_classify_corpus_counts():
    recs = [
        _rec("full_history_clean_event", "full_history_clean_event", 1, 10,
             events=[{"kind": "interval", "start": 10, "end": 20, "interval_type": "event"}],
             blocks=[{"start": 10, "end": 20}]),
        _rec("fallback", "recent_window", 12, 10),
    ]
    tax = classify_corpus(recs)
    assert tax["n"] == 2 and tax["capability_gaps"] == 1

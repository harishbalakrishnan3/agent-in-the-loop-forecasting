"""Test-first (Principle II) — changepoint family-aware evaluators + summarize + projector."""

from __future__ import annotations

from ailf.pipelines.changepoint.eval.evaluators import (
    boundary_recall_interval,
    chose_authored_family,
    point_boundary_recall_detector,
    summarize,
)
from ailf.pipelines.changepoint.eval.projector import example_inputs, example_metadata


class _O:
    def __init__(self, o):
        self.outputs = o


def _interval_rec(family="full_history_ramp_regressor", recall_full=True):
    gt = [{"kind": "interval", "start": 100, "end": 200, "interval_type": "drift"}]
    drifts = [{"start": 100, "end": 200}] if recall_full else []
    return {"scenario_id": "s", "seed": 1729,
            "ground_truth": {"expected_intervention_family": family, "family_channel": "interval",
                             "ground_truth_events": gt, "n_changepoints_to_detect": 2, "seasonal_period": 365},
            "prediction": {"chosen_tool": family, "candidate_drift_intervals": drifts,
                           "candidate_event_blocks": [], "detected_changepoints": []},
            "outcome": {"beat_naive": True, "agent_is_winner": True, "agent_minus_naive_mae": -1.0}}


def _point_rec():
    return {"scenario_id": "p", "seed": 1729,
            "ground_truth": {"expected_intervention_family": "full_history_step_regressor",
                             "family_channel": "point",
                             "ground_truth_events": [{"kind": "point", "index": 300}],
                             "n_changepoints_to_detect": 2, "seasonal_period": 365},
            "prediction": {"chosen_tool": "full_history_step_regressor", "candidate_drift_intervals": [],
                           "candidate_event_blocks": [], "detected_changepoints": [305]},
            "outcome": {"beat_naive": False, "agent_is_winner": False, "agent_minus_naive_mae": 1.0}}


def test_boundary_recall_interval_runs_on_interval_na_on_point():
    assert boundary_recall_interval(_O(_interval_rec()), None)["score"] == 1.0
    assert boundary_recall_interval(_O(_point_rec()), None)["score"] is None


def test_point_detector_runs_on_point_na_on_interval():
    assert point_boundary_recall_detector(_O(_point_rec()), None)["score"] == 1.0   # 305 within ±25 of 300
    assert point_boundary_recall_detector(_O(_interval_rec()), None)["score"] is None


def test_chose_authored_family_fallback_tool_matches_fallback_label():
    rec = {"prediction": {"chosen_tool": "full_history_default"},
           "ground_truth": {"expected_intervention_family": "fallback"}}
    assert chose_authored_family(_O(rec), None)["score"] == 1
    rec2 = {"prediction": {"chosen_tool": "recent_window"},
            "ground_truth": {"expected_intervention_family": "fallback"}}
    assert chose_authored_family(_O(rec2), None)["score"] == 0


def test_summarize_headline_and_crash_tolerant():
    crash = {"scenario_id": "c", "ground_truth": {"family_channel": "none", "ground_truth_events": [],
             "expected_intervention_family": "fallback"},
             "prediction": {"chosen_tool": None, "candidate_drift_intervals": [], "candidate_event_blocks": []},
             "outcome": {"beat_naive": False, "agent_is_winner": False}, "crash_info": {"exception_type": "IndexError"}}
    s = summarize([_interval_rec(), _point_rec(), crash])
    assert s["n"] == 3 and s["beat_naive_count"] == "1/3"
    assert s["interval_recall_micro"] == 1.0 and s["interval_family_n"] == 1


def test_projector_inputs_exclude_ground_truth_and_metadata_has_role():
    from ailf.pipelines.changepoint.eval.curated import CURATED_IDS
    rec = _interval_rec()
    rec["scenario_id"] = CURATED_IDS[0]
    ins = example_inputs(rec)
    assert set(ins) == {"scenario_id", "seed", "n_changepoints_to_detect", "seasonal_period"}
    assert "expected_intervention_family" not in ins and "ground_truth" not in ins
    md = example_metadata(rec)
    assert md["curated_role"] == "control" and "failure_mode" in md and "family_channel" in md

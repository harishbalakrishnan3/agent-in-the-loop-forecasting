"""Changepoint family-aware evaluators + the concrete evaluator list (promoted from the POC).

These branch on changepoint family names / read changepoint diagnostic fields, so they live in the
pipeline (Principle VII). They compose with the domain-agnostic core evaluators via
``ailf.core.eval.build_evaluator_set``. The LLM-judge is appended only when requested (it calls
Bedrock).
"""

from __future__ import annotations

from typing import Any

from ailf.core.eval import (
    agent_is_winner,
    agent_minus_naive_mae,
    beat_naive,
    build_evaluator_set,
    match_intervals,
    match_points,
    record_of,
)

_FALLBACK_TOOL = "full_history_default"  # how the agent expresses the gold label "fallback"


def boundary_recall_interval(run, example) -> dict[str, Any]:
    """Interval families (ramp/clean_event): recall of injected intervals via IoU>=0.5. score=None
    on point families (their boundary signal is the detector diagnostic below)."""
    rec = record_of(run, example)
    g = rec.get("ground_truth", {})
    if g.get("family_channel") != "interval":
        return {"key": "boundary_recall_interval", "score": None, "value": "n/a_point_family"}
    family = g.get("expected_intervention_family")
    pred = (rec["prediction"]["candidate_drift_intervals"] if family == "full_history_ramp_regressor"
            else rec["prediction"]["candidate_event_blocks"])
    m = match_intervals(g.get("ground_truth_events", []), pred)
    return {"key": "boundary_recall_interval", "score": m["recall"] if m["recall"] is not None else 0.0,
            "comment": f"tp={m['tp']} fp={m['fp']} fn={m['fn']}"}


def point_boundary_recall_detector(run, example) -> dict[str, Any]:
    """Point families (step/holiday): recall of injected changepoints by the detector within ±N.
    Labelled DETECTOR — measures Prophet's grid, NOT the agent. score=None on interval families."""
    rec = record_of(run, example)
    g = rec.get("ground_truth", {})
    if g.get("family_channel") != "point":
        return {"key": "point_boundary_recall_detector", "score": None, "value": "n/a_interval_family"}
    m = match_points(g.get("ground_truth_events", []), rec["prediction"]["detected_changepoints"])
    return {"key": "point_boundary_recall_detector", "score": m["recall"] if m["recall"] is not None else 0.0,
            "comment": f"DETECTOR (not agent): tp={m['tp']} fp={m['fp']} fn={m['fn']} N={m['tolerance']}"}


def _family_matches(chosen: str | None, expected: str | None) -> bool:
    if chosen == expected:
        return True
    # gold label "fallback" (unsolvable) is expressed by choosing the always-valid fallback tool
    return expected == "fallback" and chosen == _FALLBACK_TOOL


def chose_authored_family(run, example) -> dict[str, Any]:
    """Did the agent pick the gold family? Treats full_history_default as matching the 'fallback'
    label. CAVEAT: authored intent may differ from the gate-winner — diagnostic, not headline."""
    rec = record_of(run, example)
    chosen = rec.get("prediction", {}).get("chosen_tool")
    expected = rec.get("ground_truth", {}).get("expected_intervention_family")
    return {"key": "chose_authored_family", "score": 1 if _family_matches(chosen, expected) else 0,
            "comment": f"chosen={chosen} authored={expected}"}


# The changepoint evaluator list = core outcome-only evaluators + the family-aware ones.
CHANGEPOINT_EVALUATORS = build_evaluator_set(
    [beat_naive, agent_is_winner, agent_minus_naive_mae],
    extra=[boundary_recall_interval, point_boundary_recall_detector, chose_authored_family],
)


def failure_mode_metadata(rec: dict[str, Any]) -> dict[str, Any]:
    """Topic-4 diagnosis as plain METADATA (a label, not a metric): primary failure mode + class
    flags. Attached to LangSmith examples so the UI can filter/group by it."""
    from ailf.pipelines.changepoint.eval.failure_modes import classify_record  # noqa: PLC0415
    row = classify_record(rec)
    labels = row["failure_mode_labels"] or ["unlabeled"]
    primary = next((l for l in labels if l != "clean_success"), labels[0])
    return {"failure_mode": primary, "failure_mode_labels": labels,
            "is_capability_gap": row["is_capability_gap"],
            "is_behavioral_failure": row["is_behavioral_failure"],
            "is_pipeline_blindness": row["is_pipeline_blindness"]}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline over a set of records: beat-naive rate + micro interval-recall. Crash-record-tolerant
    (crash records carry stubbed outcome/prediction/ground_truth blocks with beat_naive=False)."""
    n = len(records)
    beat = sum(1 for r in records if r["outcome"].get("beat_naive"))
    winner = sum(1 for r in records if r["outcome"].get("agent_is_winner"))
    tp_sum = fn_sum = interval_n = 0
    for r in records:
        g = r["ground_truth"]
        if g.get("family_channel") != "interval":
            continue
        interval_n += 1
        family = g["expected_intervention_family"]
        pred = (r["prediction"]["candidate_drift_intervals"] if family == "full_history_ramp_regressor"
                else r["prediction"]["candidate_event_blocks"])
        m = match_intervals(g.get("ground_truth_events", []), pred)
        tp_sum += m["tp"]
        fn_sum += m["fn"]
    interval_recall = (tp_sum / (tp_sum + fn_sum)) if (tp_sum + fn_sum) > 0 else None
    return {"n": n, "beat_naive_rate": beat / n if n else None,
            "beat_naive_count": f"{beat}/{n}", "agent_is_winner_count": f"{winner}/{n}",
            "interval_recall_micro": interval_recall, "interval_family_n": interval_n}

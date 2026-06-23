"""Changepoint golden-record builder: a run dir (agent_trace.json + metrics.json) + held-out ground
truth -> one self-contained schema-1.1 golden record.

Changepoint-specific (hard-codes the family names + the agent_trace/metrics schema), so it lives in
the pipeline. The domain-agnostic matching primitives live in ``ailf.core.eval.matching``. This is
used only by the OPTIONAL regenerate path (the default CLI replays the committed self-contained
records); it emits schema 1.1 with the judge inputs INLINED (judged_iteration) and NO trace_path, so
its output equals the committed asset for the non-crash curated cases.

Index basis (Topic-1, verified): indices are 0-based rows into the full series = training-region row
for idx < train_end. EventBlock.end is already exclusive (copied); DriftInterval.end is inclusive
(stored half-open as end = raw_end + 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ailf.core.eval.matching import read_json
from ailf.pipelines.changepoint.eval.scenarios import family_channel, load_ground_truth

_GATED_TOOL = "full_history_prophet_tuned_holidays"  # the precondition-gated tool the judge targets


def decode_ground_truth_events(family: str | None, boundaries: list[int]) -> list[dict[str, Any]]:
    """Decode the flat true_injected_boundaries into normalized events per family (Topic-1).

    step / prophet_tuned_holidays -> POINTS; ramp -> one drift INTERVAL; clean_event -> consecutive
    event-block INTERVAL pairs; anything else (recent_window/fallback) -> []."""
    if family in ("full_history_step_regressor", _GATED_TOOL):
        return [{"kind": "point", "index": int(i)} for i in boundaries]
    if family == "full_history_ramp_regressor":
        if len(boundaries) < 2:
            return []
        return [{"kind": "interval", "start": int(boundaries[0]), "end": int(boundaries[1]),
                 "interval_type": "drift"}]
    if family == "full_history_clean_event":
        return [{"kind": "interval", "start": int(boundaries[i]), "end": int(boundaries[i + 1]),
                 "interval_type": "event"} for i in range(0, len(boundaries) - 1, 2)]
    return []


def _normalize_drift_intervals(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DriftInterval.end is inclusive -> store half-open end = raw_end + 1."""
    return [{"start": int(d["start"]), "end": int(d["end"]) + 1,
             "slope_per_step": d.get("slope_per_step"), "total_delta": d.get("total_delta")}
            for d in raw]


def _normalize_event_blocks(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """EventBlock.end is already exclusive -> copy verbatim."""
    return [{"start": int(b["start"]), "end": int(b["end"]), "duration": b.get("duration"),
             "mean_excess": b.get("mean_excess"),
             "closed_before_origin": b.get("closed_before_origin")} for b in raw]


def _judged_iteration(trace: dict[str, Any]) -> dict[str, Any]:
    """Inline the judge inputs (schema 1.1): pick the gated-tool iteration if any, else iterations[0]."""
    its = trace.get("iterations", [])
    if not its:
        return {"rationale": "", "tool_argued_for": "", "diag": {}}
    gated = next((it for it in its if it["proposal"].get("tool") == _GATED_TOOL), None)
    it = gated or its[0]
    d = trace.get("diagnostics", {})
    return {"rationale": it["proposal"].get("rationale", ""),
            "tool_argued_for": it["proposal"].get("tool", ""),
            "diag": {"recurring_event_summary": d.get("recurring_event_summary"),
                     "transient_event_score": d.get("transient_event_score"),
                     "permanent_shift_magnitude": d.get("permanent_shift_magnitude"),
                     "candidate_drift_intervals_count": len(d.get("candidate_drift_intervals", [])),
                     "candidate_event_blocks_count": len(d.get("candidate_event_blocks", []))}}


def build_golden_record(run_dir: str | Path, gt_loader=load_ground_truth) -> dict[str, Any]:
    """Join one reports/changepoint/<run_id>/ into a self-contained schema-1.1 golden record
    (judge inputs inlined, no trace_path). ``gt_loader(scenario_id)`` resolves the held-out GT."""
    run_dir = Path(run_dir)
    trace = read_json(run_dir / "agent_trace.json")
    metrics = read_json(run_dir / "metrics.json")
    scenario_id = trace["scenario_id"]
    gt = gt_loader(scenario_id)
    family = gt["expected_intervention_family"]

    derived = trace.get("split_provenance", {}).get("derived", {})
    if "train_end" not in derived:
        raise ValueError(f"{run_dir}: split_provenance.derived.train_end missing — cannot scope scoring.")
    train_end = int(derived["train_end"])
    if train_end != int(gt["train_end"]):
        raise ValueError(f"{run_dir}: trace train_end {train_end} != metadata {gt['train_end']}.")

    diag = trace.get("diagnostics", {})
    methods = metrics["methods"]
    return {
        "record_schema_version": "1.1",
        "run_id": f"{scenario_id}-{trace['seed']}",
        "scenario_id": scenario_id,
        "seed": trace["seed"],
        "ground_truth": {
            "expected_intervention_family": family,
            "family_channel": family_channel(family),
            "true_injected_boundaries_raw": gt["true_injected_boundaries"],
            "ground_truth_events": decode_ground_truth_events(family, gt["true_injected_boundaries"]),
            "n_changepoints_to_detect": gt["n_changepoints_to_detect"],
            "seasonal_period": gt["seasonal_period"],
            "note": gt["note"],
            "intended_failure_lever": gt.get("intended_failure_lever"),
            "dev_or_test": gt.get("dev_or_test"),
            "source_bucket": gt.get("source_bucket"),
            "ground_truth_kind": gt.get("ground_truth_kind"),
            "authored_intent_family": gt.get("authored_intent_family"),
            "gate_winner_family": gt.get("gate_winner_family"),
        },
        "prediction": {
            "chosen_tool": trace.get("final_candidate", {}).get("tool"),
            "chosen_tool_params": trace.get("final_candidate", {}).get("params", {}),
            "final_case": trace.get("final_case"),
            "is_fallback": trace.get("final_candidate", {}).get("tool") == "full_history_default",
            "n_iterations": len(trace.get("iterations", [])),
            "detected_changepoints": [int(c["index"]) for c in diag.get("detected_changepoints", [])
                                      if c is not None],
            "candidate_event_blocks": _normalize_event_blocks(diag.get("candidate_event_blocks", [])),
            "candidate_drift_intervals": _normalize_drift_intervals(diag.get("candidate_drift_intervals", [])),
            "split": {"train_end": train_end, "fit_end": derived.get("fit_end")},
        },
        "outcome": {
            "winner": metrics["winner"],
            "beat_naive": methods["agent"]["mae"] < methods["naive_workflow"]["mae"],
            "agent_is_winner": metrics["winner"] == "agent",
            "horizon": metrics.get("horizon"),
            "agent_test_metrics": {k: methods["agent"][k] for k in ("mae", "rmse", "wape", "smape")},
            "naive_test_metrics": {k: methods["naive_workflow"][k] for k in ("mae", "rmse", "wape", "smape")},
            "full_history_prophet_test_metrics": {k: methods["full_history_prophet"][k]
                                                  for k in ("mae", "rmse", "wape", "smape")},
            "agent_minus_naive_mae": methods["agent"]["mae"] - methods["naive_workflow"]["mae"],
        },
        "judged_iteration": _judged_iteration(trace),
    }

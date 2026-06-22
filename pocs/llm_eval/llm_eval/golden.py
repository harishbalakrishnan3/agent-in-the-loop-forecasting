"""Topic-1 join: a run dir (agent_trace.json + metrics.json) + held-out ground truth -> one
golden record. Plus the boundary-matching helpers (point ±N tolerance, interval IoU).

Index basis (Topic-1, verified): all indices are 0-based rows into the full series, which equals
the training-region row index for any index < train_end. Interval ends are normalized to half-open
[start, end): EventBlock.end is already exclusive (copied verbatim); DriftInterval.end is INCLUSIVE
so we store end = raw_end + 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_eval.scenarios import family_channel, load_ground_truth

# Boundary-matching defaults (Topic-1 §4). Point tolerance is grid-based (Prophet ~28-day grid);
# it only ever feeds the DETECTOR diagnostic, never the agent headline.
DEFAULT_IOU_THRESHOLD = 0.5
DEFAULT_POINT_TOLERANCE = 25


# --------------------------------------------------------------------------------------
# Ground-truth decode (branch on the FULL family name — never infer from list parity)
# --------------------------------------------------------------------------------------

def decode_ground_truth_events(family: str | None, boundaries: list[int]) -> list[dict[str, Any]]:
    """Decode the flat true_injected_boundaries into normalized events per family (Topic-1 §0/§4).

    - full_history_step_regressor / full_history_prophet_tuned_holidays -> POINTS (one per int).
    - full_history_ramp_regressor -> one drift INTERVAL [start, end).
    - full_history_clean_event -> consecutive event-block INTERVAL pairs [start, end).
    Anything else (recent_window / fallback / objective-only) -> [] (no boundary scoring).
    """
    if family in ("full_history_step_regressor", "full_history_prophet_tuned_holidays"):
        return [{"kind": "point", "index": int(i)} for i in boundaries]
    if family == "full_history_ramp_regressor":
        if len(boundaries) < 2:
            return []
        return [{"kind": "interval", "start": int(boundaries[0]), "end": int(boundaries[1]),
                 "interval_type": "drift"}]
    if family == "full_history_clean_event":
        out: list[dict[str, Any]] = []
        for i in range(0, len(boundaries) - 1, 2):
            out.append({"kind": "interval", "start": int(boundaries[i]), "end": int(boundaries[i + 1]),
                        "interval_type": "event"})
        return out
    return []


# --------------------------------------------------------------------------------------
# Matching (pure; reused by evaluators.py so the score is computed once, consistently)
# --------------------------------------------------------------------------------------

def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    """IoU of two half-open intervals [start, end)."""
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union if union > 0 else 0.0


def match_intervals(gt: list[dict[str, Any]], pred: list[dict[str, Any]],
                    iou_threshold: float = DEFAULT_IOU_THRESHOLD) -> dict[str, Any]:
    """Greedy 1:1 interval match by descending IoU. Returns tp/fp/fn + precision/recall.

    precision is None when there are no predictions (tp+fp==0) — "found nothing" must not score
    1.0 (Topic-1 §4). recall is over the ground-truth intervals.
    """
    pairs = []
    for gi, g in enumerate(gt):
        for pi, p in enumerate(pred):
            v = _iou(g, p)
            if v >= iou_threshold:
                pairs.append((v, gi, pi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))  # desc IoU, deterministic tie-break
    used_g, used_p, matches = set(), set(), []
    for v, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matches.append({"gt": gt[gi], "pred": pred[pi], "iou": round(v, 4)})
    tp = len(matches)
    fp = len(pred) - tp
    fn = len(gt) - tp
    precision = None if (tp + fp) == 0 else tp / (tp + fp)
    recall = None if (tp + fn) == 0 else tp / (tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "matches": matches, "missed": [gt[i] for i in range(len(gt)) if i not in used_g],
            "iou_threshold": iou_threshold}


def match_points(gt: list[dict[str, Any]], detected: list[int],
                 tolerance: int = DEFAULT_POINT_TOLERANCE) -> dict[str, Any]:
    """Greedy 1:1 point match within ±tolerance. DETECTOR diagnostic only (Topic-1 blocker:
    Prophet ranks by slope-change so pure level shifts rarely land on the grid — this measures the
    detector, NOT the agent)."""
    g_idx = [g["index"] for g in gt]
    pairs = []
    for gi, g in enumerate(g_idx):
        for di, d in enumerate(detected):
            if abs(d - g) <= tolerance:
                pairs.append((abs(d - g), gi, di))
    pairs.sort(key=lambda t: (t[0], t[1], t[2]))  # asc distance, deterministic tie-break
    used_g, used_d = set(), set()
    for dist, gi, di in pairs:
        if gi in used_g or di in used_d:
            continue
        used_g.add(gi)
        used_d.add(di)
    tp = len(used_g)
    fp = len(detected) - len(used_d)
    fn = len(g_idx) - tp
    precision = None if (tp + fp) == 0 else tp / (tp + fp)
    recall = None if (tp + fn) == 0 else tp / (tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "tolerance": tolerance, "measures": "detector"}


# --------------------------------------------------------------------------------------
# Join: run dir -> golden record
# --------------------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _normalize_drift_intervals(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DriftInterval.end is inclusive -> store half-open end = raw_end + 1 (Topic-1 §4)."""
    return [{"start": int(d["start"]), "end": int(d["end"]) + 1,
             "slope_per_step": d.get("slope_per_step"), "total_delta": d.get("total_delta")}
            for d in raw]


def _normalize_event_blocks(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """EventBlock.end is already exclusive -> copy verbatim."""
    return [{"start": int(b["start"]), "end": int(b["end"]), "duration": b.get("duration"),
             "mean_excess": b.get("mean_excess"),
             "closed_before_origin": b.get("closed_before_origin")} for b in raw]


def build_golden_record(run_dir: str | Path, gt_loader=load_ground_truth) -> dict[str, Any]:
    """Join one reports/changepoint/<run_id>/ into a Topic-1 golden record.

    ``gt_loader(scenario_id) -> dict`` resolves the held-out ground truth; defaults to the committed
    6-scenario loader, but the POC 100-case path passes ``poc_runner.poc_ground_truth`` so each
    case joins against the generated metadata (incl. lever / bucket / authored-vs-gate-winner)."""
    run_dir = Path(run_dir)
    trace = _read_json(run_dir / "agent_trace.json")
    metrics = _read_json(run_dir / "metrics.json")

    scenario_id = trace["scenario_id"]
    gt = gt_loader(scenario_id)
    family = gt["expected_intervention_family"]

    # Split frame: train_end is the load-bearing bound (Topic-1 §3 step 3) — fail loud if missing.
    derived = trace.get("split_provenance", {}).get("derived", {})
    if "train_end" not in derived:
        raise ValueError(f"{run_dir}: split_provenance.derived.train_end missing — cannot scope "
                         "boundary scoring. (Pre-split-provenance trace?)")
    train_end = int(derived["train_end"])
    if train_end != int(gt["train_end"]):
        raise ValueError(f"{run_dir}: trace train_end {train_end} != metadata {gt['train_end']} — "
                         "split mismatch would mis-scope boundary scoring.")

    diag = trace.get("diagnostics", {})
    methods = metrics["methods"]

    return {
        "record_schema_version": "1.0",
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
            # POC lever fields (present for the 100-case set; absent/None for the committed 6):
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
            # PRIMARY headline signal: the TRUE 2-way beat-naive (agent.mae < naive.mae), NOT the
            # 3-way winner (which also requires beating full_history_prophet). See topic3 doc §1.
            "beat_naive": methods["agent"]["mae"] < methods["naive_workflow"]["mae"],
            "agent_is_winner": metrics["winner"] == "agent",
            "horizon": metrics.get("horizon"),
            "agent_test_metrics": {k: methods["agent"][k] for k in ("mae", "rmse", "wape", "smape")},
            "naive_test_metrics": {k: methods["naive_workflow"][k] for k in ("mae", "rmse", "wape", "smape")},
            "full_history_prophet_test_metrics": {k: methods["full_history_prophet"][k]
                                                  for k in ("mae", "rmse", "wape", "smape")},
            "agent_minus_naive_mae": methods["agent"]["mae"] - methods["naive_workflow"]["mae"],
        },
        "trace_path": str(run_dir / "agent_trace.json"),
        "metrics_path": str(run_dir / "metrics.json"),
    }


def build_all(run_dirs: list[str | Path]) -> list[dict[str, Any]]:
    return [build_golden_record(d) for d in run_dirs]


def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

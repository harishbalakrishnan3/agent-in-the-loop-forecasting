"""Deterministic code-check evaluators (LangSmith ``fn(run, example) -> {key, score}`` contract).

No LLM-as-judge in the MVP — every evaluator is a pure function over the golden record. In the
REPLAY design the full golden record is in BOTH ``example.outputs`` (ground truth) and
``run.outputs`` (prediction/outcome); each evaluator reads the convenient side. A LangSmith
``EvaluationResult`` allows ``score=None`` (verified on 0.8.15) — we use it for "not applicable"
(e.g. interval recall on a point family) so those rows are excluded from the per-key mean.

HEADLINE = ``beat_naive`` (the honest, baseline-relative, 2-way oracle: agent.mae < naive.mae).
Everything else is a labeled DIAGNOSTIC, not the headline (see topic3_mvp_pipeline.md §1, §3).
"""

from __future__ import annotations

from typing import Any

from llm_eval.golden import match_intervals, match_points


def _rec(run, example) -> dict[str, Any]:
    """Pull the golden record. Prefer run.outputs (prediction side); fall back to example.outputs.

    Accepts both the LangSmith Run/Example objects (``.outputs`` attribute) and plain dicts (the
    local test harness passes dicts), so the same evaluators run offline and in LangSmith.
    """
    out = getattr(run, "outputs", None)
    if not out and isinstance(run, dict):
        out = run.get("outputs")
    if not out:  # REPLAY target may echo the record straight through example
        out = getattr(example, "outputs", None) or (example.get("outputs") if isinstance(example, dict) else None)
    return out or {}


# ---- HEADLINE -------------------------------------------------------------------------

def beat_naive(run, example) -> dict[str, Any]:
    """PRIMARY headline: did the agent's chosen tool beat the naive baseline on TEST MAE?

    This is the true 2-way comparison (agent.mae < naive.mae), NOT winner=='agent' (which is a
    3-way win also requiring the agent to beat full_history_prophet). See topic3 doc §1.
    """
    rec = _rec(run, example)
    return {"key": "beat_naive", "score": 1 if rec.get("outcome", {}).get("beat_naive") else 0}


def boundary_recall_interval(run, example) -> dict[str, Any]:
    """Interval families (ramp / clean_event) only: recall of injected event/drift intervals via
    IoU>=0.5. Returns score=None for point families (excluded from the agent headline; their
    boundary signal is a detector diagnostic — see ``point_boundary_recall_detector``)."""
    rec = _rec(run, example)
    g = rec.get("ground_truth", {})
    if g.get("family_channel") != "interval":
        return {"key": "boundary_recall_interval", "score": None, "value": "n/a_point_family"}
    gt = g.get("ground_truth_events", [])
    family = g.get("expected_intervention_family")
    pred = (rec["prediction"]["candidate_drift_intervals"] if family == "full_history_ramp_regressor"
            else rec["prediction"]["candidate_event_blocks"])
    m = match_intervals(gt, pred)
    score = m["recall"] if m["recall"] is not None else 0.0
    return {"key": "boundary_recall_interval", "score": score,
            "comment": f"tp={m['tp']} fp={m['fp']} fn={m['fn']}"}


# ---- DIAGNOSTICS (reported, not the headline) -----------------------------------------

def agent_is_winner(run, example) -> dict[str, Any]:
    """3-way winner (agent beats BOTH naive and full_history_prophet). Explains cases where the
    agent beats naive but plain Prophet is already strong."""
    rec = _rec(run, example)
    return {"key": "agent_is_winner", "score": 1 if rec.get("outcome", {}).get("agent_is_winner") else 0}


def chose_authored_family(run, example) -> dict[str, Any]:
    """Did the agent pick the AUTHORED expected family? CAVEAT (Topic-2): the authored intent can
    differ from the family that actually wins the gate (a clean step is best fixed by the ramp
    tool), so a 0 here is NOT necessarily an agent error. Diagnostic only — never the headline."""
    rec = _rec(run, example)
    chosen = rec.get("prediction", {}).get("chosen_tool")
    expected = rec.get("ground_truth", {}).get("expected_intervention_family")
    return {"key": "chose_authored_family", "score": 1 if chosen == expected else 0,
            "comment": f"chosen={chosen} authored={expected} (authored-intent; may differ from gate-winner)"}


def agent_minus_naive_mae(run, example) -> dict[str, Any]:
    """Continuous margin (agent.mae - naive.mae); negative = agent better. Magnitude of the win."""
    rec = _rec(run, example)
    return {"key": "agent_minus_naive_mae",
            "score": float(rec.get("outcome", {}).get("agent_minus_naive_mae", 0.0))}


def point_boundary_recall_detector(run, example) -> dict[str, Any]:
    """Point families (step / holiday) only: recall of injected changepoints by the Prophet
    detector within ±N. Labeled a DETECTOR diagnostic — it measures Prophet's grid, NOT the agent
    (Topic-1 blocker). score=None for interval families."""
    rec = _rec(run, example)
    g = rec.get("ground_truth", {})
    if g.get("family_channel") != "point":
        return {"key": "point_boundary_recall_detector", "score": None, "value": "n/a_interval_family"}
    m = match_points(g.get("ground_truth_events", []), rec["prediction"]["detected_changepoints"])
    score = m["recall"] if m["recall"] is not None else 0.0
    return {"key": "point_boundary_recall_detector", "score": score,
            "comment": f"DETECTOR (not agent): tp={m['tp']} fp={m['fp']} fn={m['fn']} N={m['tolerance']}"}


def failure_mode_label(run, example) -> dict[str, Any]:
    """Topic-4 diagnosis as a categorical LangSmith result: the primary failure-mode label for this
    case (or 'clean_success'). Surfaces *why* a case failed, not just that it did. score=None
    (categorical); the label rides in ``value`` so it's filterable in the UI."""
    from llm_eval.failure_modes import classify_record  # noqa: PLC0415
    rec = _rec(run, example)
    row = classify_record(rec)
    labels = row["failure_mode_labels"] or ["unlabeled"]
    # primary = first non-success label, else clean_success
    primary = next((l for l in labels if l != "clean_success"), labels[0])
    return {"key": "failure_mode", "score": None, "value": primary,
            "comment": f"labels={labels} capability_gap={row['is_capability_gap']} "
                       f"behavioral={row['is_behavioral_failure']}"}


ALL_EVALUATORS = [
    beat_naive,                       # headline
    boundary_recall_interval,         # headline (interval families)
    agent_is_winner,                  # diagnostic
    chose_authored_family,            # diagnostic (caveated)
    agent_minus_naive_mae,            # diagnostic
    point_boundary_recall_detector,   # diagnostic (detector, not agent)
    failure_mode_label,               # Topic-4 diagnosis (categorical)
]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the headline locally from golden records (the source of truth for the printed
    number; the LangSmith UI per-key means should match for the binary keys).

    - beat_naive_rate: mean of the 2-way beat_naive over all records.
    - interval_recall_micro: sum(tp)/(sum(tp)+sum(fn)) over interval-family records (micro-avg —
      weights by ground-truth interval count; the UI column is a per-case macro mean, captioned).
    """
    n = len(records)
    beat = sum(1 for r in records if r["outcome"]["beat_naive"])
    winner = sum(1 for r in records if r["outcome"]["agent_is_winner"])
    authored = sum(1 for r in records if r["prediction"]["chosen_tool"]
                   == r["ground_truth"]["expected_intervention_family"])
    tp_sum = fn_sum = 0
    interval_n = 0
    for r in records:
        g = r["ground_truth"]
        if g["family_channel"] != "interval":
            continue
        interval_n += 1
        family = g["expected_intervention_family"]
        pred = (r["prediction"]["candidate_drift_intervals"] if family == "full_history_ramp_regressor"
                else r["prediction"]["candidate_event_blocks"])
        m = match_intervals(g["ground_truth_events"], pred)
        tp_sum += m["tp"]
        fn_sum += m["fn"]
    interval_recall = (tp_sum / (tp_sum + fn_sum)) if (tp_sum + fn_sum) > 0 else None
    return {
        "n": n,
        "beat_naive_rate": beat / n if n else None,
        "beat_naive_count": f"{beat}/{n}",
        "agent_is_winner_count": f"{winner}/{n}",
        "chose_authored_family_count": f"{authored}/{n}",
        "interval_recall_micro": interval_recall,
        "interval_family_n": interval_n,
    }

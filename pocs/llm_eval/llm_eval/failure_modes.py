"""Topic 4 — forecasting failure-mode taxonomy + a deterministic classifier over golden records.

The MVP scores each case (pass/fail per evaluator); this module DIAGNOSES *why* a case failed by
assigning named failure modes. It preserves the crucial D8 distinction:

  - CAPABILITY GAP  : the agent correctly fell back / no tool can win (high error, NOT an agent bug)
  - BEHAVIORAL FAIL : the agent did something wrong it could have gotten right

Each mode is a pure predicate over one golden record (no LLM). The taxonomy was derived by coding
the real traces; counts + per-case labels are produced by ``classify_corpus``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from llm_eval.golden import match_intervals

# A failure mode: name, one-line definition, class (capability|behavioral|none), predicate.
Mode = tuple[str, str, str, Callable[[dict], bool]]


def _interval_recall(rec: dict) -> float | None:
    g = rec["ground_truth"]
    if g.get("family_channel") != "interval":
        return None
    family = g["expected_intervention_family"]
    pred = (rec["prediction"]["candidate_drift_intervals"] if family == "full_history_ramp_regressor"
            else rec["prediction"]["candidate_event_blocks"])
    m = match_intervals(g.get("ground_truth_events", []), pred)
    return m["recall"]


def _is_unsolvable(rec: dict) -> bool:
    return rec["ground_truth"].get("expected_intervention_family") == "fallback"


def _beat(rec: dict) -> bool:
    return bool(rec["outcome"]["beat_naive"])


def _chose_gate_winner(rec: dict) -> bool:
    """Did the agent pick the family the gate proved wins? (For solvable cases the expected_family
    IS the gate winner.)"""
    return rec["prediction"]["chosen_tool"] == rec["ground_truth"].get("expected_intervention_family")


# ---- the taxonomy (derived from coding the traces) ----------------------------------------------

def _m_capability_gap(rec: dict) -> bool:
    # Unsolvable case where the agent did NOT beat naive — correct/forgivable; the toolset is the limit.
    return _is_unsolvable(rec) and not _beat(rec)


def _m_spurious_win_on_unsolvable(rec: dict) -> bool:
    # Unsolvable per the gate, yet the agent beat naive on test — noteworthy (model variance / the
    # gate's validation verdict didn't hold on test). Not a failure, but flagged.
    return _is_unsolvable(rec) and _beat(rec)


def _m_accepted_worse_than_naive(rec: dict) -> bool:
    # SOLVABLE case the agent failed to beat naive on test — a behavioral miss (a winning tool existed).
    return (not _is_unsolvable(rec)) and not _beat(rec)


def _m_wrong_family_but_won(rec: dict) -> bool:
    # Beat naive but with a tool other than the gate-winning family — acceptable outcome, suboptimal
    # diagnosis (behavioral, mild).
    return (not _is_unsolvable(rec)) and _beat(rec) and not _chose_gate_winner(rec)


def _m_missed_boundary_structure(rec: dict) -> bool:
    # Interval-family case where the diagnostic surfaced <50% of the injected structure (recall<0.5):
    # a PIPELINE-side blindness (the detector/diagnostics hid the structure), distinct from the agent.
    r = _interval_recall(rec)
    return r is not None and r < 0.5


def _m_clean_success(rec: dict) -> bool:
    # Solvable, beat naive, chose the gate-winning family — the good case.
    return (not _is_unsolvable(rec)) and _beat(rec) and _chose_gate_winner(rec)


TAXONOMY: list[Mode] = [
    ("clean_success", "solvable; beat naive with the gate-winning family", "none", _m_clean_success),
    ("capability_gap", "unsolvable; agent correctly did NOT beat naive (toolset limit, not a bug)", "capability", _m_capability_gap),
    ("spurious_win_on_unsolvable", "gate-unsolvable yet agent beat naive on test (model variance)", "none", _m_spurious_win_on_unsolvable),
    ("accepted_worse_than_naive", "solvable but agent failed to beat naive (a winning tool existed)", "behavioral", _m_accepted_worse_than_naive),
    ("wrong_family_but_won", "beat naive but not via the gate-winning family (suboptimal diagnosis)", "behavioral", _m_wrong_family_but_won),
    ("missed_boundary_structure", "interval recall <0.5: diagnostics hid the injected structure", "pipeline", _m_missed_boundary_structure),
]


def classify_record(rec: dict) -> dict[str, Any]:
    """Assign all applicable failure-mode labels to one record (a case may carry several, e.g. a
    behavioral miss AND a missed-boundary). Also flags the capability vs behavioral class."""
    labels = [name for name, _desc, _cls, pred in TAXONOMY if pred(rec)]
    classes = {cls for name, _desc, cls, pred in TAXONOMY if pred(rec) and cls != "none"}
    return {
        "scenario_id": rec["scenario_id"],
        "lever": rec["ground_truth"].get("intended_failure_lever"),
        "expected_family": rec["ground_truth"].get("expected_intervention_family"),
        "chosen_tool": rec["prediction"]["chosen_tool"],
        "beat_naive": _beat(rec),
        "failure_mode_labels": labels,
        "is_capability_gap": "capability" in classes,
        "is_behavioral_failure": "behavioral" in classes,
        "is_pipeline_blindness": "pipeline" in classes,
    }


def classify_corpus(records: list[dict]) -> dict[str, Any]:
    """Label every record + produce taxonomy counts and a per-lever cross-tab."""
    labeled = [classify_record(r) for r in records]
    mode_counts = Counter()
    for row in labeled:
        for m in row["failure_mode_labels"]:
            mode_counts[m] += 1
    lever_x_class = Counter()
    for row in labeled:
        lever = row["lever"] or "n/a"
        if row["is_behavioral_failure"]:
            lever_x_class[(lever, "behavioral")] += 1
        if row["is_capability_gap"]:
            lever_x_class[(lever, "capability")] += 1
        if row["is_pipeline_blindness"]:
            lever_x_class[(lever, "pipeline")] += 1
    return {
        "n": len(records),
        "mode_counts": dict(mode_counts),
        "behavioral_failures": sum(1 for r in labeled if r["is_behavioral_failure"]),
        "capability_gaps": sum(1 for r in labeled if r["is_capability_gap"]),
        "pipeline_blindness": sum(1 for r in labeled if r["is_pipeline_blindness"]),
        "lever_x_class": {f"{k[0]}::{k[1]}": v for k, v in lever_x_class.items()},
        "labeled": labeled,
    }

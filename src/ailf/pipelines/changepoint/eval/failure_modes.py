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

from ailf.core.eval.matching import match_intervals

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


def _m_no_proposal_beat_naive(rec: dict) -> bool:
    # SOLVABLE case (a tool CAN beat naive) where the agent did NOT find a beating tool in its
    # iterations. NOTE: nothing was "accepted" — final_case is best_proposal_no_beat, and the
    # evaluation layer still falls back to the best baseline (winner = min test-MAE over the 3
    # methods), so the *forecast is safe*. This is an AGENT-SEARCH shortfall (it left value on the
    # table), not a system failure and not a "failed to fall back". Borderline cases may actually be
    # capability gaps if the gate's solvable verdict is unstable.
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


# --- crash modes (the agent run did not complete; rec carries a crash_info block) ----------------
# These are gated ONLY on rec["crash_info"], so they are False on every normal (completed) record
# and the 6 outcome-based modes above stay untouched. Conversely, a crash record has no real
# outcome, so the outcome-based modes are suppressed for it (see _is_crash guard in classify_record).

def _crash(rec: dict) -> dict:
    return rec.get("crash_info") or {}


def _m_looped_on_blocked_tool(rec: dict) -> bool:
    # Agent re-proposed a precondition-rejected tool >=2x until iterations ran out (BUG#3 precursor;
    # can also occur without a crash). Recovered from events.jsonl proposals.
    return bool(_crash(rec).get("repeated_blocked_tool"))


def _m_crashed_at_final_eval(rec: dict) -> bool:
    # BUG#3: final_evaluation re-invoked an unvalidated (blocked) proposal -> ToolBoundsError escaped.
    return _crash(rec).get("crash_stage") == "final_eval"


def _m_crashed_indexerror(rec: dict) -> bool:
    # BUG#1: ramp drift-interval end index out of the validation frame -> IndexError escaped.
    return _crash(rec).get("exception_type") == "IndexError"


TAXONOMY: list[Mode] = [
    ("clean_success", "solvable; beat naive with the gate-winning family", "none", _m_clean_success),
    ("capability_gap", "unsolvable; agent correctly did NOT beat naive (toolset limit, not a bug)", "capability", _m_capability_gap),
    ("spurious_win_on_unsolvable", "gate-unsolvable yet agent beat naive on test (model variance)", "none", _m_spurious_win_on_unsolvable),
    ("no_proposal_beat_naive", "solvable, but the agent's proposals never beat naive (agent-search shortfall; system still falls back to the best baseline — forecast is safe)", "behavioral", _m_no_proposal_beat_naive),
    ("wrong_family_but_won", "beat naive but not via the gate-winning family (suboptimal diagnosis)", "behavioral", _m_wrong_family_but_won),
    ("missed_boundary_structure", "interval recall <0.5: diagnostics hid the injected structure", "pipeline", _m_missed_boundary_structure),
    # crash modes (Topic-4, bugs #1/#3 captured as failure modes):
    ("looped_on_blocked_tool", "agent re-proposed a precondition-rejected tool >=2x until iterations ran out", "behavioral", _m_looped_on_blocked_tool),
    ("crashed_at_final_eval", "final_evaluation re-invoked a blocked proposal; ToolBoundsError escaped the run", "behavioral", _m_crashed_at_final_eval),
    ("crashed_indexerror", "ramp interval end out of the validation frame; IndexError escaped validation_node", "pipeline", _m_crashed_indexerror),
]

# Modes that should NOT fire on a crash record (they read a real outcome the crashed run never produced).
_OUTCOME_MODES = {"clean_success", "capability_gap", "spurious_win_on_unsolvable",
                  "no_proposal_beat_naive", "wrong_family_but_won", "missed_boundary_structure"}


def classify_record(rec: dict) -> dict[str, Any]:
    """Assign all applicable failure-mode labels to one record (a case may carry several, e.g. a
    behavioral miss AND a missed-boundary). Also flags the capability vs behavioral class.

    A CRASHED run (rec carries ``crash_info``) never produced a real outcome, so the six
    outcome-based modes are suppressed for it — only the crash modes apply."""
    is_crash = bool(rec.get("crash_info"))
    active = [(n, d, c, p) for n, d, c, p in TAXONOMY if not (is_crash and n in _OUTCOME_MODES)]
    labels = [name for name, _desc, _cls, pred in active if pred(rec)]
    classes = {cls for name, _desc, cls, pred in active if pred(rec) and cls != "none"}
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

"""Stage identifiers + lifecycle status (FR-026/FR-027, contracts/event_contract.md).

The 11 stage ids in causal order. Every run step emits — including the deterministic prelude
(changepoint detection + both baseline fits), not only the agent-graph stages (clarification 8).
"""

from __future__ import annotations

from enum import Enum


class StageId(str, Enum):
    CONFIG_RESOLVED = "config_resolved"
    SPLIT_BUILT = "split_built"
    CHANGEPOINT_DETECTION = "changepoint_detection"
    BASELINE_FULL_HISTORY_PROPHET = "baseline_full_history_prophet"
    BASELINE_NAIVE_WORKFLOW = "baseline_naive_workflow"
    DIAGNOSTICS_COMPUTED = "diagnostics_computed"
    VISUAL_INSPECTION = "visual_inspection"  # only when visual_analysis_enabled
    DECISION_ITERATION = "decision_iteration"
    VALIDATION_OUTCOME = "validation_outcome"
    FINAL_EVALUATION = "final_evaluation"
    RUN_COMPLETE = "run_complete"


# Canonical causal order (for stream-ordering assertions; iteration stages repeat).
CAUSAL_ORDER = [s.value for s in StageId]


class StageStatus(str, Enum):
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"

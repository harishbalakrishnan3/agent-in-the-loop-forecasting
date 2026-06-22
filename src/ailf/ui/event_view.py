"""Map a serialized StageEvent dict to a renderable view-model (data-model §2, FR-019).

PURE module. Input is ``StageEvent.to_dict()`` (plain dict: run_id, seq, ts, stage, status,
concurrency_group, payload, error). Output is an ``EventViewModel`` the Streamlit shell renders as
an expandable entry. Handles offloaded ($ref) payloads (FR-021) and error events (FR-020), and never
surfaces hidden-test data from a pre-final stage (FR-022).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Stages whose payloads are allowed to carry test metrics. Any other stage is "pre-final" and the
# view-model must not expose a test_metrics* key from it (defence-in-depth on top of the backend
# leakage guard — FR-022).
_FINAL_STAGES = {"final_evaluation", "run_complete"}

# Friendly, neutral titles (no internal pipeline jargon leaked to the consumer — FR-002).
_STAGE_TITLES = {
    "config_resolved": "Configuration resolved",
    "split_built": "Data split prepared",
    "changepoint_detection": "Structural changes detected",
    "baseline_full_history_prophet": "Baseline: full-history forecast",
    "baseline_naive_workflow": "Baseline: naive forecast",
    "diagnostics_computed": "Diagnostics computed",
    "visual_inspection": "Agent visual inspection",
    "decision_iteration": "Agent decision",
    "validation_outcome": "Guardrail validation",
    "final_evaluation": "Final evaluation",
    "run_complete": "Run complete",
}


@dataclass(frozen=True)
class EventViewModel:
    seq: int
    stage: str
    status: str
    title: str
    summary: str
    payload: dict[str, Any]
    is_error: bool
    payload_ref: str | None
    concurrency_group: str | None


def _is_ref(payload: Any) -> str | None:
    """Return the sidecar ref path if the payload was offloaded, else None (FR-021)."""
    if isinstance(payload, dict) and isinstance(payload.get("$ref"), str):
        return payload["$ref"]
    return None


def _strip_test_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Defensively drop any test-metric keys from a pre-final payload (FR-022)."""
    return {k: v for k, v in payload.items() if "test_metric" not in k}


def _title(stage: str, status: str, payload: dict[str, Any]) -> str:
    base = _STAGE_TITLES.get(stage, stage.replace("_", " ").title())
    if stage == "decision_iteration" and isinstance(payload, dict):
        i = payload.get("i")
        return f"{base} #{i}" if i is not None else base
    if stage == "validation_outcome" and isinstance(payload, dict):
        i = payload.get("i")
        return f"{base} #{i}" if i is not None else base
    return base


def _summary(stage: str, status: str, payload: dict[str, Any], error: Any) -> str:
    if status == "error":
        if isinstance(error, dict):
            return f"{error.get('type', 'Error')}: {error.get('message', '')}"
        return "Stage error"
    if not isinstance(payload, dict):
        return ""
    if stage == "changepoint_detection":
        return f"{payload.get('n_detected', 0)} structural change(s) detected"
    if stage == "decision_iteration":
        prop = payload.get("proposal", {}) or {}
        tool = prop.get("tool", "?")
        rationale = prop.get("rationale", "")
        return f"chose `{tool}` — {rationale}" if rationale else f"chose `{tool}`"
    if stage == "validation_outcome":
        if payload.get("beat_naive"):
            return "accepted (beat the naive baseline)"
        reason = payload.get("rejected_reason")
        return f"rejected — {reason}" if reason else "rejected (did not beat naive)"
    if stage == "final_evaluation":
        chosen = payload.get("chosen", {}) or {}
        return f"final method: `{chosen.get('tool', '?')}`"
    if stage == "run_complete":
        return f"winner: {payload.get('winner', '?')}"
    if stage == "diagnostics_computed":
        diags = payload.get("diagnostics", {}) or {}
        return f"{len(diags)} diagnostic(s) exposed to the agent"
    return ""


def from_event(event: dict[str, Any]) -> EventViewModel:
    """Build an EventViewModel from a serialized StageEvent dict."""
    stage = event.get("stage", "")
    status = event.get("status", "")
    raw_payload = event.get("payload", {}) or {}
    error = event.get("error")

    payload_ref = _is_ref(raw_payload)
    if payload_ref is not None:
        payload: dict[str, Any] = {"$ref": payload_ref}
    else:
        payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        if stage not in _FINAL_STAGES:
            payload = _strip_test_keys(payload)

    return EventViewModel(
        seq=int(event.get("seq", 0)),
        stage=stage,
        status=status,
        title=_title(stage, status, payload),
        summary=_summary(stage, status, payload, error),
        payload=payload,
        is_error=(status == "error"),
        payload_ref=payload_ref,
        concurrency_group=event.get("concurrency_group"),
    )

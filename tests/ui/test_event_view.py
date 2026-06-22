"""T013 — event-dict → view-model mapping (data-model §2, FR-019/020/021/022)."""

from __future__ import annotations

from ailf.ui.event_view import EventViewModel, from_event


def _evt(stage, status="complete", payload=None, error=None, seq=1, cg=None):
    return {
        "run_id": "r",
        "seq": seq,
        "ts": "2026-06-22T00:00:00Z",
        "stage": stage,
        "status": status,
        "concurrency_group": cg,
        "payload": payload if payload is not None else {},
        "error": error,
    }


def test_basic_mapping_fields():
    vm = from_event(_evt("config_resolved", payload={"a": 1}, seq=3))
    assert isinstance(vm, EventViewModel)
    assert vm.seq == 3 and vm.stage == "config_resolved" and vm.status == "complete"
    assert vm.title and not vm.is_error and vm.payload_ref is None


def test_decision_iteration_title_and_summary():
    vm = from_event(_evt("decision_iteration", payload={
        "i": 2, "proposal": {"tool": "recent_window", "rationale": "recent shift"}}))
    assert "#2" in vm.title
    assert "recent_window" in vm.summary


def test_validation_outcome_accept_reject_summary():
    accepted = from_event(_evt("validation_outcome", payload={"i": 1, "beat_naive": True}))
    assert "accepted" in accepted.summary.lower()
    rejected = from_event(_evt("validation_outcome", payload={
        "i": 2, "beat_naive": False, "rejected_reason": "out of bounds"}))
    assert "rejected" in rejected.summary.lower() and "out of bounds" in rejected.summary


def test_error_event_flagged():
    vm = from_event(_evt("changepoint_detection", status="error", payload={},
                         error={"type": "ValueError", "message": "boom"}))
    assert vm.is_error
    assert "ValueError" in vm.summary and "boom" in vm.summary


def test_oversized_ref_payload_does_not_break():
    vm = from_event(_evt("diagnostics_computed", payload={"$ref": "event_payloads/7.json"}, seq=7))
    assert vm.payload_ref == "event_payloads/7.json"
    assert vm.payload == {"$ref": "event_payloads/7.json"}
    assert not vm.is_error


def test_prefinal_stage_never_surfaces_test_metrics():
    # Defence-in-depth on FR-022: even if a pre-final payload somehow carried a test_metrics key,
    # the view-model must not expose it.
    vm = from_event(_evt("diagnostics_computed", payload={"diagnostics": {}, "test_metrics": {"mae": 1.0}}))
    assert "test_metrics" not in vm.payload
    assert all("test_metric" not in k for k in vm.payload)


def test_final_stage_may_carry_test_metrics():
    vm = from_event(_evt("final_evaluation", payload={
        "test_metrics_by_method": {"agent": {"mae": 1.0}}}))
    assert "test_metrics_by_method" in vm.payload  # allowed at final

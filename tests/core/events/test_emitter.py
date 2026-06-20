"""T069/T071 — emitter (seq, stage ctx mgr, fail-fast, $ref offload) + sinks (JSONL/ListSink)."""

from __future__ import annotations

import json

import pytest

from ailf.core.events.emitter import MAX_INLINE_PAYLOAD_BYTES, EventEmitter, NullEmitter
from ailf.core.events.leakage import LeakageError
from ailf.core.events.sink import FileEventSink, ListSink
from ailf.core.events.stages import StageId, StageStatus


def test_seq_is_monotonic():
    sink = ListSink()
    em = EventEmitter("r", [sink])
    em.emit(StageId.CONFIG_RESOLVED, StageStatus.COMPLETE, {})
    em.emit(StageId.SPLIT_BUILT, StageStatus.COMPLETE, {})
    assert [e.seq for e in sink.events] == [1, 2]
    assert all(e.run_id == "r" for e in sink.events)
    assert all(e.ts for e in sink.events)  # ISO timestamp stamped


def test_stage_ctx_emits_start_then_complete():
    sink = ListSink()
    em = EventEmitter("r", [sink])
    with em.stage(StageId.DIAGNOSTICS_COMPUTED) as payload:
        payload["diagnostics"] = {"x": 1}
    statuses = [(e.stage.value, e.status.value) for e in sink.events]
    assert statuses == [("diagnostics_computed", "start"), ("diagnostics_computed", "complete")]
    assert sink.events[-1].payload == {"diagnostics": {"x": 1}}


def test_stage_ctx_emits_terminal_error_and_reraises():
    sink = ListSink()
    em = EventEmitter("r", [sink])
    with pytest.raises(ValueError, match="boom"):
        with em.stage(StageId.CHANGEPOINT_DETECTION):
            raise ValueError("boom")
    assert sink.events[-1].status == StageStatus.ERROR
    assert sink.events[-1].error["type"] == "ValueError"
    assert sink.events[-1].error["message"] == "boom"


def test_pre_final_leakage_is_blocked():
    em = EventEmitter("r", [ListSink()])
    with pytest.raises(LeakageError):
        em.emit(StageId.DIAGNOSTICS_COMPUTED, StageStatus.COMPLETE, {"test_metrics": {"mae": 1.0}})


def test_final_evaluation_may_carry_test_metrics():
    sink = ListSink()
    em = EventEmitter("r", [sink])
    em.emit(StageId.FINAL_EVALUATION, StageStatus.COMPLETE, {"test_metrics_by_method": {"agent": {"mae": 1.0}}})
    assert sink.events[-1].payload["test_metrics_by_method"]["agent"]["mae"] == 1.0


def test_oversized_payload_offloaded_to_ref(tmp_path):
    sink = ListSink()
    em = EventEmitter("r", [sink], payload_dir=tmp_path / "event_payloads")
    big = {"blob": "x" * (MAX_INLINE_PAYLOAD_BYTES + 10)}
    em.emit(StageId.DIAGNOSTICS_COMPUTED, StageStatus.COMPLETE, big)
    ev = sink.events[-1]
    assert "$ref" in ev.payload
    assert (tmp_path / "event_payloads" / f"{ev.seq}.json").exists()


def test_file_sink_writes_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    em = EventEmitter("r", [FileEventSink(path)])
    em.emit(StageId.CONFIG_RESOLVED, StageStatus.COMPLETE, {"a": 1})
    em.emit(StageId.RUN_COMPLETE, StageStatus.COMPLETE, {"winner": "agent"})
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["stage"] == "config_resolved" and first["seq"] == 1


def test_null_emitter_is_noop():
    em = NullEmitter()
    em.emit(StageId.CONFIG_RESOLVED, StageStatus.COMPLETE, {})
    with em.stage(StageId.SPLIT_BUILT):
        pass  # no error, no record

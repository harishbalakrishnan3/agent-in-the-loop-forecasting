"""T002 — QueueEventSink contract (contracts/event_stream_consumption.md, FR-032).

A QueueEventSink is an EventSink that pushes ``event.to_dict()`` onto a stdlib queue so a UI thread
can drain the typed stream live. It must preserve order and must never raise on a put failure (a
raise would break the emitter's sink fan-out loop).
"""

from __future__ import annotations

import queue

from ailf.core.events.event import StageEvent
from ailf.core.events.sink import EventSink, QueueEventSink
from ailf.core.events.stages import StageId, StageStatus


def _event(seq: int) -> StageEvent:
    return StageEvent(
        run_id="r",
        seq=seq,
        ts="2026-06-22T00:00:00Z",
        stage=StageId.DECISION_ITERATION,
        status=StageStatus.COMPLETE,
        payload={"i": seq},
    )


def test_conforms_to_event_sink_protocol():
    sink = QueueEventSink(queue.Queue())
    assert isinstance(sink, EventSink)  # runtime-checkable Protocol


def test_write_puts_serialized_dict_onto_queue():
    q: queue.Queue = queue.Queue()
    sink = QueueEventSink(q)
    sink.write(_event(1))
    item = q.get_nowait()
    assert isinstance(item, dict)
    assert set(item) == {"run_id", "seq", "ts", "stage", "status", "concurrency_group", "payload", "error"}
    assert item["seq"] == 1 and item["stage"] == "decision_iteration" and item["status"] == "complete"


def test_preserves_order():
    q: queue.Queue = queue.Queue()
    sink = QueueEventSink(q)
    for i in range(1, 6):
        sink.write(_event(i))
    seqs = [q.get_nowait()["seq"] for _ in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


def test_never_raises_on_put_failure():
    class _BoomQueue:
        def put_nowait(self, item):
            raise RuntimeError("full")

        def put(self, item, *a, **k):
            raise RuntimeError("full")

    # Must swallow the failure — a raise here would break EventEmitter.emit()'s fan-out loop.
    QueueEventSink(_BoomQueue()).write(_event(1))

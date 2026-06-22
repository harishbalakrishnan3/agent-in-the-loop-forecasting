"""Event sinks (FR-030, contracts/event_contract.md).

``FileEventSink`` appends one JSON line per event to ``<run_dir>/events.jsonl`` (flush per record,
append-safe under fail-fast). ``ListSink`` is an in-memory sink for tests. ``QueueEventSink`` pushes
serialized events onto a stdlib queue so an in-process consumer (the streamlined UI worker thread)
can drain the typed stream live (feature 006, FR-032).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ailf.core.events.event import StageEvent
from ailf.core.events.leakage import to_json


@runtime_checkable
class EventSink(Protocol):
    def write(self, event: StageEvent) -> None: ...


class ListSink:
    """In-memory sink — records events for assertions."""

    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    def write(self, event: StageEvent) -> None:
        self.events.append(event)


class FileEventSink:
    """Append each event as one JSON line to ``<run_dir>/events.jsonl``."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: StageEvent) -> None:
        with self._path.open("a") as fh:
            fh.write(to_json(event.to_dict()))  # strict serializer — raises on non-JSON
            fh.write("\n")
            fh.flush()


class QueueEventSink:
    """Push ``event.to_dict()`` onto a stdlib queue for live in-process consumption (FR-032).

    Used by the streamlined UI: the pipeline runs on a worker thread with this sink, and the
    Streamlit main thread drains the queue to render events as they occur. ``write`` must never
    raise — a raise would break ``EventEmitter.emit``'s sink fan-out loop and abort the run; a
    failed put is swallowed (the file sink remains the durable record).
    """

    def __init__(self, q: Any) -> None:
        self._q = q

    def write(self, event: StageEvent) -> None:
        try:
            self._q.put_nowait(event.to_dict())
        except Exception:  # noqa: BLE001 — never break the emit fan-out on a queue error
            pass

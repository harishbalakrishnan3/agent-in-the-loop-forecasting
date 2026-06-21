"""Event sinks (FR-030, contracts/event_contract.md).

``FileEventSink`` appends one JSON line per event to ``<run_dir>/events.jsonl`` (flush per record,
append-safe under fail-fast). ``ListSink`` is an in-memory sink for tests. The concrete network
transport is out of scope for this feature; these prove the contract is exercisable without a UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ailf.core.events.event import StageEvent
from ailf.core.events.leakage import to_json


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

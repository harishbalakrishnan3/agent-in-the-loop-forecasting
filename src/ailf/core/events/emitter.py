"""Event emitter (FR-026/FR-028/FR-031/FR-032, contracts/event_contract.md).

``EventEmitter`` owns the run id, a monotonic ``seq`` counter, the active concurrency group, and a
list of sinks. ``stage()`` is a context manager: emits ``start`` on enter and ``complete`` on clean
exit, or a TERMINAL ``error`` event + re-raise on exception (fail-fast). Oversized payloads
(> MAX_INLINE_PAYLOAD_BYTES) are written to ``<run_dir>/event_payloads/<seq>.json`` and referenced
by ``$ref`` rather than inlined. ``NullEmitter`` is a no-op for runs that don't record events.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ailf.core.events.event import StageEvent
from ailf.core.events.leakage import assert_no_leakage, to_json
from ailf.core.events.sink import EventSink
from ailf.core.events.stages import StageId, StageStatus

MAX_INLINE_PAYLOAD_BYTES = 32_768


class NullEmitter:
    """No-op emitter (runs that don't record events)."""

    def emit(self, *args: Any, **kwargs: Any) -> None:
        pass

    @contextmanager
    def stage(self, *args: Any, **kwargs: Any) -> Iterator[None]:
        yield


class EventEmitter:
    def __init__(self, run_id: str, sinks: list[EventSink], *, payload_dir: Path | None = None) -> None:
        self._run_id = run_id
        self._sinks = sinks
        self._seq = 0
        self._concurrency_group: str | None = None
        self._payload_dir = payload_dir

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _maybe_offload(self, seq: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Offload an oversized payload to a sidecar file, returning a $ref (FR-031)."""
        if self._payload_dir is None:
            return payload
        try:
            size = len(to_json(payload))
        except TypeError:
            raise
        if size <= MAX_INLINE_PAYLOAD_BYTES:
            return payload
        self._payload_dir.mkdir(parents=True, exist_ok=True)
        sidecar = self._payload_dir / f"{seq}.json"
        sidecar.write_text(to_json(payload, indent=2))
        return {"$ref": f"event_payloads/{seq}.json"}

    def emit(
        self,
        stage: StageId,
        status: StageStatus,
        payload: dict[str, Any] | None = None,
        *,
        concurrency_group: str | None = None,
        error: dict[str, str] | None = None,
        check_leakage: bool = True,
    ) -> StageEvent:
        payload = payload or {}
        # Pre-final-evaluation events must not carry hidden-test/audit fields (FR-029).
        if check_leakage and stage not in (StageId.FINAL_EVALUATION, StageId.RUN_COMPLETE):
            assert_no_leakage(payload)
        seq = self._next_seq()
        payload = self._maybe_offload(seq, payload)
        event = StageEvent(
            run_id=self._run_id,
            seq=seq,
            ts=self._now(),
            stage=stage,
            status=status,
            payload=payload,
            concurrency_group=concurrency_group if concurrency_group is not None else self._concurrency_group,
            error=error,
        )
        for sink in self._sinks:
            sink.write(event)
        return event

    @contextmanager
    def stage(
        self,
        stage: StageId,
        *,
        concurrency_group: str | None = None,
        complete_payload: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Emit start on enter; complete on clean exit OR a terminal error + re-raise (FR-032).

        Yields a mutable dict the caller can fill; its contents become the ``complete`` payload.
        """
        self.emit(stage, StageStatus.START, {}, concurrency_group=concurrency_group)
        payload: dict[str, Any] = dict(complete_payload or {})
        try:
            yield payload
        except Exception as exc:  # noqa: BLE001 — fail-fast: terminal error event then re-raise
            self.emit(
                stage,
                StageStatus.ERROR,
                {},
                concurrency_group=concurrency_group,
                error={"type": type(exc).__name__, "message": str(exc)},
                check_leakage=False,
            )
            raise
        else:
            self.emit(stage, StageStatus.COMPLETE, payload, concurrency_group=concurrency_group)

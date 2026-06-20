"""StageEvent envelope (frozen dataclass, FR-026, contracts/event_contract.md).

Plain serializable — to_dict() output passes the strict ``to_json`` serializer. ``seq`` is a
monotonic per-emitter integer (strict total order); ``ts`` is an ISO-8601 UTC instant stamped at
emit time by the emitter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ailf.core.events.stages import StageId, StageStatus


@dataclass(frozen=True)
class StageEvent:
    run_id: str
    seq: int
    ts: str  # ISO-8601 UTC
    stage: StageId
    status: StageStatus
    payload: dict[str, Any]
    concurrency_group: str | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.ts,
            "stage": self.stage.value,
            "status": self.status.value,
            "concurrency_group": self.concurrency_group,
            "payload": self.payload,
            "error": self.error,
        }

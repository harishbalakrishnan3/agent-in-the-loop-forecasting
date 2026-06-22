"""Worker-thread orchestration for a UI run (contracts/run_invocation.md, event_stream_consumption.md).

Runs ``run_scenario`` on a daemon worker thread with a ``QueueEventSink`` so the Streamlit main
thread can drain the typed event stream live. The worker NEVER calls ``st.*`` or touches
``st.session_state`` — the only cross-thread channels are the queue (events) and a ``RunHandle``
holder (final return dict / exception). Emission stays single-threaded on the worker, so the
emitter's seq counter cannot race (research R1/R2).
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from ailf.core.config.schema import ConfigOverride
from ailf.core.events.sink import QueueEventSink


@dataclass
class RunHandle:
    """Shared state between the worker thread and the main thread."""

    events: "queue.Queue" = field(default_factory=queue.Queue)
    thread: threading.Thread | None = None
    result: dict[str, Any] | None = None
    error: BaseException | None = None

    @property
    def done(self) -> bool:
        return self.thread is not None and not self.thread.is_alive()


def start_run(
    *,
    scenario_id: str,
    override: ConfigOverride | None = None,
    series_df: Any | None = None,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seasonal_period: int = 365,
    n_changepoints_to_detect: int = 3,
    reports_root: Any | None = None,
) -> RunHandle:
    """Spawn a daemon worker running ``run_scenario`` with a live ``QueueEventSink``.

    Returns immediately with a ``RunHandle``; the caller drains ``handle.events`` and, once the
    thread finishes, reads ``handle.result`` / ``handle.error``.
    """
    # Local import: keeps this module importable in environments without the full pipeline deps,
    # and matches the lazy-import discipline used elsewhere for the changepoint pipeline.
    from ailf.pipelines.changepoint.pipeline import run_scenario  # noqa: PLC0415

    handle = RunHandle()
    sink = QueueEventSink(handle.events)

    def _worker() -> None:
        try:
            kwargs: dict[str, Any] = {
                "override": override,
                "reports_root": reports_root,
                "extra_sinks": [sink],
            }
            if series_df is not None:
                kwargs.update(
                    series_df=series_df,
                    train_ratio=train_ratio,
                    val_ratio=val_ratio,
                    test_ratio=test_ratio,
                    seasonal_period=seasonal_period,
                    n_changepoints_to_detect=n_changepoints_to_detect,
                )
            handle.result = run_scenario(scenario_id, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — surface any failure to the UI thread
            handle.error = exc

    handle.thread = threading.Thread(target=_worker, name=f"ailf-run-{scenario_id}", daemon=True)
    handle.thread.start()
    return handle


def drain(handle: RunHandle, *, timeout: float = 0.25) -> list[dict[str, Any]]:
    """Non-blocking-ish drain: return all events currently available (up to a short timeout window).

    Pulls one event with a bounded wait (so the UI stays responsive during quiet periods — the
    long-running/stalled-run case), then greedily drains anything else already queued.
    """
    out: list[dict[str, Any]] = []
    try:
        out.append(handle.events.get(timeout=timeout))
    except queue.Empty:
        return out
    while True:
        try:
            out.append(handle.events.get_nowait())
        except queue.Empty:
            break
    return out

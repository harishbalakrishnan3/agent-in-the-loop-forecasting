# Contract: Event Stream Consumption (live)

How the UI consumes the typed event stream and what the backend guarantees about it. Consumer: `ui/run_controller.py` (drain) + `ui/event_view.py` (render mapping).

## Wire shape (per event)

Each item the UI dequeues is a plain dict = `StageEvent.to_dict()` (`core/events/event.py`):

```jsonc
{
  "run_id": "level_shift_loses_seasonality-1729",
  "seq": 7,                       // monotonic, unique, strictly increasing
  "ts": "2026-06-22T10:15:03.123Z",
  "stage": "decision_iteration",  // string value of StageId
  "status": "complete",           // "start" | "complete" | "error"
  "concurrency_group": null,      // or "visual_diagnostics"
  "payload": { /* stage-specific, see data-model §2 */ },
  "error": null                   // or a message string when status="error"
}
```

## Ordering & liveness guarantees (backend)

- **Monotonic seq**: all events carry a strictly increasing, unique `seq`. The UI renders/sorts by `seq`. (Guaranteed because emission is single-threaded on the driver — research R2.)
- **Causal order**: stages arrive in causal order; the stream ends with `final_evaluation` then `run_complete`. (Asserted by `tests/pipelines/changepoint/test_event_stream.py`.)
- **Live in-graph emission** (this feature): `visual_inspection`, each `decision_iteration`, each `validation_outcome`, and `final_evaluation` are emitted **as their node completes** (via `.stream()`), not in a post-invoke burst. So the agent's iterations appear while the run is still in progress (FR-018/030).
- **No double emission**: the previous post-invoke reconstruction is removed; each stage emits exactly once (FR-031).
- **No leakage pre-final**: `assert_no_leakage` keeps test metrics out of all pre-final payloads; `test_metrics_by_method` appears only in `final_evaluation` and `run_complete` (FR-022). The UI MUST NOT attempt to read/show test results before then.

## Stage taxonomy the UI must handle (11 stages)

`config_resolved, split_built, changepoint_detection, baseline_full_history_prophet, baseline_naive_workflow, diagnostics_computed, visual_inspection (only when visual on), decision_iteration (×N), validation_outcome (×N), final_evaluation, run_complete`.

- The UI renders **any** event generically from `(stage, status, payload)` — it does not hardcode stage-specific layout beyond friendly titles/summaries (data-model §2). Unknown/new stages still render via the generic path.
- `visual_inspection` is **absent** when `visual_analysis_enabled=false` — the UI must not assume it appears.

## Oversized payloads

When the backend offloads a large payload, the event's `payload` is `{"$ref": "event_payloads/<seq>.json"}` (`emitter.py`). The UI MUST detect the `$ref` and render a reference note (and may lazily load the sidecar file at completion) rather than break the stream (FR-021).

## Drain loop (consumer behavior)

```text
loop:
  event = queue.get(timeout=…)            # main thread
  vm = event_view.from_event(event)
  render/append vm in seq order           # st.* only on main thread
  if vm.is_error: show error, stop draining cleanly
  if event.stage == "run_complete": break
also stop if worker thread is dead AND queue is empty (defensive)
```

- The UI uses a bounded `get(timeout=…)` and a periodic rerun so the page updates as events arrive; it never blocks the main thread indefinitely.
- Backpressure: `queue.Queue` is unbounded enough for one run's event count (tens–hundreds); `QueueEventSink.write` must be non-blocking and must not raise (a raise would break the emit fan-out loop — see risk in research R1; the sink swallows/ignores put failures defensively).

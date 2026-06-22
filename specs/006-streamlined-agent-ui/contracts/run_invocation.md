# Contract: Run Invocation (UI → backend)

How the UI starts a run and what the backend guarantees in return. This is the seam between `ui/run_controller.py` and `ailf.pipelines.changepoint.pipeline.run_scenario`.

## Backend signature changes (this feature)

```python
# core/events/sink.py  — NEW
class QueueEventSink:
    def __init__(self, q: "queue.Queue") -> None: ...
    def write(self, event: StageEvent) -> None:   # Protocol-conformant
        self._q.put(event.to_dict())              # plain dict crosses the thread boundary

# changepoint/pipeline.py  — run_scenario AMENDED
def run_scenario(
    scenario_id: str,
    *,
    override: ConfigOverride | None = None,
    model_wrappers: tuple | None = None,
    reports_root: Path | None = None,
    emit_events: bool = True,
    series_df: "pd.DataFrame | None" = None,
    train_ratio: float = 0.8,          # CHANGED: was split_ratio (single float)
    val_ratio: float = 0.1,            # NEW: explicit (sum with test ≈ 1)
    test_ratio: float = 0.1,           # NEW
    seasonal_period: int = 365,
    n_changepoints_to_detect: int = 3,
    extra_sinks: "list[EventSink] | None" = None,   # NEW: UI passes QueueEventSink
) -> dict: ...
```

- `extra_sinks` are appended to `[FileEventSink(...)]` when `emit_events=True` (research R1). Backward compatible: default `None` ⇒ behaviour unchanged for existing callers/tests.
- Custom-CSV split now honors three fractions via the extended `_series_split_from_df` (research R5). Scenario runs ignore the ratio args (they use metadata/golden split).
- Return dict gains `csv_path` (absolute path to `forecast_comparison.csv`) alongside the existing `{**metrics_report, "run_id", "final_eval"}` (research R6).

## Invocation — scenario run

```python
override = ConfigOverride.from_dict(config_builder.to_override_dict(ui_cfg))
result = run_scenario(scenario_id, override=override, extra_sinks=[QueueEventSink(q)])
```

## Invocation — custom CSV run

```python
override = ConfigOverride.from_dict(config_builder.to_override_dict(ui_cfg))  # no split block
result = run_scenario(
    scenario_id="custom",                      # label only
    override=override,
    series_df=ui_cfg.custom_df,                # columns exactly ds, y
    train_ratio=ui_cfg.train_ratio,
    val_ratio=ui_cfg.val_ratio,
    test_ratio=ui_cfg.test_ratio,
    seasonal_period=ui_cfg.seasonal_period,
    n_changepoints_to_detect=ui_cfg.n_changepoints_to_detect,
    extra_sinks=[QueueEventSink(q)],
)
```

## Override dict shape (`to_override_dict`)

```jsonc
{
  "models": {
    "visual_model_id":   "us.anthropic.claude-opus-4-8",
    "decision_model_id": "us.anthropic.claude-sonnet-4-6"
  },
  "visual_analysis_enabled": true,
  "diagnostics": { /* EXACTLY the 13 DiagnosticsBundle keys -> bool */ },
  "agent_tools": {
    "recent_window": true,
    "full_history_step_regressor": true,
    "full_history_ramp_regressor": true,
    "full_history_clean_event": true,
    "full_history_prophet_tuned_holidays": true,
    "full_history_default": true            /* fallback: ALWAYS true, never user-toggled */
  },
  "seed": 1729
}
```

Rules (enforced by `resolve_config`, must not be violated by the UI):
- `diagnostics` keys MUST equal `DiagnosticsBundle.field_names()` exactly; `agent_tools` keys MUST equal the 5 structural names + `full_history_default` exactly (lockstep). The UI builds these from the imported canonical lists.
- `full_history_default` MUST be `true`.
- `aws_region` need not be sent (defaults from `config.yaml`); send it only if overriding.

## Threading & lifecycle guarantees

- The UI runs `run_scenario` on a **daemon worker thread**. The worker MUST NOT call any `st.*` API or write `st.session_state`.
- The **only** cross-thread channels are: the `queue.Queue` (events, drained live by the main thread) and a result holder (final return dict / exception, read after the worker finishes).
- All event emission happens on the worker (pipeline driver) thread; `seq` stays monotonic (the counter is single-threaded — never emit from the UI thread).
- Completion is signaled by the `run_complete` event (and the worker terminating). On worker exception, the holder carries the error; the UI surfaces it (FR-020).

## Failure modes

| Condition | Backend behavior | UI behavior |
|---|---|---|
| Neither provider configured | `resolve_config` raises `ConfigError` (research R4) | Caught before/at run start; clear message; no broken run (FR-029). |
| Custom CSV missing `ds`/`y` | `load`/coerce raises | UI pre-validates and blocks Start (FR-010); backstop catch surfaces error. |
| Split fractions ≠ 1 | n/a (UI blocks first) | Start disabled / inputs flagged (FR-009). |
| Mid-run stage error | stage emits `status="error"`, raises | Error event rendered; stream stops cleanly; prior events stay (FR-020). |

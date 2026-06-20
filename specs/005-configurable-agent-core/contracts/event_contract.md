# Contract: stage events — envelope, stages, per-stage payloads, sink

Owner: `core/events/{event,stages,emitter,sink,payloads,leakage}.py`. Covers FR-026..032, SC-010,
US5/US6. The concrete network transport is **out of scope**; this contract + a default file sink land now.

## Envelope (`StageEvent`)

```
{ run_id: str,
  seq: int,                       # monotonic per-emitter; strict total order across the whole run
  ts: str,                        # ISO-8601 UTC; stamped at emit via datetime.now(timezone.utc).isoformat()
  stage: StageId,                 # closed enum below
  status: "start"|"complete"|"error",
  concurrency_group: str | null,  # "visual_diagnostics" for the fan-out pair; null otherwise
  payload: dict,                  # per-stage shape below; or {"$ref": "event_payloads/<seq>.json"} if > 32 KB
  error: { type: str, message: str } | null }   # set only when status="error"
```

Serialized to `<run_dir>/events.jsonl` (one `to_dict()` per line, flushed per record) by
`FileEventSink`; tests use an in-memory `ListSink`. All payloads pass the strict `to_json` serializer
(raises on numpy / `pd.Timestamp` / handles).

## `StageId` (closed enum, causal order)

`config_resolved` → `split_built` → `changepoint_detection` → `baseline_full_history_prophet` →
`baseline_naive_workflow` → `diagnostics_computed` → `visual_inspection` (only when enabled) →
`decision_iteration` (×N) → `validation_outcome` (×N) → `final_evaluation` → `run_complete`.

## Emission model (resolves the seq-race — FR-028)

- The **deterministic prelude** (`config_resolved` … `diagnostics_computed`) is emitted **sequentially
  by the single-threaded driver** (`pipeline.py`) **before** graph invocation.
- Inside the graph, the only concurrency is the `visual ∥ diagnostics` fan-out (visual-on only). Their
  `start`/`complete` are emitted **from the single-threaded driver**, not inside node bodies, so the
  integer seq counter cannot race. Both carry `concurrency_group="visual_diagnostics"`.
- Visual-off ⇒ linear graph ⇒ no `visual_inspection` events, no concurrency group.
- `EventEmitter.stage(stage, payload_fn)` context manager: emit `start` on enter; on clean exit emit
  `complete` with the built payload; on exception emit a **terminal `error`** event and re-raise
  (fail-fast, FR-032).

## Leakage (FR-029) — allowlist by construction

Every **pre-final** payload is sourced from agent-facing views: filtered `to_agent_dict`, `summary_dict`
with `test_metrics` stripped. `val_metrics` never appear in `validation_outcome`. `test_metrics` first
appear only in `final_evaluation`/`run_complete`. `audit_only` fields never enter core. `assert_no_leakage(payload)`
is asserted in tests for every pre-final stage.

## Oversized payloads (FR-031)

`MAX_INLINE_PAYLOAD_BYTES = 32_768`. If a payload's serialized size exceeds it (or it would carry a
binary artifact), it is written to `<run_dir>/event_payloads/<seq>.json` and the event payload becomes
`{"$ref": "event_payloads/<seq>.json"}`. A test asserts no pre-final event inlines a forecast array.

## Per-stage payload shapes (the documented contract — FR-027/SC-010; each backed by a schema test)

| `stage` | `complete` payload |
|---------|--------------------|
| `config_resolved` | `{ effective_config: <EffectiveConfig.to_dict>, hidden_diagnostics: [str], removed_tools: [str], visual_analysis_enabled: bool }` |
| `split_built` | `{ provenance: <SplitProvenance.to_dict> }` (source, units, resolved rows, derived train_end/fit_end/forecast_origin_index) |
| `changepoint_detection` | `{ n_requested: int, detected: [{index:int, ds:str, trend_delta:float}] }` |
| `baseline_full_history_prophet` | `{ val_metrics: {mae,rmse,wape,smape} }` (no test metrics) |
| `baseline_naive_workflow` | `{ candidates: [{label, val_metrics, window_start}], selected_window_start: int }` (val only) |
| `diagnostics_computed` | `{ diagnostics: <FILTERED to_agent_dict>, hidden: [str] }` (agent-facing filtered view) |
| `visual_inspection` | `{ observations:[str], pattern_summary:str, hypotheses:[str], uncertainties:[str], image_ref: "agent_context.png" }` |
| `decision_iteration` | `{ i:int, proposal:{tool, params, rationale, action_signature, expected_effect}, menu:[tool names advertised] }` |
| `validation_outcome` | `{ i:int, action_signature:str, beat_naive:bool, rejected_reason: str\|null }` — **no `val_metrics`** |
| `final_evaluation` | `{ final_case: "accepted_beat_naive"\|"best_proposal_no_beat", chosen:{tool,params}, test_metrics_by_method:{full_history_prophet, naive_workflow, agent} }` — first appearance of test metrics |
| `run_complete` | `{ winner:str, artifacts:[relative paths], run_dir:str }` |

`start` events carry an empty or minimal payload (`{}` or a stage label). Any stage may emit `error`
with `{type, message}` (terminal, fail-fast).

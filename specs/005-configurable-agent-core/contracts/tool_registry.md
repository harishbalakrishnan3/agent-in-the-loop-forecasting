# Contract: MCP-ready tool registry + deterministic gate

Owner: `core/agent/registry.py` (generic) + `core/backtest/gate.py` (generic) +
`pipelines/changepoint/interventions.py` (the 5 concrete tools + fallback). Covers
FR-016, FR-022..025, FR-034, SC-005, SC-011, Principle IV.

## Proposer / guardrail separation (unchanged from POC)

The agent proposes **one** `Proposal` (tool name + bounded params + rationale) via structured output.
A **separate** deterministic gate scores it on the validation holdout. The agent **never** sees the
numeric validation score — only `accepted` or that an `action_signature` was rejected. No free-form
model configuration; no executable payload.

## Registry types (`core/agent/registry.py`) — plain data + non-serialized callables

- `ToolParamSchema(name, kind, allowed, default, required)` — the **single source of bounds**. The
  POC grids become `allowed` data: `CPS_GRID=[0.01,0.05,0.1,0.5]`, `SPS_GRID=[1.0,10.0]`,
  `HPS_GRID=[1.0,10.0]`, `MODE_GRID=["additive","multiplicative"]`, `RANGE_GRID=[0.8,0.9]`.
- `ToolSpec(name, description, params, enabled, structural, invoker, precondition)` — `invoker` and
  `precondition` are callables held registry-side and **never serialized**; `to_dict()` emits only
  `{name, description, params[], enabled, structural}` (the agent menu view).
- `ToolRegistry`:
  - `register(spec)` — pipeline registers each tool.
  - `for_run(enabled_names: set[str]) -> ToolRegistry` — projects a registry whose `menu()` and
    `allowed_names()` both reflect only enabled tools (FR-014: disabled ⇒ absent from menu AND gate).
  - `menu() -> list[dict]` — the enabled `ToolSpec.to_dict()`s used to fill the prompt `{{tool_menu}}`.
  - `allowed_names() -> set[str]`.
  - `validate_params(tool, params) -> dict` — checks each param against its `ToolParamSchema.allowed`;
    raises `ToolBoundsError` on violation/unknown.
  - `invoke(tool, ToolContext, params) -> ToolResult` — resolves the spec, runs `precondition`, calls
    `invoker`. **Only the gate calls this.**
- `Proposal(tool, params, rationale)`; `action_signature` property =
  `f"{tool}|{json.dumps(params, sort_keys=True)}"` (POC-identical, so rejected-repeat detection is
  unchanged).

## Crossing types (the MCP-relocatable boundary — SC-011)

```
ToolContext = {
  "training": [ {"ds": "<ISO-8601>", "y": <float>}, ... ],   # rows [0, fit_end)
  "future":   [ "<ISO-8601>", ... ],                          # horizon timestamps
  "diagnostics": { ... full bundle ... }                      # full to_agent_dict (tools see all)
}
ToolResult = { "yhat": [<float>, ...], "resolved_params": { ... } }
```

No `SeriesSplit`, `DiagnosticsBundle` object, or live Prophet/model handle crosses. An out-of-process
(MCP-served) tool with the same `(ToolContext, params) -> ToolResult` contract is a drop-in replacement
— the SC-011 conformance test swaps a real tool for a stub and asserts the agent loop, gate, prompts,
trace, and event format are unchanged.

## The five structural tools (pipeline `register_changepoint_registry()`)

| Tool | Params (allowed) | Precondition |
|------|------------------|--------------|
| `recent_window` | `window_start ∈ {latest, primary}` | a detected changepoint exists |
| `full_history_step_regressor` | `changepoints ∈ {primary, all_detected}` | ≥1 in-range changepoint |
| `full_history_ramp_regressor` | `intervals ∈ {primary, all_candidate}` | (has fallback to cp-span) |
| `full_history_clean_event` | `blocks = all_closed \| list[int]` | ≥1 closed-before-origin block; list items must be closed-before-origin (FR-026a) |
| `full_history_prophet_tuned_holidays` | `changepoint_prior_scale∈CPS_GRID, seasonality_prior_scale∈SPS_GRID, holidays_prior_scale∈HPS_GRID, seasonality_mode∈MODE_GRID, changepoint_range∈RANGE_GRID` | `recurring_event_summary.is_calendar_recurring == true` (FR-031) |

Each `invoker` reconstructs pandas/Prophet from `ToolContext` server-side and returns `yhat`. Each is a
**pure** `(context, params) -> yhat` mapping — **no** in-tool grid sweep, no validation access (the
agent proposes concrete grid points; verified the POC already does single-point fits, so this is
behavior-preserving).

## Fallback (FR-016)

`full_history_default` is registered as **always-enabled, `structural=False`**: fit a default Prophet on
the full training window and predict the horizon (no diagnostics dependency). The config resolver MAY
NOT disable it (an override doing so → `ConfigError`). When all five structural tools are disabled,
`for_run()` yields a menu of just `{full_history_default}`; the trace records the reduction. It is
excluded from the lockstep exact-match (it's not in `TOOL_NAMES`).

## The gate (`core/backtest/gate.py`) — sole scoring authority (Principle IV, FR-025/FR-034)

`evaluate_on_validation(proposal, ...) ` and `evaluate_on_test(proposal, ...)` (test only at final
evaluation). Steps: (1) tool ∈ `allowed_names()`? (2) `validate_params` (bounds); (3) `precondition`;
(4) `invoke` → `yhat` on the validation holdout; (5) MAE; (6) **strictly** beat naive (`mae < naive_mae`,
no ties → accept). The agent observes only `accept` / rejected-signature.

**Failure classification** (FR-032):
- bounds rejection, not-in-allowed-set, precondition failure, not-beating-naive ⇒ **normal in-loop
  flow** (append `rejected_signature`, re-prompt, emit ordinary `validation_outcome` event) — **not** a
  terminal error.
- a genuine `invoke()` exception (e.g. Prophet crash) ⇒ a **stage failure**: terminal error event,
  fail-fast.

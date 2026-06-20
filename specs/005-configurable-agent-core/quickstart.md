# Quickstart: Configurable Agent Core

A validation/run guide proving the promoted core + changepoint pipeline works end-to-end. Run from the
repo root. Implementation details live in `tasks.md` (after `/speckit-tasks`) and the code; this is the
"does it work" guide.

## Prerequisites

```bash
uv sync                      # shared venv from the committed uv.lock (now pins prophet==1.1.6)
cp .env.example .env         # fill ANTHROPIC_API_KEY + AWS creds (secrets stay in .env, never config.yaml)
```

Config defaults live at `src/ailf/pipelines/changepoint/config.yaml` (model ids,
`visual_analysis_enabled`, the 13 diagnostics toggles, the tool toggles, split). Secrets are **not** in
that file.

## 1. Deterministic suite (Tier A — no Bedrock needed)

```bash
uv run pytest tests/core tests/pipelines/changepoint
```

Expected: green. This covers the config resolver/merge/lockstep, the split resolver + rounding +
provenance + round-trip, the registry + bounds gate, metrics, the event emitter + file sink + per-stage
payload schemas + leakage, the detector (known-injected-ground-truth precision/recall/FPR), diagnostics
(incl. compute-but-hide + golden byte-identity), and the graph wiring/routing with a `FakeModelWrapper`.

## 2. POC parity (SC-001)

```bash
# One-time oracle capture from the UN-PROMOTED POC (committed under tests fixtures):
uv run python -m tests.pipelines.changepoint.capture_poc_parity   # writes poc_parity_reference.json
# Then the parity test asserts the PROMOTED core path matches it:
uv run pytest tests/core/parity
```

Expected: for each of the five scenarios the promoted path's detected changepoints, full-history-Prophet
val metrics, every naive candidate's val metrics + `selected_window_start`, and the two baselines' test
metrics match the oracle (floats within `1e-6`; structural fields exact).

## 3. Import-cleanliness & lift-and-shift (SC-002, SC-011)

```bash
uv run pytest tests/core/agent -k "import_guard or stub_swap"
```

Expected: `langgraph` importable only via `core/agent/engine`; `langchain_aws` only via
`core/models/llm`; importing `core.backtest`/`core.agent`/`core.events` does **not** pull
`core.datasets`; the changepoint pipeline imports only `core` + stdlib; and swapping a tool's
implementation for a contract-equivalent stub leaves the agent loop, gate, prompts, and event/trace
format unchanged.

## 4. End-to-end single-scenario run (the real agent)

```bash
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
```

Expected: a run directory `reports/changepoint/<run_id>/` containing `effective_config.json`,
`metrics.json`, `agent_trace.json`, `report.md`, `events.jsonl`, `agent_context.png` (visual on),
`forecast_comparison.png`. The events file has one well-formed `StageEvent` per stage lifecycle in
causal order (config_resolved → split_built → changepoint_detection → both baselines →
diagnostics_computed → visual_inspection → decision/validation iterations → final_evaluation →
run_complete).

## 5. Configurability checks (US2, US3, SC-004/005/006/009)

```bash
# Visual off (US3, SC-006): no agent_context.png, diagnostics-only prompt, run still completes
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"visual_analysis_enabled": false}'

# Hide a diagnostic (SC-004): still computed, absent from the agent's decision input + trace records it
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"diagnostics": {"recurring_event_summary": false}}'

# Remove a tool (SC-005): absent from menu + gate; never accepted; trace records removal
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"agent_tools": {"full_history_prophet_tuned_holidays": false}}'

# Split override (SC-009): ratios and equivalent absolute resolve to identical rows
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"split": {"units": "ratios", "train_ratio": 0.76, "val_ratio": 0.12, "test_ratio": 0.12}}'
```

Verify in each run's `effective_config.json` + `agent_trace.json`: the override is merged onto defaults,
`hidden_diagnostics`/`removed_tools`/`visual_analysis_enabled` are recorded, and `SplitProvenance`
reflects the source/units/resolved rows.

## 6. Failure modes (FR-010, FR-018, FR-032, SC-008)

```bash
# Unknown diagnostic key → ConfigError naming the field (no silent default)
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"diagnostics": {"not_a_real_field": false}}'

# Ambiguous split (ratios AND absolute) → SplitError
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"split": {"units": "ratios", "train_ratio": 0.8, "val_ratio": 0.1, "test_ratio": 0.1, "train_rows": 700}}'

# Disabling the fallback → ConfigError
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality \
  --override '{"agent_tools": {"full_history_default": false}}'
```

Expected: each fails fast with an explicit, field-naming message; for a stage failure mid-run a terminal
`error` event is the last line of `events.jsonl` and no partial agent forecast is produced.

## 7. Golden-set agent eval (opt-in; Bedrock required — Principle III)

```bash
uv run pytest -m golden            # skipped automatically without Bedrock credentials
```

Expected (when credentials present): across the five scenarios, the accepted/best-val tool family
matches each scenario's `expected_intervention_family`, and the holiday tool is selected only on the
recurring-event scenario. Never gates the deterministic suite.

## Success = the spec's SCs

Steps 1–2 → SC-001/SC-003/SC-004/SC-005. Step 3 → SC-002/SC-011. Step 4 → SC-010/SC-012 + full artifact
set. Step 5 → SC-006/SC-007/SC-009 + US2/US3. Step 6 → SC-008. Step 7 → Principle III / agent-quality.

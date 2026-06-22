# Phase 0 Research: Streamlined Agent UI

All unknowns from the Technical Context are resolved below, grounded in the current code. Each item is a decision, why it was chosen, and the alternatives rejected.

---

## R1 — How to receive the event stream in the UI without disk polling

**Decision**: Add a generic `QueueEventSink` to `core/events/sink.py` and an `extra_sinks: list[EventSink] | None = None` parameter to `run_scenario`. The UI worker thread passes `QueueEventSink(queue.Queue())`; the Streamlit main thread drains the queue live.

**Rationale**:
- `EventSink` is a one-method Protocol: `write(self, event: StageEvent) -> None` (`core/events/sink.py:17-18`). A queue sink is trivial and fully conformant.
- `EventEmitter.__init__(run_id, sinks: list[EventSink], *, payload_dir=...)` already accepts **multiple** sinks and `emit()` fans out to all of them (`core/events/emitter.py:37, 92-93`). So adding a sink needs no emitter change.
- `run_scenario` constructs the emitter in exactly one place (`pipeline.py:190`): `EventEmitter(run_id, [FileEventSink(...)], ...)`. Adding `extra_sinks` and appending them is minimal and backward-compatible (existing callers/tests unaffected).
- `StageEvent.to_dict()` yields a plain dict with keys `run_id, seq, ts, stage (str), status (str), concurrency_group, payload, error` (`core/events/event.py`). The UI consumes these strings/dicts — no core enums leak across the boundary (Principle I).

**Alternatives rejected**:
- *Tail `events.jsonl` from disk*: adds file-poll latency + parsing, and the disk file is the same data; the queue is strictly better for liveness.
- *A network transport (WebSocket/FastAPI)*: more moving parts; out of scope for a single-user local presentation.

---

## R2 — Making in-graph agent stages emit LIVE (the highest-risk change)

**Decision**: In the pipeline driver, replace `app.invoke(...)` with iterating `app.stream(...)`, emitting each in-graph stage (visual inspection, each decision iteration, each validation outcome, final evaluation) **as its node completes, from the single-threaded driver**. **Remove** the post-invoke reconstruction block (`pipeline.py:264-275`).

**Rationale**:
- Today the prelude (config→split→detect→baselines→diagnostics) streams live, but the entire in-graph portion is emitted in a burst **after** `invoke()` returns (`pipeline.py:264-275`) — so the most interesting part (the agent reasoning) is not live. This is the gap the spec's FR-018/030 close.
- LangGraph `1.2.4`'s sync `StateGraph.invoke()` runs the `visual ∥ diagnostics` fan-out **serially within a single thread** (no OS threads); state merges via the `_take_right` reducer (`core/agent/state.py:13-15`). Therefore emission must remain driver-controlled to keep ordering deterministic.
- Node bodies today do **not** emit (verified: zero `ctx.emitter.emit()` calls in `nodes.py`). Keeping emission out of nodes preserves the design rationale recorded in feature 005 (Decision 11): "their start/complete are emitted from the single-threaded driver … so the integer seq counter cannot race."
- `.stream()` yields per-super-step updates; the driver emits as each node's output appears, so `seq` stays monotonic and single-threaded. `test_event_stream.py` asserts strict-monotonic, unique seq and causal-order tail (`final_evaluation, run_complete`) — these stay green because emission is still serial in the driver.
- Removing the post-invoke block is **mandatory**: emitting live *and* reconstructing afterward would double-emit, breaking the uniqueness/seq asserts.

**Risks & mitigations**:
- *Visual-OFF mode*: when `visual_enabled=False` the visual node is omitted from the graph entirely; the stream loop must simply not see a visual update (no phantom emit). Covered by a test asserting no `visual_inspection` event in visual-off runs.
- *`concurrency_group="visual_diagnostics"`*: a UI/causal marker, not a threading directive. Preserve it on the visual/diagnostics emits so consumers can still group them.
- *Mapping stream updates → existing payload builders*: reuse the exact payload builders already used in the post-invoke block (`ev.visual_inspection`, `ev.decision_iteration`, `ev.validation_outcome`) so payload shapes are byte-for-byte identical (FR-031). Decision/validation iterations are emitted per-iteration as they complete rather than looped at the end.

**Alternatives rejected**:
- *Emit inside node bodies*: reintroduces causal-ordering jitter for the visual∥diagnostics pair and risks seq races; explicitly rejected by the 005 design.
- *Thread-safe lock around `emit()`*: solves a data race that doesn't exist here (emission is single-threaded); doesn't fix ordering; unnecessary.

---

## R3 — Building the `ConfigOverride` from UI controls

**Decision**: `config_builder.py` produces an override dict consumed by `ConfigOverride.from_dict`:

```
{
  "models": {"visual_model_id": <bedrock-form id>, "decision_model_id": <bedrock-form id>},
  "visual_analysis_enabled": <bool>,
  "diagnostics": {<all 13 keys>: <bool>},          # key-wise, must be the EXACT 13 keys
  "agent_tools": {<5 structural>: <bool>, "full_history_default": true},  # fallback always true
  "seed": <int, default 1729>
  # "split": only for scenarios if a non-golden split is requested (custom CSV uses the run_scenario params, see R5)
}
```

**Rationale** (all verified):
- `ConfigOverride` fields: `models, visual_analysis_enabled, diagnostics, agent_tools, split, seed` — all optional (`config/schema.py:118-146`).
- Diagnostics/tools are **key-wise merged with no new keys allowed** and **lockstep-validated** (`resolve.py:71-84, 87-116`). The UI must send the **exact** keys or config resolution fails.
- The 13 diagnostic keys = `DiagnosticsBundle` fields: `detected_changepoints, latest_changepoint, primary_changepoint, post_changepoint_history_len, post_changepoint_shorter_than_season, seasonal_period, segment_stats, candidate_event_blocks, recurring_event_summary, local_boundary_jumps, candidate_drift_intervals, transient_event_score, permanent_shift_magnitude` (`diagnostics.py:53-66`).
- Tool keys = 5 structural (`recent_window, full_history_step_regressor, full_history_ramp_regressor, full_history_clean_event, full_history_prophet_tuned_holidays`) **plus** the always-on `full_history_default` (`interventions.py:28-35`). The fallback must be present and `true` or resolution raises (`resolve.py:171-174`) → the UI never offers an off-switch for it (FR-014).
- To avoid drift, the UI imports the canonical key lists from the pipeline (`DiagnosticsBundle.field_names()`, `structural_tool_names()`, `FALLBACK_TOOL`) rather than hardcoding them.

**Alternatives rejected**: hardcoding the key lists in the UI (would silently break lockstep if the bundle changes).

---

## R4 — Provider initialization (Anthropic-first, fail-fast) and model-id mapping

**Decision**: Rewrite `_detect_llm_provider()` to:
```
if ANTHROPIC_API_KEY set -> "anthropic"
elif AWS_ACCESS_KEY_ID set -> "bedrock"
else raise ConfigError("Neither ANTHROPIC_API_KEY nor AWS_ACCESS_KEY_ID is set ...")
```
Keep model-id translation as-is. The UI always passes Bedrock-form ids; the backend translates to native when provider is `anthropic`.

**Rationale**:
- Current order is **reversed** (Bedrock first) and silently defaults to bedrock when neither is set, deferring failure to first model call (`resolve.py:49-60`). The spec wants Anthropic-first (FR-027) and a clear early failure (FR-029).
- Raising at `resolve_config` time surfaces the error before any compute, as a `ConfigError` (consistent with all other config errors), which the UI shows pre-run.
- The translation table maps `us.anthropic.claude-opus-4-8 → claude-opus-4-8` and `us.anthropic.claude-sonnet-4-6 → claude-sonnet-4-6` (`resolve.py:27-46`), applied only when provider is `anthropic` (`resolve.py:144-148`). So the UI's friendly choices (Opus 4.8 / Sonnet 4.6) work on either provider.
- "Initialize the client once per run" already holds at the provider-detection level (detected once in `resolve_config`) and the role level (two `ModelWrapper`s, one per role, built once in `pipeline.py:234-241`). *Optional hardening*: the Anthropic proxy reconstructs an `anthropic.Anthropic` client on every invoke (`llm.py:76-79`); moving it into `__init__` would make it truly once-per-role. This is noted as a **non-blocking** optional improvement (the `httpx.Client(verify=False)` SSL wart is out of scope).

**Risks & mitigations**: test fixtures relying on the silent bedrock default must explicitly set a credential env var; add/adjust tests. Distinguish "key not set" (ConfigError pre-run) from "key invalid" (surfaces at first call) in messaging.

**Alternatives rejected**: defer the neither-set error to first model call (current behavior) — fails the "clear early failure" requirement.

---

## R5 — Custom-CSV three-fraction split

**Decision**: Extend `_series_split_from_df` to accept explicit `train_ratio, val_ratio, test_ratio` (sum≈1, each segment ≥1 row) and thread them through `run_scenario`'s custom-CSV branch. The UI validates the three inputs sum to 1 (within tolerance) **before** starting the run.

**Rationale**:
- `_series_split_from_df(df, split_ratio=0.8, val_ratio=0.1)` computes `test = 1 - split_ratio` and caps val internally — it cannot honor three independent user fractions (`pipeline.py:79-122`). The custom-CSV path calls it with only `split_ratio` (`pipeline.py:161`), bypassing `override.split` entirely.
- The spec (FR-009) requires three fractions summing to 1, so the signature must change. Reuse the existing `ResolvedSplit.from_lengths(...)` machinery (floor-based rounding, each segment ≥1) so the split provenance stays consistent with scenario runs.

**Alternatives rejected**: routing custom CSV through `override.split` (the custom path deliberately bypasses metadata and split-spec; adding three params to the DF helper is the smaller, clearer change).

---

## R6 — Threading pattern and final-chart data source

**Decision**: Daemon worker thread runs `run_scenario(..., extra_sinks=[QueueEventSink(q)])` and stores its return value/exception in a holder; the Streamlit main thread drains `q` for live events and, on completion, reads `forecast_comparison.csv` **once** to build the Plotly figure. `run_scenario` is amended to **return the csv path** (today it isn't returned).

**Rationale**:
- The existing app proves the daemon-thread + holder + main-thread-poll pattern works without `st.*` calls from the worker (`drift/streamlit_app.py` threaded path). We keep that discipline and **add** the queue for liveness (the old app never consumed events).
- The comparison frame already contains everything the chart needs in one place — `ds, y_actual, region, yhat_full_history, yhat_naive, yhat_agent` (`pipeline.py:327-363`) — making it the lowest-friction chart source. Reading it once at the end is fine; only *liveness* must avoid disk polling, and that's handled by the queue.
- The run's return dict also carries `final_eval` (yhat arrays + per-method test_metrics) and `winner` (`pipeline.py:391`), which feed the verdict (R7).
- Region gap: the frame labels only `train`/`forecast`. Use `split.fit_end`/`split.train_end`/`split.val_df`/`split.test_df` (`scenarios.py:42-76`) to emit `train`/`val`/`test` so the chart shades three regions (FR-025).
- Changepoints: the `changepoint_detection` event payload is `[{index, ds, trend_delta}]` with training-region indices (`payloads.py:27`, `pipeline.py:204`) → vertical markers by `ds`.

**Pitfalls captured**: never write `st.session_state` or call `st.*` from the worker; the queue is the only cross-thread channel for events; the holder is the only channel for the final return/exception.

**Alternatives rejected**: reconstructing the chart frame in the UI from `final_eval` + the split (more code, duplicates what the pipeline already writes).

---

## R7 — Verdict derivation

**Decision**: `verdict.py` reads the three methods' test metrics from the run's `final_eval` (or `metrics.json`) and declares the winner by **lowest test MAE** among `agent`, `full_history_prophet`, `naive_workflow`, plus the margin `naive_mae - agent_mae`.

**Rationale**: This mirrors the backend's own winner logic (`reporting/artifacts.py:31-33`, `delta_vs_naive`) exactly, so the UI verdict and the written report agree (FR-023). All three methods' `test_metrics{mae,rmse,wape,smape}` are present in `final_eval` (`agent/nodes.py:152-160`).

**Alternatives rejected**: re-scoring in the UI (would duplicate metric logic and risk disagreement with the report — violates Principle I).

---

## R8 — Cleanup scope (what is safe to delete)

**Decision**: Delete `drift/streamlit_app.py`, `drift/llm_reason.py`, `drift/fallback.py`. In `drift/pipeline.py`, remove the embedded forecast HTML UI (`_UI_HTML`), its `/forecast/*` endpoints, and the `/changepoint/run` bridge — but **keep** the `app` object and the drift **dataset-generation** routes.

**Rationale** (verified):
- `streamlit_app.py`, `llm_reason.py`, `fallback.py` have **no importers anywhere outside `drift/`** and **no test references** (grep confirmed; the many "fallback" hits are the unrelated `full_history_default` tool). Safe to delete.
- `drift/pipeline.py`'s `app` **is** imported by `tests/pipelines/drift/test_api.py`, which only exercises `/drift/config`, `/drift/generate/*`, and `/docs` — the **dataset-generation** surface. Those must keep working, so the app + those routes stay; only the forecast/changepoint UI bits go.
- `llm_reason`/`fallback` are imported by `drift/pipeline.py` **lazily** (inside functions), so removing the forecast endpoints removes the only references; module deletion then leaves no dangling top-level imports.
- The drift dataset modules (`datasets.py`, `dataset_generator.py`, `corpus.py`, `tools.py`) and the `anomaly/` directory are **out of scope** and untouched (covered by their own tests).

**Alternatives rejected**: deleting the whole `drift/` package (would break the dataset-generation tests and remove in-use data tooling); leaving the old UI in place (perpetuates the multi-pathway confusion the feature exists to remove).

---

## Resolved Technical Context items

| Context field | Resolution |
|---|---|
| Live-stream feasibility | Yes — `.stream()` driver emission (R2) |
| Event transport | In-process queue via `QueueEventSink` + `extra_sinks` (R1, R6) |
| Provider order | Anthropic-first, fail-fast `ConfigError` (R4) |
| Custom split | New three-fraction signature (R5) |
| Chart data | `forecast_comparison.csv` once at end + region relabel + changepoint payload (R6) |
| Cleanup blast radius | 2 file deletes + 1 embedded-HTML/endpoint removal; dataset gen kept (R8) |
| New dependencies | None (streamlit, plotly already present) |

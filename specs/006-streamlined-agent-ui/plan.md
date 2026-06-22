# Implementation Plan: Streamlined Agent UI for Final Presentation

**Branch**: `006-streamlined-agent-ui` | **Date**: 2026-06-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-streamlined-agent-ui/spec.md`

## Summary

Build one presentation-ready interface (`src/ailf/ui/`) that drives the existing changepoint agent pipeline end-to-end: a left control pane (Start, scenario-or-CSV dataset, visual + reasoning model selectors, 13 diagnostic toggles, tool toggles, visual-analysis on/off) and a right area (run-command metadata → **live** event stream → final verdict banner + interactive Plotly comparison graph).

Three small backend changes enable it, all grounded in the code: (1) a generic `QueueEventSink` plus an `extra_sinks` parameter on `run_scenario`, so the UI worker thread receives the typed event stream in-memory; (2) switch the agent driver from `app.invoke()` to `app.stream()` so in-graph stages (visual, each decision/validation iteration, final eval) emit **live** from the single-threaded driver instead of in a post-invoke burst — preserving monotonic `seq` and causal order; (3) flip provider detection to Anthropic-API-first / Bedrock-fallback and raise a clear `ConfigError` when neither is configured. Plus a small split-signature change so custom-CSV runs honor three user fractions, and a region-labeling tweak so the comparison frame distinguishes train/val/test. Finally, remove the superseded UI surfaces (`drift/streamlit_app.py`, the embedded forecast HTML in `drift/pipeline.py`) and the demo-only modules they alone used (`drift/llm_reason.py`, `drift/fallback.py`).

## Technical Context

**Language/Version**: Python 3.11+ (existing `uv` workspace).

**Primary Dependencies**: Streamlit (`>=1.35`), Plotly (`>=6.8`) — both already in `pyproject.toml`; LangGraph `1.2.4`; the existing `ailf.core` (events, agent engine, config, models) and `ailf.pipelines.changepoint` (`run_scenario`). No new dependencies.

**Storage**: None new. Reads committed scenario fixtures + `scenario_metadata.json`; the run writes its usual artifacts under `reports/changepoint/<run_id>/` (the UI reads `forecast_comparison.csv` once at completion for the chart).

**Testing**: `pytest` (existing). New: unit tests for `QueueEventSink`, the three-fraction split, the provider-flip, and the live-stream driver (seq monotonicity + causal order must stay green). UI logic is factored into pure helper functions that are unit-tested without launching Streamlit.

**Target Platform**: Local single-user web app (`streamlit run`), for a live presentation on macOS/Linux.

**Project Type**: Single Python workspace; the UI is a thin front-end client over the importable core (Constitution Principle I), not a pipeline.

**Performance Goals**: Event-to-screen latency is human-perceptible-live (sub-second per event under normal model latency); a full scenario run completes within the time of one agent loop (model-bound, typically a few minutes). No throughput target — single concurrent run.

**Constraints**: Streamlit `st.*` calls only from the main thread; the worker thread only produces events/artifacts (no `st.*`, no `session_state` writes). `seq` counter is not thread-safe → all emission stays on the single pipeline driver thread (never the UI thread). Pre-final events must not carry hidden-test data (existing leakage guard).

**Scale/Scope**: One UI module (~few hundred LOC split into `app.py` + pure helpers), ~4 focused backend edits, deletion of 2 files + 1 embedded HTML block, ~6–8 new tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Importable Core (Serializable Boundary) | ✅ PASS | The UI is a thin client; it imports `run_scenario` + `ConfigOverride` + scenario metadata and consumes the serializable event stream. No forecasting/diagnosis/agent/eval logic is re-implemented in the UI (FR-004). Events cross the boundary as plain dicts (`StageEvent.to_dict()`). |
| II. Test-First for Deterministic Logic (NON-NEGOTIABLE) | ✅ PASS | All deterministic additions — `QueueEventSink`, three-fraction split resolution, provider detection, region labeling, and the live-stream driver's seq/causal-order guarantee — get failing-first tests before implementation. UI rendering itself is non-deterministic glue and is kept thin; its pure helpers (override-building, split validation, chart-frame assembly) are unit-tested. |
| III. Agent Quality Through Golden-Set Evaluation | ✅ PASS (N/A) | No prompt/model/agent-logic change. Model *selection* is surfaced to the user but the agent's reasoning and golden-set behavior are unchanged. |
| IV. Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE) | ✅ PASS | Untouched. The UI only toggles which tools are on the menu (via `ConfigOverride.agent_tools`, lockstep-validated) and which diagnostics are exposed; the backtest gate and bounds are entirely in the core. The always-on fallback tool remains non-disable-able (FR-014). |
| V. Reproducible & Honest Evaluation | ✅ PASS | Seed flows through `ConfigOverride.seed` (default 1729). Baselines (full-history Prophet, naive) are always computed and shown in the verdict (FR-023). The "what's running" metadata surfaces the equivalent CLI invocation + config for reproducibility (FR-016). |
| VI. Transparent, Explainable Outputs | ✅ PASS | This feature *strengthens* transparency: every agent decision + validation outcome is shown live and individually inspectable (FR-018/019), and the run still writes its report artifacts. |
| VII. Shared Core, Independent Pipelines | ⚠️ PASS WITH REVIEW | Touches `core/events` (new generic sink), `core/agent/engine`+pipeline driver (invoke→stream), and `core/config/resolve` (provider order). These are **core changes** → require extra review and must keep all core tests green (per the per-change gate). The changes are generic (no changepoint symbols added to core) and the new UI is a front-end consumer, not a pipeline — so the "pipelines MUST NOT import one another" rule is not violated (the UI is not a pipeline). |

**Gate result**: PASS. The only flagged item (VII) is the expected, spec-acknowledged core touch; it is review-gated, generic, and test-guarded. No unjustified violations → no entry in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/006-streamlined-agent-ui/
├── plan.md              # This file
├── research.md          # Phase 0 output — resolved unknowns (live-emission, sink injection, split, provider, chart source)
├── data-model.md        # Phase 1 output — UI run-config, event view-model, chart frame, verdict
├── quickstart.md        # Phase 1 output — how to launch + validate each user story
├── contracts/           # Phase 1 output — UI↔backend contracts (event stream, run invocation, model choices, CSV)
│   ├── event_stream_consumption.md
│   ├── run_invocation.md
│   ├── model_selection.md
│   └── custom_csv.md
└── checklists/
    └── requirements.md  # Already created by /speckit-specify (12/12 pass)
```

### Source Code (repository root)

```text
src/ailf/
├── ui/                                  # NEW — the single streamlined front-end (thin client)
│   ├── __init__.py
│   ├── app.py                           # Streamlit entry: layout, control pane, live stream loop, results
│   ├── run_controller.py                # Worker-thread orchestration: builds override, spawns run_scenario with QueueEventSink, drains queue
│   ├── config_builder.py                # PURE: control selections -> ConfigOverride dict (+ scenario/custom-CSV branch); split-fraction validation
│   ├── event_view.py                    # PURE: map a StageEvent dict -> a renderable view-model (title, status, expandable payload)
│   ├── chart.py                         # PURE: build the final Plotly figure from the comparison frame + changepoints + region boundaries
│   ├── verdict.py                       # PURE: derive winner + margin-vs-naive from final metrics
│   └── models.py                        # Friendly model-choice catalog (Sonnet/Opus) -> Bedrock-form model ids
│
├── core/
│   ├── events/
│   │   └── sink.py                      # EDIT — add generic QueueEventSink (Protocol-conforming)
│   ├── agent/
│   │   └── engine.py                    # EDIT (small) — expose a stream-driver helper OR keep engine as-is and stream in pipeline driver (see research)
│   └── config/
│       └── resolve.py                   # EDIT — flip _detect_llm_provider to Anthropic-first; raise ConfigError when neither set
│
└── pipelines/
    ├── changepoint/
    │   └── pipeline.py                  # EDIT — extra_sinks param; invoke()->stream() live emission (remove post-invoke reconstruction); 3-fraction split; train/val/test region labels in comparison frame; return csv path
    └── drift/
        ├── streamlit_app.py             # DELETE (superseded UI)
        ├── llm_reason.py                # DELETE (demo-only; no importers outside drift)
        ├── fallback.py                  # DELETE (demo-only; no importers outside drift)
        └── pipeline.py                  # EDIT — remove embedded forecast HTML UI + its /forecast/* endpoints + the /changepoint/run bridge; KEEP the drift dataset-generation app (tests depend on it)

tests/
├── core/
│   ├── events/test_queue_sink.py        # NEW — QueueEventSink contract + ordering
│   └── config/test_provider_detection.py# NEW — Anthropic-first; neither-set raises ConfigError
├── pipelines/changepoint/
│   ├── test_event_stream.py             # EDIT/EXTEND — live stream still monotonic + causal; no double-emit
│   └── test_custom_split.py             # NEW — three-fraction split honored; sums!=1 rejected
└── ui/
    ├── test_config_builder.py           # NEW — override dict shape (scenario + custom CSV); split validation
    ├── test_event_view.py               # NEW — event-dict -> view-model mapping (incl. oversized $ref payloads)
    ├── test_verdict.py                   # NEW — winner/margin derivation
    └── test_chart_frame.py              # NEW — region labeling + changepoint markers assembled correctly
```

**Structure Decision**: The UI lives in a **new neutral `src/ailf/ui/` package** (per the spec's resolved decision and Principle I's "thin client" allowance), never under `pipelines/`, so consumers see "the forecasting agent," not a pathway name. All non-trivial UI logic is extracted into **pure, importable helpers** (`config_builder`, `event_view`, `chart`, `verdict`, `models`) so it is unit-testable without launching Streamlit; `app.py` is the thin Streamlit shell, and `run_controller.py` is the only place that touches threads. Backend edits are surgically confined to the four files named above.

## Key design decisions (from Phase 0 research)

1. **Live emission via `.stream()` from the driver, NOT inside node bodies.** LangGraph `1.2.4` `StateGraph.invoke()` runs the `visual ∥ diagnostics` fan-out serially in one thread; emitting inside nodes would reintroduce the causal-ordering jitter the existing design deliberately avoids. Instead, the pipeline driver iterates `app.stream(...)` and emits each stage as its node completes — keeping `seq` assignment single-threaded and monotonic. The current post-invoke reconstruction block (`pipeline.py:264-275`) is **removed** to avoid double emission (which would break `test_event_stream.py`'s strict-monotonic + causal-order asserts).

2. **Generic `QueueEventSink` + `extra_sinks` injection.** `EventEmitter` already fans out to a `list[EventSink]`. Add a `QueueEventSink(queue.Queue)` implementing `write(event)` → `queue.put(event.to_dict())`, and add `extra_sinks: list[EventSink] | None = None` to `run_scenario`. The UI worker passes a `QueueEventSink`; the main thread drains the queue and renders. The `FileEventSink` (events.jsonl) still writes as before. Emission stays on the single driver thread, so the non-thread-safe `seq` counter is safe.

3. **Transport: in-process thread + in-memory queue.** `run_controller.py` spawns a daemon thread running `run_scenario(..., extra_sinks=[QueueEventSink(q)])`; the Streamlit main thread drains `q` in a loop, rendering events as they arrive, until a `run_complete` event (or thread death). No subprocess, no disk polling for liveness. The chart frame is read **once** at completion from `forecast_comparison.csv` (run_scenario will also return its path). The worker never calls `st.*`.

4. **Provider flip + fail-fast.** Rewrite `_detect_llm_provider()` to return `anthropic` if `ANTHROPIC_API_KEY` set, else `bedrock` if `AWS_ACCESS_KEY_ID` set, else `raise ConfigError(...)` at resolve time (FR-029). The UI surfaces that `ConfigError` as a clear pre-run message. Bedrock-form model ids (`us.anthropic.claude-opus-4-8`, `us.anthropic.claude-sonnet-4-6`) translate to native ids via the existing `_BEDROCK_TO_ANTHROPIC_MODEL_ID` table when provider is `anthropic`, so the UI always passes Bedrock-form ids and the backend resolves them.

5. **Three-fraction custom split.** `_series_split_from_df` currently takes a single `split_ratio` + hardcoded `val_ratio=0.1`. Extend it (and `run_scenario`'s custom-CSV branch) to accept `train_ratio`, `val_ratio`, `test_ratio` (validated to sum to 1 within tolerance) so the UI's three inputs are honored. Scenario runs are unaffected (they use metadata/golden split).

6. **Region labeling for the chart.** The comparison frame currently labels regions `train`/`forecast` only. Use `split.fit_end` vs `split.train_end` to emit `fit`/`val`/`test` (or `train`/`val`/`test`) so the graph can shade all three regions (FR-025). Changepoints come from the `changepoint_detection` event payload (`[{index, ds, trend_delta}]`, training-region indices) for vertical markers.

## Complexity Tracking

> No constitution violations require justification. (Item VII is a sanctioned, review-gated core touch, not a violation — table intentionally empty.)

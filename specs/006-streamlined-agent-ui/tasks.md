---
description: "Task list for Streamlined Agent UI for Final Presentation"
---

# Tasks: Streamlined Agent UI for Final Presentation

**Input**: Design documents from `/specs/006-streamlined-agent-ui/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (all present)

**Tests**: INCLUDED. Constitution Principle II (NON-NEGOTIABLE) requires failing-first tests for all deterministic logic. Tests are written for the deterministic backend seams and the pure UI helpers; the thin Streamlit shell (`app.py`) and threading glue are validated via `quickstart.md`.

**Organization**: Tasks are grouped by user story. US1 (P1) is the MVP. US2/US3/US4 are independent increments.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 (setup, foundational, polish carry no story label)
- Every task names an exact file path

## Path Conventions

Single Python workspace: source under `src/ailf/`, tests under `tests/`. The new UI lives in `src/ailf/ui/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the neutral UI package so consumers never see pathway vocabulary (FR-002).

- [X] T001 Create the `src/ailf/ui/` package and empty module stubs (`__init__.py`, `app.py`, `run_controller.py`, `config_builder.py`, `event_view.py`, `chart.py`, `verdict.py`, `models.py`) plus the test package `tests/ui/__init__.py`. No logic yet — just importable skeletons with module docstrings. (streamlit/plotly are already in `pyproject.toml`; no dependency changes.)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared backend seams and UI infrastructure that **every** user story depends on — the event-queue transport, live in-loop emission, provider selection, model catalog, override builder, and the worker/queue controller.

**⚠️ CRITICAL**: No user story can run until this phase is complete (every story performs a run and consumes the live event stream).

### Tests for Foundational (write FIRST, ensure they FAIL) ⚠️

- [X] T002 [P] Write `tests/core/events/test_queue_sink.py`: assert `QueueEventSink` conforms to the `EventSink` protocol, that `write(event)` puts `event.to_dict()` (plain dict with keys `run_id, seq, ts, stage, status, concurrency_group, payload, error`) onto the queue, preserves order, and never raises on a put failure (defensive). (Contract: `contracts/event_stream_consumption.md`.)
- [X] T003 [P] Write `tests/core/config/test_provider_detection.py`: with only `ANTHROPIC_API_KEY` set → `_detect_llm_provider()` returns `"anthropic"`; with only `AWS_ACCESS_KEY_ID` set → `"bedrock"`; with both set → `"anthropic"` (precedence); with neither set → raises `ConfigError` with a clear message. Use monkeypatched env. (Contract: `contracts/model_selection.md`, FR-027/029.)
- [X] T004 [P] Write `tests/ui/test_config_builder.py`: assert `to_override_dict(cfg)` emits `models.{visual_model_id,decision_model_id}` as Bedrock-form ids, a `diagnostics` dict whose keys equal `DiagnosticsBundle.field_names()` exactly, an `agent_tools` dict whose keys equal the 5 structural names + `full_history_default` with the fallback forced `True`, the `visual_analysis_enabled` flag, and `seed`. Assert the result round-trips through `ConfigOverride.from_dict` and passes `resolve_config` lockstep. (Contract: `contracts/run_invocation.md`, data-model §1/§5.)
- [X] T005 Write the live in-loop emission test in `tests/pipelines/changepoint/test_event_stream.py` (extend): inject `FakeModelWrapper`s and a recording sink; assert that `decision_iteration` #i is observed by the sink **before** the (i+1)-th decision is requested (proving emission happens during the agent loop, not in a post-invoke burst — FR-018/030), AND that seqs remain strictly monotonic/unique with the causal-order tail `final_evaluation → run_complete`, AND that no stage is emitted twice (guards the removed reconstruction block — FR-031). This test MUST fail against the current burst implementation.

### Implementation for Foundational

- [X] T006 [P] Add `QueueEventSink` to `src/ailf/core/events/sink.py`: `__init__(self, q: queue.Queue)` and `write(self, event: StageEvent) -> None` that calls `self._q.put(event.to_dict())`, swallowing `queue.Full`/errors so it cannot break the emit fan-out loop. Make T002 pass.
- [X] T007 [P] Flip provider detection in `src/ailf/core/config/resolve.py`: rewrite `_detect_llm_provider()` to return `"anthropic"` if `ANTHROPIC_API_KEY` set, else `"bedrock"` if `AWS_ACCESS_KEY_ID` set, else `raise ConfigError(...)` with the clear "neither configured" message. Keep `_to_anthropic_model_id` / `_BEDROCK_TO_ANTHROPIC_MODEL_ID` unchanged. Make T003 pass.
- [X] T008 Add `extra_sinks: list[EventSink] | None = None` to `run_scenario` in `src/ailf/pipelines/changepoint/pipeline.py` and append them to `[FileEventSink(...)]` when `emit_events=True` (backward compatible). (Contract: `contracts/run_invocation.md`.)
- [X] T009 In `src/ailf/pipelines/changepoint/pipeline.py`, switch the agent driver from `app.invoke(...)` to iterating `app.stream(...)`, emitting each in-graph stage (`visual_inspection`, each `decision_iteration` + `validation_outcome`, `final_evaluation`) from the single-threaded driver **as its node completes**, reusing the existing `ev.*` payload builders for byte-identical payloads; **delete** the post-invoke reconstruction block (current lines ~264-275) to avoid double emission. Preserve `concurrency_group="visual_diagnostics"` on the visual/diagnostics emits and the visual-off case (no visual event). Make T005 pass. (Depends on T008 — same file; research R2.)
- [X] T010 [P] Implement the model catalog in `src/ailf/ui/models.py`: friendly labels (`Claude Opus 4.8`, `Claude Sonnet 4.6`) → Bedrock-form ids (`us.anthropic.claude-opus-4-8`, `us.anthropic.claude-sonnet-4-6`), with role applicability and defaults matching `config.yaml` (visual=Opus 4.8, reasoning=Sonnet 4.6). (data-model §5.)
- [X] T011 [P] Implement `to_override_dict()` in `src/ailf/ui/config_builder.py`: import canonical key lists from the pipeline (`DiagnosticsBundle.field_names()`, `structural_tool_names()`, `FALLBACK_TOOL`) — never hardcode — and build the override dict per the contract, forcing `full_history_default=True`. Make T004 pass.
- [X] T012 Implement `src/ailf/ui/run_controller.py`: a daemon worker thread that runs `run_scenario(..., extra_sinks=[QueueEventSink(q)])`, a `queue.Queue` for live events, and a result/exception holder. Expose a `start_run(...)` returning `(queue, holder, thread)` and a generic drain helper. The worker MUST NOT call `st.*` or touch `st.session_state`; the only cross-thread channels are the queue (events) and the holder (final dict / error). (Depends on T006, T008; contract: `contracts/run_invocation.md` + `event_stream_consumption.md`.)

**Checkpoint**: Backend seams emit live over an in-memory queue, provider selection is Anthropic-first with fail-fast, and the UI can build overrides and drive a run on a worker thread. User stories can now begin.

---

## Phase 3: User Story 1 - Run a built-in scenario and watch the agent work live (Priority: P1) 🎯 MVP

**Goal**: Select a built-in scenario, click Start, watch events stream live (including each agent decision/validation iteration), then see a verdict banner + interactive comparison graph.

**Independent Test**: Pick a scenario, click Start; confirm events appear incrementally (agent iterations visible mid-run), and on completion a winner-by-MAE verdict and an interactive Plotly graph (3 forecasts + actuals, train/val/test shading, changepoint markers, zoom/pan/hover/legend) render.

### Tests for User Story 1 (write FIRST, ensure they FAIL) ⚠️

- [X] T013 [P] [US1] Write `tests/ui/test_event_view.py`: `event_view.from_event(event_dict)` maps each stage/status to a view-model (`seq, stage, status, title, summary, payload, is_error, payload_ref, concurrency_group`); handles an offloaded `{"$ref": "event_payloads/<seq>.json"}` payload without breaking (FR-021); flags `status="error"` as `is_error` (FR-020); and, as a no-leak guard, asserts the view-model derived from a pre-final stage never surfaces a `test_metrics*` key (the UI trusts the backend leakage guarantee and must not read hidden-test data early — FR-022). (data-model §2.)
- [X] T014 [P] [US1] Write `tests/ui/test_verdict.py`: `verdict.derive(final_eval)` picks the winner by lowest test MAE among agent / full_history_prophet / naive_workflow (mirroring `reporting/artifacts.py`), computes `margin_vs_naive = naive_mae - agent_mae`, and builds a headline. (data-model §4, FR-023.)
- [X] T015 [P] [US1] Write `tests/ui/test_chart_frame.py`: `chart.build_frame(csv_df, changepoints, split_bounds)` relabels regions to `train`/`val`/`test` using the fit/train boundaries, attaches changepoint markers from the `changepoint_detection` payload, and sets the recent-history-plus-full-forecast view window. (data-model §3, FR-024/025.)

### Implementation for User Story 1

- [X] T016 [US1] In `src/ailf/pipelines/changepoint/pipeline.py`, relabel the `forecast_comparison.csv` region column to `train`/`val`/`test` using `split.fit_end`/`split.train_end` (was `train`/`forecast`), and add the csv path to the `run_scenario` return dict. (research R6; needed by the US1 chart.)
- [X] T017 [P] [US1] Implement `event_view.from_event()` in `src/ailf/ui/event_view.py` with friendly titles/summaries per stage and `$ref`/error handling. Make T013 pass.
- [X] T018 [P] [US1] Implement `verdict.derive()` in `src/ailf/ui/verdict.py`. Make T014 pass.
- [X] T019 [US1] Implement `chart.build_frame()` + `chart.build_figure()` (Plotly) in `src/ailf/ui/chart.py`: three forecast traces + actuals, distinct train/val/test shading, changepoint vlines, zoom/pan/hover, full legend. Make T015 pass. (Depends on T016 for region labels.)
- [X] T020 [US1] Build the `src/ailf/ui/app.py` shell: wide layout with a left control pane (Start button; dataset = built-in scenario selector populated from scenario metadata via the pipeline's `load_metadata()`; visual + reasoning model selectors from `ui/models.py`) and a right area; on Start, render the run metadata (equivalent CLI command + resolved config). Scenario runs MUST use the metadata/golden split — the override MUST NOT carry a `split` block for the scenario branch (FR-003/005/007/012/016).
- [X] T021 [US1] In `src/ailf/ui/app.py`, implement the live stream loop: call `run_controller.start_run(...)`, drain the queue on the main thread with a bounded `queue.get(timeout=…)` + periodic rerun, render each `EventViewModel` incrementally in `seq` order as an expandable entry, and end on `run_complete`. Handle the long-running/stalled-run edge case: keep already-streamed events visible and show a "work in progress" indicator during quiet periods (FR-017/018/019; spec.md:93). Surface error events and stop cleanly, and defensively terminate if the worker thread is dead and the queue is drained (FR-020). (Depends on T012, T017, T020.)
- [X] T022 [US1] In `src/ailf/ui/app.py`, on completion read the returned `csv_path`, build the chart via `ui/chart.py`, and render the verdict banner (`ui/verdict.py`) above the interactive graph (FR-023/024/025/026). Surface a clear pre-run message if the run fails with the "neither provider configured" `ConfigError` (FR-029). (Depends on T018, T019, T021.)

**Checkpoint**: MVP — a built-in scenario runs end-to-end with live agent streaming and a final verdict + interactive graph. Demo-ready.

---

## Phase 4: User Story 2 - Bring your own data via custom CSV (Priority: P2)

**Goal**: Upload a `ds`/`y` CSV, set train/val/test fractions summing to 1, optionally tune advanced detection settings, and run the same live experience.

**Independent Test**: Upload a conforming 2-column CSV with splits `0.8/0.1/0.1` → full run + verdict + graph. A non-conforming file or splits not summing to 1 are blocked before any run starts, with a clear message.

### Tests for User Story 2 (write FIRST, ensure they FAIL) ⚠️

- [X] T023 [P] [US2] Write `tests/pipelines/changepoint/test_custom_split.py`: the extended `_series_split_from_df` honors three explicit fractions (`train_ratio,val_ratio,test_ratio`), rejects fractions not summing to 1 (tolerance 1e-6), and guarantees each segment ≥1 row. (research R5, FR-009.)
- [X] T024 [P] [US2] Add custom-CSV validation tests to `tests/ui/test_config_builder.py` (or a new `tests/ui/test_custom_csv.py`): the validator accepts a DataFrame with exactly `ds`/`y`, and rejects each defect with a clear, specific message — missing/extra columns, `ds` not datetime-parseable, `ds` not chronologically sorted, duplicate `ds` timestamps, `y` non-numeric or containing nulls, fraction sums ≠ 1 (tolerance 1e-6), and too-few-rows-for-split (a segment would be empty). One assertion per defect. (Contract: `contracts/custom_csv.md` "UI validation order"; spec.md:92 edge case.)

### Implementation for User Story 2

- [X] T025 [US2] Extend `_series_split_from_df` and `run_scenario`'s custom-CSV branch in `src/ailf/pipelines/changepoint/pipeline.py` to accept `train_ratio`, `val_ratio`, `test_ratio` (replacing the single `split_ratio`), reusing `ResolvedSplit.from_lengths`. Make T023 pass. (research R5.)
- [X] T026 [US2] Add custom-CSV validation helpers to `src/ailf/ui/config_builder.py` returning structured, message-bearing results, covering the full contract: exact `ds`/`y` columns, `ds` datetime-parseable + chronologically sorted + no duplicate timestamps, `y` numeric + non-null, fraction sum ≈ 1 (tolerance 1e-6), and row-count feasibility (each segment ≥1 row). Make T024 pass. (Contract: `contracts/custom_csv.md`.)
- [X] T027 [US2] In `src/ailf/ui/app.py`, add the custom-CSV dataset branch: file uploader with visible `ds`/`y` contract help (icon/caption), three split-fraction inputs (default 0.8/0.1/0.1), advanced `seasonal_period` (365) and `n_changepoints_to_detect` (3) inputs, pre-run validation that blocks Start with a clear message on any failure, and invocation via `run_scenario(series_df=..., train_ratio=..., val_ratio=..., test_ratio=..., seasonal_period=..., n_changepoints_to_detect=...)`. (FR-006/008/009/010/011.)

**Checkpoint**: Both built-in scenarios and custom CSVs run end-to-end with identical live + verdict + graph experience.

---

## Phase 5: User Story 3 - Configure the agent's instruments before running (Priority: P2)

**Goal**: Toggle which of the 13 diagnostics are exposed, which tools are on the menu, and whether visual analysis runs — and see those choices reflected in the run.

**Independent Test**: Disable some diagnostics + a tool and turn visual analysis off; confirm via the stream that hidden diagnostics aren't exposed, disabled tools are absent from the agent menu (fallback remains), and no visual-inspection event occurs.

### Tests for User Story 3 (write FIRST, ensure they FAIL) ⚠️

- [X] T028 [P] [US3] Write `tests/pipelines/changepoint/test_instrument_config.py`: with a `FakeModelWrapper` and an override disabling some diagnostics/tools and `visual_analysis_enabled=False`, assert the `config_resolved` event lists the disabled diagnostics under `hidden_diagnostics` and disabled tools under `removed_tools`, the `decision_iteration.menu` omits disabled tools but keeps `full_history_default`, and **no** `visual_inspection` event is emitted. (FR-013/014/015, SC-004.)

### Implementation for User Story 3

- [X] T029 [US3] In `src/ailf/ui/app.py`, add the diagnostic-bundle controls (13 checkboxes) and agent-tools controls (5 toggles + the always-on `full_history_default` shown locked/disabled), wired into `config_builder.to_override_dict`. (FR-013/014.)
- [X] T030 [US3] In `src/ailf/ui/app.py`, add the visual-analysis on/off toggle that sets `visual_analysis_enabled` in the override and greys out the visual-model selector when off. Make T028 pass (in combination with T029). (FR-015.)
- [X] T031 [US3] Wire the toggle state through the run path and confirm the streamed `config_resolved`/`diagnostics_computed`/`decision_iteration` events reflect the selections (covered by T028; add any missing plumbing in `src/ailf/ui/app.py`/`config_builder.py`).

**Checkpoint**: Instrument configuration measurably shapes the run and is observable in the live stream.

---

## Phase 6: User Story 4 - One coherent interface, no pathway confusion (Priority: P1)

**Goal**: Remove the superseded UI surfaces and demo-only modules so there is exactly one discoverable entry point, with the drift dataset-generation API preserved.

**Independent Test**: Only `src/ailf/ui/app.py` launches as a UI; the old Streamlit/embedded-HTML surfaces are gone; `tests/pipelines/drift/test_api.py` (dataset generation) still passes.

> US4 is largely independent of US1–US3 and may be done in parallel; T034/T035 depend on T033 (removing the lazy imports first).
>
> **Priority note**: US4 is **P1** (equal to US1) because "single coherent interface, no pathway confusion" is core to the final-presentation goal. It is sequenced after the P2 stories only because it is pure cleanup that touches just `drift/` files and carries no dependency on US1–US3. For a presentation build, pull T032–T036 forward to run alongside US1 so the single-entry-point property is present in the demo (and `streamlit run` exposes exactly one UI).

### Implementation for User Story 4

- [X] T032 [P] [US4] Delete `src/ailf/pipelines/drift/streamlit_app.py` (superseded UI; no importers outside `drift/`).
- [X] T033 [US4] In `src/ailf/pipelines/drift/pipeline.py`, remove the embedded forecast HTML UI (`_UI_HTML`), the `/forecast/*` endpoints, and the `/changepoint/run` bridge (and their lazy `llm_reason`/`fallback`/`run_scenario` imports). KEEP the `app` object and all `/drift/config` + `/drift/generate/*` + `/docs` dataset-generation routes intact. (research R8, FR-033/035.)
- [X] T034 [P] [US4] Delete `src/ailf/pipelines/drift/llm_reason.py` (demo-only; only referenced by the now-removed endpoints). (After T033.)
- [X] T035 [P] [US4] Delete `src/ailf/pipelines/drift/fallback.py` (demo-only; only referenced by the now-removed endpoints). (After T033.)
- [X] T036 [US4] Verify cleanup: run `uv run pytest tests/pipelines/drift/test_api.py -q` (must stay green) and grep the repo to confirm no remaining importers of `streamlit_app`/`llm_reason`/`fallback`. (FR-036, SC-007.)

**Checkpoint**: Single UI entry point; dataset-generation API and all other tests still green.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, docs, and optional hardening.

- [ ] T037 [P] Run the full `quickstart.md` validation for all four user stories (scenario live run, custom CSV + negative cases, instrument toggles reflected in stream, single-entry-point cleanup check).
- [X] T038 Run `uv run pytest -q` and confirm the entire suite is green — core tests included (Constitution Principle VII core-change gate).
- [X] T039 [P] Update `.env.example` to document the Anthropic-preferred / Bedrock-fallback order, and add a one-line pointer (README or `CLAUDE.md` run notes) to launch via `uv run streamlit run src/ailf/ui/app.py`.
- [X] T040 [P] (Optional, non-blocking) Harden the Anthropic client in `src/ailf/core/models/llm.py` to construct the `anthropic.Anthropic` client once in `AnthropicStructuredClient.__init__` and reuse it across invokes (true once-per-role init); leave the `httpx.Client(verify=False)` SSL behavior as-is (out of scope). (research R4.)
- [ ] T041 Export this feature's Claude session(s) to `sessions/<iisc-username>/` (constitution session-transparency gate).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all user stories.**
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on Foundational; independent of US1 (adds the custom-CSV branch + 3-fraction split).
- **US3 (Phase 5)**: depends on Foundational; independent of US1/US2 (adds toggle controls).
- **US4 (Phase 6)**: depends only on Setup conceptually (pure cleanup); can run in parallel with US1–US3.
- **Polish (Phase 7)**: depends on the user stories being complete (T037/T038 after US1–US4).

### Within Each Story

- Tests are written first and must FAIL before implementation (Principle II).
- Foundational: T008 → T009 (same file, sequential); T012 depends on T006+T008.
- US1: T016 (region data) → T019 (chart); T020 → T021 → T022 (all `app.py`, sequential).
- US2: T025 (split) and T026 (validation) before T027 (app branch).
- US3: T029 + T030 before T031; T028 validated once T029/T030 land.
- US4: T033 before T034/T035.

### Parallel Opportunities

- **Foundational tests**: T002, T003, T004, T005 in parallel (different files).
- **Foundational impl**: T006, T007, T010, T011 in parallel (different files); T008→T009 sequential; T012 after T006/T008.
- **US1 tests**: T013, T014, T015 in parallel.
- **US1 impl**: T016, T017, T018 in parallel; then T019; then T020→T021→T022.
- **US2 tests**: T023, T024 in parallel.
- **US4 deletions**: T032 in parallel with the rest of US4; T034/T035 in parallel after T033.
- **Cross-story**: with capacity, US4 (cleanup) can proceed alongside US1–US3 since it touches only `drift/` files.

---

## Parallel Example: Foundational Phase

```bash
# Write the foundational failing tests together:
Task: "tests/core/events/test_queue_sink.py"
Task: "tests/core/config/test_provider_detection.py"
Task: "tests/ui/test_config_builder.py"
Task: "extend tests/pipelines/changepoint/test_event_stream.py (live emission)"

# Then implement the independent seams together:
Task: "QueueEventSink in src/ailf/core/events/sink.py"
Task: "provider flip in src/ailf/core/config/resolve.py"
Task: "model catalog in src/ailf/ui/models.py"
Task: "to_override_dict in src/ailf/ui/config_builder.py"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup → Phase 2 Foundational (CRITICAL — the live-stream + provider seams).
2. Phase 3 US1.
3. **STOP and VALIDATE**: run a built-in scenario, watch the live stream, confirm verdict + interactive graph.
4. Demo-ready.

### Incremental Delivery

1. Setup + Foundational → seams ready.
2. US1 → live scenario run + verdict + graph (MVP) → demo.
3. US2 → custom CSV → demo.
4. US3 → instrument toggles → demo.
5. US4 → single coherent interface (cleanup) → final presentation form.
6. Polish → full suite green + docs.

### Core-change discipline (Principle VII)

T007, T008, T009, T016, T025 touch shared core/pipeline files. Keep `uv run pytest` green throughout; the foundational tests (T002–T005) are the regression guard, and T038 is the final gate.

---

## Notes

- [P] = different files, no incomplete-task dependency.
- [Story] label maps each task to its user story for traceability.
- The thin Streamlit shell (`app.py`) and threading glue are validated via `quickstart.md`; all extracted pure helpers (`config_builder`, `event_view`, `verdict`, `chart`, `models`) and every backend seam are unit-tested.
- Worker thread never calls `st.*` or writes `st.session_state` — queue (events) and holder (result/error) are the only cross-thread channels.
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.

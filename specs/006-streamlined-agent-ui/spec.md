# Feature Specification: Streamlined Agent UI for Final Presentation

**Feature Branch**: `006-streamlined-agent-ui`

**Created**: 2026-06-22

**Status**: Draft

**Input**: User description: "Clean up the UI code and streamline it into one pathway for final presentation. Left control pane (start button, dataset choice of selected scenario or custom CSV, visual + reasoning model options, 13-diagnostic bundle, agent-tools selection); right main area (backend-command metadata, live streaming of backend events in expandable boxes, then a final interactive graph with a 'who won' verdict). Backend: initialize the model client once per run, preferring the Anthropic API when configured and falling back to AWS Bedrock otherwise."

## Overview

The system already has a working agent-in-the-loop changepoint pipeline that emits a rich, ordered stream of typed events as it runs (config resolution, split, detection, baselines, diagnostics, visual inspection, each agent decision and validation outcome, final evaluation, and run completion). What it lacks is a single, presentation-ready interface a non-technical observer (e.g. a professor) can drive end-to-end.

Today three overlapping, confusingly-named UI surfaces exist — a large Streamlit app and an embedded HTML page, both physically located inside the `drift` directory, plus standalone non-agent demo modules they depend on. Only one underlying pipeline is a real agent pipeline. The current UI does not consume the event stream at all; it reconstructs progress by reading files off disk after the run finishes.

This feature replaces all of that with **one** streamlined interface that lives in a neutral location, runs only the real agent pipeline, **streams the agent's reasoning live as it happens**, and ends on a clear verdict plus an interactive comparison graph. It also makes a small, focused backend change so the live stream and the model-provider selection behave the way a clean demo needs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a built-in scenario and watch the agent work live (Priority: P1)

A presenter opens the interface, picks one of the curated built-in scenarios from a dropdown, leaves the default models and diagnostic/tool selections, and clicks **Start**. The right-hand area immediately shows what is being run and then streams the backend's events one by one as they occur — configuration resolved, data split, changepoints detected, baselines computed, diagnostics, the agent's visual inspection, and each decision/validation iteration as the agent reasons. When the run completes, a verdict banner declares the winner and an interactive graph appears.

**Why this priority**: This is the core demo. Without it there is nothing to present. It exercises the whole chain — control pane → live event stream → final verdict + graph — against known, curated data, which is the safest path for a live audience.

**Independent Test**: Select a known scenario, click Start, and confirm that (a) events appear incrementally rather than all at the end, (b) each agent decision and its accept/reject outcome is individually inspectable, and (c) a verdict and interactive graph render on completion. Delivers a complete, watchable agent run on its own.

**Acceptance Scenarios**:

1. **Given** the interface is open with a built-in scenario selected, **When** the presenter clicks Start, **Then** the right area first displays the command/run metadata describing what is being executed, then renders backend events incrementally in the order the backend emits them.
2. **Given** a run is streaming, **When** the agent proposes an intervention and the guardrail validates it, **Then** that decision (chosen tool, parameters, rationale, expected effect) and its validation outcome (accepted / rejected and why) each appear as their own inspectable, expandable entry while the run is still in progress — not only after it finishes.
3. **Given** a run has finished, **When** the presenter looks at the top of the results, **Then** a verdict banner names the winning method (agent vs. full-history Prophet vs. naive) by lowest test error and states the margin over the naive baseline.
4. **Given** a run has finished, **When** the presenter views the graph, **Then** an interactive chart shows recent training history plus the full forecast region, with the three forecast lines, the actuals, train/validation/test regions distinguished, and changepoint markers, and supports zoom, pan, hover, and a clear legend.

---

### User Story 2 - Bring your own data via custom CSV (Priority: P2)

An observer wants to try their own series. They choose the **Custom CSV** option, see a clear note that the file must contain a time column named `ds` and a value column named `y`, upload the file, set train/validation/test split fractions that must sum to 1, optionally adjust advanced detection settings, and run the same live experience as Story 1.

**Why this priority**: It makes the demo interactive and credible beyond the curated set, but the curated path (P1) must work first and is the safer live default.

**Independent Test**: Upload a small two-column CSV with `ds`/`y`, set splits to `0.8 / 0.1 / 0.1`, run, and confirm the pipeline executes and produces a verdict + graph. Reject a file missing the required columns or splits that do not sum to 1, with a clear message, before any run starts.

**Acceptance Scenarios**:

1. **Given** the Custom CSV option is selected, **When** the observer views the data controls, **Then** the required column contract (`ds` time column, `y` value column) is stated visibly (help text and/or a help icon) and the train/validation/test fraction inputs are enabled.
2. **Given** a custom CSV is chosen, **When** the three split fractions do not sum to 1 (within a small tolerance), **Then** Start is blocked or the inputs are flagged with an explanatory message, and no run begins.
3. **Given** an uploaded file lacks a `ds` or `y` column, **When** the observer attempts to start, **Then** the interface reports the contract violation clearly and does not start a broken run.
4. **Given** a valid custom CSV and valid splits, **When** the observer clicks Start, **Then** the run streams and concludes exactly as in Story 1, using the observer's split fractions and any advanced detection settings supplied.

---

### User Story 3 - Configure the agent's instruments before running (Priority: P2)

Before starting, the presenter narrows what the agent may see and use: which of the 13 diagnostics are exposed to the agent, which intervention tools are on the menu, whether the visual-analysis step runs, and which models play the visual and reasoning roles. These selections shape the run that then streams live.

**Why this priority**: It is what makes the demo a teaching tool — showing how the agent behaves with more or fewer instruments — but the system must run with sensible defaults (Story 1) regardless of whether anyone touches these controls.

**Independent Test**: Toggle off several diagnostics and one or more tools, turn the visual-analysis step off, start a run, and confirm via the streamed events that the hidden diagnostics are not exposed to the agent, the disabled tools are absent from the agent's menu, and no visual-inspection step occurs.

**Acceptance Scenarios**:

1. **Given** the diagnostic bundle controls, **When** the presenter disables a subset of the 13 diagnostics, **Then** the run treats exactly those as hidden from the agent and the rest as exposed, and this is reflected in the streamed configuration/diagnostics events.
2. **Given** the agent-tools controls, **When** the presenter disables one or more selectable tools, **Then** those tools do not appear on the agent's menu for the run, while the always-available fallback tool remains present.
3. **Given** the visual-analysis toggle is off, **When** the run executes, **Then** the visual-inspection step is skipped entirely (no chart image is produced or sent to a model) and the visual-model choice is treated as irrelevant for that run.
4. **Given** the model controls, **When** the presenter picks a visual model and a reasoning model from the offered choices, **Then** the run uses those roles, and the backend selects the correct concrete model identifier for whichever provider it initializes.

---

### User Story 4 - One coherent interface, no pathway confusion (Priority: P1)

A consumer of the app — a professor or reviewer — interacts with a single, coherent interface and is never exposed to internal use-case vocabulary ("drift", "changepoint", "anomaly") or to alternate, half-built run modes. There is exactly one way to run, presented as "the forecasting agent."

**Why this priority**: The stated goal is a clean final presentation. Multiple overlapping pathways and leaked internal naming directly undermine that and create live-demo risk (wrong toggle, dead path).

**Independent Test**: Launch the interface and confirm there is a single start control and a single run pathway, with no selector for alternate detection engines or unrelated demo modes, and no internal use-case names presented to the user. Confirm the old UI surfaces no longer launch as competing entry points.

**Acceptance Scenarios**:

1. **Given** the streamlined interface, **When** a consumer surveys the controls, **Then** there is one Start control and one run pathway, with no choice between competing detection engines or demo modes.
2. **Given** the repository after this feature, **When** a developer looks for UI entry points, **Then** the previous overlapping UI surfaces and the demo-only modules that only they depended on are gone, leaving the single streamlined interface as the entry point.
3. **Given** the streamlined interface, **When** a consumer reads the labels and help text, **Then** the experience is framed around forecasting/diagnosis and the agent, without requiring the user to understand internal pipeline names.

---

### Edge Cases

- **Model provider not configured**: neither an Anthropic API key nor Bedrock credentials are available. The run must fail with a clear, early, human-readable message rather than a cryptic mid-run error.
- **Run errors mid-stream**: a backend stage raises. The interface must surface the failed stage and its error in the stream and stop cleanly, leaving already-streamed events visible, rather than hanging or silently dying.
- **Custom CSV degeneracies**: too few rows for the requested split (a segment would be empty), non-chronological or duplicate timestamps, missing/empty values, or a frequency that does not match the advanced detection settings. Each should be prevented up front or surfaced as a clear message, never a broken half-run.
- **Long-running or stalled run**: the agent loop runs several iterations or the model is slow. The interface must keep already-streamed events visible and indicate that work is still in progress.
- **No intervention beats the baseline**: the agent never clears the guardrail. The verdict must still render honestly (e.g. a baseline wins) with the comparison intact.
- **Oversized event payloads**: some events carry large payloads that the backend offloads to a side reference. The interface must still display such events meaningfully without breaking the stream.
- **Visual analysis on but the run is otherwise minimal**: the visual step must appear in the stream when enabled and be absent when disabled, consistently with Story 3.

## Requirements *(mandatory)*

### Functional Requirements

#### Single streamlined interface

- **FR-001**: The system MUST provide exactly one user-facing interface for running the forecasting agent, with a single Start control and a single run pathway.
- **FR-002**: The interface MUST be presented in neutral, user-facing terms and MUST NOT require the consumer to understand or select among internal use-case names ("drift", "changepoint", "anomaly").
- **FR-003**: The interface MUST be organized as a left control pane (inputs and configuration) and a right main area (run metadata, live event stream, and final results).
- **FR-004**: The interface MUST be a thin client over the existing importable core/pipeline: it MUST NOT re-implement forecasting, diagnosis, agent reasoning, or evaluation logic, and MUST obtain all results from the core/pipeline.

#### Left control pane — controls

- **FR-005**: The control pane MUST provide a Start control that begins a run using the current selections.
- **FR-006**: The control pane MUST let the user choose the dataset by exactly one of two mutually exclusive options: (a) a built-in scenario, or (b) a custom CSV upload.
- **FR-007**: For the built-in scenario option, the interface MUST present the available scenarios sourced from the project's scenario metadata, and the run MUST use the train/validation/test split defined for that scenario by its metadata (the user does not set splits in this option).
- **FR-008**: For the custom CSV option, the interface MUST clearly state (via help text and/or a help icon) that the file must contain a time column named `ds` and a value column named `y`, and MUST enable train, validation, and test fraction inputs.
- **FR-009**: For the custom CSV option, the three split fractions MUST be required to sum to 1 (within a small tolerance); if they do not, the interface MUST prevent the run and explain why.
- **FR-010**: For the custom CSV option, the interface MUST validate that the uploaded data satisfies the required column contract before starting a run, and MUST surface a clear message and block the run if it does not.
- **FR-011**: For the custom CSV option, the interface MUST expose advanced detection settings (the seasonal period and the number of changepoints to detect) as optional inputs with sensible defaults, applied only to custom-CSV runs.
- **FR-012**: The control pane MUST provide a "visual model" selector and a "reasoning agent model" selector, each offering a small set of valid model choices (at minimum the current-generation Sonnet and Opus options); the user picks a role-appropriate model and the backend resolves the concrete model identifier for whichever provider it uses.
- **FR-013**: The control pane MUST provide controls to individually enable/disable each of the 13 diagnostics in the diagnostic bundle, determining which diagnostics are exposed to the agent for the run.
- **FR-014**: The control pane MUST provide controls to individually enable/disable the selectable agent intervention tools, determining the agent's tool menu for the run; the always-available fallback tool MUST remain present and MUST NOT be disable-able.
- **FR-015**: The control pane MUST provide a visual-analysis on/off toggle. When off, the run MUST skip the visual-inspection step entirely and the visual-model selection MUST have no effect; when on, the visual-inspection step MUST run using the selected visual model.

#### Right main area — run metadata and live streaming

- **FR-016**: When a run starts, the right area MUST first display metadata describing what is being run (a human-readable summary of the equivalent backend invocation and the chosen configuration).
- **FR-017**: The interface MUST consume the backend's typed event stream and display events incrementally, in the order emitted, as the run progresses.
- **FR-018**: The agent's reasoning iterations — each decision (chosen tool, parameters, rationale, expected effect) and each validation outcome (accepted/rejected and the reason) — MUST appear individually and live during the run, not only as a batch after the run completes.
- **FR-019**: Each streamed event MUST be individually inspectable (e.g. an expandable entry) so an observer can verify its details, including its stage, status, and payload.
- **FR-020**: The interface MUST handle a run that errors mid-stream by surfacing the failing stage and its error and stopping cleanly, while keeping previously streamed events visible.
- **FR-021**: The interface MUST display events whose payloads were offloaded by the backend (oversized payloads) without breaking the stream.
- **FR-022**: Pre-final events MUST NOT expose hidden-test data; the interface MUST rely on the backend's existing guarantee that test metrics appear only at final evaluation and run completion, and MUST NOT attempt to read or display hidden-test results before then.

#### Right main area — final verdict and interactive graph

- **FR-023**: On run completion, the interface MUST display a verdict banner naming the winning method among the agent, the full-history baseline, and the naive baseline, decided by lowest test error (MAE), and stating the margin relative to the naive baseline.
- **FR-024**: On run completion, the interface MUST display an interactive graph that overlays the three forecasts (agent, full-history baseline, naive) and the actuals over a window comprising recent training history plus the full forecast region.
- **FR-025**: The graph MUST visually distinguish the train, validation, and test regions and MUST mark detected changepoints.
- **FR-026**: The graph MUST support interactive zoom, pan, and hover, and MUST include a clear legend identifying every series and region.

#### Backend changes

- **FR-027**: The backend MUST initialize the model client once per run, selecting the provider by preferring the Anthropic API when its credentials are configured and otherwise falling back to AWS Bedrock. (This reverses the current detection order, which prefers Bedrock.)
- **FR-028**: The chosen provider MUST drive a single, clean initialization for both model roles (visual and reasoning) for the run, with the user-selected role models resolved to the correct concrete identifiers for that provider.
- **FR-029**: If neither provider is configured, the run MUST fail with a clear, human-readable message surfaced to the interface, rather than a cryptic or deferred error.
- **FR-030**: The backend agent loop MUST emit its in-loop events (visual inspection, each decision iteration, each validation outcome, and final evaluation) through a live mechanism as they occur, so a consumer can render them in real time, while preserving the existing event envelope, ordering guarantees, monotonic sequence, and no-leakage guarantees.
- **FR-031**: The change enabling live in-loop emission MUST NOT alter the meaning, schema, or causal ordering of existing events, and MUST keep the existing event-stream tests and core tests green.
- **FR-032**: The interface MUST run the pipeline in-process (in a background worker) and receive events through an in-memory channel as they are emitted, without requiring a separate server process or polling files on disk for liveness.

#### Cleanup and consolidation

- **FR-033**: The previous overlapping UI surfaces MUST be removed: the prior large Streamlit application and the embedded HTML/in-browser UI served by the backend.
- **FR-034**: The demo-only modules that existed solely to support those removed UI surfaces (the standalone non-agent detection module and the non-agent fallback-pipeline module) MUST be removed, provided nothing still required is left depending on them.
- **FR-035**: Removal MUST NOT delete or break the agent pipeline, the shared core, the dataset-generation services, or the scenario data and fixtures that the streamlined interface and the pipeline rely on.
- **FR-036**: After cleanup there MUST be a single discoverable UI entry point, and the removed surfaces MUST no longer be launchable as competing entry points.

### Key Entities *(include if feature involves data)*

- **Run configuration**: the user's selections for a run — dataset choice (scenario id, or uploaded series plus split fractions and advanced detection settings), visual and reasoning model roles, the enabled/disabled diagnostics, the enabled/disabled tools, and the visual-analysis on/off flag.
- **Scenario**: a curated, named dataset with metadata defining its series and its train/validation/test split; the source for the built-in dataset option.
- **Custom series**: a user-uploaded time series with a `ds` time column and a `y` value column, partitioned by user-supplied train/validation/test fractions.
- **Run event**: one typed, ordered item in the backend's stream — carrying a stage, a status, a sequence position, a timestamp, and a payload — covering configuration, split, detection, baselines, diagnostics, visual inspection, agent decisions, validation outcomes, final evaluation, and completion.
- **Verdict**: the end-of-run determination of the winning method by lowest test error, with the comparison among the agent and the baselines and the margin over the naive baseline.
- **Comparison graph**: the interactive final visualization overlaying the three forecasts and the actuals with train/validation/test regions and changepoint markers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A presenter can run a built-in scenario end-to-end — open, select, start, watch the live stream, and reach a verdict and graph — without editing code or files and without any command-line step.
- **SC-002**: During a run, the agent's individual decision and validation iterations become visible while the run is still in progress (before completion is reported), confirming live streaming rather than batch-at-end display.
- **SC-003**: A user can upload a conforming two-column custom CSV, set splits that sum to 1, and complete a full run; a non-conforming file or invalid splits are caught before any run starts, with a message that states the exact problem.
- **SC-004**: Every one of the 13 diagnostics and every selectable tool can be individually toggled, and the effect of those toggles is observable in the streamed run (hidden diagnostics not exposed; disabled tools absent from the menu; visual step present only when enabled).
- **SC-005**: On completion, 100% of runs display a verdict naming the winner by lowest test error and an interactive graph with zoom, pan, hover, a legend, the three forecasts, actuals, distinguished train/validation/test regions, and changepoint markers.
- **SC-006**: With only Anthropic API credentials present, runs use the Anthropic API; with only Bedrock credentials present, runs use Bedrock; with neither present, the run fails with a clear message before doing substantive work — verified across the three configurations.
- **SC-007**: The repository exposes exactly one UI entry point after this feature; the previously existing UI surfaces and the demo-only modules they depended on are gone, and the remaining agent pipeline, shared core, dataset services, and scenario fixtures still function (existing core and event-stream tests remain green).
- **SC-008**: A first-time observer can identify what to do (choose data, optionally adjust, Start) and interpret the outcome (who won and why, from the graph and verdict) without being exposed to internal use-case names.

## Assumptions

- The streamlined interface lives in a new neutral location (`src/ailf/ui/`) and is treated as a thin front-end client, not a pipeline; per the project's principles it MAY depend on the agent pipeline and shared core (the no-cross-import rule constrains pipelines, not front-end consumers).
- Only the changepoint agent pipeline is a real agent pipeline today; it is the single pipeline this interface drives. The "drift" and "anomaly" directories are not peer agent pipelines (drift hosts UI/demo code and a dataset service; anomaly is a deterministic script).
- The required input contract is exactly two columns named `ds` (time) and `y` (value); this is verified in the data-loading path and is not user-configurable.
- The default custom-CSV split is `0.8 / 0.1 / 0.1` (train/validation/test) and default advanced detection settings are a seasonal period of 365 and 3 changepoints to detect; these match the pipeline's current defaults and are surfaced as editable defaults.
- The event stream already carries everything the final graph and verdict need (three forecast series, actuals, train/validation/test boundaries, changepoint markers, per-method test metrics, and the winner); no new persisted artifacts are required for the results view.
- The offered model choices are current-generation Claude options (at minimum a Sonnet and an Opus tier); the backend maps the selected role model to the correct concrete identifier for the active provider, reusing the existing identifier-mapping logic.
- "Recent training history plus the full forecast region" means the graph defaults to a trailing window of training context (rather than the entire series from its start) followed by the complete forecast region, to keep the forecast comparison legible while preserving context.
- Removing the demo-only modules is in scope; the drift dataset-generation service and the anomaly directory are left in place (only the old UI surfaces and the modules that solely supported them are removed).
- The interface targets a single concurrent run for a live presentation; multi-user concurrency, authentication, and deployment hardening are out of scope for this feature.
- This feature touches the shared core (live in-loop event emission and provider-selection order); those changes are review-gated and must keep core tests green, per the project's core-change gate.

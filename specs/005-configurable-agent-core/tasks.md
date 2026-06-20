---
description: "Task list for Configurable Agent Core (POC → Core Promotion)"
---

# Tasks: Configurable Agent Core (POC → Core Promotion)

**Input**: Design documents from `/specs/005-configurable-agent-core/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (config_schema,
tool_registry, event_contract, graph_engine, split_resolver), quickstart.md

**Tests**: REQUIRED. Constitution Principle II (Test-First for Deterministic Logic) is **binding** —
the POC exemption no longer applies once code enters `src/ailf/core` / a promoted pipeline. Every
deterministic unit is built failing-then-passing. The non-deterministic LLM stages (visual, decision)
are NOT unit-tested on exact output (Principle III); they are covered by trace-invariant + leakage
tests with a `FakeModelWrapper`, plus an opt-in golden-set eval.

**Organization**: Tasks are grouped by user story. This is a **promotion**: US1 (P1) is the
deterministic end-to-end spine that reproduces the POC; US2–US6 are configurability/observability
increments that build on US1. Dependencies reflect that reality.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US6 (Setup/Foundational/Polish have no story label)
- File paths are exact (per `plan.md` → Project Structure)

## Conventions

- Core lives in `src/ailf/core/`; the changepoint pipeline in `src/ailf/pipelines/changepoint/`.
- Tests mirror packages: `tests/core/**`, `tests/pipelines/changepoint/**`.
- Commands: `uv run pytest <path>`; run a single scenario via
  `uv run python -m ailf.pipelines.changepoint.pipeline --scenario <id>`.
- The POC under `pocs/changepoint/` is **left untouched** (provenance + parity oracle).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffolding, dependency pin, fixtures, and the parity oracle — captured before any code moves.

- [X] T001 Create core package tree with `__init__.py` files: `src/ailf/core/{config,agent,backtest,metrics,models,events,prompts,reporting}/` (reuse existing `agent/models/backtest/metrics/reporting/prompts` stubs; add `config/` and `events/`)
- [X] T002 Create changepoint pipeline package files (empty/typed stubs to be filled): `src/ailf/pipelines/changepoint/{scenarios,datasets,detector,diagnostics,interventions,baselines,schemas,viz,pipeline}.py` and `prompts/`, `data/` dirs
- [X] T003 Pin `prophet==1.3.0` (the installed/working version) in `pyproject.toml`, run `uv sync`, and commit the updated `uv.lock` (parity stability — research Decision 17; the exact pin must match the version the oracle + promoted code both run on)
- [X] T004 [P] Copy committed fixtures into the pipeline: `pocs/changepoint/data/csv/*.csv` and `scenario_metadata.json` → `src/ailf/pipelines/changepoint/data/{csv/,scenario_metadata.json}`
- [X] T005 [P] Create test tree dirs + `conftest.py`: `tests/core/{config,agent,backtest,metrics,events,parity}/`, `tests/pipelines/changepoint/fixtures/`
- [X] T006 Verify `reports/changepoint/<run_id>/` artifact dirs are gitignored (already covered by the existing `reports/*` rule in `.gitignore`; add an explicit entry only if that rule changes)
- [X] T007 Capture the POC parity oracle from the **un-promoted POC**: write `tests/pipelines/changepoint/capture_poc_parity.py` that runs each of the 5 scenarios through `pocs/changepoint` (seed 1729) and records detected changepoints (index+trend_delta), full-history-Prophet val metrics, every naive candidate val metrics + `selected_window_start`, and the two baselines' test metrics → committed `tests/pipelines/changepoint/fixtures/poc_parity_reference.json` (research Decision 18)

**Checkpoint**: packages scaffolded, prophet pinned, fixtures in place, parity oracle committed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting primitives every user story depends on. No story work begins until these exist.

**⚠️ CRITICAL**: Blocks all user stories.

- [X] T008 [P] Define core exceptions: `ConfigError`/`SplitError` in their owning modules and `StageError` in `src/ailf/core/agent/runtime.py` (or a shared `core/agent/errors.py`); `ToolBoundsError` in `src/ailf/core/agent/registry.py`; `ModelUnavailableError` in `src/ailf/core/models/llm.py` (data-model.md → Exceptions)
- [X] T009 [P] Write failing test for the strict JSON serializer in `tests/core/events/test_leakage.py`: `to_json(obj)` raises `TypeError` on numpy arrays, `pd.Timestamp`, and arbitrary handles (no `default=str` coercion)
- [X] T010 Implement `to_json` strict serializer + `assert_no_leakage(payload)` in `src/ailf/core/events/leakage.py` (import-clean; no emitter deps) — make T009 pass (research Decision 16)
- [X] T011 [P] Write failing closed-form tests for forecast metrics in `tests/core/metrics/test_metrics.py` (MAE/RMSE/WAPE/sMAPE on hand-computed vectors)
- [X] T012 Implement `metrics()` (MAE/RMSE/WAPE/sMAPE) in `src/ailf/core/metrics/metrics.py`, shaped as an extension point for MASE/PI-coverage (deferred — plan Deviation 1) — make T011 pass
- [X] T013 [P] Promote the LLM provider wrapper to `src/ailf/core/models/llm.py`: `ModelWrapper` with `invoke_structured_text`/`invoke_structured_with_image` (generic pydantic TypeVar), `build_visual_model`, `build_decision_model` (renamed from `build_react_model`), `ModelUnavailableError` + no-silent-fallback wrapping; **only** module importing `langchain_aws` (research Decision 13, FR-036)
- [X] T014 [P] Add `FakeModelWrapper` test double in `tests/core/conftest.py`: returns canned pydantic objects, records `(prompt, image_path)` seen (for leakage asserts), can raise `ModelUnavailableError`
- [X] T015 [P] Write failing test for the generic prompt loader in `tests/core/prompts/test_loader.py` (loads `<name>_vN.md`, fills `{{placeholder}}`)
- [X] T016 Implement `load_prompt(dir, name, version)` + placeholder fill in `src/ailf/core/prompts/loader.py` — make T015 pass

**Checkpoint**: serializer, metrics, LLM wrapper + fake, prompt loader, exceptions ready.

---

## Phase 3: User Story 1 — Promote the changepoint agent into a reusable, serializable core (Priority: P1) 🎯 MVP

**Goal**: A single golden-config scenario runs end-to-end through the core entrypoint and reproduces
the POC's deterministic baseline + validation metrics, producing the POC artifact set (agent-context
image, forecast comparison plot, `metrics.json`, `agent_trace.json`).

**Independent Test**: `uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality`
with golden config → artifact set present; `uv run pytest tests/core/parity` → deterministic metrics
match the oracle (floats `1e-6`, structural fields exact). Core contains zero changepoint/Prophet/UI symbols.

### Config (load golden defaults only — override machinery is US2)

- [X] T017 [P] [US1] Write failing tests for config schema round-trip in `tests/core/config/test_schema.py` (`EffectiveConfig`/`ModelConfig`/`SplitSpec`/`ConfigOverride` `to_dict`/`from_dict` lossless)
- [X] T018 [US1] Implement frozen config dataclasses in `src/ailf/core/config/schema.py` (data-model.md → Configuration domain) — make T017 pass
- [ ] T019 [US1] Author the pipeline defaults file `src/ailf/pipelines/changepoint/config.yaml` (models, `aws_region`, `visual_analysis_enabled: true`, 13 diagnostics, 5 tools + `full_history_default`, `split: {source: golden}`, `seed: 1729`) per contracts/config_schema.md
- [ ] T020 [US1] Implement `src/ailf/core/config/loader.py`: read `config.yaml` → `EffectiveConfig` (golden split, derive `enabled_diagnostics`/`enabled_tools`); test in `tests/core/config/test_loader.py`

### Split resolver (golden path) + scenario loading

- [X] T021 [P] [US1] Write failing tests for the split golden path in `tests/core/backtest/test_split.py`: `ResolvedSplit` invariants + nested-view derivation (`fit_end`, `train_end`, test range); `resolve_split(None, n, golden)` returns golden verbatim
- [X] T022 [US1] Implement `src/ailf/core/backtest/split.py` golden path: `ResolvedSplit`, `SplitProvenance`, `resolve_split` (None→golden), `SplitError` (contracts/split_resolver.md) — make T021 pass
- [X] T023 [US1] Implement `src/ailf/pipelines/changepoint/datasets.py`: `golden_split_from_metadata(meta)→ResolvedSplit` (rejects non-positive train_rows) + committed-CSV fixture loading
- [X] T024 [US1] Write the **golden-reproduction test** `tests/pipelines/changepoint/test_split_golden.py`: derived `train_end`/`fit_end`/test indices equal the POC `SeriesSplit` for all 5 scenarios (gates SC-001 before further split work)
- [X] T025 [US1] Implement `src/ailf/pipelines/changepoint/scenarios.py`: `Scenario` + pandas `SeriesSplit` adapter built from `ResolvedSplit`; `load_scenario`; `audit_only` kept strictly off the agent path; test in `tests/pipelines/changepoint/test_scenarios.py` (incl. audit-not-exposed assertion)

### Detector + diagnostics

- [X] T026 [P] [US1] Write KNOWN-injected-ground-truth tests in `tests/pipelines/changepoint/test_detector.py`: precision/recall/FPR vs `audit_only.true_injected_boundaries` (±15-row window; event-pair starts → nearest detected) + clean single-effect synthetic series (research Decision 18)
- [X] T027 [US1] Implement `src/ailf/pipelines/changepoint/detector.py` (deterministic Prophet trend-delta changepoints, honors `n_changepoints_to_detect`) — make T026 pass
- [X] T028 [P] [US1] Write failing tests in `tests/pipelines/changepoint/test_diagnostics.py`: all 13 fields computed; `to_agent_dict(enabled)` filters; **golden byte-identity** of the all-enabled filtered view vs the POC `asdict` (parity guard)
- [X] T029 [US1] Implement `src/ailf/pipelines/changepoint/diagnostics.py` (13-field `DiagnosticsBundle`; full bundle always computed; `to_agent_dict(enabled: set[str])`) — make T028 pass

### Tool registry + gate + the five tools

- [ ] T030 [P] [US1] Write failing tests for registry types in `tests/core/agent/test_registry.py`: `ToolParamSchema`/`ToolSpec`/`Proposal.action_signature`; `validate_params` raises `ToolBoundsError`; `for_run(enabled)` prunes both `menu()` and `allowed_names()`
- [ ] T031 [US1] Implement `src/ailf/core/agent/registry.py`: `ToolParamSchema`, `ToolSpec` (incl. non-serialized `invoker`/`precondition`), `ToolRegistry` (`register`/`for_run`/`menu`/`allowed_names`/`validate_params`/`invoke`), `Proposal`, `ToolContext`/`ToolResult` shapes, `ToolBoundsError` (contracts/tool_registry.md) — make T030 pass
- [ ] T032 [P] [US1] Write failing tests for the changepoint tools in `tests/pipelines/changepoint/test_interventions.py`: each tool's `invoke(ToolContext, params)→yhat` purity (no validation access), bounds via `ToolSpec.allowed`, holiday `precondition` gate, `full_history_default` always-on
- [ ] T033 [US1] Implement `src/ailf/pipelines/changepoint/interventions.py`: `register_changepoint_registry()` registering the 5 structural tools (grids → `allowed` data) + the always-on `full_history_default` fallback + holiday precondition; invokers reconstruct pandas/Prophet from `ToolContext` — make T032 pass
- [ ] T034 [P] [US1] Write failing tests for the gate in `tests/core/backtest/test_gate.py`: validate→precondition→invoke→MAE→**strictly** beat naive; failure classification (bounds/precondition/not-beat = normal rejection; `invoke` crash = stage failure)
- [ ] T035 [US1] Implement `src/ailf/core/backtest/gate.py` (`evaluate_on_validation`/`evaluate_on_test`; sole scoring authority; agent never sees the score) — make T034 pass (FR-025/FR-034)

### Baselines + LLM schemas + prompts

- [X] T036 [P] [US1] Write failing tests for baselines in `tests/pipelines/changepoint/test_baselines.py` (full-history Prophet val metrics; naive-window candidate selection by val MAE)
- [X] T037 [US1] Implement `src/ailf/pipelines/changepoint/baselines.py` (full-history + naive workflow, `CandidateResult`, `NaiveWorkflowResult`, `fit_predict_prophet` helper) — make T036 pass
- [ ] T038 [P] [US1] Add `src/ailf/pipelines/changepoint/schemas.py`: pydantic `VisualInspectionResult` + `InterventionChoice` (LLM I/O only)
- [ ] T039 [P] [US1] Promote `prompts/visual_inspection_v1.md` UNCHANGED; author `prompts/react_decision_v2.md` with a `{{tool_menu}}` placeholder (visual-on arm; menu generated from `for_run()` registry — research Decision 7)

### Agent engine + nodes + runtime + state (visual-ON graph)

- [ ] T040 [P] [US1] Add `src/ailf/core/agent/state.py`: `AgentState` TypedDict (POC shape, `_take_right` reducer, langgraph-clean)
- [ ] T041 [US1] Add `src/ailf/core/agent/runtime.py`: `RunContext` (model handles, full diagnostics bundle, naive result, image path, `for_run()` registry, `visual_enabled`, `enabled_diagnostics`, emitter, `ResolvedSplit`, prompt ids)
- [ ] T042 [US1] Implement `src/ailf/core/agent/nodes.py`: `visual_inspection`, `diagnostics` (applies `to_agent_dict(enabled)`), `decision` (menu from registry; visual-first rationale; `StageError` invariant when visual on), `validation` (calls gate), `final_evaluation` (only place test indices read) — node bodies take `(state, RunContext)`
- [ ] T043 [US1] Implement `src/ailf/core/agent/engine.py`: `GraphSpec` + `build_agent_graph(spec, ctx)` compiling the **visual-on** topology onto LangGraph (`visual ∥ diagnostics → decision ↔ validation → final`); **only** module importing `langgraph`
- [ ] T044 [US1] Write graph wiring/routing test in `tests/core/agent/test_engine.py` using `FakeModelWrapper`: fan-out join, decision↔validation loop ≤5 iters, accepted/budget-exhausted routing, `final_evaluation` reads test only at the end

### Reporting + viz + entrypoint

- [ ] T045 [P] [US1] Implement `src/ailf/core/reporting/run_dir.py` (create `reports/changepoint/<run_id>/`; stamp seed) and `src/ailf/core/reporting/artifacts.py` (`write_metrics_json`, `write_agent_trace` via strict `to_json`, `write_report_md` narrative with before/after deltas vs naive + agent limitations — Principle VI)
- [ ] T046 [P] [US1] Implement `src/ailf/pipelines/changepoint/viz.py`: `render_agent_context` (training-only image) + `render_forecast_comparison` (human-only, post-final; never re-fed to an agent)
- [ ] T047 [US1] Implement `src/ailf/pipelines/changepoint/pipeline.py` single-scenario entrypoint: seed(1729) FIRST → deterministic prelude (detector, both baselines, diagnostics) → build visual-on `GraphSpec` from golden config → `build_agent_graph` + invoke (NullEmitter for now) → write artifacts (research Decision 17)
- [X] T048 [US1] Write the **SC-001 parity test** `tests/core/parity/test_poc_parity.py`: the promoted core path matches `poc_parity_reference.json` for all 5 scenarios (floats `1e-6`; structural fields exact)
- [ ] T049 [US1] Write end-to-end smoke test `tests/pipelines/changepoint/test_pipeline_smoke.py`: golden run with `FakeModelWrapper` produces the full artifact set (image, comparison plot, `metrics.json`, `agent_trace.json`)

**Checkpoint**: golden-config single-scenario run reproduces POC metrics end-to-end (MVP). 🎯

---

## Phase 4: User Story 2 — Drive agent behavior from configuration (Priority: P1)

**Goal**: A per-run override merges onto `config.yaml` defaults, is validated + lockstep-checked +
recorded; disabled diagnostics are computed-but-hidden and disabled tools are removed from menu+gate;
split knobs (ratios/absolute) take effect.

**Independent Test**: run once all-on, once with a diagnostic + a tool disabled → trace shows the
diagnostic hidden (still computed) and the tool removed; both runs record their resolved config.

- [ ] T050 [P] [US2] Write failing tests for override merge in `tests/core/config/test_resolve.py`: scalar replace; `diagnostics`/`agent_tools` key-wise partial merge (no new keys); `split` replace-as-a-unit; validation errors (unknown key, malformed value, empty model id, disabling `full_history_default`) each raise field-naming `ConfigError`
- [ ] T051 [US2] Implement `src/ailf/core/config/resolve.py`: deep-merge override → validate → return `EffectiveConfig`; `ConfigError` (contracts/config_schema.md) — make T050 pass
- [ ] T052 [US2] Implement `assert_config_in_lockstep(diagnostics_field_names, structural_tool_names, cfg_diagnostics, cfg_tools)` in `resolve.py` (symmetric diff → `ConfigError`; scopes tools to structural)
- [ ] T053 [US2] Write `tests/pipelines/changepoint/test_config_lockstep.py`: reflect `dataclasses.fields(DiagnosticsBundle)` + live registry structural names; assert committed `config.yaml` key-sets equal them exactly (SC-003)
- [ ] T054 [P] [US2] Write failing tests for split override in `tests/core/backtest/test_split.py` (extend): ratios sum-to-1.0 rounding (`floor_test_val_train_absorbs`); absolute units; ambiguous (ratio+absolute) → `SplitError`; segment≥1 / sum≤n / test>rows guards; **ratio vs equivalent-absolute resolve identically on n=1000 and n=1730** (SC-009)
- [ ] T055 [US2] Extend `src/ailf/core/backtest/split.py` with `SplitSpec` units (ratios/absolute) + rounding rule + ambiguity + validation — make T054 pass
- [ ] T056 [US2] Wire toggles + override into the entrypoint: `pipeline.py` accepts `--override` (JSON), resolves config, derives `enabled_diagnostics`/`enabled_tools`, builds `for_run()` registry projection, and threads them via `RunContext`; the `diagnostics` node hides via `to_agent_dict(enabled)`, the decision menu + gate use the projected registry (FR-013/FR-014)
- [ ] T057 [US2] Write integration test `tests/pipelines/changepoint/test_toggles.py` (with `FakeModelWrapper`): a disabled diagnostic is absent from the decision input but present in the full recorded bundle; a disabled tool is absent from menu + `allowed_names()` and never accepted; trace records `hidden_diagnostics`/`removed_tools`

**Checkpoint**: config overrides + toggles + split knobs take effect and are recorded.

---

## Phase 5: User Story 3 — Toggle the visual-analysis node (Priority: P1)

**Goal**: `visual_analysis_enabled: false` skips the visual stage entirely (no image produced/sent),
runs a diagnostics-only decision prompt, and still completes with a valid agent forecast; visual-on
preserves the visual-first ordering guarantee.

**Independent Test**: same scenario visual-on vs visual-off → on-trace has a visual result before the
decision; off-trace has no visual result, uses the diagnostics-only prompt, still yields a forecast + metrics.

- [ ] T058 [P] [US3] Author `prompts/react_decision_diagnostics_only_v1.md` (visual-off arm; `{{tool_menu}}` placeholder; rationale cites numeric diagnostics; no visual references)
- [ ] T059 [US3] Extend `src/ailf/core/agent/engine.py` to build a **linear** `GraphSpec` (`START → diagnostics → decision → validation → final`) when `visual_enabled` is false — omit the `visual_inspection` node entirely
- [ ] T060 [US3] In `pipeline.py`, when visual is off: select the diagnostics-only prompt, do **not** render or pass `agent_context.png`; record `visual_analysis_enabled=false` in the trace (FR-015)
- [ ] T061 [US3] Confirm the visual-first ordering invariant is enforced as a `StageError` (not a bare `assert`) and **only** when visual is on (`nodes.py`)
- [ ] T062 [US3] Write `tests/pipelines/changepoint/test_visual_toggle.py` (with `FakeModelWrapper`): visual-off run produces no `agent_context.png`, uses the diagnostics-only prompt, and still yields a forecast + full metrics; visual-on run records a visual result before the decision (SC-006)

**Checkpoint**: visual node cleanly ablatable; both arms produce valid runs.

---

## Phase 6: User Story 4 — Relocatable intervention tools (MCP-ready) (Priority: P2)

**Goal**: Prove the tool registry contract is transport-agnostic — an in-process tool can be swapped
for a contract-equivalent out-of-process stub with no change to the agent loop, gate, or prompts.

**Independent Test**: swap a tool's implementation for a stub with the same
`(ToolContext, params)→ToolResult` contract → agent loop, gate, prompts, trace, and event format unchanged.

- [ ] T063 [P] [US4] Write the **stub-swap conformance test** `tests/core/agent/test_tool_stub_swap.py` (SC-011): register a stub tool returning a canned `ToolResult` with the same contract as a real tool; assert the gate scores it and the loop/prompt/trace shapes are identical
- [ ] T064 [P] [US4] Write the **boundary-purity test** `tests/core/agent/test_tool_boundary.py`: assert `ToolContext`/`ToolResult` carry only JSON-native data (records `[{ds,y}]`, ISO timestamps, plain dicts, `yhat` floats) — no `SeriesSplit`, `DiagnosticsBundle` object, or Prophet/model handle crosses
- [ ] T065 [P] [US4] Write **import-guard tests** `tests/core/agent/test_import_guards.py` (SC-002): `langgraph` importable only via `ailf.core.agent.engine`; `langchain_aws` only via `ailf.core.models.llm`; importing `ailf.core.backtest`/`ailf.core.agent`/`ailf.core.events` does NOT transitively import `ailf.core.datasets`; the changepoint pipeline imports only `ailf.core.*` + stdlib (not another pipeline, not `ailf.core.datasets`)
- [ ] T066 [US4] Write **disabled-tool pruning test** `tests/core/agent/test_menu_pruning.py` (FR-014/SC-005): a disabled tool is absent from the generated `{{tool_menu}}` AND `allowed_names()`; if force-proposed it is rejected by the gate (depends on US2 toggles)
- [ ] T067 [US4] Resolve any boundary-purity failures from T063–T066 in `src/ailf/core/agent/registry.py` / `src/ailf/pipelines/changepoint/interventions.py` (make the contract genuinely relocatable)

**Checkpoint**: tool registry is provably lift-and-shift ready.

---

## Phase 7: User Story 5 — Every stage emits a structured event (Priority: P2)

**Goal**: Every run step (incl. deterministic detection + both baseline fits) emits a typed,
serializable `StageEvent` in causal order to a default file sink; leakage controls extend to events;
oversized payloads are referenced not inlined; a stage failure emits a terminal error event (fail-fast).

**Independent Test**: run with the default sink → `events.jsonl` has one well-formed event per stage
lifecycle in causal order, each conforming to its documented payload shape; no pre-final payload
carries hidden-test/audit fields.

- [ ] T068 [P] [US5] Add `src/ailf/core/events/event.py` (`StageEvent` frozen dataclass + `to_dict`, `StageStatus`) and `src/ailf/core/events/stages.py` (`StageId` closed enum, 11 ids in causal order) per contracts/event_contract.md
- [ ] T069 [P] [US5] Write failing tests for the emitter in `tests/core/events/test_emitter.py`: monotonic `seq`, `stage()` context manager emits start→complete, exception path emits a terminal `error` event + re-raises (fail-fast), `NullEmitter` is a no-op
- [ ] T070 [US5] Implement `src/ailf/core/events/emitter.py` (`Emitter` protocol, `EventEmitter` with seq counter + active `concurrency_group` + `stage()` ctx mgr + fail-fast, `NullEmitter`) — make T069 pass
- [ ] T071 [P] [US5] Write failing tests for sinks in `tests/core/events/test_sink.py` (`FileEventSink` JSONL append/flush-per-record; in-memory `ListSink`)
- [ ] T072 [US5] Implement `src/ailf/core/events/sink.py` (`EventSink` protocol, `FileEventSink` → `<run_dir>/events.jsonl`, `ListSink`) — make T071 pass
- [ ] T073 [US5] Implement `src/ailf/core/events/payloads.py`: the per-stage payload builders for all 11 stages (documented shapes in contracts/event_contract.md), sourcing pre-final payloads from agent-facing/filtered views; oversized (>32 KB) or binary payloads written to `event_payloads/<seq>.json` and referenced by `$ref` (FR-031)
- [ ] T074 [US5] Wire the emitter into `pipeline.py`: emit the deterministic prelude SEQUENTIALLY from the single-threaded driver, emit the concurrent `visual∥diagnostics` start/complete FROM THE DRIVER (not node bodies) with `concurrency_group="visual_diagnostics"`, emit decision/validation/final/run_complete; replace `NullEmitter` with `FileEventSink` (research Decision 11, FR-028)
- [ ] T075 [P] [US5] Write per-stage payload-schema tests in `tests/core/events/test_payloads.py` (each of the 11 stages conforms to its documented shape; `start` minimal; `error` carries `{type,message}`)
- [ ] T076 [P] [US5] Write leakage tests in `tests/core/events/test_event_leakage.py`: no pre-final event payload contains hidden-test values, `audit_only` fields, or `val_metrics` in `validation_outcome`; `test_metrics` first appear only in `final_evaluation`/`run_complete`; no pre-final event inlines a forecast array (FR-029)
- [ ] T077 [US5] Write the **end-to-end event-stream test** `tests/pipelines/changepoint/test_event_stream.py` (with `FakeModelWrapper` + `FileEventSink`): run a full scenario, then assert the recorded `events.jsonl` is the complete, in-order stream — exactly the expected `StageId` sequence ordered by `seq` (config_resolved → split_built → changepoint_detection → both baseline fits → diagnostics_computed → visual_inspection → decision/validation iterations → final_evaluation → run_complete), each event valid per its documented payload shape, and `concurrency_group="visual_diagnostics"` present visual-on / the `visual_inspection` events + group absent visual-off (SC-010, FR-026/FR-028; depends on T074)

**Checkpoint**: full event stream recorded to `events.jsonl`; UI-ready contract verified end-to-end without a UI.

---

## Phase 8: User Story 6 — Reproducible, configuration-stamped artifacts (Priority: P2)

**Goal**: A completed run records its resolved effective config, split provenance, hidden diagnostics,
removed tools, visual flag, prompt versions, and model ids; re-running with the recorded config
reproduces identical deterministic metrics with stable provenance.

**Independent Test**: open a run dir → all of the above present; re-run with the recorded
`effective_config.json` as override → identical deterministic metrics; provenance stable (golden→golden, override→override).

- [ ] T078 [US6] Stamp `effective_config.json` in `run_dir.py`: `EffectiveConfig.to_dict` + `SplitProvenance` (source, units, resolved absolute rows, rounding_rule, derived indices) + model ids + recorded seed (FR-021/SC-012)
- [ ] T079 [US6] Enrich `write_agent_trace` (artifacts.py) to record `visual_analysis_enabled`, sorted `hidden_diagnostics`, sorted `removed_tools`, decision/visual prompt ids+versions actually loaded, and `{visual_model_id, decision_model_id}` (SC-004/005/012)
- [ ] T080 [P] [US6] Write the **SC-007 round-trip test** `tests/core/backtest/test_split_roundtrip.py` + `tests/pipelines/changepoint/test_config_roundtrip.py`: re-ingesting a recorded `effective_config.json` as override reproduces identical deterministic metrics; provenance is stable for both a golden-source and an override-source original run (research Decision 14)
- [ ] T081 [US6] Implement the round-trip resolution rule in `resolve.py`/`split.py`: a recorded `source=golden` re-derives golden verbatim (stays `golden`); a recorded `source=override` re-resolves from recorded absolute rows (no re-rounding) — make T080 pass

**Checkpoint**: every run is fully reproducible and self-describing.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Honesty fixes, the opt-in golden eval, and final validation.

- [ ] T082 [P] Correct the `src/ailf/core/backtest/__init__.py` docstring: describe the **single validation-holdout gate** as the current contract and note rolling-origin as a future extension (plan Deviation 2 / SC-002 "verifiable by inspection")
- [ ] T083 [P] Update the `src/ailf/core/models/__init__.py` docstring to scope the uniform-forecaster interface as deferred (this feature's `models/` is the LLM wrapper only — research Decision 2)
- [ ] T084 [P] Write the opt-in golden-set eval `tests/pipelines/changepoint/test_golden_eval.py` behind `@pytest.mark.golden` + a Bedrock-credential guard: accepted/best-val tool family matches each scenario's `expected_intervention_family`; holiday tool selected only on the recurring-event scenario (Principle III; never gates the deterministic suite). NOTE: SC-008's behavioral half has no hard CI gate — by design (Principle III / plan Deviation 3); FR-031's deterministic half is gated by T032.
- [ ] T085 [P] Register the `golden` pytest marker in `pyproject.toml` (`[tool.pytest.ini_options].markers`)
- [ ] T086 Run the full deterministic suite `uv run pytest tests/core tests/pipelines/changepoint` green; then walk `quickstart.md` steps 1–6 end-to-end and confirm each SC
- [ ] T087 [P] Document the before/after golden-set capture for the two agent-affecting changes (new `react_decision_v2.md` + generated menu) in the PR description (Principle III sign-off — plan Deviation 3)

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no deps; T007 (parity oracle) must complete before T048 and any refactor that could change POC behavior.
- **Foundational (P2)**: depends on Setup; **blocks all user stories**.
- **US1 (P3)**: depends on Foundational. This is the spine and the MVP.
- **US2–US6**: depend on **US1** (promotion reality — they extend the spine), not just on Foundational. Among themselves: US4's menu-pruning test (T066) depends on US2 toggles (T056); US6 round-trip (T080/T081) depends on US2 resolve (T051) + US1 reporting (T045); US5's end-to-end event-stream test (T077) depends on the emitter wiring (T074). US3 and US5 depend only on US1. US4's import-guards/stub-swap depend only on US1.
- **Polish (P9)**: depends on all desired stories.

### Within each story

- Tests are written FIRST and must FAIL before implementation (Tier A). LLM-stage behavior is covered by trace-invariant/leakage tests with `FakeModelWrapper`, not exact-output asserts.
- Schema/types → resolver/service → wiring → integration test.

### Parallel opportunities

- Setup: T004, T005 in parallel (T007 after fixtures exist).
- Foundational: T009/T011/T013/T014/T015 are independent files → parallel (impl tasks follow their tests).
- US1: the test-writing tasks T017/T021/T026/T028/T030/T032/T034/T036 are different files → parallel; T038/T039/T040/T045/T046 are independent → parallel. Implementations serialize where they share a file or depend on a type (e.g. gate T035 needs registry T031 + metrics T012).
- US4: T063/T064/T065 are independent test files → parallel.
- US5: T068, T069/T071 (then their impls), T075/T076 → parallel within groups; T077 (end-to-end stream) runs after T074 wiring.
- Across teams: once US1 is green, US3, US4, US5 can proceed in parallel; US2 unblocks US6 and US4's pruning test.

---

## Parallel Example: User Story 1 (test-first batch)

```bash
# Write these failing tests together (different files):
Task: "T017 config schema round-trip in tests/core/config/test_schema.py"
Task: "T021 split golden path in tests/core/backtest/test_split.py"
Task: "T026 detector ground-truth precision/recall in tests/pipelines/changepoint/test_detector.py"
Task: "T028 diagnostics + golden byte-identity in tests/pipelines/changepoint/test_diagnostics.py"
Task: "T030 registry types + for_run pruning in tests/core/agent/test_registry.py"
Task: "T034 gate accept rule in tests/core/backtest/test_gate.py"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and VALIDATE**: `uv run pytest tests/core/parity tests/pipelines/changepoint` green; one
   golden scenario runs end-to-end with the POC artifact set. This is the headline deliverable.

### Incremental delivery

1. US1 (MVP) → POC-equivalent run under golden config.
2. US2 → config overrides + toggles + split knobs take effect and are recorded.
3. US3 → visual node ablatable.
4. US4 → tool registry proven MCP-relocatable.
5. US5 → full event stream to `events.jsonl` (UI-ready contract).
6. US6 → fully reproducible, self-describing runs.
7. Polish → honesty docstrings, opt-in golden eval, quickstart sign-off.

### Parallel team strategy

Once US1 is green: Dev A → US3 (visual), Dev B → US5 (events), Dev C → US4 (registry proof). US2 (config)
is on the critical path for US6 and US4's pruning test, so land US2 early after US1.

---

## Notes

- `[P]` = different files, no dependency on incomplete tasks.
- `[Story]` label maps each task to its user story for traceability; Setup/Foundational/Polish carry none.
- Verify each Tier-A test FAILS before implementing (Constitution II).
- The POC under `pocs/changepoint/` is the parity oracle — do not modify it.
- Commit after each task or logical group; keep core tests green (Constitution VII review gate).
- The narrative `report.md` (T045) satisfies Principle VI; MASE/PI-coverage and rolling-origin backtest
  are explicitly deferred (plan Deviations 1 & 2).

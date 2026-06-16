---
description: "Task list for Agent-in-the-Loop Changepoint Forecasting POC"
---

# Tasks: Agent-in-the-Loop Changepoint Forecasting POC

**Input**: Design documents from `/specs/003-changepoint-agent-poc/`

**Prerequisites**: plan.md, spec.md (+ Clarifications), research.md, data-model.md, contracts/, quickstart.md

**Tests**: NOT included. This work lives in `pocs/changepoint/` and is exempt from the
test-first gate per the constitution's POC exemption; the spec does not request tests. Validate
via `quickstart.md` and the smoke check instead.

**Donor code**: An early rough single-file script (`pocs/changepoint/changepoint_agent_poc.py`,
quarantined) is NOT the design — but its deterministic diagnostics, the diagnostics
leakage-stripping helper, and the Prophet step/ramp/clean-event/holiday fit functions are
largely sound and may be lifted/adapted into the modules below. Do NOT carry over its
test-set acceptance, silent local fallback, ARIMA, or single hardcoded model id.

**Organization**: Tasks grouped by user story. US1/US2/US3 are all P1 and form one integrated
agent pipeline, so US1's full three-method comparison depends on the agent halves built in
US2+US3 (see Dependencies). The deterministic baselines in US1 are independently runnable first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5 maps to the spec's user stories
- All paths are relative to repo root

## Path Conventions

Single self-contained POC package at `pocs/changepoint/` (per plan.md Structure Decision). Does
NOT import `src/ailf/core` (those are empty stubs). Output under `pocs/changepoint/runs/<ts>/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, package skeleton, environment, ignore rules

- [X] T001 Add dependencies: run `uv add langchain-aws boto3 python-dotenv`, then `uv sync`; commit the updated `uv.lock` (research.md Decision 1; `python-dotenv` for `.env` loading in T005)
- [X] T002 [P] Create package skeleton: `pocs/changepoint/__init__.py`, `pocs/changepoint/graph/__init__.py`, and the `pocs/changepoint/prompts/` directory
- [X] T003 [P] Update `.env.example` with `VISUAL_MODEL_ID=`, `REACT_MODEL_ID=`, `AWS_ACCESS_KEY_ID=`, `AWS_SECRET_ACCESS_KEY=`, `AWS_REGION=us-west-2`, plus a comment naming intended defaults (Opus 4.8 visual / Sonnet 4.6 react) without hardcoding them (FR-022/023, contracts/artifacts.md)
- [X] T004 [P] Add `pocs/changepoint/runs/` (and `_debug/`) to `.gitignore` so bulk run artifacts stay uncommitted

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared deterministic substrate + model factory that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement `pocs/changepoint/config.py`: load `.env`; read `VISUAL_MODEL_ID`/`REACT_MODEL_ID`/`AWS_REGION`/LangSmith vars; fail-fast with an explicit error if either model id is unset (no hardcoded ids, no silent fallback — FR-022/024, SC-010); expose a fixed recorded `SEED` (FR-040)
- [X] T006 Implement `pocs/changepoint/scenarios.py`: load `pocs/changepoint/data/scenario_metadata.json` + each `data/csv/<id>.csv`; build `Scenario` and `SeriesSplit` (`train_idx`/`fit_idx`/`val_idx`/`test_idx` per data-model.md); keep `audit_only` in a separate struct that never enters agent-facing data; guard splits (`train_end>validation_horizon>0`, `train_end+test_horizon<=row_count`) with clear errors (FR-001/002/003, edge cases); assert the five required `scenario_id`s are present (FR-005). See [[project-changepoint-data-fixtures]]
- [X] T007 [P] Implement `pocs/changepoint/forecasting.py`: default-Prophet fit/predict helpers and metric functions MAE/RMSE/WAPE/sMAPE (lift `metrics()` + `fit_prophet_default` from donor script)
- [X] T008 [P] Implement `pocs/changepoint/detector.py`: deterministic Prophet trend-delta changepoint detector returning the top `n_changepoints_to_detect` (from metadata) as `ChangepointSet` with `latest`/`primary` (research.md Decision 2, FR-013)
- [X] T009 Implement `pocs/changepoint/diagnostics.py`: full `DiagnosticsBundle` from training history only — post-cp history len + shorter-than-season flag, segment means/stds, candidate event blocks (with `closed_before_origin`), recurring-event summary (`is_calendar_recurring`), local boundary jumps, candidate drift intervals, transient-event score, permanent-shift magnitude (FR-014, data-model.md); include an agent-facing serializer that strips provenance/audit (adapt donor `diagnostics_for_scenario` + `agent_input_diagnostics`); depends on T008
- [X] T010 Implement `pocs/changepoint/llm.py`: `ChatBedrockConverse` factory for the visual and react models from `config`; structured-output (Pydantic) parsing helpers; surface an explicit error naming the configured model id when Bedrock reports it unavailable — never substitute another model (FR-024, SC-010, research.md Decision 5); depends on T005

**Checkpoint**: Substrate ready — scenarios load, splits/detector/diagnostics compute deterministically, model factory fails clearly without valid ids.

---

## Phase 3: User Story 1 - Agent beats the naive baseline on hard scenarios (Priority: P1) 🎯 MVP

**Goal**: Produce, per scenario, comparable hidden-test metrics for all three methods
(full-history Prophet, naive workflow, agent) plus a cross-scenario summary.

**Independent Test**: Run the POC; each scenario emits `metrics.json` with hidden-test errors for
all three methods, and a `summary.md` states the winner per scenario. The two deterministic
baselines are independently runnable before the agent exists.

- [X] T011 [P] [US1] Implement full-history default Prophet baseline in `pocs/changepoint/baselines.py` (train `[0,train_end)`, evaluate on `test_idx` only at final reporting — FR-010)
- [X] T012 [US1] Implement the naive changepoint workflow in `pocs/changepoint/baselines.py`: candidate windows = full history + every detected changepoint window; fit default Prophet on each; select min validation MAE on the single holdout (`val_idx`); return `NaiveWorkflowResult` (FR-011/012, contracts; Prophet-only, NO ARIMA); depends on T008, uses T007
- [X] T013 [US1] Implement `pocs/changepoint/viz.py::render_forecast_comparison` → `forecast_comparison.png`: train history, hidden-test actuals, full-history Prophet, naive forecast, agent forecast; produced only at/after final evaluation, never passed to any agent node (FR-035, contracts/artifacts.md)
- [X] T014 [US1] Implement `metrics.json` writer (MetricsReport schema + `winner` = lowest test MAE) in `pocs/changepoint/run_poc.py` or a `reporting.py` helper (FR-036, data-model.md)
- [X] T015 [US1] Implement cross-scenario `summary.md` writer: one row per scenario with winner, agent tool, and agent/naive/full-history test MAE (FR-038, SC-011)
- [X] T016 [US1] Implement `pocs/changepoint/run_poc.py` orchestration: per-scenario run dir `runs/<timestamp>/<scenario_id>/`, `--scenario` flag, set+record `SEED`, run the two baselines, evaluate them on hidden test, write `metrics.json` + `forecast_comparison.png` + top-level `summary.md` (agent column wired in T029) — FR-033, FR-040

**Checkpoint**: Deterministic baselines produce reproducible hidden-test metrics + summary (SC-004, SC-007 for baselines).

---

## Phase 4: User Story 2 - Visual-first, leakage-free agent reasoning is provable (Priority: P1)

**Goal**: The agent sees only a training-only chart and produces visual observations recorded
before any decision; no test/audit data ever reaches an LLM node.

**Independent Test**: Open any `agent_context.png` (training-only, no test points/annotations) and
the trace (visual output present and ordered before decision; rationale cites visual first).

- [X] T017 [US2] Implement `pocs/changepoint/viz.py::render_agent_context` → `agent_context.png`: plain training-only line plot + forecast-origin marker, NO test data, NO changepoint/boundary annotations (FR-034, SC-002, contracts/artifacts.md)
- [X] T018 [P] [US2] Author `pocs/changepoint/prompts/visual_inspection_v1.md`: image-only inspection returning `{observations, pattern_summary, hypotheses, uncertainties}`; explicitly must NOT choose an intervention (FR-016)
- [X] T019 [P] [US2] Implement `pocs/changepoint/graph/state.py`: serializable state TypedDict accumulating split refs, diagnostics, visual result, naive summary, iterations, rejected signatures, accepted/final candidate; test values absent until final eval (data-model.md)
- [X] T020 [US2] Implement `visual_inspection_node` in `pocs/changepoint/graph/nodes.py`: sends only the `agent_context.png` image + instruction to the visual model; returns structured `VisualInspectionResult`; no diagnostics/test access (FR-016); depends on T010, T017, T018, T019
- [X] T021 [US2] Add leakage invariants (assertions/guards): `agent_context.png` rendered solely from `y[train_idx]`; no node except final reads `test_idx` or `audit_only`; `state.visual` populated before any `iterations` entry (SC-002/003, contracts/graph_nodes.md)

**Checkpoint**: Visual node runs on a training-only image and its output is provably recorded before any decision.

---

## Phase 5: User Story 3 - Bounded interventions validated before they count (Priority: P1)

**Goal**: The agent chooses only bounded interventions, each accepted only if it strictly beats
the naive baseline on the historical holdout; hidden test touched only after the loop.

**Independent Test**: Trace shows every proposal is from the menu within bounds, scored only on
`val_idx`, accepted only on strict improvement; rejected signatures not re-proposed; test scored
only in final evaluation.

- [X] T022 [US3] Implement `pocs/changepoint/interventions.py`: all five bounded tools with the exact grids in `contracts/intervention_menu.md`; `action_signature`; clean-event restricted to blocks `closed_before_origin` (FR-026a); holiday windows from the recurring-event diagnostic (lift/adapt donor step/ramp/clean/holiday fit fns) — FR-026/028/029; depends on T007, T009
- [X] T023 [US3] Implement `diagnostics_node` in `pocs/changepoint/graph/nodes.py`: deterministic, NO LLM; produces the `DiagnosticsBundle` + `naive_summary` into state (FR-017); depends on T009, T012
- [X] T024 [P] [US3] Author `pocs/changepoint/prompts/react_decision_v1.md`: bounded menu, `visual_first_rationale` citing visual observations before numerics, and the holiday-gating rule (FR-018/030/031)
- [X] T025 [US3] Implement `react_decision_node` in `pocs/changepoint/graph/nodes.py`: choose exactly one tool via the react model; mechanically reject out-of-bounds params, repeated `action_signature`, and the holiday tool when `is_calendar_recurring==false`; re-prompt with the rejection list (FR-018/020/031, SC-009); depends on T010, T020, T022, T024
- [X] T026 [US3] Implement `validation_node` in `pocs/changepoint/graph/nodes.py`: fit on `fit_idx`, score MAE on `val_idx` (single holdout); accept iff strictly less than naive selected val MAE (no ties); never touch `test_idx` (FR-019/020, clarifications); depends on T022, T023
- [X] T027 [US3] Implement `final_evaluation_node` in `pocs/changepoint/graph/nodes.py`: pick final candidate = accepted, else best-val proposal; set `final_case`; compute hidden-test metrics for all three methods — the only place `test_idx` is read (FR-021, clarifications); depends on T011, T012, T026
- [X] T028 [US3] Implement `pocs/changepoint/graph/build.py`: wire `START→{visual_inspection, diagnostics}` concurrently, join at `react_decision`, loop `react_decision ↔ validation` (≤5 iters), route to `final_evaluation→END` (FR-015/020, contracts/graph_nodes.md); depends on T020, T023, T025, T026, T027
- [X] T029 [US3] Integrate the compiled graph into `pocs/changepoint/run_poc.py` as the third method; assemble per-iteration records and the accepted/final candidate for downstream metrics/summary/trace; depends on T016, T028

**Checkpoint**: Full three-method comparison runs end-to-end; US1 metrics now include the real agent (SC-001/005/006).

---

## Phase 6: User Story 4 - Each intervention family is demonstrated (Priority: P2)

**Goal**: Across the five scenarios, each intervention family is demonstrated (accepted choice
OR best-validation proposal) at least once, and holiday tuning is never chosen for non-calendar
patterns.

**Independent Test**: Inspect proposed/accepted tools across the five traces — step, ramp,
clean-event, and holidays-tuned each appear ≥1×; the non-recurring scenarios never select holidays.

- [X] T030 [US4] Verify/strengthen the holiday hard-gate (`is_calendar_recurring==false` ⇒ holiday tool rejected) and the recurring-event diagnostic accuracy on `prophet_prior_tuning_recurring_event` vs the others (FR-031, US4 AS2); touches `pocs/changepoint/diagnostics.py` + `graph/nodes.py`. Confirmed live: holiday tool rejected on temporary_event; recurring=True only on the recurring fixture
- [X] T031 [US4] Run all five scenarios and confirm each of the four structural families is demonstrated ≥1× as an accepted choice OR best-validation proposal (SC-008). Removed the generic-tuning escape-hatch tool so each family maps to a dedicated fixture; improved the drift diagnostic + react prompt so ramp/clean are actually proposed (not the bounds). Coverage achieved honestly
- [X] T032 [US4] Add a family-coverage line to `summary.md` recording, per family, whether it was an accepted winner or a validated best proposal (SC-008); `reporting.families_demonstrated` + summary writer

**Checkpoint**: All five intervention families demonstrated; holiday gating proven.

---

## Phase 7: User Story 5 - Reproducible, human-readable artifacts per run (Priority: P2)

**Goal**: Each run is fully inspectable after the fact and deterministic parts reproduce exactly.

**Independent Test**: Open a run dir — agent-context image, comparison plot, metrics, structured
trace, and summary all present and consistent; rerun reproduces identical deterministic metrics.

- [X] T033 [US5] Implement the `agent_trace.json` writer (full AgentTrace schema: visual, diagnostics, naive_summary, iterations[] with proposal+val_result+beat_naive, rejected_signatures, accepted, final_candidate, final_case, model_ids{visual,react}, seed) in `pocs/changepoint/run_poc.py` (FR-037, data-model.md); depends on T029
- [X] T034 [US5] Confirm reproducibility: seed fixed+recorded; rerunning a scenario yields identical full-history + naive + validation metrics; per-`<timestamp>` run dir prevents overwrites (FR-040, SC-007); touches `pocs/changepoint/run_poc.py`
- [X] T035 [US5] Add a `--debug-plots` flag to `run_poc.py` that writes any diagnostics/debug plot to a `_debug/` subdir only — never by default and never passed to an agent node (FR-039)

**Checkpoint**: All artifacts complete and reproducible.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T036 [P] Leakage audit (quickstart.md): grep written `agent_trace.json` for any `audit_only`/`true_injected_boundaries` content → expect none; confirm `forecast_comparison.png` is written only post-final and never referenced by the visual node
- [X] T037 [P] Run the full `quickstart.md` validation table end-to-end (all 11 SC checks) and the no-Bedrock smoke check
- [X] T038 [P] Remove the obsolete rough script `pocs/changepoint/changepoint_agent_poc.py` and stale `pocs/changepoint/__pycache__/` now that the modular design supersedes it (see [[project-changepoint-poc]])
- [X] T039 [P] Align `pocs/changepoint/export_scenario_csvs.py` as the OPTIONAL off-path fixture generator and confirm the runtime does not import or depend on it (FR-004)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Baselines depend only on Foundational; the full three-method comparison
  (T014/T015 final numbers, agent column) completes after US2+US3 via T029
- **US2 (Phase 4)**: Depends on Foundational (T010 llm, plus T017/T019)
- **US3 (Phase 5)**: Depends on Foundational AND US2 (the decision node consumes the visual node);
  T029 also depends on US1's T016 orchestration
- **US4 (Phase 6)**: Depends on US3 (needs the running agent + interventions)
- **US5 (Phase 7)**: Depends on US3 (trace) and US1 (run dir/metrics)
- **Polish (Phase 8)**: After the stories you intend to ship

### Critical path

T001→T005/T006→T007/T008→T009/T010 → (US2: T017/T019/T020) → (US3: T022→T025, T026, T027, T028, T029) → US4/US5 → Polish.

### Within stories

- US1: T011 ∥ then T012; T013/T014/T015 ∥; T016 after baselines
- US2: T017 ∥ T018 ∥ T019 → T020 → T021
- US3: T022 ∥ T024; T023 after T009/T012; T025 after T020/T022/T024; T026 after T022/T023; T027 after T011/T012/T026; T028 after all nodes; T029 after T016/T028

### Parallel opportunities

- Setup: T002, T003, T004 in parallel
- Foundational: T007 ∥ T008 (then T009 after T008); T010 ∥ T007/T008
- US1: T011, T013, T014, T015 are independent files/sections
- US2: T017, T018, T019 in parallel
- Polish: T036, T037, T038, T039 in parallel

---

## Parallel Example: Foundational

```bash
# After T005/T006, these touch different files:
Task: "Implement forecasting.py (Prophet helpers + metrics)"      # T007
Task: "Implement detector.py (Prophet trend-delta top-N)"          # T008
Task: "Implement llm.py (ChatBedrockConverse factory, fail-fast)"  # T010
```

## Parallel Example: User Story 2

```bash
Task: "Render agent_context.png training-only in viz.py"      # T017
Task: "Author prompts/visual_inspection_v1.md"                 # T018
Task: "Implement graph/state.py serializable state"            # T019
```

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup → Phase 2 Foundational.
2. Phase 3 US1 baselines (T011–T016): a runnable two-method (full-history + naive) comparison
   with reproducible metrics + summary. **STOP and VALIDATE** SC-004/SC-007 for baselines.
3. This is a demoable deterministic MVP before any LLM cost is incurred.

### Incremental Delivery

1. Foundational + US1 baselines → deterministic comparison harness (MVP).
2. US2 → visual-first input proven leakage-free.
3. US3 → agent closes the loop; full three-method comparison (SC-001/005/006). This is the
   headline result.
4. US4 → demonstrate intervention-family breadth (SC-008).
5. US5 → complete reproducible artifacts (SC-007/SC-011) + trace (FR-037).
6. Polish → leakage audit, quickstart validation, remove rough script.

### Notes

- [P] = different files, no incomplete dependencies.
- Commit after each task or logical group; keep changes inside `pocs/changepoint/`.
- No formal test suite (POC exemption); validate through quickstart + smoke check.
- Reuse donor code only where it matches the spec; never carry over its leakage/fallback/ARIMA.

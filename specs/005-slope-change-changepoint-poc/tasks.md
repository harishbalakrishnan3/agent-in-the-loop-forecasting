---
description: "Task list for Slope-Change Changepoint POC & Prophet Baseline Evaluation"
---

# Tasks: Slope-Change Changepoint POC & Prophet Baseline Evaluation

**Input**: Design documents from `/specs/005-slope-change-changepoint-poc/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — the spec requires automated tests as a deliverable (FR-018, SC-007).

**Organization**: Tasks are grouped to follow the requested build order — dataset generation +
tests first, then visualization/PNG export, then naive Prophet-native evaluation, then the naive
Prophet summary report. Each task is small and carries its own acceptance criteria.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story the task serves (US1 = data generation, US2 = Prophet eval, US3 = viz)
- All paths are relative to repo root.

## Path Conventions

POC lives entirely under `pocs/changepoint/slope_change/` (self-contained per FR-016/FR-017).
Spec design docs live under `specs/005-slope-change-changepoint-poc/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the self-contained POC package skeleton mirroring `level_shift/`.

- [X] T001 Create directory `pocs/changepoint/slope_change/` and empty `pocs/changepoint/slope_change/__init__.py`.
  - **Acceptance**: `pocs/changepoint/slope_change/__init__.py` exists; `python -c "import pocs.changepoint.slope_change"` succeeds from repo root.
- [X] T002 [P] Author POC-local spec `pocs/changepoint/slope_change/spec.md` mirroring `pocs/changepoint/level_shift/spec.md` structure, retitled for slope changes and listing the S1–S10 catalog.
  - **Acceptance**: File exists, references `slope_change` (not `level_shift`), and its dataset table lists all 10 IDs S1–S10 from data-model.md.
- [X] T003 [P] Create empty `pocs/changepoint/slope_change/plots/` directory with a `.gitkeep`.
  - **Acceptance**: `pocs/changepoint/slope_change/plots/.gitkeep` exists.

**Checkpoint**: Package importable; structure mirrors the sibling POC.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None beyond Setup — the generator (US1) is itself the foundation every later phase
builds on, so it is delivered as User Story 1 below rather than duplicated here.

**⚠️ CRITICAL**: All later phases depend on US1 (the generator) being complete.

---

## Phase 3: User Story 1 - Generate slope-change series with ground truth (Priority: P1) 🎯 MVP

**Goal**: A seeded generator producing 10 synthetic series whose changepoints are continuous
slope changes (no level jumps), each with exact ground-truth metadata.

**Independent Test**: `generate_all_datasets()` returns 10 `(TimeSeries, metadata)` pairs; the
noise-free trend's slope changes at planted indices and stays continuous; metadata schema matches.

### Implementation for User Story 1

- [X] T004 [US1] Implement `generate_slope_change_series(...)` in `pocs/changepoint/slope_change/datasets.py` building a continuous piecewise-linear trend via cumulative slope (slope starts at `initial_slope`, bumped by each `slope_deltas[i]` at `changepoint_indices[i]`), plus optional seasonality and seeded Gaussian noise; returns `(TimeSeries, metadata_dict)`. Imports limited to numpy/pandas/darts.
  - **Acceptance**: Function signature matches `contracts/datasets.md`; calling it with one changepoint returns a Darts `TimeSeries` of the requested length and a metadata dict; no import of `level_shift` or `ailf`.
- [X] T005 [US1] Add input validation to `generate_slope_change_series` (raise `ValueError` on len mismatch of `changepoint_indices`/`slope_deltas`, index outside `[min_segment, length - min_segment)`, or non-increasing indices) in `pocs/changepoint/slope_change/datasets.py`.
  - **Acceptance**: Each invalid case raises `ValueError`; a valid config does not (contract C4). Includes a covering test in `test_slope_change.py` (`test_validation_rejects_invalid_config`) that asserts `ValueError` for (a) length mismatch, (b) a **near-boundary index** inside the first/last `min_segment` points (FR-007 boundary guard), and (c) non-increasing indices.
- [X] T006 [US1] Populate the metadata dict with all fields from data-model.md ("Ground-truth metadata"), including `type="slope_change"`, `slope_deltas`, `slopes_per_segment`, and `changepoint_dates` matching indices, in `pocs/changepoint/slope_change/datasets.py`.
  - **Acceptance**: Metadata contains every listed field; `changepoint_dates[i]` equals the series date at `changepoint_indices[i]`; `slopes_per_segment[0] == initial_slope` (contract C5).
- [X] T007 [US1] Define `DATASET_CONFIGS` (10 entries S1–S10 per data-model.md, each with unique `seed` and matching `dataset_id`; difficulty tuned via slope-delta, noise, count, and placement relative to the 80% split) and `generate_all_datasets()` in `pocs/changepoint/slope_change/datasets.py`.
  - **Acceptance**: `list(generate_all_datasets().keys())` equals the 10 IDs S1_…–S10_…; S9 has zero changepoints; S10 has ≥1 changepoint within the last 20% of its length; S6 sets a non-null `seasonality_period` with `seasonality_amplitude > 0` (FR-003).

### Tests for User Story 1

- [X] T008 [P] [US1] In `pocs/changepoint/slope_change/test_slope_change.py`, add `test_output_type_and_length` and `test_reproducibility` (same seed → identical values; different seed → different).
  - **Acceptance**: Both tests pass; reproducibility asserts array equality on two identical calls.
- [X] T009 [P] [US1] Add `test_slope_changes_at_indices` and `test_trend_is_continuous` to `pocs/changepoint/slope_change/test_slope_change.py` verifying (on a noise-free config) the per-segment slope differs by `slope_deltas` at each index and no level jump occurs at changepoints.
  - **Acceptance**: Tests pass; continuity check asserts `|value[cp] - value[cp-1]|` ≈ local slope, not a jump (contracts C1, C2).
- [X] T010 [P] [US1] Add `test_control_constant_slope`, `test_metadata_schema`, and `test_seasonality_component_present` to `pocs/changepoint/slope_change/test_slope_change.py` (S9 has zero recorded changepoints / constant slope; metadata has all required keys with `type=="slope_change"`; a seasonal config — e.g. S6 — produces a detectable periodic component on the noise-free series, FR-003).
  - **Acceptance**: All three tests pass; the seasonality test confirms the seasonal term materially changes the series versus the same config with `seasonality_amplitude=0`.

**Checkpoint**: `uv run pytest pocs/changepoint/slope_change/ -v` passes for all US1 tests; datasets generate reproducibly (SC-001, SC-002).

---

## Phase 4: User Story 3 - Visual inspection: datasets + ground truth + PNG export (Priority: P2)

**Goal**: Interactive and static visualization of each dataset with ground-truth slope-change
markers. (Prophet overlays are added later in Phase 5 once the evaluator exists.)

**Independent Test**: The interactive figure renders all 10 datasets with a dropdown and
ground-truth markers; `export_plots.py` writes one PNG per dataset.

### Implementation for User Story 3

- [ ] T011 [US3] Implement `build_figure()` in `pocs/changepoint/slope_change/visualize.py` rendering, per dataset, the raw series (line) and ground-truth slope-change vertical markers, with a dropdown over S1–S10; imports only plotly + local `datasets`.
  - **Acceptance**: `build_figure()` returns a `plotly.graph_objects.Figure`; switching the dropdown shows each dataset's series + its ground-truth markers; no `level_shift`/`ailf` import.
- [ ] T012 [US3] Add a `main()` (and `__main__` guard) to `pocs/changepoint/slope_change/visualize.py` that calls `fig.show()`.
  - **Acceptance**: `uv run python -m pocs.changepoint.slope_change.visualize` opens a figure without error.
- [ ] T013 [P] [US3] Implement `build_single_figure(name, config)` and `export_all()` in `pocs/changepoint/slope_change/export_plots.py` writing one PNG per dataset (raw series + ground-truth markers) to `plots/` via kaleido; imports only plotly + local `datasets`.
  - **Acceptance**: `uv run python -m pocs.changepoint.slope_change.export_plots` writes 10 PNGs named `S1_…`–`S10_…` into `pocs/changepoint/slope_change/plots/`.

**Checkpoint**: Datasets are visually inspectable interactively and as 10 exported PNGs (partial SC-006).

---

## Phase 5: User Story 2 - Naive Prophet-native detection & forecast evaluation (Priority: P1)

**Goal**: Fit default ("naive") Prophet on the first 80% of each series, forecast the held-out
20%, score forecast error and changepoint detection vs. ground truth, classify pass/fail, and
extend the visualizations with Prophet overlays.

**Independent Test**: `evaluate_all()` returns one fully-populated result per dataset with
detection precision/recall and held-out MAE/RMSE/MAPE + classification; ≥1 simple dataset passes
and ≥1 complex dataset fails.

### Implementation for User Story 2

- [ ] T014 [US2] Define tunable constants (`TRAIN_FRACTION=0.8`, `PASS_MAPE=10.0`, `FAIL_MAPE=25.0`, `MATCH_TOL_FRACTION=0.05`, `DELTA_KEEP_FRACTION=0.01`) and the `SlopeChangeEvalResult` dataclass (fields per data-model.md) in `pocs/changepoint/slope_change/prophet_eval.py`.
  - **Acceptance**: Module imports; `SlopeChangeEvalResult` has every field listed in data-model.md "Prophet evaluation result".
- [ ] T015 [US2] Implement a train/forecast helper in `pocs/changepoint/slope_change/prophet_eval.py`: convert a `TimeSeries` to a Prophet `ds,y` frame, fit default `Prophet()` on the first `TRAIN_FRACTION`, forecast the held-out tail, and return forecast vs. actual arrays.
  - **Acceptance**: Helper fits with no custom args (naive, contract E1) and returns held-out forecast aligned to held-out actuals of equal length (E2).
- [ ] T016 [US2] Implement forecast metrics (MAE, RMSE, MAPE) on the held-out horizon in `pocs/changepoint/slope_change/prophet_eval.py`.
  - **Acceptance**: On a flat/easy series MAPE is small (<10); functions handle the held-out arrays without divide-by-zero (levels are positive).
- [ ] T017 [US2] Implement Prophet changepoint extraction in `pocs/changepoint/slope_change/prophet_eval.py`: take fitted Prophet changepoints, keep those with `|delta| ≥ DELTA_KEEP_FRACTION × max|delta|`, map their dates to series indices, and match to ground-truth indices within `±MATCH_TOL_FRACTION × length`; compute precision/recall.
  - **Acceptance**: Returns detected indices + matched-truth list; control S9 (zero true CPs) yields recall 1.0 by convention and counts any detection against precision (contracts E3, E5).
- [ ] T018 [US2] Implement `evaluate_dataset(series, metadata) -> SlopeChangeEvalResult` and `evaluate_all() -> list[SlopeChangeEvalResult]` (with MAPE-band classification pass/borderline/fail) in `pocs/changepoint/slope_change/prophet_eval.py`, plus a `__main__` that prints the per-dataset table.
  - **Acceptance**: `uv run python -m pocs.changepoint.slope_change.prophet_eval` prints a 10-row table; every result has all fields populated, none missing (E4, E6, SC-005).
- [ ] T019 [US2] Tune `DATASET_CONFIGS` (in `datasets.py`) and/or thresholds so that across the catalog at least one simple dataset (S1/S2/S9) classifies `pass` and at least one complex dataset (target S10, likely also S3/S5/S8) classifies `fail`; record the realized outcome.
  - **Acceptance**: `evaluate_all()` yields ≥1 `pass` and ≥1 `fail` (FR-012, SC-004); change is reproducible under fixed seeds.

### Extend visualizations with Prophet overlays

- [ ] T020 [US2] Extend `build_figure()` in `visualize.py` to overlay, per dataset, Prophet's detected changepoints and the forecast-vs-actual line over the held-out horizon (calling `prophet_eval`).
  - **Acceptance**: Each dataset view now shows ground-truth markers, Prophet changepoints (distinct color), and forecast-vs-actual on the held-out tail (FR-014, completes SC-006).
- [ ] T021 [US2] Extend `export_plots.py` so each exported PNG also shows Prophet changepoints and the forecast-vs-actual overlay.
  - **Acceptance**: Re-running export writes 10 PNGs that include the Prophet overlay.

### Tests for User Story 2

- [ ] T022 [P] [US2] Add `test_eval_result_schema_populated` and `test_simple_dataset_passes` to `pocs/changepoint/slope_change/test_slope_change.py` (run `evaluate_dataset` on S1/S2; assert all fields set and MAPE below `FAIL_MAPE`).
  - **Acceptance**: Tests pass.
- [ ] T023 [P] [US2] Add `test_complex_dataset_fails` to `pocs/changepoint/slope_change/test_slope_change.py` (run `evaluate_dataset` on S10; assert MAPE above `PASS_MAPE` / classification not `pass`).
  - **Acceptance**: Test passes, demonstrating the baseline breakdown.

**Checkpoint**: Naive Prophet evaluation complete; detection + forecast metrics reported for all 10 datasets; simple-vs-complex breakdown demonstrated and tested.

---

## Phase 6: Naive Prophet summary report

**Goal**: Produce the `slope_change_poc.md` summary report from the naive Prophet evaluation
results. (Scope is strictly **naive** Prophet — no tuning — per spec FR-008 and the user's
decision.)

- [ ] T024 [US2] Implement `summarize(results) -> str` in `pocs/changepoint/slope_change/prophet_eval.py` rendering a per-dataset markdown table (detection precision/recall + held-out MAE/RMSE/MAPE + classification) and a dedicated "Complex datasets where naive Prophet fails" section listing every `fail` with its metrics.
  - **Acceptance**: Returned string contains a 10-row table and an explicit failure section (FR-013, FR-021, FR-022).
- [ ] T025 [US2] Write `pocs/changepoint/slope_change/slope_change_poc.md` (mirroring `level_shift/level_shift_poc.md` structure) embedding the generated naive-Prophet results table, the failure section, and links to the `plots/` PNGs.
  - **Acceptance**: File exists with the per-dataset naive-Prophet results table and the explicit complex-dataset failure section (FR-020–FR-022, SC-009).

**Checkpoint**: Final deliverables present — datasets, PNGs, passing tests, and the naive Prophet results report with the complex-dataset failure section.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T026 [P] Verify self-containment: `grep -rE "level_shift|ailf" pocs/changepoint/slope_change/*.py` returns nothing.
  - **Acceptance**: Command outputs no matches (FR-017, SC-008).
- [ ] T027 Run the full `quickstart.md` validation (steps 1–6) and confirm each expected outcome.
  - **Acceptance**: All 6 quickstart checkboxes pass; `uv run pytest pocs/changepoint/slope_change/ -v` is fully green (SC-007).
- [ ] T028 [P] Commit a small sample of exported PNGs (or confirm `plots/` handling matches repo gitignore policy) and ensure `uv.lock` is unchanged (no new deps were needed).
  - **Acceptance**: `git status` shows only intended POC files; `uv.lock` not modified.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **User Story 1 (Phase 3)**: Depends on Setup. **Blocks all later phases** (generator is the foundation).
- **User Story 3 (Phase 4)**: Depends on US1 (needs datasets + metadata).
- **User Story 2 (Phase 5)**: Depends on US1; its overlay tasks (T020–T021) also depend on Phase 4's viz/export.
- **Phase 6 (naive summary report)**: Depends on US2 (T018, T019).
- **Phase 7 (polish)**: Depends on all desired phases complete.

### User Story Dependencies

- **US1 (P1)**: Independent — the MVP.
- **US3 (P2)**: Needs US1 datasets. Dataset-only views are independently demoable before US2 exists.
- **US2 (P1)**: Needs US1. Extends US3's viz/export with Prophet overlays.

### Within Each Story

- Generator implementation (T004–T007) before its tests (T008–T010).
- Prophet helper/metrics/detection (T015–T017) before `evaluate_*` (T018) before catalog calibration (T019) before overlays/report.

### Parallel Opportunities

- T002, T003 in Setup run in parallel.
- US1 tests T008/T009/T010 run in parallel (same new test file — coordinate, or write sequentially if editing one file).
- T013 (export) can be drafted in parallel with T011/T012 (visualize) — different files.
- US2 tests T022/T023 run in parallel.
- Polish T026/T028 run in parallel.

---

## Parallel Example: User Story 1

```bash
# After the generator (T004–T007) is implemented, its independent test checks:
Task: "test_output_type_and_length + test_reproducibility in test_slope_change.py"
Task: "test_slope_changes_at_indices + test_trend_is_continuous in test_slope_change.py"
Task: "test_control_constant_slope + test_metadata_schema in test_slope_change.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 3 US1 generator + tests → 3. **STOP & VALIDATE**: `uv run pytest pocs/changepoint/slope_change/` green; 10 datasets reproducible. This alone is a usable, gradable data generator.

### Incremental Delivery (matches requested order)

1. Setup → US1 datasets + tests (MVP).
2. US3 visualization + PNG export (dataset + ground-truth views).
3. US2 naive Prophet evaluation + tests + overlay the viz/export.
4. Naive Prophet `slope_change_poc.md` summary report.
5. Polish: self-containment + quickstart validation.

Each step adds value without breaking the previous one.

---

## Notes

- [P] = different files, no incomplete-task dependencies. Tasks editing the same new test file
  (`test_slope_change.py`) are marked [P] for planning but should be appended carefully if done
  concurrently.
- All generation is seeded (constitution Principle V); no new dependencies are required (all libs
  already in `pyproject.toml`).
- POC is exempt from the test-first gate, but tests ship as a required deliverable (FR-018).
- Scope is strictly **naive** (default-configuration) Prophet — no tuning — per spec FR-008.

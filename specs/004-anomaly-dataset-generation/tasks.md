---
description: "Task list for Anomaly Dataset Generation & Diagnostic POC"
---

# Tasks: Anomaly Dataset Generation & Diagnostic POC

**Input**: Design documents from `/specs/004-anomaly-dataset-generation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: INCLUDED. Dataset generation, splitting, diagnostic tools, and metric computation are
deterministic logic and must be covered by pytest per Constitution Principle II.

**Organization**: Tasks are grouped by user story to map cleanly to the implemented anomaly PR.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel.
- **[Story]**: User story label from the spec.
- Exact file paths are included in implementation tasks.

---

## Phase 1: Setup

**Purpose**: Keep CI and test collection stable across independently owned pipeline folders.

- [X] T001 Configure pytest import mode to avoid duplicate test module-name collisions across
  pipeline folders in `pyproject.toml`.
- [X] T002 [P] Confirm anomaly pipeline directories exist under
  `src/ailf/pipelines/anomaly/`, `tests/pipelines/anomaly/`, and `pocs/anomaly/`.

---

## Phase 2: User Story 1 - Generate labeled anomaly datasets (Priority: P1)

**Goal**: Seeded generators return labeled datasets with a consistent DataFrame schema.

**Independent Test**: Generate each dataset with seed `42`; assert schema, lengths, anomaly
counts, and reproducibility.

### Tests for User Story 1

- [X] T003 [P] [US1] Test simple outlier dataset length, schema, anomaly count,
  reproducibility, and metadata in `tests/pipelines/anomaly/test_datasets.py`.
- [X] T004 [P] [US1] Test NAB-like point, level-shift, and trend datasets for length, anomaly
  ratio, anomaly count, type naming, and reproducibility in
  `tests/pipelines/anomaly/test_datasets.py`.
- [X] T005 [P] [US1] Test contextual seasonal anomaly dataset length, seasonality, anomaly
  presence, and reproducibility in `tests/pipelines/anomaly/test_datasets.py`.
- [X] T006 [P] [US1] Test dataset registry entries are present and callable in
  `tests/pipelines/anomaly/test_datasets.py`.

### Implementation for User Story 1

- [X] T007 [US1] Implement `AnomalyDataset` dataclass in
  `src/ailf/pipelines/anomaly/datasets.py`.
- [X] T008 [US1] Implement `generate_simple_outlier_dataset` in
  `src/ailf/pipelines/anomaly/datasets.py`.
- [X] T009 [US1] Implement `generate_nab_like_synthetic` for point, level-shift, and trend
  anomaly types in `src/ailf/pipelines/anomaly/datasets.py`.
- [X] T010 [US1] Implement `generate_contextual_anomaly_dataset` in
  `src/ailf/pipelines/anomaly/datasets.py`.
- [X] T011 [US1] Implement `get_available_datasets` registry in
  `src/ailf/pipelines/anomaly/datasets.py`.

**Checkpoint**: Labeled anomaly datasets are reproducible and test-covered.

---

## Phase 3: User Story 2 - Run deterministic anomaly diagnostics (Priority: P1)

**Goal**: Pure diagnostic functions detect outliers/level shifts, partition labeled data, and
score predictions.

**Independent Test**: Run tools on seeded data and assert binary outputs, valid indices,
partition preservation, and metric schema.

### Tests for User Story 2

- [X] T012 [P] [US2] Test `detect_outliers` output shape, binary labels, simple recall target,
  empty input, and single-point input in `tests/pipelines/anomaly/test_tools.py`.
- [X] T013 [P] [US2] Test `detect_level_shift` on level-shift, smooth, and obvious-shift
  examples in `tests/pipelines/anomaly/test_tools.py`.
- [X] T014 [P] [US2] Test `split_by_anomaly` preserves length and separates normal/anomalous
  rows in `tests/pipelines/anomaly/test_tools.py`.
- [X] T015 [P] [US2] Test `compute_metrics` schema and degenerate cases in
  `tests/pipelines/anomaly/test_tools.py`.
- [X] T016 [P] [US2] Test integrated outlier and level-shift flows in
  `tests/pipelines/anomaly/test_tools.py`.

### Implementation for User Story 2

- [X] T017 [US2] Implement `detect_outliers` in `src/ailf/pipelines/anomaly/tools.py`.
- [X] T018 [US2] Implement `detect_level_shift` in `src/ailf/pipelines/anomaly/tools.py`.
- [X] T019 [US2] Implement `split_by_anomaly` in `src/ailf/pipelines/anomaly/tools.py`.
- [X] T020 [US2] Implement `compute_metrics` in `src/ailf/pipelines/anomaly/tools.py`.

**Checkpoint**: Deterministic anomaly diagnostics are test-covered.

---

## Phase 4: User Story 3 - Demonstrate intervention through a simple pipeline (Priority: P2)

**Goal**: Show baseline forecast, anomaly diagnosis, training-only cleaning intervention,
intervention forecast, MAE comparison, and recommendation.

- [X] T021 [US3] Implement `AnomalyDetectionPipeline` run orchestration in
  `src/ailf/pipelines/anomaly/pipeline.py`.
- [X] T022 [US3] Implement baseline and intervention Prophet MAE comparison in
  `src/ailf/pipelines/anomaly/pipeline.py`.
- [X] T023 [US3] Serialize pipeline output to `pocs/anomaly/pipeline_results.json` from the
  pipeline CLI in `src/ailf/pipelines/anomaly/pipeline.py`.

**Checkpoint**: The anomaly POC can run end to end and emit JSON results.

---

## Phase 5: User Story 4 - Produce human-readable POC artifacts (Priority: P3)

**Goal**: Write a dashboard artifact for reviewer inspection.

- [X] T024 [US4] Implement plotly dashboard creation in `pocs/anomaly/poc_visualization.py`.
- [X] T025 [US4] Commit/update sample POC artifacts
  `pocs/anomaly/pipeline_results.json` and `pocs/anomaly/agent_visualization.html`.

**Checkpoint**: Reviewers can inspect saved anomaly POC output without rerunning the pipeline.

---

## Phase 6: Polish & Validation

- [X] T026 Add this spec-kit documentation folder under
  `specs/004-anomaly-dataset-generation/`.
- [X] T027 Run `uv run pytest` or `.venv/bin/pytest` and confirm the full suite is green.
- [X] T028 Squash PR branch changes into a single reviewable commit after validation.

## Dependencies & Execution Order

1. Setup first, because pytest collection must be stable.
2. US1 dataset generators before US2 diagnostic tests that consume seeded data.
3. US2 tools before US3 pipeline orchestration.
4. US4 visualization after the pipeline writes JSON results.
5. Final validation and squash after docs and CI fix are complete.

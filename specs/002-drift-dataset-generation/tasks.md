---
description: "Task list for Drift Dataset Generation & Procurement"
---

# Tasks: Drift Dataset Generation & Procurement

**Input**: Design documents from `/specs/002-drift-dataset-generation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (generator-api.md, corpus-format.md), quickstart.md

**Tests**: INCLUDED. Test-first is NON-NEGOTIABLE here (Constitution Principle II; research R9):
the generator is deterministic logic, so failing tests asserting injected ground truth,
reproducibility, and knob-validation rejections MUST be written and fail before implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths are included in every task

## Path / shared-file notes

- Drift-specific code: `src/ailf/pipelines/drift/` · Generic plumbing: `src/ailf/core/datasets/`
  (review-gated shared-core touch per Principle VII).
- **`src/ailf/pipelines/drift/datasets.py` is touched by US1, US2, US3, and US4.** Tasks editing
  this single file are NOT marked `[P]` relative to each other and the stories that share it are
  sequenced (US1 → US2 → US3 → US4) to avoid same-file conflicts.
- **`src/ailf/core/datasets/__init__.py`** is touched by Foundational, US2, and US5 (export lines);
  those edits are sequential.
- Run tests with `uv run --extra dev pytest tests/pipelines/drift tests/core/datasets`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, and gitignored output dirs

- [ ] T001 Add the visual-overlay dependencies with `uv add plotly kaleido` (updates `pyproject.toml` and commits the refreshed `uv.lock`); confirm import with `uv run python -c "import plotly, kaleido"`
- [ ] T002 [P] Ensure the bulk output dirs `data/synthetic/` and `reports/` are gitignored in `/Users/hbalakr2/Documents/Learning/IISc/agent-in-the-loop-forecasting/.gitignore` (add entries if missing)
- [ ] T003 [P] Create the test package dirs `tests/core/datasets/` and confirm `tests/pipelines/drift/` exists (remove the `.gitkeep` placeholders once real test files land)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The generic, domain-agnostic `Case` container that EVERY user story produces or consumes (data-model.md → Case; contracts/generator-api.md → Case round-trip).

**⚠️ CRITICAL**: No user story work can begin until the `Case` container exists and round-trips.

- [ ] T004 [P] Write FAILING test for `Case` serialization round-trip (`to_dict`/`from_dict` preserve series values + labels + flags exactly; univariate `darts.TimeSeries` rehydration) in `tests/core/datasets/test_case.py`
- [ ] T005 Implement the generic `Case` container (fields: `case_id`, `series`, `labels`, `is_synthetic`, `labeled`, `config`, `metadata`; `to_dict()`/`from_dict()` to plain JSON-compatible data; series ↔ timestamp/value records) in `src/ailf/core/datasets/case.py`
- [ ] T006 Export `Case` from `src/ailf/core/datasets/__init__.py`

**Checkpoint**: `Case` round-trips losslessly — generation, corpus, loaders, and viz can now build on it.

---

## Phase 3: User Story 1 - Generate a single-flavor labeled drift case (Priority: P1) 🎯 MVP

**Goal**: A seeded, parameterized generator that emits a univariate `Case` containing exactly one injected drift flavor plus a machine-readable `DriftLabel`, reproducible from `(flavor, seed, config)`.

**Independent Test**: `generate_case(DriftFlavor.mean_level, seed=42)` returns a labeled synthetic `Case` whose label names flavor/onset/transition_width/affected_component; regenerating with the same seed yields identical series and labels; all four flavors generate with the correct affected component (quickstart §2).

### Tests for User Story 1 (write FIRST, ensure they FAIL) ⚠️

- [ ] T007 [P] [US1] Test case structure + reproducibility (same `(flavor, seed, config)` ⇒ identical series & labels; different seeds ⇒ same flavor/onset semantics, different noise) in `tests/pipelines/drift/test_generate_case.py`
- [ ] T008 [P] [US1] Test per-flavor injection correctness — the realized series actually exhibits the change over `[onset, onset+Δt]` (rolling-mean step for `mean_level`, slope bend for `trend_slope`, rolling-std growth for `variance_inflation`, seasonal-amplitude growth for `seasonal_amplitude`) in `tests/pipelines/drift/test_flavors.py`
- [ ] T009 [P] [US1] Test label correctness — `flavor`, `affected_component` (trend/seasonality/noise), `onset_index`, `onset_time`, `transition_width`, `magnitude` populated and consistent with config for each of the four flavors in `tests/pipelines/drift/test_labels.py`
- [ ] T010 [P] [US1] Test knob-validation rejections (FR-009 edge cases) — each raises a clear validation error, never a silently mislabeled/clamped case: onset too near either boundary, `transition_width < 1`, `onset+width` past end (rejected, NOT clamped), `magnitude == 0`, `variance_inflation` with `base_noise <= 0`, `seasonal_amplitude` without seasonality in `tests/pipelines/drift/test_validation.py`

### Implementation for User Story 1

- [ ] T011 [US1] Implement `DriftFlavor` enum (4 values bound to Prophet components) and the `DriftLabel` record (`to_dict`/`from_dict`, derives `affected_component` from flavor) in `src/ailf/pipelines/drift/datasets.py`
- [ ] T012 [US1] Implement `GeneratorConfig` (knobs + defaults from data-model.md) and the validation rules that reject contradictory knob combinations (FR-009) in `src/ailf/pipelines/drift/datasets.py`
- [ ] T013 [US1] Implement base-series composition (`linear_timeseries` + `sine_timeseries` + `gaussian_timeseries` from `darts.utils.timeseries_generation` via an isolated `np.random.default_rng(seed)`) and the clamped-linear/smoothstep transition-ramp helper (0 before onset → full magnitude across Δt → held for duration) in `src/ailf/pipelines/drift/datasets.py`
- [ ] T014 [US1] Implement the four per-flavor injectors (trend-slope ramp, mean-level ramp, variance-inflation noise scaling, seasonal-amplitude multiplier) operating on the ramp + base series in `src/ailf/pipelines/drift/datasets.py`
- [ ] T015 [US1] Implement `generate_case(flavor, *, seed=42, config=None) -> Case` wiring validation → base series → injector → `Case(is_synthetic=True, labeled=True, labels=[DriftLabel], config=…)` in `src/ailf/pipelines/drift/datasets.py`

**Checkpoint**: MVP — single-flavor labeled cases generate reproducibly with correct ground truth. SC-001, SC-002 satisfied. STOP and VALIDATE before proceeding.

---

## Phase 4: User Story 2 - Produce the reproducible eval corpus (Priority: P1)

**Goal**: A single command materializes the canonical ≈110-case corpus (≈25 × 4 single-flavor + ≈10 combined) to disk as `series.csv` + `labels.json` per case plus a `corpus.json` manifest, regenerable to an identical state from committed config; consumers enumerate it without bespoke parsing.

**Independent Test**: `uv run python -m ailf.pipelines.drift.corpus` writes the agreed composition under `data/synthetic/drift/`; deleting and re-running reproduces a byte-identical corpus; `load_corpus(...)` yields ≥110 enumerable `Case`s each with their labels (quickstart §4).

### Tests for User Story 2 (write FIRST, ensure they FAIL) ⚠️

- [ ] T016 [P] [US2] Test generic corpus persistence — write → read → enumerate identity for a `Case` (series.csv + labels.json + manifest row round-trip preserves series & labels) in `tests/core/datasets/test_corpus.py`
- [ ] T017 [P] [US2] Test `build_corpus` composition against the build config's declared counts (exactly 25 cases per flavor → 100 single-flavor split 25/25/25/25, plus 10 combined = 110 total; manifest lists every case) and full-corpus reproducibility (delete-and-rebuild with same `base_seed` + config ⇒ byte-identical `series.csv`/`labels.json`) in `tests/pipelines/drift/test_corpus.py`
- [ ] T018 [P] [US2] Test `generate_combined_case` — multiple injected flavors each represented by a distinct `DriftLabel`, coherent on overlapping onsets/components (FR-007) in `tests/pipelines/drift/test_combined.py`

### Implementation for User Story 2

- [ ] T019 [P] [US2] Implement generic corpus persistence — `write_case`, `load_corpus(root) -> Iterable[Case]`, manifest read/write/enumerate per corpus-format.md — in `src/ailf/core/datasets/corpus.py`
- [ ] T020 [US2] Export the corpus helpers from `src/ailf/core/datasets/__init__.py` (after T019, sequential with T006)
- [ ] T021 [US2] Implement `generate_combined_case(flavors, *, seed, configs=None) -> Case` (applies multiple injectors, one `DriftLabel` per flavor) in `src/ailf/pipelines/drift/datasets.py`
- [ ] T022 [US2] Implement the committed drift build config — the single source of truth for corpus composition: a knob sweep producing **exactly 25 cases per flavor (100 single-flavor) + 10 combined = 110 total**, with per-case onset/magnitude/Δt varied deterministically by case index — plus `build_corpus(root, *, base_seed, overwrite=False)` with deterministic per-case seeds, a `load_corpus` re-export, and the `__main__` CLI entry in `src/ailf/pipelines/drift/corpus.py` (depends on T019, T021)

**Checkpoint**: The reproducible on-disk corpus exists and is enumerable. SC-003, SC-007 satisfied.

---

## Phase 5: User Story 3 - Generate ambiguous (mid-transition-width) cases (Priority: P2)

**Goal**: The `transition_width` knob spans narrow (changepoint-like) → ambiguous → wide (clearly gradual), with named default bands, so deliberately ambiguous cases are producible on demand and small vs large Δt demonstrably differ in change concentration.

**Independent Test**: `generate_case(..., config=GeneratorConfig(transition_width=3))` vs `transition_width=120` both succeed; the small-Δt case concentrates the change in a narrow window, the large-Δt case spreads it across many points; labels record the respective widths (quickstart §3).

### Tests for User Story 3 (write FIRST, ensure they FAIL) ⚠️

- [ ] T023 [P] [US3] Test ambiguous-band generation and narrow-vs-wide change concentration (label records the given `transition_width`; measurable difference in how concentrated the transition is) in `tests/pipelines/drift/test_ambiguous.py`

### Implementation for User Story 3

- [ ] T024 [US3] Add named transition-width bands (e.g. `narrow` / `gradual` / `ambiguous`) as documented constants/helper without hard-committing the cross-team Δt threshold (spec Dependencies), in `src/ailf/pipelines/drift/datasets.py`

**Checkpoint**: Ambiguous cases controllable on demand. SC-004 satisfied.

---

## Phase 6: User Story 4 - Load a real demo series through the same interface (Priority: P2)

**Goal**: Two curated real univariate series (Air Passengers; Mauna Loa CO₂ resampled to regular monthly) load as `Case`s through the same interface as synthetic, flagged `labeled=False` / `is_synthetic=False` with documented `metadata.qualitative_drift`.

**Independent Test**: `load_air_passengers()` and `load_mauna_loa_co2()` each return an unlabeled `Case` with empty labels and a qualitative-drift description; CO₂ is regular monthly with no gaps; `list_real_series()` enumerates ≈2 (quickstart §5).

### Tests for User Story 4 (write FIRST, ensure they FAIL) ⚠️

- [ ] T025 [P] [US4] Test real-loader shape/flags (univariate `Case`, `labeled=False`, `labels==[]`, `metadata["qualitative_drift"]` set), CO₂ regular-monthly frequency (no gaps), and `list_real_series()` enumerates ≈2 in `tests/pipelines/drift/test_real_series.py`

### Implementation for User Story 4

- [ ] T026 [US4] Implement `load_air_passengers()` (Darts `AirPassengersDataset`), `load_mauna_loa_co2()` (`statsmodels.datasets.co2`, resampled to regular monthly), and `list_real_series()` returning `Case`s with `labeled=False` and documented `metadata.qualitative_drift`, in `src/ailf/pipelines/drift/datasets.py`

**Checkpoint**: Real demo series load via the shared interface, clearly unlabeled. SC-005 satisfied.

---

## Phase 7: User Story 5 - Visually confirm a case contains drift (Priority: P3)

**Goal**: A standard plotly overlay (observations + rolling mean + rolling-std band, with a vertical onset marker iff the case is labeled) reproducing proposal Figure 3, plus a helper that writes paired `.png` + `.html` under `reports/` for manual inspection.

**Independent Test**: `plot_drift_overlay(case)` returns a figure whose traces include observations, rolling mean, and a rolling-std band, with an onset marker present for a synthetic case and absent for a real series; `save_drift_overlay(...)` writes paired png/html named from `case_id` (quickstart §6).

### Tests for User Story 5 (write FIRST, ensure they FAIL) ⚠️

- [ ] T027 [P] [US5] Test overlay structure headlessly — figure contains observations + rolling-mean + rolling-std traces, onset marker present iff `case.labeled` (synthetic vs real), asserting on traces/shapes without rendering — in `tests/core/datasets/test_viz.py`

### Implementation for User Story 5

- [ ] T028 [US5] Implement `plot_drift_overlay(case, *, window=None) -> plotly.graph_objects.Figure` and `save_drift_overlay(case, out_dir="reports/", *, window=None) -> (png_path, html_path)` (HTML via `write_html`, PNG via `write_image`/kaleido) in `src/ailf/core/datasets/viz.py`
- [ ] T029 [US5] Export the viz functions from `src/ailf/core/datasets/__init__.py` (sequential with T006, T020)

**Checkpoint**: Any case is visually confirmable. SC-006 satisfied.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T030 [P] Add concise module docstrings to `src/ailf/core/datasets/{case,corpus,viz}.py` and `src/ailf/pipelines/drift/{datasets,corpus}.py` documenting the public surface (only where the WHY is non-obvious)
- [ ] T031 Run the full quickstart.md scenarios end-to-end (§2–§6) and confirm each behaves as documented (generate, ambiguous, build+load corpus, real loaders, overlay artifacts)
- [ ] T032 Run `uv run --extra dev pytest tests/pipelines/drift tests/core/datasets` and confirm green; keep existing core tests green (Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories (everything needs `Case`).
- **User Stories (Phase 3–7)**: All depend on Foundational. Priority order P1 (US1, US2) → P2 (US3, US4) → P3 (US5).
- **Polish (Phase 8)**: Depends on all targeted user stories.

### User Story Dependencies

- **US1 (P1)** — depends only on Foundational. The generation core other stories build on.
- **US2 (P1)** — depends on Foundational + **US1** (`build_corpus` calls `generate_case`; T021 combined generation extends US1's injectors). Generic corpus IO (T019) depends only on Foundational and can start in parallel with US1.
- **US3 (P2)** — depends on **US1** (`generate_case` + `transition_width`). Edits the same `datasets.py`.
- **US4 (P2)** — depends only on Foundational (`Case`). Edits the same `datasets.py` (sequence after US3 to avoid conflicts).
- **US5 (P3)** — depends on Foundational (`Case`); uses a synthetic case (US1) and a real case (US4) as test fixtures. Lives entirely in `core/datasets/viz.py`.

### Within Each User Story

- Tests are written FIRST and MUST FAIL before implementation (Principle II).
- Schema (`DriftFlavor`/`DriftLabel`/`GeneratorConfig`) before injectors before `generate_case`.
- Generic core (`case.py`, `corpus.py`) before the drift pipeline code that consumes it.

### Parallel Opportunities

- Setup: T002, T003 in parallel (T001 edits pyproject/lock; keep separate).
- Foundational: T004 (test) parallel-authorable; T005 then T006 sequential.
- US1 tests T007–T010 all `[P]` (separate test files). US1 impl T011–T015 are sequential (one file).
- US2 tests T016–T018 all `[P]`. Impl: T019 (core) `[P]` with US1; T021 (`datasets.py`) sequences after US1; T022 after T019+T021.
- US3/US4/US5 tests (T023, T025, T027) are `[P]` (separate files).
- **Cross-story caution**: US1, US2 (T021), US3, US4 all edit `src/ailf/pipelines/drift/datasets.py` — do NOT run those impl tasks in parallel; sequence US1 → US2(T021) → US3 → US4.

---

## Parallel Example: User Story 1 tests

```bash
# Author/run all US1 test files together (they live in separate files):
Task: "test_generate_case.py — structure + reproducibility"   # T007
Task: "test_flavors.py — per-flavor injection correctness"      # T008
Task: "test_labels.py — label correctness for 4 flavors"        # T009
Task: "test_validation.py — knob-validation rejections"         # T010
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (`Case`) → 3. Phase 3 US1 (generate_case).
4. **STOP and VALIDATE**: single-flavor labeled cases generate reproducibly with correct ground truth (SC-001, SC-002). This is the substrate every downstream drift deliverable rests on.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → MVP (labeled single-flavor cases).
3. US2 → reproducible on-disk corpus (the shared eval artifact).
4. US3 → ambiguous-case control · US4 → real demo series.
5. US5 → visual-confirmation overlay (human acceptance aid).

### Suggested MVP scope

**User Story 1 only** (Phases 1–3): satisfies SC-001 and SC-002 and unblocks the future drift-detection tool's unit tests.

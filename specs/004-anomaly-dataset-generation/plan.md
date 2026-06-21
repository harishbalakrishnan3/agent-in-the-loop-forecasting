# Implementation Plan: Anomaly Dataset Generation & Diagnostic POC

**Branch**: `003-anomaly-dataset-generation` | **Date**: 2026-06-16 | **Spec**:
[spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-anomaly-dataset-generation/spec.md`

## Summary

Document and validate the anomaly track work in PR #8: seeded synthetic anomaly generators,
deterministic outlier and level-shift diagnostics, a simple Prophet baseline-vs-intervention
pipeline, tests, and POC visualization artifacts. The work lives in the anomaly-owned pipeline
and POC directories, with no shared-core changes required.

Technical approach: keep anomaly-specific generation and tools in
`src/ailf/pipelines/anomaly/`; keep review/demo artifacts in `pocs/anomaly/`; keep deterministic
tests in `tests/pipelines/anomaly/`. The test suite is run by CI with pytest importlib mode so
duplicate test filenames across pipeline folders do not collide.

## Technical Context

**Language/Version**: Python >=3.11, managed by `uv`.

**Primary Dependencies**: numpy, pandas, Darts (`gaussian_timeseries`), scipy,
scikit-learn metrics, Prophet, plotly for POC visualization.

**Storage**: Generated datasets are in memory. POC outputs are written to
`pocs/anomaly/pipeline_results.json` and `pocs/anomaly/agent_visualization.html`.

**Testing**: pytest. Deterministic anomaly dataset and tool logic is covered by
`tests/pipelines/anomaly/`. Full CI runs `uv run pytest`.

**Target Platform**: Local development and GitHub Actions CI on Linux. POC also runs on macOS.

**Project Type**: Importable Python library plus POC artifacts.

**Performance Goals**: Small synthetic datasets should generate and test in seconds.

**Constraints**:
- Seeded generation must be reproducible.
- Dataset splits preserve temporal order.
- Diagnostics are pure typed functions.
- No anomaly pipeline code imports drift or changepoint pipelines.
- POC intervention cleans training data only.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Importable Core (Serializable Boundary)** - PASS. The public anomaly functions return
  pandas/numpy/dataclass values and JSON-serializable pipeline results.
- **II. Test-First for Deterministic Logic (NON-NEGOTIABLE)** - APPLIES. Dataset generators,
  splits, detectors, and metrics are deterministic logic and are covered by pytest tests under
  `tests/pipelines/anomaly/`.
- **III. Agent Quality Through Golden-Set Evaluation** - SUPPORTING. This feature supplies
  labeled synthetic examples that can become part of a future anomaly golden set.
- **IV. Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE)** - PARTIAL. The POC applies one
  bounded cleaning intervention and accepts it only if MAE improves. A full menu-based agent is
  out of scope.
- **V. Reproducible & Honest Evaluation** - PASS. Seeds are fixed, baseline and intervention MAE
  are both reported, and CI runs tests from the repository.
- **VI. Transparent, Explainable Outputs** - PASS. The pipeline emits logs and JSON results; the
  POC visualization creates an inspectable HTML dashboard.
- **VII. Shared Core, Independent Pipelines** - PASS. Work stays inside
  `src/ailf/pipelines/anomaly/`, `tests/pipelines/anomaly/`, `pocs/anomaly/`, and this feature
  spec folder.

**Gate result: PASS.** No non-negotiable violation is planned.

## Project Structure

### Documentation (this feature)

```text
specs/004-anomaly-dataset-generation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── tasks.md
```

### Source Code

```text
src/ailf/pipelines/anomaly/
├── __init__.py
├── datasets.py      # AnomalyDataset + seeded synthetic generators + splits
├── tools.py         # outlier/level-shift diagnostics + metrics
├── pipeline.py      # baseline/intervention POC pipeline
└── prompts/

tests/pipelines/anomaly/
├── test_datasets.py
└── test_tools.py

pocs/anomaly/
├── pipeline_results.json
├── poc_visualization.py
└── agent_visualization.html
```

**Structure Decision**: Keep the anomaly work independent. Unlike the drift feature, this
branch does not need new shared `core` dataset plumbing because the current anomaly API is a
small pandas-based POC surface.

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| POC pipeline writes artifacts under `pocs/anomaly/` | Reviewers need saved JSON and HTML output from the demonstration. | Keeping only in-memory output would make PR review harder. |
| Pytest importlib mode in `pyproject.toml` | Multiple pipeline folders use the same test basename, such as `test_datasets.py`. | Renaming all existing tests would create unnecessary churn across teams. |

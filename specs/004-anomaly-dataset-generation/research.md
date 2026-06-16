# Phase 0 Research: Anomaly Dataset Generation & Diagnostic POC

This document records the technical decisions behind the anomaly branch as implemented in PR
#8. The scope is a tested synthetic data and diagnostic foundation, not the final anomaly agent.

## R1. Synthetic labeled anomaly data

- **Decision**: Use small seeded synthetic datasets with explicit binary anomaly labels:
  Gaussian point outliers, NAB-like point/level-shift/trend anomalies, and a contextual seasonal
  anomaly dataset.
- **Rationale**: Known labels make precision, recall, and F1 measurable. Small generated data
  keeps CI fast and avoids external benchmark downloads.
- **Alternatives considered**: Real anomaly benchmarks such as NAB or spacecraft telemetry.
  Rejected for this PR because they add data procurement and licensing/format work beyond the
  current branch.

## R2. DataFrame schema

- **Decision**: Represent every anomaly dataset as a pandas DataFrame with `value` and
  `anomaly_label` columns, indexed by timestamps.
- **Rationale**: This is simple, serializable enough for POC work, and directly usable by the
  current detectors and Prophet pipeline.
- **Alternatives considered**: Reusing the generic `Case` container from `core.datasets`.
  Deferred. The anomaly branch already works with pandas and does not need corpus persistence in
  this PR.

## R3. Reproducibility

- **Decision**: Generators accept a seed, and tests assert repeated generation with the same seed
  produces the same DataFrame.
- **Rationale**: Satisfies the project reproducibility principle and prevents flaky diagnostic
  tests.
- **Alternatives considered**: Unseeded random anomaly placement. Rejected because test metrics
  would drift across runs.

## R4. Diagnostic tools

- **Decision**: Provide deterministic tools:
  - `detect_outliers` using a local median/MAD-style threshold.
  - `detect_level_shift` using rolling before/after mean shifts.
  - `split_by_anomaly` for labeled DataFrames.
  - `compute_metrics` using precision, recall, F1, and confusion matrix.
- **Rationale**: These tools are simple enough to audit, work on the generated synthetic data,
  and provide the future agent a typed tool surface.
- **Alternatives considered**: ML-based detectors. Rejected for this PR because they require
  training, model selection, and extra reproducibility controls.

## R5. Forecast intervention demonstration

- **Decision**: The POC pipeline compares default Prophet on original training data against
  Prophet after linearly interpolating detected anomalous training points.
- **Rationale**: This demonstrates the project loop: diagnose, intervene, validate with MAE, and
  accept/reject. It is bounded and easy to inspect.
- **Alternatives considered**: Multiple intervention menus or LLM-selected actions. Deferred to
  a later anomaly-agent feature.

## R6. Visualization artifact

- **Decision**: Use plotly to write `pocs/anomaly/agent_visualization.html`, backed by
  `pipeline_results.json`.
- **Rationale**: The artifact helps reviewers see the series, ground-truth anomalies, detected
  anomalies, level-shift markers, MAE comparison, and reasoning logs.
- **Alternatives considered**: Static matplotlib plot only. Rejected because the existing repo
  already uses plotly for interactive inspection.

## R7. CI test collection

- **Decision**: Configure pytest with `--import-mode=importlib`.
- **Rationale**: The repo has multiple pipeline folders with duplicate test filenames. Importlib
  mode avoids top-level module-name collisions without renaming team-owned test files.
- **Alternatives considered**: Rename `test_datasets.py` files or add package `__init__.py`
  files through all test folders. Rejected as higher churn.

# Feature Specification: Anomaly Dataset Generation & Diagnostic POC

**Feature Branch**: `003-anomaly-dataset-generation`

**Created**: 2026-06-16

**Status**: Draft

**Input**: User description: "Create a formal spec-kit feature record for the anomaly work in
PR #8: seeded anomaly dataset generators, deterministic anomaly diagnostic tools, a simple
forecast-intervention pipeline, tests, and POC visualization artifacts."

## Overview

The anomaly track needs a small, reproducible substrate for proving that outlier and
level-shift failures can be injected, detected, evaluated against known labels, and used to
drive a bounded forecasting intervention. This feature documents and validates the anomaly
work currently implemented under `src/ailf/pipelines/anomaly/` and `pocs/anomaly/`.

The primary deliverable is a seeded synthetic anomaly data layer with known labels. The
secondary deliverable is a deterministic diagnostic layer that flags point outliers and level
shifts, computes precision/recall/F1, and feeds a simple pipeline that compares a baseline
Prophet forecast with an anomaly-cleaned intervention.

This feature is intentionally narrower than the full future anomaly agent. It does not build a
provider-backed LLM loop or a production anomaly evaluation harness. It creates the tested data
and tool foundation for that later work.

## User Scenarios & Testing

### User Story 1 - Generate labeled anomaly datasets (Priority: P1)

An anomaly-track developer needs reproducible synthetic time series with ground-truth anomaly
labels so diagnostic tools can be tested against known injected events.

**Why this priority**: Diagnostic precision, recall, and F1 require known labels. Without the
seeded labeled datasets, downstream anomaly evaluation is not measurable.

**Independent Test**: Generate each registered dataset with a fixed seed; confirm schema,
length, anomaly counts, and reproducibility.

**Acceptance Scenarios**:

1. **Given** a request for a simple outlier dataset, **When** generation runs with a fixed seed,
   **Then** it returns a DataFrame with `value` and `anomaly_label` columns and the requested
   number of injected anomalies.
2. **Given** a request for a NAB-like point, level-shift, or trend anomaly dataset, **When**
   generation runs, **Then** it returns labeled observations and records the realized anomaly
   count.
3. **Given** a request for the contextual seasonal anomaly dataset, **When** generation runs,
   **Then** it returns a seasonal daily series with contextual anomaly labels.
4. **Given** identical seed and parameters, **When** generation is repeated, **Then** the
   returned series and labels are identical.

---

### User Story 2 - Run deterministic anomaly diagnostics (Priority: P1)

A developer validating the anomaly track needs pure Python tools that can detect outlier-like
points and level-shift-like changes, then score detections against ground truth.

**Why this priority**: These deterministic tools are the trustworthy substrate the agent will
call. They must be tested before any LLM reasoning depends on them.

**Independent Test**: Run the tools on seeded synthetic datasets and assert binary outputs,
valid index bounds, expected minimum recall on simple outliers, and metric schema.

**Acceptance Scenarios**:

1. **Given** a labeled outlier dataset, **When** `detect_outliers` runs, **Then** it returns one
   binary label per observation.
2. **Given** a level-shift synthetic dataset, **When** `detect_level_shift` runs, **Then** it
   returns detected shift indices within the valid series range.
3. **Given** true and predicted labels, **When** `compute_metrics` runs, **Then** it returns
   precision, recall, F1, and a confusion matrix.
4. **Given** a labeled DataFrame, **When** `split_by_anomaly` runs, **Then** normal and
   anomalous rows partition the original series without dropping observations.

---

### User Story 3 - Demonstrate intervention through a simple pipeline (Priority: P2)

A researcher wants a runnable anomaly POC that shows the diagnosis-to-intervention loop:
generate data, run a baseline forecast, detect anomalies, clean detected anomalous training
points, rerun the forecast, and accept or reject the intervention based on MAE.

**Why this priority**: This proves the anomaly data and tools can plug into the project thesis:
diagnosis should only matter if it improves a forecast under an objective gate.

**Independent Test**: Run the anomaly pipeline and inspect the returned JSON-like result for
logs, baseline/intervention MAE, anomaly metrics, recommendation, and timestamp.

**Acceptance Scenarios**:

1. **Given** the anomaly pipeline, **When** it runs with seed `42`, **Then** it generates a
   labeled level-shift dataset and logs every major step.
2. **Given** baseline and intervention forecasts, **When** the pipeline completes, **Then** it
   reports both MAE values and a recommendation to accept or reject the intervention.
3. **Given** detected anomaly labels, **When** the intervention is applied, **Then** only the
   training portion is cleaned before refitting.

---

### User Story 4 - Produce human-readable POC artifacts (Priority: P3)

A reviewer needs a quick way to inspect what the anomaly POC did without rerunning every step.

**Why this priority**: Visual and JSON artifacts make the POC easier to grade and debug, but the
tested dataset and diagnostic contracts are more important.

**Independent Test**: Run the visualization script after the pipeline result exists; confirm it
writes `pipeline_results.json` and `agent_visualization.html` under `pocs/anomaly/`.

**Acceptance Scenarios**:

1. **Given** a completed pipeline run, **When** results are saved, **Then** the JSON file includes
   logs, metrics, backtest results, recommendation, and timestamp.
2. **Given** the saved results, **When** the visualization script runs, **Then** it writes an
   interactive HTML dashboard showing the series, anomaly markers, diagnostics, MAE comparison,
   and recent reasoning log entries.

## Edge Cases

- **Empty input**: Outlier detection must fail clearly on an empty array.
- **Single-point input**: Outlier detection must return one non-anomalous label.
- **No anomalies in ground truth**: Metric computation must avoid divide-by-zero warnings and
  return a defined result.
- **Short series for level-shift detection**: The detector should return no shifts rather than
  indexing outside available windows.
- **Temporal leakage**: Dataset splits must preserve chronological order. Any cleaning
  intervention must use training rows only.
- **Duplicate test basenames**: Multiple pipeline folders may contain files named
  `test_datasets.py`; pytest collection must import tests in a way that avoids module-name
  collisions.

## Requirements

### Functional Requirements

**Dataset generation**

- **FR-001**: The system MUST provide a labeled `AnomalyDataset` container with name, series,
  description, anomaly count, optional period, and source.
- **FR-002**: The system MUST generate a simple Gaussian point-outlier dataset with configurable
  length, seed, and outlier count.
- **FR-003**: The system MUST generate NAB-like synthetic datasets for point, level-shift, and
  trend anomaly types.
- **FR-004**: The system MUST generate a contextual seasonal anomaly dataset.
- **FR-005**: Every generated dataset MUST expose a DataFrame with `value` and `anomaly_label`
  columns, where `anomaly_label` is binary.
- **FR-006**: Generation MUST be reproducible for identical seed and parameters.
- **FR-007**: The system MUST expose a dataset registry so callers can enumerate available
  generator functions.
- **FR-008**: The system MUST split datasets into train, validation, and test partitions while
  preserving time order.

**Diagnostic tools**

- **FR-009**: The system MUST provide a deterministic outlier detector returning binary labels
  aligned to the input array.
- **FR-010**: The system MUST provide a deterministic level-shift detector returning detected
  index positions.
- **FR-011**: The system MUST split a labeled DataFrame into normal and anomalous partitions.
- **FR-012**: The system MUST compute precision, recall, F1, and confusion matrix from true and
  predicted labels.
- **FR-013**: Diagnostic tools MUST handle edge cases clearly: empty arrays, single-point arrays,
  degenerate labels, and short series.

**Pipeline and artifacts**

- **FR-014**: The anomaly pipeline MUST run a baseline Prophet forecast and report baseline MAE.
- **FR-015**: The anomaly pipeline MUST detect anomalies, apply a bounded cleaning intervention
  to training data only, rerun Prophet, and report intervention MAE.
- **FR-016**: The anomaly pipeline MUST accept the intervention only if intervention MAE is lower
  than baseline MAE.
- **FR-017**: The pipeline result MUST be serializable as JSON with logs, backtest results,
  anomaly metrics, recommendation, and timestamp.
- **FR-018**: The POC visualization MUST write an interactive HTML artifact from the saved JSON
  result.

### Key Entities

- **AnomalyDataset**: Dataclass containing dataset metadata and a labeled pandas DataFrame.
- **Anomaly label**: Binary column where `0` means normal and `1` means anomalous.
- **Diagnostic result**: Binary label array for outliers or index array for level shifts.
- **Pipeline result**: Serializable dict with logs, metrics, MAE comparison, recommendation, and
  timestamp.

## Success Criteria

- **SC-001**: All anomaly generators produce correctly shaped labeled DataFrames.
- **SC-002**: Re-running generators with identical seed and parameters produces identical data.
- **SC-003**: Anomaly tools return well-formed outputs and metric dictionaries on seeded data.
- **SC-004**: The simple outlier detector catches a useful share of injected point outliers in
  the existing test threshold.
- **SC-005**: The pipeline emits baseline/intervention MAE and an accept/reject recommendation.
- **SC-006**: The POC visualization artifact can be generated from saved results.

## Assumptions

- The initial anomaly track focuses on synthetic labeled data, not curated real anomaly
  benchmarks.
- The pipeline is a POC-quality demonstration, not the final provider-backed ReAct agent.
- Prophet is sufficient for the POC forecast comparison already implemented in this branch.
- Tests are the merge gate for deterministic anomaly data and tools.

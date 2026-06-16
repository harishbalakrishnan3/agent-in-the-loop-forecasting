# Quickstart & Validation: Anomaly Dataset Generation & Diagnostic POC

Runnable checks for the anomaly feature. These mirror the acceptance scenarios in
[spec.md](./spec.md).

## Prerequisites

```bash
uv sync --extra dev
```

If `uv` is unavailable locally but the repo virtualenv already exists, use:

```bash
.venv/bin/pytest tests/pipelines/anomaly
```

## 1. Run anomaly tests

```bash
uv run pytest tests/pipelines/anomaly
```

**Expected**: green. Covers dataset shape, reproducibility, anomaly counts, split behavior,
outlier/level-shift detectors, anomaly partitioning, and metric computation.

## 2. Generate a labeled anomaly dataset

```python
from ailf.pipelines.anomaly.datasets import generate_simple_outlier_dataset

dataset = generate_simple_outlier_dataset(n_points=300, seed=42, outlier_count=10)
assert len(dataset.series) == 300
assert dataset.anomaly_count == 10
assert set(dataset.series.columns) == {"value", "anomaly_label"}
```

**Expected**: a timestamp-indexed DataFrame with binary anomaly labels.

## 3. Run diagnostics and metrics

```python
from ailf.pipelines.anomaly.datasets import generate_simple_outlier_dataset
from ailf.pipelines.anomaly.tools import detect_outliers, compute_metrics

dataset = generate_simple_outlier_dataset(n_points=300, seed=42, outlier_count=10)
predicted = detect_outliers(dataset.series["value"].values)
metrics = compute_metrics(dataset.series["anomaly_label"].values, predicted)

assert {"precision", "recall", "f1", "confusion_matrix"} <= metrics.keys()
```

**Expected**: binary predictions and a standard metric dictionary.

## 4. Run the anomaly pipeline

```bash
uv run python -m ailf.pipelines.anomaly.pipeline
```

**Expected**: prints a JSON-like result and writes:

```text
pocs/anomaly/pipeline_results.json
```

The result contains baseline MAE, intervention MAE, anomaly metrics, logs, and an
accept/reject recommendation.

## 5. Generate the POC visualization

```bash
uv run python pocs/anomaly/poc_visualization.py
```

**Expected**: writes:

```text
pocs/anomaly/agent_visualization.html
```

Open the HTML artifact to inspect the series, anomaly markers, level-shift markers, MAE
comparison, and recent reasoning-log entries.

## 6. Run full CI-equivalent tests

```bash
uv run pytest
```

**Expected**: green. Pytest is configured with importlib mode so duplicate test filenames in
different pipeline folders do not collide.

## Success-Criteria Traceability

| Scenario | Validates |
|----------|-----------|
| 1 | SC-001, SC-002, SC-003 |
| 2 | SC-001, SC-002 |
| 3 | SC-003, SC-004 |
| 4 | SC-005 |
| 5 | SC-006 |
| 6 | CI collection and cross-pipeline compatibility |

# Phase 1 Data Model: Anomaly Dataset Generation & Diagnostic POC

The anomaly branch uses a small pandas-based data model. Public data is simple and easily
serialized for POC artifacts.

## AnomalyDataset

Dataclass returned by all anomaly dataset generators.

| Field | Type | Notes |
|-------|------|-------|
| `name` | str | Human-readable dataset name. |
| `series` | pandas DataFrame | Time-indexed observations with `value` and `anomaly_label`. |
| `description` | str | What the dataset represents. |
| `anomaly_count` | int | Number of points labeled anomalous. |
| `period` | int or None | Seasonality period when applicable. |
| `source` | str | Generator/source identifier. |

## Series Schema

Every generated dataset uses:

| Column | Type | Meaning |
|--------|------|---------|
| `value` | float | Observed time-series value. |
| `anomaly_label` | int | `0` for normal, `1` for anomalous. |

The index is a pandas `DatetimeIndex`. Existing generators use daily timestamps starting at
`2020-01-01`.

## Dataset Generators

| Function | Output | Main knobs |
|----------|--------|------------|
| `generate_simple_outlier_dataset` | Gaussian baseline with injected spike outliers | `n_points`, `seed`, `outlier_count` |
| `generate_nab_like_synthetic` | Synthetic point, level-shift, or trend anomalies | `n_points`, `seed`, `anomaly_ratio`, `anomaly_type` |
| `generate_contextual_anomaly_dataset` | Seasonal series with contextual summer dips | `seed` |
| `get_available_datasets` | Registry of generator callables | none |

## Diagnostic Outputs

| Function | Input | Output |
|----------|-------|--------|
| `detect_outliers` | 1D numeric array | Binary numpy array aligned to input length. |
| `detect_level_shift` | 1D numeric array | Numpy array of detected shift indices. |
| `split_by_anomaly` | DataFrame with `anomaly_label` | `(normal_df, anomalous_df)`. |
| `compute_metrics` | true labels and predicted labels | Dict with precision, recall, F1, confusion matrix. |

## Dataset Split

`split_dataset(dataset, train_ratio=0.7, val_ratio=0.15)` partitions by position:

```text
train = [0, train_end)
val   = [train_end, val_end)
test  = [val_end, n)
```

No shuffling is performed.

## Pipeline Result

The anomaly pipeline returns and writes a JSON-compatible dict:

| Field | Type | Notes |
|-------|------|-------|
| `success` | bool | Whether the run completed. |
| `logs` | list[dict] | Timestamped step messages. |
| `backtest_results` | dict | `baseline_mae` and `intervention_mae`. |
| `anomaly_detection_metrics` | dict | precision, recall, F1, confusion matrix. |
| `recommendation` | str | Accept/reject decision based on MAE. |
| `timestamp` | str | Completion time. |

## Relationships

```text
Generator -> AnomalyDataset -> split_dataset -> Prophet baseline
                           -> diagnostic tools -> metrics
                           -> training-only cleaning intervention -> Prophet intervention
                           -> Pipeline result -> JSON + HTML visualization
```

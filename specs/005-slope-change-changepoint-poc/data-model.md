# Phase 1 Data Model: Slope-Change Changepoint POC

**Feature**: 005-slope-change-changepoint-poc | **Date**: 2026-06-20

All entities are plain, serializable Python data (dicts / dataclasses) — no UI types — keeping the
serializable-boundary principle (I) even though the POC is exempt.

---

## Entity: Slope-change series

A univariate synthetic time series built from a continuous piecewise-linear trend.

| Aspect | Detail |
|--------|--------|
| Representation | Darts `TimeSeries` (single component, datetime-indexed) |
| Trend construction | `base_level + cumsum(slope[t])`, slope starts at `initial_slope`, bumped by `slope_delta_i` at `changepoint_index_i` — continuous at every changepoint |
| Plus | optional additive seasonality, additive Gaussian noise (seeded) |
| Length | `length` points at frequency `freq` from `start_date` |

---

## Entity: Generator configuration (input)

Parameters accepted by `generate_slope_change_series(...)`.

| Field | Type | Default | Validation |
|-------|------|---------|-----------|
| `length` | int | 500 | > 0 |
| `freq` | str | "D" | valid pandas freq |
| `start_date` | str | "2023-01-01" | parseable date |
| `base_level` | float | 100.0 | any finite |
| `initial_slope` | float | 0.1 | any finite |
| `changepoint_indices` | list[int] | [] | each in `[min_segment, length - min_segment)`; strictly increasing |
| `slope_deltas` | list[float] | [] | `len == len(changepoint_indices)` |
| `noise_std` | float | 3.0 | ≥ 0 |
| `seasonality_period` | int \| None | None | None or > 1 |
| `seasonality_amplitude` | float | 0.0 | ≥ 0 |
| `min_segment` | int | 20 | ≥ 1 (boundary guard so each segment can define a slope) |
| `seed` | int | 42 | any int |
| `dataset_id` | str | "unnamed" | non-empty |

**Validation rules** (FR-007): mismatched `changepoint_indices`/`slope_deltas` lengths → error;
index out of `[min_segment, length - min_segment)` → error (boundary guard); non-increasing indices
→ error.

---

## Entity: Ground-truth metadata (output of generator)

Returned alongside the `TimeSeries`. JSON-serializable dict.

| Field | Type | Description |
|-------|------|-------------|
| `dataset_id` | str | catalog id, e.g. `"S1_single_gentle"` |
| `length` | int | series length |
| `changepoint_indices` | list[int] | planted slope-change indices |
| `changepoint_dates` | list[str] | dates at those indices |
| `slope_deltas` | list[float] | change in per-step slope at each changepoint |
| `slopes_per_segment` | list[float] | resulting slope in each segment (initial + cumulative deltas) |
| `type` | str | always `"slope_change"` |
| `noise_std` | float | noise level used |
| `base_level` | float | starting level |
| `initial_slope` | float | first-segment slope |
| `seasonality_period` | int \| None | seasonal period or null |
| `seasonality_amplitude` | float | seasonal strength |
| `seed` | int | seed used |

---

## Entity: Dataset catalog

`DATASET_CONFIGS`: ordered mapping `name -> config-dict`, plus `generate_all_datasets()` returning
`name -> (TimeSeries, metadata)`. The fixed 10 entries (per spec FR-006 / Clarifications):

| ID | Name | Shape | Expected |
|----|------|-------|----------|
| S1 | `single_gentle` | 1 small slope-delta, low noise | Easy / pass |
| S2 | `single_sharp` | 1 large slope-delta, low noise | Easy / pass |
| S3 | `single_subtle` | 1 small slope-delta, higher noise | Hard |
| S4 | `multiple_changes` | 3 slope changes | Medium |
| S5 | `noisy` | 1 slope change, high noise | Hard |
| S6 | `with_seasonality` | 1 slope change + seasonality | Medium |
| S7 | `trend_reversal` | slope flips sign | Medium |
| S8 | `close_together` | 2 changes a few points apart | Hard |
| S9 | `no_changepoint` | constant slope (control) | Control / pass |
| S10 | `frequent_changes` | many changes, near forecast horizon | Hardest / fail |

---

## Entity: Prophet evaluation result (output of evaluator)

Per-dataset record returned by the evaluator (dataclass `SlopeChangeEvalResult`). Serializable.

| Field | Type | Description |
|-------|------|-------------|
| `dataset_id` | str | which dataset |
| `train_end_index` | int | split point (80% of length) |
| `horizon` | int | held-out length (length − train_end_index) |
| `detected_changepoint_indices` | list[int] | retained Prophet changepoints (index units) |
| `detected_changepoint_dates` | list[str] | their dates |
| `matched_true_indices` | list[int] | ground-truth indices matched within tolerance |
| `detection_precision` | float | matched detections / all detections (0 if none) |
| `detection_recall` | float | matched truths / all true changepoints (1.0 if none to find) |
| `mae` | float | held-out mean absolute error |
| `rmse` | float | held-out root mean squared error |
| `mape` | float | held-out mean absolute percentage error (primary) |
| `classification` | str | `"pass"` / `"borderline"` / `"fail"` from MAPE bands |
| `expected_difficulty` | str | from catalog (easy/medium/hard/control) |

**Derived rules**:
- `classification` = `pass` if `mape ≤ 10`, `fail` if `mape ≥ 25`, else `borderline`.
- A true changepoint counts as matched if some detected changepoint is within `±5% × length` indices.
- Control (S9): zero true changepoints ⇒ `detection_recall = 1.0` by convention; any detection
  counts against precision.

---

## Entity: Catalog results summary

Aggregate over all 10 results (returned by `evaluate_all()` / rendered into `slope_change_poc.md`):
a table of one `SlopeChangeEvalResult` row per dataset, plus the explicit list of datasets with
`classification == "fail"` (the complex-dataset failure section, FR-022).

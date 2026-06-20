# Contract: Naive Prophet Evaluation (`prophet_eval.py`)

**Module**: `pocs.changepoint.slope_change.prophet_eval`

Self-contained — imports only `numpy`, `pandas`, `prophet`, `darts`, and the local `datasets`
module. No imports from `level_shift/` or `src/ailf/*` (FR-017).

---

## Tunable constants (documented, inspectable)

```python
TRAIN_FRACTION = 0.8          # hold out last 20% as the forecast horizon
PASS_MAPE = 10.0              # MAPE ≤ 10% ⇒ "pass" (Prophet handles it)
FAIL_MAPE = 25.0              # MAPE ≥ 25% ⇒ "fail" (baseline breaks down)
MATCH_TOL_FRACTION = 0.05     # changepoint match window = ±5% of series length
DELTA_KEEP_FRACTION = 0.01    # keep Prophet changepoints with |delta| ≥ 1% of max |delta|
```

---

## Dataclass: `SlopeChangeEvalResult`

Fields exactly as in data-model.md "Prophet evaluation result". Plain dataclass, serializable via
`dataclasses.asdict`.

---

## Function: `evaluate_dataset`

```python
def evaluate_dataset(
    series: "TimeSeries",
    metadata: dict,
) -> SlopeChangeEvalResult:
    """Fit naive (default) Prophet on the first TRAIN_FRACTION of the series,
    forecast the held-out remainder, score forecast error (MAE/RMSE/MAPE) on the
    horizon, extract Prophet's own changepoints (ranked by |trend delta|), match
    them to ground-truth slope changes within ±MATCH_TOL_FRACTION × length, and
    classify pass/borderline/fail by MAPE bands.
    """
```

### Contract guarantees

- **E1 (naive)**: constructs `Prophet()` with default settings (no changepoint hints, no custom
  priors, no manual seasonality beyond Prophet defaults); fits only on the training rows.
- **E2 (horizon)**: forecasts exactly the held-out tail; MAE/RMSE/MAPE computed on held-out actual
  vs. forecast only (FR-010).
- **E3 (detection)**: `detected_changepoint_indices` are Prophet changepoints with `|delta| ≥
  DELTA_KEEP_FRACTION × max|delta|`, mapped to series indices; matching uses the ±tolerance window
  (FR-009).
- **E4 (classification)**: `classification` derived from MAPE per the bands (FR-011).
- **E5 (robustness)**: handles zero detections and zero true changepoints without error (control
  S9 ⇒ recall 1.0 by convention).
- **E6 (completeness)**: every field populated for every dataset — no missing metric (SC-005).

---

## Function: `evaluate_all`

```python
def evaluate_all() -> list[SlopeChangeEvalResult]:
    """Generate the full catalog and evaluate each dataset. Returns one result
    per dataset in catalog order."""
```

## Function: `summarize` (report helper)

```python
def summarize(results: list[SlopeChangeEvalResult]) -> str:
    """Render a markdown per-dataset results table plus a 'Complex datasets where
    naive Prophet fails' section listing every result with classification == 'fail'
    and its metrics (FR-013, FR-021, FR-022)."""
```

Guarantee (FR-012 / SC-004): across the catalog, at least one dataset classifies as `pass` (a
simple one) and at least one as `fail` (a complex one); if the realized seeds do not produce this,
the catalog configs are tuned until they do (documented in the summary).

---

## CLI entry point

```bash
uv run python -m pocs.changepoint.slope_change.prophet_eval
# prints the per-dataset table to stdout
```

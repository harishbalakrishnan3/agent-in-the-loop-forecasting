# POC Spec: Slope-Change Detection & Naive-Prophet Evaluation in Changepoint Pipeline

**Owner:** Goutham
**Location:** `pocs/changepoint/slope_change/`
**Status:** Draft
**Created:** 2026-06-20

---

## Goal

Generate synthetic time series whose changepoints are **changes in trend slope** (the rate of
increase/decrease changes) rather than abrupt level jumps, with known planted ground truth, and
evaluate whether a **naive (default-configuration) Prophet** model can both (a) place its
automatic changepoints near the true slope changes and (b) forecast a held-out future horizon
accurately. The POC characterizes where a naive baseline breaks down — motivating later
agent-in-the-loop intervention.

---

## Scope (POC Only)

- Synthetic dataset generation (Darts) with configurable slope changes (continuous trend)
- Naive Prophet detection + forecast evaluation (default config, fit on train only)
- Unit tests proving generation against planted ground truth + an end-to-end Prophet smoke
- Interactive visualization (Plotly) and static PNG export for inspection and reports
- A summary report calling out the complex datasets where naive Prophet fails

**Out of scope for this POC:**
- Agent integration, forecasting *fixes*, interventions, backtesting
- Level-shift or variance-change detection (level_shift POC covers level shifts)
- Tuned Prophet — scope is strictly *naive* Prophet
- Production code promotion (stays in `pocs/`)

---

## Components

### 1. Dataset Generator (`datasets.py`)

Generate synthetic time series with known slope changes using Darts. The trend is a continuous
piecewise-linear function: the slope starts at `initial_slope` and is incremented by each
`slope_deltas[i]` at `changepoint_indices[i]`; values accumulate cumulatively so there is **no
level jump** at a changepoint.

**Interface:**

```python
from darts import TimeSeries

def generate_slope_change_series(
    length: int = 500,
    freq: str = "D",
    start_date: str = "2023-01-01",
    base_level: float = 100.0,
    initial_slope: float = 0.1,
    changepoint_indices: list[int] | None = None,
    slope_deltas: list[float] | None = None,
    noise_std: float = 3.0,
    seasonality_period: int | None = None,
    seasonality_amplitude: float = 0.0,
    min_segment: int = 20,
    seed: int = 42,
    dataset_id: str = "unnamed",
) -> tuple[TimeSeries, dict]:
    """Returns (Darts TimeSeries, ground-truth metadata dict)."""
```

**Datasets to generate (catalog):**

| ID | Name | Description | Difficulty |
|----|------|-------------|-----------|
| S1 | `single_gentle` | 1 slope change, small slope-delta, low noise | Easy |
| S2 | `single_sharp` | 1 slope change, large slope-delta, low noise | Easy |
| S3 | `single_subtle` | 1 slope change, small slope-delta, higher noise | Hard |
| S4 | `multiple_changes` | 3 slope changes at different positions | Medium |
| S5 | `noisy` | 1 slope change, high additive noise | Hard |
| S6 | `with_seasonality` | 1 slope change + weekly seasonal pattern | Medium |
| S7 | `trend_reversal` | 1 slope change where the slope flips sign | Medium |
| S8 | `close_together` | 2 slope changes only a few points apart | Hard |
| S9 | `no_changepoint` | Constant-slope series (negative control) | Control |
| S10 | `frequent_changes` | Many slope changes, with changes near the forecast horizon | Hardest |

**Ground-truth metadata format:**

```json
{
  "dataset_id": "S1_single_gentle",
  "length": 500,
  "changepoint_indices": [250],
  "changepoint_dates": ["2023-09-08"],
  "slope_deltas": [0.4],
  "slopes_per_segment": [0.1, 0.5],
  "type": "slope_change",
  "noise_std": 3.0,
  "base_level": 100.0,
  "initial_slope": 0.1,
  "seasonality_period": null,
  "seasonality_amplitude": 0.0,
  "seed": 42
}
```

---

### 2. Naive Prophet Evaluation (`prophet_eval.py`)

Fit default `Prophet()` on the first 80% of each series, forecast the held-out 20%, score
forecast error (MAE/RMSE/MAPE), extract Prophet's own changepoints (ranked by trend-delta
magnitude), match them to ground truth within a tolerance window, and classify pass/borderline/fail.

```python
@dataclass
class SlopeChangeEvalResult:
    dataset_id: str
    train_end_index: int
    horizon: int
    detected_changepoint_indices: list[int]
    detected_changepoint_dates: list[str]
    matched_true_indices: list[int]
    detection_precision: float
    detection_recall: float
    mae: float
    rmse: float
    mape: float
    classification: str        # "pass" | "borderline" | "fail"
    expected_difficulty: str
```

**Thresholds (tunable constants):** `TRAIN_FRACTION=0.8`, `PASS_MAPE=10.0`, `FAIL_MAPE=25.0`,
`MATCH_TOL_FRACTION=0.05` (±5% of series length), `DELTA_KEEP_FRACTION=0.01`.

---

### 3. Tests (`test_slope_change.py`)

Generator ground-truth (slope changes at planted indices, continuous trend), reproducibility,
control flatness, metadata schema, seasonality presence, input validation (incl. near-boundary
rejection), and an end-to-end Prophet-eval smoke on a simple and a complex dataset.

### 4. Visualization (`visualize.py`) + Static export (`export_plots.py`)

Interactive Plotly dashboard (dropdown over S1–S10) and one-PNG-per-dataset export showing the
raw series, ground-truth slope-change markers, Prophet's detected changepoints, and the
forecast-vs-actual overlay on the held-out horizon.

### 5. Summary report (`slope_change_poc.md`)

Per-dataset naive-Prophet results table plus a dedicated section calling out the complex datasets
where naive Prophet fails.

---

## File Structure

```
pocs/changepoint/slope_change/
├── spec.md              ← this file
├── __init__.py
├── datasets.py          ← Darts-based slope-change generator + S1–S10 catalog
├── prophet_eval.py      ← naive Prophet detection + forecast evaluation
├── test_slope_change.py ← unit tests (run with pytest)
├── visualize.py         ← Plotly interactive visualization
├── export_plots.py      ← static PNG export → plots/
├── slope_change_poc.md  ← summary report
└── plots/               ← exported PNGs (one per dataset)
```

---

## Dependencies

```
darts          # synthetic time series generation
prophet        # naive baseline under test (detection + forecast)
pandas, numpy  # data + piecewise-linear trend synthesis
plotly         # interactive visualization
kaleido        # static PNG export
pytest         # testing
```

All already present in the workspace `pyproject.toml`.

---

## Success Criteria

- [ ] All 10 datasets generated with correct ground-truth metadata
- [ ] Slope changes continuous (no level jump) at each changepoint
- [ ] Naive Prophet evaluated on all 10: detection + held-out forecast error
- [ ] ≥1 simple dataset passes (MAPE ≤ 10%), ≥1 complex dataset fails (MAPE ≥ 25%)
- [ ] Zero false-failure on the control (S9)
- [ ] All unit tests passing
- [ ] Interactive + static visualizations show ground truth vs. Prophet clearly
- [ ] Summary report with results table + complex-failure section
- [ ] Self-contained: no imports from `level_shift/` or `src/ailf/*`
- [ ] All code seeded and reproducible

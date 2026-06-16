# POC Spec: Level Shift Detection in Changepoint Pipeline

**Owner:** Meena  
**Location:** `pocs/changepoint/level_shift/`  
**Status:** Draft  
**Created:** 2026-06-15

---

## Goal

Prove that a PELT-based level shift detector can reliably identify abrupt mean changes
in synthetic time-series data, and that the detection is accurate enough to serve as
input to the agent-in-the-loop forecasting system.

---

## Scope (POC Only)

- Synthetic dataset generation (Darts) with configurable level shifts
- Level shift detection tool (ruptures, PELT with L2 cost)
- Unit tests proving detection against planted ground truth
- Interactive visualization (Plotly) for inspection and debugging

**Out of scope for this POC:**
- Agent integration
- Forecasting / fixing / backtesting
- Slope change or variance change detection
- Production code promotion (stays in `pocs/`)

---

## Components

### 1. Dataset Generator (`datasets.py`)

Generate synthetic time series with known level shifts using Darts.

**Interface:**

```python
from darts import TimeSeries

def generate_level_shift_series(
    length: int = 500,
    freq: str = "D",
    start_date: str = "2023-01-01",
    base_level: float = 100.0,
    base_slope: float = 0.0,
    noise_std: float = 5.0,
    changepoint_indices: list[int] | None = None,
    magnitudes: list[float] | None = None,
    seasonality_period: int | None = None,
    seasonality_amplitude: float = 0.0,
    seed: int = 42,
) -> tuple[TimeSeries, dict]:
    """
    Returns:
      - Darts TimeSeries object
      - Ground truth metadata dict
    """
```

**Datasets to generate:**

| ID | Name | Description | Difficulty |
|----|------|-------------|-----------|
| D1 | `single_large` | 1 changepoint, magnitude=40, noise=5 | Easy |
| D2 | `single_subtle` | 1 changepoint, magnitude=10, noise=8 | Hard |
| D3 | `multiple` | 3 changepoints at different positions | Medium |
| D4 | `noisy` | 1 changepoint, magnitude=30, noise=15 | Hard |
| D5 | `with_trend` | 1 changepoint + underlying linear trend | Medium |
| D6 | `with_seasonality` | 1 changepoint + weekly seasonal pattern | Medium |
| D7 | `close_together` | 2 changepoints only 50 points apart | Hard |
| D8 | `no_changepoint` | Clean series, no shifts (negative control) | Control |
| D9 | `large_series` | 1 changepoint in a 2000-point series | Medium |
| D10 | `small_magnitude_large_series` | Subtle shift in long series | Hard |

**Knobs/Parameters:**

| Parameter | Purpose | Range |
|-----------|---------|-------|
| `length` | Series length | 100 – 5000 |
| `base_level` | Starting mean | Any float |
| `base_slope` | Underlying trend | -1.0 to 1.0 |
| `noise_std` | Background noise | 0.1 – 50.0 |
| `changepoint_indices` | Where shifts occur | List of ints within [0, length) |
| `magnitudes` | Size of each shift | List of floats (positive or negative) |
| `seasonality_period` | Periodic pattern length | None, 7, 30, 365 |
| `seasonality_amplitude` | Seasonal strength | 0.0 – 50.0 |
| `seed` | Reproducibility | Any int |

**Ground truth metadata format:**

```json
{
  "dataset_id": "single_large",
  "length": 500,
  "changepoint_indices": [250],
  "changepoint_dates": ["2023-09-08"],
  "magnitudes": [40.0],
  "type": "level_shift",
  "noise_std": 5.0,
  "base_level": 100.0,
  "seed": 42
}
```

---

### 2. Detection Tool (`detector.py`)

Detect level shifts using PELT with L2 cost from the `ruptures` library.

**Interface:**

```python
from dataclasses import dataclass

@dataclass
class LevelShiftResult:
    changepoint_indices: list[int]
    changepoint_dates: list[str]
    magnitudes: list[float]          # mean(after) - mean(before) for each
    n_changepoints: int
    method: str                      # "pelt_l2"
    penalty: float | str             # penalty used

def detect_level_shift(
    series: TimeSeries | pd.DataFrame,
    penalty: float | str = "bic",
    min_segment_length: int = 10,
) -> LevelShiftResult:
    """
    Detect abrupt mean changes in a time series using PELT (L2 cost).
    
    Args:
        series: Input time series (Darts TimeSeries or DataFrame with [timestamp, value])
        penalty: Penalty for number of changepoints ("bic", "aic", or float)
        min_segment_length: Minimum number of points between changepoints
    
    Returns:
        LevelShiftResult with detected changepoint locations, dates, and magnitudes
    """
```

**Algorithm details:**
- Cost model: `l2` (detects changes in mean)
- Search method: PELT (Pruned Exact Linear Time) — optimal, fast
- Penalty selection: BIC by default (balances fit vs complexity)
- Post-processing: compute magnitude as `mean(segment_after) - mean(segment_before)`

---

### 3. Tests (`test_level_shift.py`)

**Test-first approach.** Write these before implementing.

| Test ID | Test | Assertion |
|---------|------|-----------|
| T1 | `test_finds_single_large_shift` | Detected index within ±5 of ground truth |
| T2 | `test_finds_multiple_shifts` | Finds all 3 changepoints (within ±5 tolerance) |
| T3 | `test_no_false_positives` | Returns 0 changepoints on clean data (D8) |
| T4 | `test_detects_subtle_shift` | Finds changepoint in D2 (may allow wider tolerance ±10) |
| T5 | `test_handles_noisy_data` | Finds changepoint in D4 (noisy) |
| T6 | `test_works_with_trend` | Finds level shift even with underlying slope (D5) |
| T7 | `test_works_with_seasonality` | Finds level shift even with seasonal pattern (D6) |
| T8 | `test_correct_magnitude` | Reported magnitude within ±20% of true magnitude |
| T9 | `test_output_schema` | Result has all required fields in LevelShiftResult |
| T10 | `test_reproducibility` | Same input → same output (deterministic) |

**Evaluation metrics (computed across all datasets):**

| Metric | Definition |
|--------|------------|
| Precision | correct detections / all detections |
| Recall | correct detections / all true changepoints |
| Detection delay | |detected_index - true_index| |
| False positive rate | false alarms on clean data |
| Magnitude accuracy | |detected_magnitude - true_magnitude| / true_magnitude |

Tolerance window: a detection is "correct" if within **±5 indices** of a ground truth changepoint.

---

### 4. Visualization (`visualize.py`)

Interactive Plotly dashboard for inspecting datasets and detection results.

**Features:**
- Plot raw time series with ground truth changepoints marked (vertical lines)
- Overlay detected changepoints (different color)
- Show segment means (horizontal lines per segment)
- Dropdown to switch between datasets (D1–D10)
- Hover info showing values, dates, magnitude
- Before/after mean annotations at each changepoint

**Usage:**
```bash
uv run python pocs/changepoint/level_shift/visualize.py
# Opens interactive Plotly figure in browser
```

---

## File Structure

```
pocs/changepoint/level_shift/
├── spec.md              ← this file
├── __init__.py
├── datasets.py          ← Darts-based synthetic data generator
├── detector.py          ← PELT L2 level shift detection
├── test_level_shift.py  ← unit tests (run with pytest)
└── visualize.py         ← Plotly interactive visualization
```

---

## Dependencies

```
darts          # synthetic time series generation
ruptures       # PELT changepoint detection
pandas         # data handling
numpy          # numerical operations
plotly         # interactive visualization
pytest         # testing
```

---

## Implementation Order

```
1. Write test_level_shift.py        → tests fail (no code yet)
2. Implement datasets.py            → generator works, dataset tests pass
3. Implement detector.py            → detection tests pass
4. Implement visualize.py           → visual inspection of results
5. Run full eval metrics            → precision, recall, delay across all datasets
```

---

## Success Criteria

- [ ] All 10 datasets generated with correct ground truth metadata
- [ ] Detection tool finds level shifts in D1, D3, D5, D6, D9 with precision ≥ 0.9
- [ ] Zero false positives on D8 (control)
- [ ] Detection delay ≤ 5 indices on easy datasets (D1, D3, D9)
- [ ] Magnitude accuracy within ±20% on easy datasets
- [ ] All unit tests passing
- [ ] Plotly visualization shows ground truth vs detected changepoints clearly
- [ ] All code seeded and reproducible

---

## Open Questions

- [ ] What penalty value works best across datasets? (Start with BIC, tune if needed)
- [ ] Should `min_segment_length` be configurable or fixed?
- [ ] How to handle detection near series boundaries (first/last 10 points)?
- [ ] Does PELT L2 struggle when trend + level shift coexist? (D5 will reveal this)

# Level Shift Detection POC — Summary Report

**Owner:** Meena  
**Date:** 2026-06-15  
**Location:** `pocs/changepoint/level_shift/`  
**Status:** Complete ✅

---

## What Was Built

A proof-of-concept for detecting **level shifts** (abrupt mean changes) in time-series data using the PELT algorithm with L2 cost, validated against synthetic datasets generated with Darts.

---

## Architecture

```
Input: Any time series (Darts TimeSeries or pandas DataFrame)
                │
                ▼
┌──────────────────────────────────────────────┐
│  detect_level_shift()                        │
│  Algorithm: PELT with L2 cost (ruptures)     │
│  Penalty: BIC (automatic)                    │
│  Min segment: 10 points                      │
└──────────────────────────────────────────────┘
                │
                ▼
Output: LevelShiftResult {
    changepoint_indices: [200],
    changepoint_dates: ["2023-07-20"],
    magnitudes: [+40.0],
    n_changepoints: 1,
    method: "pelt_l2",
    penalty: "bic"
}
```

---

## Files Created

| File | Purpose | Lines |
|------|---------|-------|
| `spec.md` | Detailed specification (requirements, interfaces, success criteria) | ~250 |
| `__init__.py` | Package marker | 1 |
| `datasets.py` | Synthetic dataset generator using Darts with configurable knobs | ~180 |
| `detector.py` | PELT L2-based level shift detection using ruptures | ~120 |
| `test_level_shift.py` | 20 unit tests (test-first methodology) | ~260 |
| `visualize.py` | Interactive Plotly dashboard with dropdown for all datasets | ~180 |

---

## Dataset Generator (`datasets.py`)

### What It Does
Generates synthetic time series with **known, planted level shifts** at exact positions. Uses Darts library for time series construction.

### Configurable Knobs

| Parameter | What it controls |
|-----------|-----------------|
| `length` | Series length (100–5000 points) |
| `base_level` | Starting mean value |
| `base_slope` | Underlying linear trend per step |
| `noise_std` | Gaussian noise standard deviation |
| `changepoint_indices` | Exact positions where shifts occur |
| `magnitudes` | Size of each shift (+/-) |
| `seasonality_period` | Period of seasonal pattern (None, 7, 30, 365) |
| `seasonality_amplitude` | Strength of seasonal component |
| `seed` | Random seed for reproducibility |

### 10 Pre-Configured Datasets

| ID | Name | Description | Difficulty |
|----|------|-------------|-----------|
| D1 | `single_large` | 1 shift, +40, low noise | Easy |
| D2 | `single_subtle` | 1 shift, +10, high noise (SNR ≈ 1.25) | Hard |
| D3 | `multiple` | 3 shifts at [150, 350, 500] | Medium |
| D4 | `noisy` | 1 shift, +30, very high noise (σ=15) | Hard |
| D5 | `with_trend` | 1 shift + underlying linear slope | Medium |
| D6 | `with_seasonality` | 1 shift + weekly seasonal pattern | Medium |
| D7 | `close_together` | 2 shifts only 50 points apart | Hard |
| D8 | `no_changepoint` | Clean series (negative control) | Control |
| D9 | `large_series` | 1 shift in 2000-point series | Medium |
| D10 | `small_magnitude_large_series` | Subtle shift (+8) in long series | Hard |

### Ground Truth Output

Each dataset produces a metadata dict:
```json
{
  "dataset_id": "D1_single_large",
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

## Detection Tool (`detector.py`)

### Algorithm: PELT with L2 Cost

- **PELT** (Pruned Exact Linear Time) — optimal changepoint search algorithm
- **L2 cost** — measures how well a constant mean fits each segment
- Finds points where splitting the series into segments with different means significantly reduces total squared error

### How It Works

$$\min \left[ \sum_{\text{segments}} \sum_{i \in \text{seg}} (y_i - \bar{y}_{\text{seg}})^2 + \text{penalty} \times k \right]$$

Where $k$ = number of changepoints. The penalty (BIC by default) prevents over-segmentation.

### Interface

```python
from pocs.changepoint.level_shift.detector import detect_level_shift, LevelShiftResult

result = detect_level_shift(
    series,                    # Darts TimeSeries or pandas DataFrame
    penalty="bic",             # "bic", "aic", or float
    min_segment_length=10,     # minimum points between changepoints
)

# result.changepoint_indices → [250]
# result.magnitudes → [40.2]
# result.n_changepoints → 1
```

### What It Returns

| Field | Type | Description |
|-------|------|-------------|
| `changepoint_indices` | `list[int]` | Positions where mean changes |
| `changepoint_dates` | `list[str]` | Corresponding timestamps |
| `magnitudes` | `list[float]` | Mean difference (after - before) at each point |
| `n_changepoints` | `int` | Count of detected shifts |
| `method` | `str` | Always `"pelt_l2"` |
| `penalty` | `float \| str` | Penalty value used |

---

## Test Results

```
20 passed in 16.23s
```

### Dataset Generator Tests (10)

| Test | What it verifies |
|------|-----------------|
| `test_output_type_and_shape` | Returns Darts TimeSeries with correct length |
| `test_metadata_has_required_fields` | All ground truth fields present |
| `test_reproducibility` | Same seed → identical output |
| `test_different_seeds_produce_different_output` | Different seeds → different series |
| `test_level_shift_present_single` | Mean jumps correctly at changepoint |
| `test_level_shift_present_multiple` | Multiple distinct levels after multiple shifts |
| `test_no_changepoint_control` | Control dataset has constant mean |
| `test_with_seasonality` | Shift visible despite seasonal pattern |
| `test_with_trend` | Shift visible despite linear trend |
| `test_metadata_dates_match_indices` | Date strings match index positions |

### Detection Tool Tests (10)

| Test | What it verifies |
|------|-----------------|
| `test_output_schema` | LevelShiftResult has all required fields |
| `test_finds_single_large_shift` | Detects obvious shift within ±5 indices |
| `test_finds_multiple_shifts` | Finds all 3 planted changepoints |
| `test_no_false_positives_on_clean_data` | Returns 0 on control dataset |
| `test_detects_subtle_shift` | Finds low-SNR shift (wider tolerance ±10) |
| `test_handles_noisy_data` | Finds shift in high-noise data |
| `test_works_with_trend` | Detects shift despite underlying slope |
| `test_works_with_seasonality` | Detects shift despite seasonal pattern |
| `test_correct_magnitude` | Reported magnitude within ±20% of truth |
| `test_reproducibility` | Same input → same detection output |

---

## Visualization (`visualize.py`)

### What It Shows

Interactive Plotly dashboard with:
- **Blue line:** Raw time series values
- **Green dashed lines:** Ground truth changepoints (where we planted them)
- **Red dotted lines:** Detected changepoints (where PELT found them)
- **Colored dashed lines:** Segment means (average value per segment)
- **Dropdown menu:** Switch between all 10 datasets

### How to Run

```bash
uv run python -m pocs.changepoint.level_shift.visualize
```

Opens in browser. Use the dropdown (top-left) to switch between D1–D10.

### What to Look For

| Dataset | Expected Observation |
|---------|---------------------|
| D1 | Green and red lines overlap exactly — detection is spot-on |
| D2 | Red line may be slightly offset — subtle shift is harder |
| D3 | Three green lines, three red lines — all found |
| D4 | Red line near green but noisier — high noise doesn't prevent detection |
| D5 | Shift clearly visible despite upward slope |
| D6 | Shift clearly visible despite wave pattern |
| D7 | Two close shifts both detected |
| D8 | No red lines — no false alarms on clean data |
| D9 | Works on long series just as well |
| D10 | Subtle shift in long series — hardest case |

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Detection algorithm | PELT (not Prophet) | Model-agnostic, exact location, detects mean changes directly |
| Cost model | L2 | Specifically designed for mean change detection |
| Penalty | BIC (automatic) | Balances sensitivity vs false positives without manual tuning |
| Data library | Darts | Project standard, provides TimeSeries type |
| Visualization | Plotly (not matplotlib) | Interactive, zoomable, dropdown switching |
| Testing approach | Test-first | Constitution Principle II (non-negotiable) |

---

## How This Feeds Into the Full System

```
THIS POC (standalone)
  ├── datasets.py    → becomes src/ailf/pipelines/changepoint/datasets_level_shift.py
  ├── detector.py    → becomes src/ailf/pipelines/changepoint/tools_level_shift.py
  └── tests          → moves to tests/pipelines/changepoint/

FULL SYSTEM (later)
  detect_changepoints() wrapper calls:
    ├── detect_level_shift()      ← THIS (Meena)
    ├── detect_slope_change()     ← Person B
    └── detect_variance_change()  ← Person C
            │
            ▼
  Agent receives typed results → picks intervention → backtest validates
```

---

## Commands Reference

```bash
# Run all tests
uv run python -m pytest pocs/changepoint/level_shift/test_level_shift.py -v

# Open interactive visualization
uv run python -m pocs.changepoint.level_shift.visualize

# Generate all datasets programmatically
uv run python -c "from pocs.changepoint.level_shift.datasets import generate_all_datasets; print(list(generate_all_datasets().keys()))"
```

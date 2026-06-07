# Changepoint Detection Pipeline — Specification

> Owners: Goutham, Meena, Dinesh

---

## 1. Overview

This document specifies the changepoint detection pipeline: synthetic data generation, standard dataset curation, the detection tool, and validation. The pipeline feeds into the Agent-in-the-Loop system as both **test data** (Phase 1) and a **diagnostic tool** (Phase 3).

---

## 2. Definitions

### What is a changepoint?

A timestamp at which the statistical structure of a time series changes abruptly. Unlike drift (gradual), a changepoint is localized to a narrow time window.

### Types of changepoints

| Type | Description | Example |
|------|-------------|---------|
| Level shift | Mean jumps to a new value | Revenue goes from ~$2,000/day → ~$3,200/day overnight |
| Slope change | Trend rate changes | Growth rate goes from +2%/month → +8%/month |
| Variance change | Noise amplitude changes | Daily fluctuations go from ±$50 → ±$200 |
| Seasonality change | Periodic pattern changes | Weekend effect doubles in magnitude |

---

## 3. Synthetic Dataset Generation

### 3.1 Generator Interface

```python
def generate_changepoint_series(
    length: int,                          # total number of data points
    freq: str,                            # "D", "H", "W", etc.
    start_date: str,                      # e.g., "2023-01-01"
    changepoint_type: str,                # "level_shift" | "slope_change" | "variance_change" | "seasonality_change"
    changepoint_indices: list[int],       # positions where changepoints occur
    magnitude: float | list[float],       # size of the shift(s)
    noise_std: float,                     # background noise level
    base_level: float,                    # starting mean value
    base_slope: float,                    # starting trend slope
    seasonality_period: int | None,       # e.g., 7 for weekly
    seasonality_amplitude: float,         # amplitude of seasonal component
    seed: int | None,                     # for reproducibility
) -> tuple[pd.DataFrame, dict]:
    """
    Returns:
        - DataFrame with columns: [timestamp, value]
        - metadata dict with ground truth
    """
```

### 3.2 Output Format

**CSV:** `datasets/changepoints/synthetic/<name>.csv`

```csv
timestamp,value
2023-01-01,102.3
2023-01-02,98.7
...
```

**Metadata:** `datasets/changepoints/synthetic/<name>_meta.json`

```json
{
  "name": "level_shift_single",
  "changepoint_type": "level_shift",
  "length": 500,
  "freq": "D",
  "start_date": "2023-01-01",
  "changepoint_dates": ["2023-08-15"],
  "changepoint_indices": [226],
  "magnitude": [30.0],
  "noise_std": 5.0,
  "base_level": 100.0,
  "base_slope": 0.0,
  "seed": 42,
  "generator_version": "1.0.0"
}
```

### 3.3 Datasets to Generate

| # | Name | Type | # Changepoints | Difficulty |
|---|------|------|-----------------|------------|
| 1 | `level_shift_single` | Level shift | 1 | Easy |
| 2 | `level_shift_multi` | Level shift | 3 | Medium |
| 3 | `slope_change_single` | Slope change | 1 | Easy |
| 4 | `slope_change_gradual` | Slope change | 1 (subtle) | Hard |
| 5 | `variance_change` | Variance change | 1 | Medium |
| 6 | `seasonality_change` | Seasonality change | 1 | Hard |
| 7 | `mixed_types` | Level + slope | 2 (different types) | Hard |
| 8 | `noisy_level_shift` | Level shift | 1 (high noise) | Hard |
| 9 | `no_changepoint` | None | 0 | Control |

> Dataset #9 is a **negative control** — the tool should return no changepoints.

### 3.4 Configurable Knobs

| Knob | What it controls | Why it matters |
|------|-----------------|----------------|
| `magnitude` | Size of the shift | Small shifts are harder to detect |
| `noise_std` | Background noise | High noise masks the changepoint |
| `length` | Series length | Short series = less evidence |
| `n_changepoints` | Number of breaks | Multiple breaks test robustness |
| `seasonality_amplitude` | Seasonal pattern strength | Seasonality can mask or mimic changepoints |

---

## 4. Standard / Benchmark Datasets

Curate 2–3 real-world datasets with known changepoints.

| # | Dataset | Source | Known Changepoints | Notes |
|---|---------|--------|--------------------|-------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

> TODO: Fill in after literature/dataset search. Candidates: Nile river flow, UK coal production, well-log data, BOCPD benchmarks.

---

## 5. Changepoint Detection Tool

### 5.1 Interface

```python
def detect_changepoints(
    series: pd.DataFrame,                 # columns: [timestamp, value]
    method: str = "pelt",                 # "pelt" | "binseg" | "bocpd" | "prophet_builtin"
    penalty: str | float = "bic",         # penalty for number of changepoints
    min_segment_length: int = 10,         # minimum points between changepoints
) -> dict:
    """
    Returns:
        {
            "changepoints_detected": ["2023-08-14", "2023-08-16"],
            "changepoint_indices": [225, 227],
            "confidence": [0.95, 0.88],
            "method": "pelt",
            "n_changepoints": 2
        }
    """
```

### 5.2 Candidate Algorithms

| Algorithm | Library | Pros | Cons |
|-----------|---------|------|------|
| PELT | `ruptures` | Fast, exact, penalty-based | Needs penalty tuning |
| Binary Segmentation | `ruptures` | Simple, interpretable | Approximate |
| BOCPD | `bayesian_changepoint_detection` | Online, probabilistic | Slower |
| Prophet built-in | `prophet` | Already in the stack | Less control |

> TODO: Pick primary algorithm after experimentation. Start with PELT via `ruptures`.

### 5.3 Output Contract

The tool must return a **consistent schema** regardless of algorithm, so the agent can consume it uniformly.

```python
@dataclass
class ChangepointResult:
    changepoints_detected: list[str]      # ISO date strings
    changepoint_indices: list[int]        # integer positions
    confidence: list[float]               # 0.0 – 1.0 per changepoint
    method: str                           # algorithm used
    n_changepoints: int                   # count
```

---

## 6. Validation Plan

### 6.1 Unit Tests for the Generator

| Test | Assertion |
|------|-----------|
| Output shape | DataFrame has `length` rows, columns `[timestamp, value]` |
| Metadata consistency | `changepoint_indices` match `changepoint_dates` |
| Reproducibility | Same `seed` → same output |
| No-changepoint control | Dataset #9 has constant mean (within noise) |
| Level shift present | Mean of segment after changepoint ≈ `base_level + magnitude` |

### 6.2 Unit Tests for the Detection Tool

| Test | Input | Expected Output |
|------|-------|-----------------|
| Finds obvious level shift | `level_shift_single` | Detected date within ±3 days of ground truth |
| Finds multiple changepoints | `level_shift_multi` | Finds all 3 (within tolerance) |
| Returns empty on clean data | `no_changepoint` | `n_changepoints == 0` |
| Handles noisy data | `noisy_level_shift` | Still finds the changepoint (may have lower confidence) |

### 6.3 Evaluation Metrics

| Metric | Definition |
|--------|------------|
| **Precision** | (correctly detected changepoints) / (all detected changepoints) |
| **Recall** | (correctly detected changepoints) / (all true changepoints) |
| **Detection delay** | |true_date − detected_date| in days |
| **False positive rate** | False alarms on clean data |

> A detected changepoint is "correct" if it falls within a tolerance window (e.g., ±5 days) of a ground-truth changepoint.

---

## 7. Integration with Agent

### How the agent uses this tool

```
Agent receives: time series + bad forecast
        │
        ▼
Agent calls: detect_changepoints(series, method="pelt")
        │
        ▼
Tool returns: {"changepoints_detected": ["2023-08-15"], "confidence": [0.95]}
        │
        ▼
Agent decides: "Add changepoint at 2023-08-15" (from intervention menu)
        │
        ▼
System refits Prophet with changepoints=["2023-08-15"]
        │
        ▼
Backtest validates the fix
```

### Tool contract with the agent framework

```python
# The agent framework calls tools by name and passes arguments as dict
TOOL_REGISTRY = {
    "detect_changepoints": {
        "function": detect_changepoints,
        "description": "Detect abrupt structural changes in a time series.",
        "parameters": {
            "series": "DataFrame with columns [timestamp, value]",
            "method": "Algorithm: pelt | binseg | bocpd (default: pelt)",
        },
        "returns": "ChangepointResult with detected dates, indices, and confidence scores"
    }
}
```

---

## 8. Folder Structure

```
datasets/
└── changepoints/
    ├── synthetic/
    │   ├── level_shift_single.csv
    │   ├── level_shift_single_meta.json
    │   ├── level_shift_multi.csv
    │   ├── level_shift_multi_meta.json
    │   ├── ... (all datasets from §3.3)
    │   └── no_changepoint.csv
    └── benchmark/
        ├── <real_dataset_1>.csv
        ├── <real_dataset_1>_meta.json
        └── ...

tools/
└── changepoint_detection/
    ├── __init__.py
    ├── detector.py             # detect_changepoints() function
    ├── models.py               # ChangepointResult dataclass
    └── tests/
        ├── test_detector.py
        └── test_generator.py

generators/
└── changepoint_generator.py    # generate_changepoint_series() function
```

---

## 9. Dependencies

```
darts              # time series generation utilities
ruptures           # changepoint detection (PELT, BinSeg)
pandas
numpy
matplotlib         # for visual validation
pytest             # testing
```

---

## 10. Open Questions

- [ ] Which algorithm to use as default? (Start with PELT, evaluate others)
- [ ] What tolerance window for "correct" detection? (±3 days? ±5 days?)
- [ ] Should the tool return changepoint *type* (level/slope/variance) or just location?
- [ ] How to handle multiple methods disagreeing on changepoint locations?
- [ ] Does the team also own the Prophet refitting step, or does Agent Development handle that?
- [ ] Which real-world benchmark datasets to use?



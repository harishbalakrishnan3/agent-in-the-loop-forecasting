# Contract: Dataset Generator (`datasets.py`)

**Module**: `pocs.changepoint.slope_change.datasets`

Self-contained — imports only `numpy`, `pandas`, `darts`. No imports from `level_shift/` or
`src/ailf/*` (FR-017).

---

## Function: `generate_slope_change_series`

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
    """Generate a synthetic series whose changepoints are slope changes.

    The trend is continuous piecewise-linear: slope starts at `initial_slope`
    and is incremented by `slope_deltas[i]` at `changepoint_indices[i]`; values
    accumulate cumulatively so there is NO level jump at a changepoint. Optional
    additive seasonality and seeded Gaussian noise are added on top.

    Returns (TimeSeries, ground_truth_metadata_dict).
    """
```

### Contract guarantees

- **C1 (continuity)**: at each changepoint index `i`, `|trend[i] - trend[i-1]|` is on the order of
  the local slope (no discontinuous jump) — distinguishes slope change from level shift.
- **C2 (slope change)**: the average slope of the segment after a changepoint differs from the
  segment before it by `slope_deltas[i]` (within numerical/noise tolerance on the noise-free trend).
- **C3 (reproducibility)**: identical args (incl. `seed`) ⇒ identical values (FR-005).
- **C4 (validation)**: raises `ValueError` on length mismatch between `changepoint_indices` and
  `slope_deltas`, on any index outside `[min_segment, length - min_segment)`, or on non-increasing
  indices (FR-007).
- **C5 (metadata)**: returns a dict with exactly the fields in data-model.md "Ground-truth
  metadata", `type == "slope_change"`, and `changepoint_dates` matching the indices.

---

## Constant: `DATASET_CONFIGS`

`dict[str, dict]` — ordered, 10 entries `S1_…` … `S10_…` (names per data-model.md catalog). Each
value is a kwargs dict for `generate_slope_change_series` including a unique `seed` and matching
`dataset_id`. Difficulty is encoded via slope-delta size, `noise_std`, changepoint count, and
changepoint placement relative to the 80% split.

## Function: `generate_all_datasets`

```python
def generate_all_datasets() -> dict[str, tuple[TimeSeries, dict]]:
    """Generate all 10 catalog datasets → {name: (TimeSeries, metadata)}."""
```

Guarantee: returns exactly the 10 catalog entries, each satisfying C1–C5.

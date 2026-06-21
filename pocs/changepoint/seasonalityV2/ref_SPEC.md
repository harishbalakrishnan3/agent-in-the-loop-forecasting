# POC Spec: Changepoint Detection — Seasonality Amplitude Shift

**Location**: `pocs/changepoint/seasonality/` (original) → `pocs/changepoint/seasonalityV2/` (reference copy)

**Status**: Reference — 2026-06-15 (original), copied 2026-06-20

**Exemption**: POC area. No quality gates, no merge checks, no PR
requirements (constitution POC exemption). Code is throwaway until
explicitly promoted into `src/ailf/pipelines/changepoint/`.

---

## Goal

Prove, on synthetic data, that:

1. A seasonality amplitude shift (abrupt doubling/halving of seasonal
   swing) is **visually obvious** in a plotly overlay.
2. PELT with an `rbf` cost model can **reliably find** a planted
   amplitude-shift changepoint.
3. PELT produces **no false positives** on a control series with no
   injected change.

This is milestone M1 for the changepoint track ("issue reproduces and
is detectable on known data").

---

## Files

| File | Responsibility |
|---|---|
| `ref_datasets_seasonal.py` | Synthetic generator: base series + amplitude-shift injection |
| `ref_tools_seasonal.py` | `detect_seasonality_change()` using PELT (rbf cost) |
| `ref_test_seasonal.py` | Tests: planted-change detection + control (no false positives) |
| `ref_viz_seasonal.py` | Interactive plotly overlay; run as a script to inspect |

No notebooks required. Plain scripts are sufficient and importable.

---

## Prerequisite: `ruptures`

PELT comes from the `ruptures` library, which is **not yet in
`pyproject.toml`**. Before running any code here:

1. Confirm `ruptures` is reachable via Walmart Artifactory (if on the
   internal network). Internal pip index: look up the correct
   `--index-url` via `content_search` or your team's Artifactory docs.
2. Add it: `uv add ruptures` (or with `--index-url` pointing at
   Artifactory).
3. Commit the updated `pyproject.toml` and `uv.lock`.

If `ruptures` is not installable in the current environment, the
detection step and tests are blocked until this is resolved.
`ref_datasets_seasonal.py` and `ref_viz_seasonal.py` can still be
developed independently (they only need `darts`, `numpy`, `plotly`).

---

## `ref_datasets_seasonal.py`

### Purpose

Generate a univariate synthetic series with a single abrupt seasonality
amplitude shift at a known index, plus a control series with no change.

### Approach

Mirror the drift track's `_base_components` pattern — copy it, do not
import from `src/ailf/pipelines/drift/`. This keeps the POC
self-contained and avoids pipeline coupling.

```
Base series:  y(t) = trend(t) + seasonal(t) + noise(t)

  trend    — flat (end_value ≈ start_value, or zero) so rbf isn't
             distracted by trend signal; use linear_timeseries with
             start_value=0, end_value=0.
  seasonal — sine_timeseries(value_frequency=1/period,
                              value_amplitude=A)
  noise    — np.random.default_rng(seed).standard_normal(length)
             scaled by base_noise

Injection (amplitude shift at break_index k):
  seasonal[t] = A                      for t < k
  seasonal[t] = A * (1 + magnitude)    for t >= k

Implemented via a step mask:

  def _step(length, break_index):
      s = np.zeros(length)
      s[break_index:] = 1.0
      return s

  seasonal_shifted = seasonal * (1.0 + magnitude * step)
  y = trend + seasonal_shifted + noise
```

### Public surface

```python
def generate_seasonal_shift(
    length: int = 365,
    break_index: int | None = None,   # defaults to length // 2
    magnitude: float = 1.0,           # amplitude doubles by default
    seasonality_period: int = 30,
    seasonality_amplitude: float = 5.0,
    base_noise: float = 0.5,          # low noise so shift is dominant
    seed: int = 42,
    start: str = "2020-01-01",
    freq: str = "D",
) -> tuple[TimeSeries, int]:
    """Return (series, break_index). break_index is the ground truth."""

def generate_control(
    length: int = 365,
    seasonality_period: int = 30,
    seasonality_amplitude: float = 5.0,
    base_noise: float = 0.5,
    seed: int = 99,
    start: str = "2020-01-01",
    freq: str = "D",
) -> TimeSeries:
    """No injected change — used for false-positive testing."""
```

---

## `ref_tools_seasonal.py`

### Purpose

Wrap PELT (rbf cost model) into a single clean function.

### Public surface

```python
def detect_seasonality_change(
    series: TimeSeries,
    pen: float = 3.0,
    min_size: int = 2,
) -> list[int]:
    """
    Run PELT with rbf cost on the series values.
    Returns a list of detected break indices (0-based, excluding the
    final index which ruptures always appends).
    pen controls the penalty — the key tunable for precision/recall.
    """
```

---

## `ref_test_seasonal.py`

### Purpose

Two focused assertions — no quality gates, but they must actually fail
and pass to constitute "proof."

### Tests

**Test 1 — Planted change is found:**

```python
series, true_break = generate_seasonal_shift(seed=42)
detected = detect_seasonality_change(series, pen=3.0)
assert len(detected) == 1
assert abs(detected[0] - true_break) <= 5   # ±5-point tolerance window
```

**Test 2 — No false positives on control series:**

```python
control = generate_control(seed=99)
detected = detect_seasonality_change(control, pen=3.0)
assert detected == []
```

---

## `ref_viz_seasonal.py`

### Purpose

Standalone plotly script. Run it to visually inspect a generated case.
Not imported by tests.

### What to show

A single plotly figure with:

- **Trace 1**: raw series values (thin line, `mode="lines"`)
- **Trace 2**: rolling mean (window = `seasonality_period`, dashed)
- **Trace 3**: rolling std band (`mean ± std`, filled area, low opacity)
- **Vertical line**: at the injected `break_index` (red dashed `vline`)
- **Title**: "Seasonality Amplitude Shift — break at index {k}"

### Usage

```bash
uv run python pocs/changepoint/seasonalityV2/ref_viz_seasonal.py
# opens interactive plotly in browser (or saves to reports/ if headless)
```

---

## What "proven" means

The POC is considered successful when:

1. `ref_viz_seasonal.py` produces an overlay where the amplitude shift is
   **visually unambiguous** (the swing clearly widens/narrows post-break).
2. `ref_test_seasonal.py` passes both the planted-change and no-false-positive
   tests for `pen=3.0` and at least two different `break_index` values.
3. The penalty range that satisfies both tests simultaneously is
   identified and noted as a comment in `ref_tools_seasonal.py`.

---

## Out of scope for this reference POC

- Phase shifts (only amplitude shift here).
- Multiple changepoints in one series.
- Integration with `ailf.core.datasets.Case` or the corpus machinery.
- Formal quality gates, CI, or PR requirements.
- Promotion-ready code (that happens in the `003-changepoint-dataset-generation` track).

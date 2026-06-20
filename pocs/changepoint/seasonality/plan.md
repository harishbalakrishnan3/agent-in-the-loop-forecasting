# Plan: Changepoint POC — Seasonality Amplitude Shift

**Feature**: `pocs/changepoint/seasonality/`
**Spec**: `SPEC.md` (same directory)
**Created**: 2026-06-15
**Exemption**: POC area — no quality gates, no CI, no PR requirements.

---

## Clarifications & Decisions

Four ambiguities in the spec were resolved here before implementation.
These are not user questions — each has a documented default and a
fallback path.

### C1 — What signal feeds PELT: raw values or rolling-std feature?

**Risk**: `ruptures.Pelt(model="rbf")` detects distributional shifts in
the raw signal. A 2× amplitude jump is a large distributional change
and *should* be detectable on raw values — but the seasonal
periodicity itself is a confounding source of variance that rbf sees
before the amplitude changes.

**Decision**: try raw values first. If goal 2 fails (planted change not
found) at any `pen` in `[0.5, 10]`, switch to a rolling-std feature:
compute a rolling standard deviation with `window = seasonality_period`
and feed that to PELT instead. This isolates the amplitude signal
cleanly. Document which approach worked as a comment in
`tools_seasonal.py`.

### C2 — `min_size` default should be ≈ one seasonal period, not 2

**Problem**: `min_size=2` allows PELT to carve within-cycle segments,
manufacturing false positives from normal within-season variance —
directly fighting goal 3.

**Decision**: set `min_size` default to `seasonality_period` (30 for
daily data). This enforces that no detected segment is shorter than one
full cycle. Expose `min_size` as a parameter so callers can override.

### C3 — Detection tolerance should be ≈ one period, not ±5 points

**Problem**: PELT localizes breaks to the start of the segment where the
distributional shift becomes statistically significant. For a
period-30 seasonal series, this can be up to a half-cycle (≈15 points)
away from the true `break_index`. A ±5 tolerance is likely too tight.

**Decision**: use `abs(detected[0] - true_break) <= seasonality_period`
(i.e. ±30) as the acceptance window. Record the actual observed offset
as a comment in `test_seasonal.py` once the POC runs.

### C4 — `pen=3.0` is a hypothesis, not a known answer

**Problem**: the spec pins `pen=3.0` in both the tool and the test
assertions, but the POC's job is to *find* a working penalty. If 3.0
happens to fail, the test structure would look like a detection failure
rather than a tuning gap.

**Decision**: the test sweeps `pen ∈ [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]`
and reports, for each:
- planted-change found within tolerance? (True/False)
- control clean? (True/False)

The test passes if **at least one pen value satisfies both**.
The "proven" pen range is then noted as a comment in
`tools_seasonal.py` and the default parameter set to the midpoint of
that range. This is the correct POC discipline — discover first, then
pin.

---

## Environment Prerequisite (Hard Blocker)

**Nothing executes until this is resolved.** The `.venv` is currently
empty — `uv sync` fails with SSL `UnknownIssuer` against
`pythonhosted.org`, meaning even `import darts` fails. Code can be
authored without the env, but visual proof and test proof both require
a working environment.

### Steps

1. Find the Walmart Artifactory pip/uv index URL (search internal docs
   or use `content_search "uv pip index url artifactory"`).
2. Configure uv to use it:
   ```bash
   uv sync --index-url <ARTIFACTORY_URL>
   # or set UV_INDEX_URL=<ARTIFACTORY_URL> in .env
   ```
3. Add `ruptures`:
   ```bash
   uv add ruptures --index-url <ARTIFACTORY_URL>
   ```
4. Verify:
   ```bash
   uv run python -c "import darts, ruptures, plotly; print('env ok')"
   ```
5. Commit updated `pyproject.toml` and `uv.lock`.

Writing all four files can happen in parallel with env setup. Proof
(running `viz_seasonal.py` and `test_seasonal.py`) is gated on step 4.

---

## Build Order

```
Step 0  Fix environment (hard prerequisite for proof)
Step 1  datasets_seasonal.py   — generator (no ruptures dependency)
Step 2  viz_seasonal.py        — visual proof (needs darts + plotly only)
Step 3  tools_seasonal.py      — PELT wrapper (needs ruptures)
Step 4  test_seasonal.py       — proof assertions (needs all of the above)
```

Steps 1 and 2 can be authored without a working env. Step 3 and 4
require ruptures to be installable.

---

## Step 1: `datasets_seasonal.py`

**Goal**: a self-contained generator — no imports from `src/ailf/`.

### `_base_components()`

Copy (not import) the pattern from `src/ailf/pipelines/drift/datasets.py`.

```python
def _base_components(
    length, start, freq, seasonality_period,
    seasonality_amplitude, base_noise, seed
):
    # trend: flat — zero to zero — so rbf sees only amplitude signal
    trend = linear_timeseries(
        start_value=0.0, end_value=0.0,
        length=length, start=pd.Timestamp(start), freq=freq,
    ).values().ravel()

    # seasonal: sine with given period and amplitude
    seasonal = sine_timeseries(
        value_frequency=1.0 / seasonality_period,
        value_amplitude=seasonality_amplitude,
        length=length, start=pd.Timestamp(start), freq=freq,
    ).values().ravel()

    rng = np.random.default_rng(seed)
    noise = base_noise * rng.standard_normal(length)

    return trend, seasonal, noise
```

**Diverges from drift track** in one place: `end_value=0.0` (flat
trend) instead of `_BASE_TREND_RISE=10.0`. This is intentional — the
POC needs rbf focused purely on amplitude variance.

### `_step()`

```python
def _step(length: int, break_index: int) -> np.ndarray:
    s = np.zeros(length)
    s[break_index:] = 1.0
    return s
```

### Validation (minimal — POC, not production)

Raise `ValueError` for:
- `break_index` is None after defaulting → resolved to `length // 2`
- `break_index < seasonality_period` — too few points for a pre-break
  pattern to establish (no stable reference regime)
- `break_index > length - seasonality_period` — too few points
  post-break (amplitude change has no room to develop)
- `magnitude == 0` — no actual change
- `length <= 0` or `seasonality_period <= 0`

### `generate_seasonal_shift()`

```python
def generate_seasonal_shift(
    length=365,
    break_index=None,      # defaults to length // 2
    magnitude=1.0,         # 1.0 → amplitude doubles (A → 2A)
    seasonality_period=30,
    seasonality_amplitude=5.0,
    base_noise=0.5,
    seed=42,
    start="2020-01-01",
    freq="D",
) -> tuple[TimeSeries, int]:
```

Returns `(series, resolved_break_index)` — ground truth is the second
element.

Injection:
```python
step = _step(length, k)
seasonal_shifted = seasonal * (1.0 + magnitude * step)
values = trend + seasonal_shifted + noise
index = pd.date_range(start=start, periods=length, freq=freq)
series = TimeSeries.from_times_and_values(index, values)
return series, k
```

### `generate_control()`

```python
def generate_control(
    length=365,
    seasonality_period=30,
    seasonality_amplitude=5.0,
    base_noise=0.5,
    seed=99,
    start="2020-01-01",
    freq="D",
) -> TimeSeries:
```

No injection — flat trend + seasonal + noise only. Uses `seed=99` (not
`42`) to ensure noise realization differs from the shift series.

---

## Step 2: `viz_seasonal.py`

**Goal**: a standalone script producing an interactive plotly figure.
Not imported by any test.

### Figure layout

One `go.Figure` with:

| Trace | Type | Style |
|---|---|---|
| Raw series | `go.Scatter` | thin solid line, opacity 1.0 |
| Rolling mean | `go.Scatter` | dashed, window = `seasonality_period` |
| Rolling std upper band | `go.Scatter` | filled area (`fill="tonexty"`), opacity 0.15 |
| Rolling std lower band | `go.Scatter` | same fill group |
| Break marker | `fig.add_vline` | red dashed, `line_width=2` |

### CLI usage

Accept optional args so the reviewer can explore without editing:
```
python viz_seasonal.py [--length N] [--break-index K]
                       [--magnitude M] [--seed S]
                       [--period P] [--save]
```

Default: run with spec defaults, open in browser (`fig.show()`).
`--save`: write `reports/poc_seasonality_shift.html` instead
(for headless environments).

### Rolling statistics

Use `pd.Series.rolling(window=seasonality_period, center=False)`.
Compute `.mean()` and `.std()`. Start the rolling traces at index
`seasonality_period` (first valid window) to avoid NaN leading edge.

---

## Step 3: `tools_seasonal.py`

**Goal**: the thinnest possible wrapper around PELT.

```python
import ruptures as rpt
from darts import TimeSeries

def detect_seasonality_change(
    series: TimeSeries,
    pen: float = 3.0,       # KEY TUNABLE — see C4
    min_size: int = 30,     # ≈ one seasonal period — see C2
) -> list[int]:
    signal = series.values().ravel()
    algo = rpt.Pelt(model="rbf", min_size=min_size, jump=1)
    algo.fit(signal)
    raw = algo.predict(pen=pen)
    return raw[:-1]   # drop the mandatory final-index ruptures appends
```

### Notes in the source

After the POC runs, add a comment block:
```python
# POC TUNING RESULTS
# Signal:  raw values OR rolling-std feature (see C1 outcome)
# Penalty sweep: {pen: (planted_found, control_clean), ...}
# Working pen range: [lo, hi]
# Default set to: <midpoint>
# min_size=30 (one period) prevents within-cycle false positives (C2)
```

---

## Step 4: `test_seasonal.py`

**Goal**: prove both goals 2 and 3 — a penalty sweep structure, not a
fixed-pen assertion (see C4).

### Structure

```python
PERIOD = 30
PENS = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]

def test_planted_change_found():
    series, true_break = generate_seasonal_shift(seed=42)
    results = {p: detect_seasonality_change(series, pen=p) for p in PENS}
    passing_pens = [
        p for p, det in results.items()
        if len(det) == 1 and abs(det[0] - true_break) <= PERIOD
    ]
    assert passing_pens, (
        f"No pen value in {PENS} found the planted break "
        f"(true={true_break}). Results: {results}"
    )

def test_no_false_positives():
    control = generate_control(seed=99)
    results = {p: detect_seasonality_change(control, pen=p) for p in PENS}
    clean_pens = [p for p, det in results.items() if det == []]
    assert clean_pens, (
        f"No pen value in {PENS} gave a clean control. Results: {results}"
    )

def test_working_pen_exists():
    """Combined: at least one pen satisfies both planted-found AND control-clean."""
    series, true_break = generate_seasonal_shift(seed=42)
    control = generate_control(seed=99)
    working = []
    for p in PENS:
        det_shift = detect_seasonality_change(series, pen=p)
        det_ctrl  = detect_seasonality_change(control, pen=p)
        planted_ok = len(det_shift) == 1 and abs(det_shift[0] - true_break) <= PERIOD
        ctrl_clean = det_ctrl == []
        if planted_ok and ctrl_clean:
            working.append(p)
    assert working, (
        f"No single pen value satisfies both goals. "
        f"Check C1: may need rolling-std feature instead of raw signal."
    )
```

### Additional tests (optional — run if the above pass)

```python
def test_early_break():
    """Break at length // 4 — confirm detection not biased to center."""
    series, true_break = generate_seasonal_shift(
        seed=7, break_index=90
    )
    det = detect_seasonality_change(series)
    assert len(det) == 1
    assert abs(det[0] - true_break) <= PERIOD

def test_amplitude_decrease():
    """magnitude=-0.5 (halving) — confirm decrease is also detected."""
    series, true_break = generate_seasonal_shift(seed=7, magnitude=-0.5)
    det = detect_seasonality_change(series)
    assert len(det) == 1
    assert abs(det[0] - true_break) <= PERIOD
```

---

## What "proven" means (updated from spec)

| Goal | Proof |
|---|---|
| 1. Visual | `viz_seasonal.py` shows unambiguous swing widening/narrowing at `vline` |
| 2. Detection | `test_working_pen_exists` passes; working pen range documented |
| 3. No false positives | Same test — control branch clean for the working range |

The POC is **done** when all three goals are proven and the working
penalty range is written as a comment in `tools_seasonal.py`.

---

## Files to create

```
pocs/changepoint/seasonality/
  SPEC.md                ✅ done
  plan.md                ✅ this file
  datasets_seasonal.py   [x] Step 1
  viz_seasonal.py        [x] Step 2
  tools_seasonal.py      [x] Step 3
  test_seasonal.py       [x] Step 4
```

---

## Out of scope (carried forward from spec)

- Phase shifts, multiple changepoints, variance jump flavor.
- Integration with `ailf.core.datasets.Case`.
- Promotion to `src/ailf/pipelines/changepoint/`.
- Formal quality gates, CI, PR requirements.

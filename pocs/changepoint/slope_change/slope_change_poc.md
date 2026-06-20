# Slope-Change Changepoint POC — Summary Report

**Owner:** Goutham
**Date:** 2026-06-20
**Location:** `pocs/changepoint/slope_change/`
**Status:** Complete ✅

---

## What Was Built

A self-contained proof-of-concept that (1) generates synthetic time series whose changepoints are
**changes in trend slope** — the rate of increase/decrease changes, with the trend staying
continuous (no level jump) — and (2) evaluates whether a **naive (default-configuration) Prophet**
model can detect those slope changes and forecast a held-out future horizon.

The POC mirrors the file structure of the sibling `pocs/changepoint/level_shift/` POC but shares no
code with it (imports nothing from `level_shift/` or `src/ailf/*`).

---

## Architecture

```
generate_slope_change_series()           detect + forecast
  continuous piecewise-linear trend  ─►   naive Prophet (default config)
  slope[t] bumped by Δslope at each        ├─ fit on first 80% of series
  changepoint; cumsum → no level jump      ├─ forecast held-out 20%
  + seasonality + seeded noise             ├─ MAE / RMSE / MAPE on horizon
                                           ├─ Prophet's own changepoints
        10-dataset catalog (S1–S10)        │   (ranked by |trend delta|)
        ground-truth metadata              └─ match vs ground truth (±5% len)
                                                     │
                                                     ▼
                                       pass / borderline / fail  (by MAPE)
```

---

## Files

| File | Purpose |
|------|---------|
| `spec.md` | POC-local specification |
| `__init__.py` | package marker |
| `conftest.py` | pytest bootstrap (puts repo root on path for the `pocs` namespace) |
| `datasets.py` | Darts-based slope-change generator + `DATASET_CONFIGS` (S1–S10) |
| `prophet_eval.py` | naive Prophet fit/forecast + changepoint matching + metrics + `summarize` |
| `test_slope_change.py` | 11 tests (generator ground-truth + Prophet-eval smoke) |
| `visualize.py` | interactive Plotly dashboard (dropdown over S1–S10) |
| `export_plots.py` | static PNG export → `plots/` |
| `plots/` | one PNG per dataset |

---

## Dataset Catalog

The trend is built as a continuous piecewise-linear function: the per-step slope starts at
`initial_slope` and is incremented by each `slope_deltas[i]` at `changepoint_indices[i]`; values
accumulate cumulatively, so there is **no level jump** at a changepoint — only the slope changes.

| ID | Name | Description | Expected |
|----|------|-------------|----------|
| S1 | `single_gentle` | 1 slope change, small Δslope, low noise | Easy |
| S2 | `single_sharp` | 1 slope change, large Δslope, low noise | Easy |
| S3 | `single_subtle` | 1 small Δslope, higher noise | Hard |
| S4 | `multiple_changes` | 3 slope changes (all within training) | Medium |
| S5 | `noisy` | 1 slope change, high noise | Hard |
| S6 | `with_seasonality` | 1 slope change + weekly seasonality | Medium |
| S7 | `trend_reversal` | slope flips sign | Medium |
| S8 | `close_together` | 2 slope changes, **late & close** (near split) | Hard |
| S9 | `no_changepoint` | constant slope (negative control) | Control |
| S10 | `frequent_changes` | many changes, **strong late reversal** | Hardest |

All generation is seeded for reproducibility.

---

## Naive Prophet Evaluation

**Protocol**: fit default `Prophet()` on the first 80% of each series, forecast the held-out 20%.
**Metrics**: MAE / RMSE / MAPE on the horizon; primary classification by held-out MAPE.
**Thresholds**: PASS ≤ 10% · FAIL ≥ 25% · between = borderline.
**Detection**: Prophet's own changepoints (kept when `|trend delta| ≥ 1%` of max), matched to ground
truth within ±5% of the series length.

### Per-dataset results

| Dataset | Difficulty | True CPs | Prophet CPs | Matched | Precision | Recall | MAE | RMSE | MAPE % | Verdict |
|---------|-----------|---------:|------------:|--------:|----------:|-------:|----:|-----:|-------:|---------|
| S1_single_gentle | easy | 1 | 7 | 1 | 0.43 | 1.00 | 1.6 | 2.0 | 0.8 | PASS |
| S2_single_sharp | easy | 1 | 5 | 1 | 0.40 | 1.00 | 1.6 | 2.0 | 0.4 | PASS |
| S3_single_subtle | hard | 1 | 9 | 1 | 0.44 | 1.00 | 5.6 | 7.1 | 2.9 | PASS |
| S4_multiple_changes | medium | 3 | 8 | 3 | 1.00 | 1.00 | 3.0 | 3.7 | 1.2 | PASS |
| S5_noisy | hard | 1 | 9 | 1 | 0.44 | 1.00 | 15.7 | 19.3 | 4.0 | PASS |
| S6_with_seasonality | medium | 1 | 5 | 1 | 0.60 | 1.00 | 2.2 | 3.0 | 0.7 | PASS |
| S7_trend_reversal | medium | 1 | 3 | 1 | 0.67 | 1.00 | 2.3 | 3.2 | 1.8 | PASS |
| S8_close_together | hard | 2 | 5 | 0 | 0.00 | 0.00 | 132.3 | 149.7 | 40.3 | **FAIL** |
| S9_no_changepoint | control | 0 | 9 | 0 | 0.00 | 1.00 | 2.8 | 3.4 | 1.2 | PASS |
| S10_frequent_changes | hardest | 4 | 12 | 3 | 0.75 | 0.75 | 150.7 | 163.5 | 80.0 | **FAIL** |

**Summary**: 8 PASS · 0 BORDERLINE · 2 FAIL.

> The table above is generated programmatically by
> `prophet_eval.summarize(evaluate_all())`; re-run `uv run python -m
> pocs.changepoint.slope_change.prophet_eval` to reproduce it.

### Complex datasets where naive Prophet fails

- **S8_close_together** (hard): held-out **MAPE = 40.3%** (≥ 25% fail threshold), RMSE = 149.7;
  matched **0** of its true slope changes. Its two slope changes sit late and close together, just
  before the train/test split — past the range where Prophet places its default changepoints — so
  Prophet never models the final regime and extrapolates the wrong slope.
- **S10_frequent_changes** (hardest): held-out **MAPE = 80.0%** (≥ 25% fail threshold),
  RMSE = 163.5; matched 3 of 4 true slope changes. A strong downward reversal at index 440 (after
  Prophet's default changepoint range and just before the split) means Prophet keeps extrapolating
  the prior upward trend while the actual series falls steeply — see `plots/S10_frequent_changes.png`.

**Why these fail and the others don't**: naive Prophet places its automatic changepoints only across
roughly the first 80% of the *training* window. When the decisive slope change lands *late* — near or
inside the held-out horizon — Prophet has no knot there and linearly extrapolates the stale trend.
This is precisely the failure mode an agent-in-the-loop intervention (adding a late changepoint /
adjusting `changepoint_range`) would target.

---

## How to Reproduce

```bash
uv sync

# 1. Generate the catalog
uv run python -c "from pocs.changepoint.slope_change.datasets import generate_all_datasets; print(list(generate_all_datasets()))"

# 2. Naive Prophet evaluation table
uv run python -m pocs.changepoint.slope_change.prophet_eval

# 3. Tests (11)
uv run pytest pocs/changepoint/slope_change/ -v

# 4. Interactive visualization
uv run python -m pocs.changepoint.slope_change.visualize

# 5. Export PNGs
uv run python -m pocs.changepoint.slope_change.export_plots
```

---

## Plots

One PNG per dataset under `plots/` (raw series, green ground-truth slope-change markers, red Prophet
changepoints, orange held-out forecast):
`S1_single_gentle` · `S2_single_sharp` · `S3_single_subtle` · `S4_multiple_changes` · `S5_noisy` ·
`S6_with_seasonality` · `S7_trend_reversal` · `S8_close_together` · `S9_no_changepoint` ·
`S10_frequent_changes`.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Trend synthesis | cumulative per-step slope | guarantees continuity at changepoints (no level jump) |
| Baseline | **naive** Prophet only | the POC question is "can a default forecaster cope?" |
| Primary metric | held-out MAPE | scale-aware, interpretable "% off" |
| Pass / Fail bands | ≤10% / ≥25% | clear gap avoids knife-edge flips under seed jitter |
| Detection | Prophet's own changepoints | tests Prophet, not an external detector |
| Split | last 20% held out | long enough for trend mis-extrapolation to show |

---

## How This Feeds the Full System

```
THIS POC (standalone)
  ├── datasets.py      → src/ailf/pipelines/changepoint/datasets_slope_change.py
  ├── prophet_eval.py  → motivates the changepoint diagnostic + intervention menu
  └── tests            → tests/pipelines/changepoint/

The two FAIL cases (late slope changes) are exactly where a bounded agent
intervention — backtest-gated — should add a changepoint and beat the naive baseline.
```

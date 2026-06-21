# Phase 0 Research: Slope-Change Changepoint POC

**Feature**: 005-slope-change-changepoint-poc | **Date**: 2026-06-20

This document resolves the open calibration decisions the spec deferred to planning (forecast
metric, thresholds, split sizes) and records the technical approach for slope-change synthesis
and naive-Prophet evaluation. All library choices are already satisfied by `pyproject.toml`
(darts, prophet, pandas, numpy, plotly, kaleido, pytest) — no NEEDS CLARIFICATION on dependencies.

---

## 1. How to synthesize a slope change (not a level shift)

**Decision**: Build the trend as a **continuous piecewise-linear function** of the time index.
Maintain a running per-step slope; at each changepoint index the slope increments by its
`slope_delta`, and the trend value is accumulated cumulatively so the curve stays continuous (no
jump in value). Concretely: `trend[t] = base_level + cumulative_sum(slope[t])`, where `slope[t]`
starts at `initial_slope` and is bumped by `slope_delta_i` at each `changepoint_index_i`. Then add
optional seasonality and additive Gaussian noise on top, seeded with `numpy.random.default_rng`.

**Rationale**:
- Cumulative-sum-of-slope guarantees C0 continuity at every changepoint — the defining property
  that separates a slope change from the level_shift POC (which adds a constant to all subsequent
  points, creating a discontinuity).
- Mirrors the level_shift `datasets.py` construction style (base + trend + seasonality + noise via
  Darts `TimeSeries.from_times_and_values`) so the two POCs read alike, while changing only the
  trend term.
- Ground truth is exact and known: indices and slope-before/after fall straight out of the config.

**Alternatives considered**:
- *Darts `linear_timeseries` segments concatenated*: rejected — concatenation risks level
  discontinuities at the seams and complicates seasonality/noise application across segments.
- *Adding ramps (`max(0, t - cp)` basis functions)*: mathematically equivalent to the cumulative
  approach but less readable; the cumulative-slope loop matches how a reader reasons about "the
  slope changes here".

---

## 2. Forecast-accuracy metric on the held-out horizon

**Decision**: Report **MAE and RMSE** on the held-out horizon, and use **MAPE (mean absolute
percentage error)** as the primary scale-aware success/failure metric. All series have a positive
base level so MAPE is well-defined.

**Rationale**:
- The spec Assumptions call for a "standard scale-aware error metric"; MAPE is scale-aware and
  directly interpretable as "% off", which makes the simple-vs-complex story legible in the report.
- MAE/RMSE are reported alongside for completeness and because they are the constitution's named
  standard metrics (Principle V), easing later comparison with the broader project.
- The thesis of the POC is *trend* mis-extrapolation; percentage error on the held-out horizon
  cleanly captures "Prophet kept extrapolating the old slope and drifted away from actuals".

**Alternatives considered**:
- *MASE*: excellent for cross-series comparison but needs an in-sample naive scale and is harder to
  read in a standalone POC table; deferred (can be added later when promoted).
- *sMAPE*: avoided to keep one headline metric; MAPE is sufficient given positive levels.

---

## 3. Success vs. failure thresholds

**Decision**: Classify per dataset on held-out **MAPE**:
- **Success ("easy" / Prophet handles it)**: MAPE ≤ **10%**.
- **Failure ("hard" / Prophet breaks down)**: MAPE ≥ **25%**.
- MAPE between 10% and 25% is labeled **"borderline"** (reported, not counted as a clean
  success or failure).

**Rationale**:
- A clear gap between the success and failure bands avoids datasets straddling a single knife-edge
  threshold and makes SC-004 ("≥1 simple passes, ≥1 complex fails") robust to noise-seed jitter.
- 10% is a conventional "good forecast" bar; 25%+ on a synthetic, noise-controlled series is
  unambiguous baseline breakdown.
- Thresholds are documented constants in `prophet_eval.py` so they are inspectable and tunable.

**Alternatives considered**:
- *Single threshold (e.g. 15%)*: rejected — too brittle; a borderline dataset could flip
  classification on a seed change and weaken the demonstrated conclusion.
- *Relative-to-naive-seasonal threshold*: more principled but pulls in a second baseline the spec
  doesn't require for this POC; deferred to promotion.

---

## 4. Train/test split and forecast horizon

**Decision**: Hold out the **last 20%** of each series as the future horizon; fit naive Prophet on
the first 80% and forecast the held-out 20%. For the "hard near-horizon" datasets (S8
close_together, S10 frequent_changes, and the late-changepoint behavior of S3/S5), place at least
one slope change inside or just before the final 20% so the held-out regime is one Prophet's
training window only partially saw.

**Rationale**:
- A fixed 80/20 split is simple, reproducible, and large enough on 400–2000-point series to give
  Prophet a fair fit while leaving a horizon long enough for trend mis-extrapolation to show up.
- Positioning a slope change near the split is precisely the mechanism that makes "even Prophet
  can't predict the future properly" (the user's words) — the model extrapolates the wrong slope.

**Alternatives considered**:
- *Rolling-origin backtest (Principle V default)*: deliberately not used — it characterizes average
  performance, whereas the POC wants to expose a specific single-horizon failure. Documented as a
  permitted POC simplification in plan.md and spec Assumptions.
- *Fixed-length horizon (e.g. 90 points)*: rejected in favor of a proportional 20% so the split
  scales sensibly across the 400–2000-point range.

---

## 5. Extracting Prophet's "detected changepoints"

**Decision**: Use Prophet's **automatically inferred changepoints** ranked by the magnitude of
their fitted trend-rate change (`deltas` in `m.params['delta']`), keeping those whose absolute
trend-delta exceeds a small fraction (e.g. 1%) of the largest, then mapping each retained
changepoint date back to a series index. This reuses Prophet's own default changepoint machinery
(it places candidate changepoints in the first 80% of history by default) — exactly the "naive"
behavior under test.

**Rationale**:
- The question is whether *default* Prophet surfaces the slope changes, so we read Prophet's own
  changepoints rather than running an external detector.
- Ranking by trend-delta magnitude filters Prophet's many near-zero candidate changepoints down to
  the ones it actually "believes", giving a fair detection comparison.

**Alternatives considered**:
- *External detector (e.g. ruptures with a linear/CART cost)*: rejected — that would test a
  detector, not Prophet, and would violate the "naive Prophet" framing.
- *Using all candidate changepoints unfiltered*: rejected — inflates false positives and makes
  detection precision meaningless.

---

## 6. Changepoint-match tolerance (detection scoring)

**Decision**: A ground-truth slope change is **matched** if a retained Prophet changepoint falls
within a tolerance window of **±5% of the series length** (index units) of the true index, mirroring
the level_shift POC's ±-index tolerance convention but scaled so it is fair across 400–2000-point
series. Report per-dataset precision/recall (or a simple matched/total count) over the catalog.

**Rationale**:
- A proportional window is fair across the catalog's length range, unlike a fixed ±5 that is tight
  on a 2000-point series.
- Precision/recall against known ground truth is the constitution's prescribed way to score
  diagnostics (Principle II rationale).

**Alternatives considered**:
- *Fixed ±5 indices (level_shift's exact value)*: kept as a floor but generalized to a percentage to
  handle the long series; documented so the two POCs remain comparable.

---

## 7. Test strategy (POC-exempt but still shipped)

**Decision**: `pytest` module `test_slope_change.py` covering: (a) generator output type/length,
(b) reproducibility (same seed → identical values), (c) slope actually changes at planted indices
and trend is continuous (no level jump) there, (d) control series has constant slope / zero
changepoints, (e) metadata schema has all required fields with matching dates, (f) an end-to-end
Prophet-eval smoke on one simple (S1/S2) and one complex (S10) dataset asserting the result schema
is populated and the simple dataset's MAPE is below the failure band while the complex one's is
above the success band.

**Rationale**: Satisfies FR-018 and gives the "all tests pass" deliverable (SC-007) without
violating the POC exemption (tests are a bonus here, not a merge gate).

**Alternatives considered**: *No tests (full POC exemption)* — rejected because the spec explicitly
requires them as a deliverable.

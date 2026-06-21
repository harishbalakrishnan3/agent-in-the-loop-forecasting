# Feature Specification: Slope-Change Changepoint POC & Prophet Baseline Evaluation

**Feature Branch**: `005-slope-change-changepoint-poc`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "Create POC code for slope change changepoint dataset under pocs/changepoint/slope_change/. We need to generate synthetic time series where changepoints are changes in slope and not level jumps. The POC should mirror the existing code file structure as in pocs/changepoint/level_shift but should be self contained. After creating the dataset, we also need to evaluate whether naive Prophet can detect and forecast the slope changepoints for each dataset that is created. We need to create some simple datasets and some complex datasets where even prophet model can't automatically predict the future properly."

## Clarifications

### Session 2026-06-20

- Q: What concrete catalog of slope-change datasets should the POC generate? → A: 10 datasets — S1 single_gentle, S2 single_sharp, S3 single_subtle, S4 multiple_changes (3 changes), S5 noisy, S6 with_seasonality, S7 trend_reversal (slope flips sign), S8 close_together, S9 no_changepoint (control), S10 frequent_changes (hardest, changes near forecast horizon).
- Q: What exactly must the POC produce as its final deliverables? → A: (1) generated datasets + ground-truth metadata, (2) one PNG per dataset in a `plots/` directory, (3) all automated tests passing, (4) a written summary report (`slope_change_poc.md`) with a per-dataset naive-Prophet results table (detection + forecast error) and a dedicated section calling out which complex datasets Prophet fails on.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate synthetic slope-change time series with known ground truth (Priority: P1)

A team member working on the changepoint use case needs a catalog of synthetic
time series in which the changepoints are **changes in trend slope** (the rate of
increase/decrease changes) rather than abrupt level jumps. Each series must come
with machine-readable ground-truth metadata recording exactly where each slope
change occurs and how the slope changed, so detection and forecasting can be
scored against a known answer.

**Why this priority**: Without seeded, ground-truth-labeled data there is nothing to
detect, forecast, or evaluate against. Every other story depends on this one. It is
independently valuable as a reusable data generator.

**Independent Test**: Run the generator for the full catalog and confirm each series
is produced with the expected length and a metadata record whose recorded slope-change
indices align with the points where the underlying slope actually changes (verifiable
by inspecting the piecewise-linear trend, ignoring noise).

**Acceptance Scenarios**:

1. **Given** a generator configured with a single slope change at a known index,
   **When** the series is generated, **Then** the returned trend's slope before and
   after that index differs by the configured amount and the metadata records the
   index, date, and slope-delta.
2. **Given** the same configuration and seed, **When** the series is generated twice,
   **Then** the two series are identical (reproducible).
3. **Given** a configuration with multiple slope changes, **When** the series is
   generated, **Then** every configured slope change appears in the metadata with the
   correct index and slope-delta.
4. **Given** a "no changepoint" control configuration, **When** the series is generated,
   **Then** the metadata records zero slope changes and the trend slope is constant.

---

### User Story 2 - Evaluate whether naive Prophet detects and forecasts slope changes (Priority: P1)

A team member wants to know, for each generated dataset, whether an out-of-the-box
("naive", default-configuration) Prophet model can (a) place its automatic changepoints
near the true slope changes and (b) produce an accurate forecast of the held-out future
portion of the series. The evaluation must report per-dataset metrics that make it
obvious which datasets Prophet handles well and which it fails on.

**Why this priority**: The core question of the POC is "where does a naive baseline break
down?" This story answers it and produces the evidence (metrics + plots) that justifies an
agent-in-the-loop intervention later.

**Independent Test**: Run the evaluation over the catalog and confirm it emits, per dataset,
a changepoint-detection score (how close Prophet's changepoints are to ground truth) and a
forecast-accuracy score on a held-out horizon, plus a clear pass/fail or easy/hard label.

**Acceptance Scenarios**:

1. **Given** a generated dataset, **When** Prophet is fit on the training portion and asked
   to forecast the held-out horizon, **Then** the evaluation reports a forecast error metric
   for that horizon.
2. **Given** a dataset with a true slope change, **When** Prophet's automatically inferred
   changepoints are compared to ground truth, **Then** the evaluation reports whether a
   Prophet changepoint falls within a tolerance window of each true slope change.
3. **Given** the full catalog, **When** the evaluation runs, **Then** at least one "simple"
   dataset is forecast accurately by naive Prophet and at least one "complex" dataset is NOT
   (forecast error exceeds a clear threshold), demonstrating the baseline's failure mode.

---

### User Story 3 - Inspect datasets and Prophet behavior visually (Priority: P2)

A team member wants to visually inspect each dataset alongside its ground-truth slope
changes, Prophet's detected changepoints, and Prophet's forecast vs. the actual held-out
values, both interactively and as exportable static images for reports.

**Why this priority**: Visual inspection makes the "naive Prophet fails here" conclusion
legible to reviewers and graders, but the numeric evaluation (P1) already establishes the
result, so this is secondary.

**Independent Test**: Generate the visualization for the catalog and confirm each dataset
renders the raw series, ground-truth slope-change markers, Prophet changepoints, and the
forecast-vs-actual overlay over the held-out horizon; confirm static images can be exported
per dataset.

**Acceptance Scenarios**:

1. **Given** the catalog, **When** the interactive visualization is opened, **Then** a user
   can switch between datasets and see ground-truth vs. Prophet changepoints and the forecast
   overlay for each.
2. **Given** the catalog, **When** static export is run, **Then** one image per dataset is
   written to a plots directory.

---

### Edge Cases

- **Slope change at or near a boundary**: A slope change planted within the first/last few
  points has too little data on one side to establish a slope — the generator must reject or
  clearly document such configurations.
- **Slope change vs. level shift confusion**: The series must change *rate* without an
  instantaneous jump in value (the trend stays continuous at the changepoint). Generated data
  must not accidentally introduce a level discontinuity.
- **Two slope changes that cancel**: Consecutive opposite slope changes can return the trend to
  its original rate; metadata must still record both, and evaluation must treat a missed middle
  changepoint correctly.
- **Forecast horizon longer than a stable final segment**: If the last slope change is close to
  the train/test split, the held-out horizon spans a regime the model never saw trending — this
  is exactly the "hard" case and must be representable.
- **Prophet detects no changepoints / many spurious changepoints**: Evaluation must handle zero
  matches and false positives without crashing.
- **Control series (no changepoint)**: Naive Prophet should forecast it well; evaluation must
  confirm no false-positive failure is reported.

## Requirements *(mandatory)*

### Functional Requirements

#### Dataset generation

- **FR-001**: The POC MUST generate synthetic univariate time series whose changepoints are
  **changes in trend slope** (piecewise-linear trend), with the trend value remaining
  continuous (no instantaneous level jump) at each changepoint.
- **FR-002**: The generator MUST accept configurable parameters including at minimum: series
  length, start date, frequency, base level, initial slope, the index of each slope change, the
  slope-delta (change in slope) at each change, additive noise level, and a random seed.
- **FR-003**: The generator MUST support optional additive seasonality so "complex" datasets can
  combine slope changes with periodic structure.
- **FR-004**: The generator MUST return ground-truth metadata for each series recording at least:
  dataset id, length, changepoint indices, changepoint dates, slope-before / slope-after (or
  slope-delta) for each change, changepoint type (`slope_change`), noise level, base level,
  initial slope, seasonality settings, and seed.
- **FR-005**: Generation MUST be fully reproducible: identical configuration and seed produce
  identical output.
- **FR-006**: The POC MUST ship a fixed catalog of **10 pre-configured datasets** spanning a
  difficulty range, including **simple** datasets a naive baseline is expected to handle and
  **complex** datasets a naive baseline is expected to fail on, plus a no-changepoint control.
  The catalog MUST be:

  | ID | Name | Description | Expected difficulty |
  |----|------|-------------|---------------------|
  | S1 | `single_gentle` | 1 slope change, small slope-delta, low noise | Easy |
  | S2 | `single_sharp` | 1 slope change, large slope-delta, low noise | Easy |
  | S3 | `single_subtle` | 1 slope change, small slope-delta, higher noise | Hard |
  | S4 | `multiple_changes` | 3 slope changes at different positions | Medium |
  | S5 | `noisy` | 1 slope change with high additive noise | Hard |
  | S6 | `with_seasonality` | 1 slope change plus periodic seasonal component | Medium |
  | S7 | `trend_reversal` | 1 slope change where the slope flips sign | Medium |
  | S8 | `close_together` | 2 slope changes only a few points apart | Hard |
  | S9 | `no_changepoint` | Constant-slope series, no changes (negative control) | Control |
  | S10 | `frequent_changes` | Many slope changes, with changes near the forecast horizon | Hardest |
- **FR-007**: The generator MUST validate inputs and reject configurations that are invalid
  (e.g., changepoint index out of range, mismatched lengths of indices and slope-deltas,
  changepoints too close to a boundary to define a slope).

#### Prophet baseline evaluation

- **FR-008**: For each dataset, the POC MUST fit a naive (default-configuration) Prophet model on
  a training portion of the series and produce a forecast over a held-out future horizon.
- **FR-009**: The POC MUST compare Prophet's automatically inferred changepoints against the
  ground-truth slope-change locations and report, per dataset, whether each true changepoint is
  matched within a stated tolerance window (detection precision/recall or equivalent).
- **FR-010**: The POC MUST compute a forecast-accuracy metric on the held-out horizon for each
  dataset (an error metric comparing forecast to actual).
- **FR-011**: The evaluation MUST classify each dataset as one where naive Prophet succeeds vs.
  fails, using a stated, consistent threshold on forecast error.
- **FR-012**: The evaluation MUST demonstrate at least one simple dataset Prophet forecasts well
  and at least one complex dataset Prophet forecasts poorly, confirming the baseline's
  breakdown.
- **FR-013**: The evaluation MUST produce a consolidated per-dataset results summary (table or
  structured output) covering detection and forecast metrics across the whole catalog.

#### Visualization

- **FR-014**: The POC MUST provide an interactive visualization that, per dataset, shows the raw
  series, ground-truth slope-change markers, Prophet's detected changepoints, and the
  forecast-vs-actual overlay over the held-out horizon, with a way to switch between datasets.
- **FR-015**: The POC MUST provide a static-image export producing one PNG figure per dataset,
  written to a `plots/` directory, for inclusion in reports.

#### Final deliverables

- **FR-020**: The POC MUST produce, as its final deliverables: (1) the generated datasets with
  their ground-truth metadata, (2) one exported PNG per dataset under `plots/`, (3) a passing
  automated test suite, and (4) a written summary report (`slope_change_poc.md`).
- **FR-021**: The summary report MUST contain a per-dataset naive-Prophet results table covering
  both the changepoint-detection outcome and the held-out forecast error for all 10 datasets.
- **FR-022**: The summary report MUST contain a dedicated section that explicitly calls out which
  complex slope-change datasets naive Prophet fails on (forecast error above the failure
  threshold and/or missed changepoints), with the supporting metrics.

#### Structure & self-containment

- **FR-016**: The POC MUST live under `pocs/changepoint/slope_change/` and MUST mirror the file
  structure of `pocs/changepoint/level_shift/` (a package marker, a datasets module, a
  detection/evaluation module, a test module, an interactive visualization module, a static
  export module, a POC spec, and a summary report).
- **FR-017**: The POC MUST be self-contained — it MUST NOT import from `pocs/changepoint/level_shift/`
  or from project `src/` packages; any shared logic it needs MUST be reimplemented locally.
- **FR-018**: The POC MUST include automated tests that verify the generator against planted
  ground truth (slope changes present at the right places, reproducibility, control series flat
  in slope, metadata schema) and that exercise the Prophet evaluation end-to-end on at least the
  simple and the complex datasets.
- **FR-019**: All synthetic data generation MUST be seeded; the POC stays inside `pocs/` and is
  exempt from production quality gates but MUST run via the project's standard command runner.

### Key Entities *(include if feature involves data)*

- **Slope-change series**: A univariate time series built from a continuous piecewise-linear
  trend (whose slope changes at planted changepoints), plus optional seasonality and additive
  noise. Carries an associated ground-truth metadata record.
- **Ground-truth metadata**: A structured record describing the planted slope changes — indices,
  dates, slope before/after each change, noise level, base level, initial slope, seasonality
  configuration, type marker (`slope_change`), and seed.
- **Dataset catalog**: A fixed, named set of pre-configured slope-change series spanning simple
  to complex, with a no-changepoint control.
- **Prophet evaluation result**: A per-dataset record of Prophet's detected changepoints,
  detection match outcome vs. ground truth, held-out forecast error, and a success/fail (easy/hard)
  classification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every dataset in the catalog is generated with ground-truth metadata whose recorded
  slope-change indices match the points where the underlying trend slope actually changes (within
  ±2 indices, ignoring noise), for 100% of datasets.
- **SC-002**: Regenerating any dataset with the same seed produces an identical series for 100% of
  datasets.
- **SC-003**: The no-changepoint control series has a constant trend slope (zero recorded slope
  changes) and naive Prophet forecasts it within the "success" error threshold.
- **SC-004**: At least one simple dataset is forecast by naive Prophet within the success threshold,
  and at least one complex dataset exceeds the failure threshold — both demonstrated in the results
  summary.
- **SC-005**: The evaluation reports, for every dataset, both a changepoint-detection outcome
  (matched within tolerance vs. ground truth) and a held-out forecast error, with no dataset
  missing a metric.
- **SC-006**: A reviewer can, per dataset, visually confirm ground-truth vs. Prophet changepoints
  and forecast-vs-actual, both interactively and via exported static images for the full catalog.
- **SC-007**: All automated tests for the POC pass.
- **SC-008**: The POC directory contains no imports from `level_shift/` or project `src/` packages
  (verifiable by inspection/search), confirming self-containment.
- **SC-009**: The final deliverable set is complete: all 10 datasets generate, one PNG per dataset
  exists under `plots/`, the test suite passes, and `slope_change_poc.md` exists with both the
  per-dataset Prophet results table and the explicit complex-dataset failure section.

## Assumptions

- "Naive Prophet" means Prophet used with its default configuration (default automatic changepoint
  detection, default seasonality behavior), fit only on the training portion — no manual changepoint
  hints, custom priors, or tuning.
- The catalog size mirrors the level_shift POC's order of magnitude (roughly 8–12 named datasets)
  spanning simple → complex plus one control; exact count is an implementation detail.
- Each series is split into a training portion and a held-out future horizon for forecast evaluation;
  the split point and horizon length are reasonable defaults chosen so that "hard" datasets place a
  regime change near or within the held-out horizon.
- A slope-change "match" between a Prophet changepoint and ground truth uses a tolerance window,
  mirroring the ±-index tolerance convention used in the level_shift POC but generalized to ±5% of
  the series length (rather than a fixed ±5 indices) so the window is fair across the catalog's
  400–2000-point range. This percentage form is the canonical definition used by the evaluation.
- Forecast accuracy is measured with a standard scale-aware error metric on the held-out horizon; the
  specific metric and the success/failure thresholds are reasonable defaults documented in the POC.
- The POC reuses the same underlying libraries and tooling conventions as the level_shift POC for time
  series construction, plotting, and testing, but reimplements any shared helpers locally to remain
  self-contained.
- The POC is exploratory (lives in `pocs/`) and is therefore exempt from the constitution's production
  quality gates, while still being seeded, tested, and runnable via the standard command runner.

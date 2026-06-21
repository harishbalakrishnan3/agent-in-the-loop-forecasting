# Feature Specification: Agent-Driven Forecasting Beats Naive Prophet

**Feature Branch**: `004-agent-forecast-beats-prophet`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "Create an agentic solution that beats naive Prophet on a synthetic
dataset rich in trend, seasonality, variance and noise with multiple complex changepoints.
Strictly limit scope to changepoint-detection-driven forecasting. Include Plotly visualisation,
naive Prophet pipeline, stats extraction for agent hypothesis formation, agent-invoked Prophet
tuning, decision matrix (val MAE vs naive MAE), pipeline trace capture, comparative
visualisation, and run result capture."

---

## Goal

Demonstrate that an LLM agent, reasoning from extracted time-series statistics, can select
Prophet hyperparameters that produce strictly lower validation MAE than a stock
default-parameter Prophet baseline on a synthetic dataset with multiple complex changepoints.
The agent must beat naive Prophet on val MAE; the headline result is test MAE for both
methods after val-based config selection is complete.

---

## Architecture

```
generate_dataset()          # datasets.py — synthetic series, 4 changepoint types
       │
       ▼
extract_stats()             # stats.py — StatsBundle from training split only
       │
       ├──► run_naive_prophet()    # naive.py — default Prophet, val + test MAE
       │
       ▼
Agent Loop (max 5 iters)    # agent.py
  1. Receive StatsBundle as context
  2. Form hypothesis (text)
  3. Call fit_prophet_with_config() tool → val MAE
  4. Accept if val MAE < naive val MAE; else record rejection + iterate
       │
       ▼
build_decision_matrix()     # decision.py — naive vs agent MAE comparison
       │
       ▼
plot_results()              # viz.py — comparative Plotly figure
       │
       ▼
write_artifacts()           # pipeline.py — all output files to runs/<timestamp>/
```

**LLM node**: single call per iteration (hypothesis + config in one turn).
**Tool contract**: agent calls `fit_prophet_with_config(changepoint_prior_scale,
seasonality_prior_scale, seasonality_mode, changepoint_range, n_changepoints)` — no raw
Python, no free-form JSON.
**Observability**: LangSmith tracing when env vars present; absent = no-op.

---

## Constraints

- **No data leakage**: agent context contains training data only. Val and test target values
  never appear in `StatsBundle` or agent prompts.
- **Bounded parameter grid**: agent may only propose values from the fixed grid in
  `config.py` (FR-022). Out-of-bounds proposals are rejected before val scoring.
- **Test MAE gated**: final test evaluation runs only after the agent loop terminates
  (acceptance or budget exhaustion).
- **Determinism**: same seed → same naive val MAE and same `StatsBundle`. Stochastic steps
  are seeded and recorded.
- **POC isolation**: no imports from `src/ailf/`. Self-contained in
  `pocs/changepoint/seasonalityV2/`.
- **Max iterations**: 5 agent iterations per run.
- **Model config**: LLM model identifier read from environment — never hardcoded.

---

## Data

**Synthetic daily series**, 1 095 observations (≈ 3 years), seed=42 by default.

Four injected changepoints at roughly equal intervals (≈ every 200 days):

| Type | Structural change | Prophet blind spot targeted |
|---|---|---|
| A — Level shift | Abrupt step in mean | `changepoint_prior_scale` too low misses it |
| B — Trend kink | Slope change, no level jump | `changepoint_range=0.8` cuts off late kinks |
| C — Variance change | Noise std doubles/halves | Heteroscedasticity not modelled by default |
| D — Seasonality mode shift | Additive → multiplicative | `seasonality_mode='additive'` default fails |

**Split** (configurable, default 70/15/15 by time):
- `train`: agent-visible; used for naive fit and stats extraction.
- `val`: hidden from agent context; used for config selection only.
- `test`: hidden until loop completes; used for final headline metrics.

Ground-truth changepoint dates stored in `changepoints` dict alongside the series.

---

## Training

"Training" in this POC refers to Prophet model fitting, not ML training:

- **Naive baseline**: Prophet with all default parameters, fit on `train`, evaluated on
  `val` (config selection) and `test` (final reporting).
- **Agent-selected model**: Prophet with the config accepted by the agent on `val`, fit on
  `train`, evaluated on `test`.
- **Prophet seed**: set via `stan_backend` seed parameter where available for
  reproducibility.
- **Iteration budget**: agent fits up to 5 candidate configs on `val` before the loop ends.
- **Acceptance rule**: strictly lower `val MAE` than naive baseline; ties are not accepted.
- **Fallback**: if no proposal beats naive on val, the best-val-scoring proposal is carried
  to test evaluation; `agent_beats_naive_on_val = false` in the run summary.

---

## Acceptance Criteria

- **AC-001**: `agent_beats_naive_on_val = true` in `run_summary.json` for reference run
  (seed=42, default config).
- **AC-002**: Dataset contains exactly the four changepoint types (A–D), asserted by
  `test_dataset.py` smoke test.
- **AC-003**: `extract_stats` returns a JSON-serialisable `StatsBundle` with all required
  fields; no NaN/Inf values.
- **AC-004**: Re-running with same seed produces identical naive val MAE and identical stats.
- **AC-005**: Every proposed config in the trace falls within the bounded grid; no
  out-of-bounds value appears in any run.
- **AC-006**: Test MAE is non-null in the trace only after `decision = "accepted"` or
  `decision = "exhausted"` — never during the loop.
- **AC-007**: All seven output files (see Output Files) are present after a completed run.
- **AC-008**: `viz_dataset.html` renders four distinct vertical changepoint markers.
- **AC-009**: `viz_results.html` shows labelled "Naive Prophet" and "Agent Prophet" traces
  with MAE annotations.
- **AC-010**: Pipeline fails with an explicit error (not silent substitution) when the
  configured LLM model is unavailable.

---

## Output Files

All files written to `runs/<YYYYMMDD-HHMMSS>-seed<SEED>/`:

| File | Description |
|---|---|
| `dataset.csv` | Full synthetic series (`ds`, `y`) with changepoint metadata |
| `stats.json` | Serialised `StatsBundle` from training split |
| `trace.json` | JSON array of agent iteration records (hypothesis, config, val MAE, decision) |
| `decision_matrix.json` | Naive vs agent MAE comparison (val + test, deltas, boolean flag) |
| `viz_dataset.html` | Interactive Plotly: full series, rolling stats, changepoint markers, split shading |
| `viz_results.html` | Interactive Plotly: train history, val/test actuals, naive + agent forecasts, MAE annotations |
| `run_summary.json` | Compact run record: seed, config hash, all MAEs, accepted config, `agent_beats_naive_on_val` |

---

## Background

This POC extends the changepoint forecasting track (`003-changepoint-agent-poc`) with a
self-contained, end-to-end demonstration whose single headline claim is:
**an LLM agent, reasoning from extracted time-series statistics, can select Prophet
hyperparameters that produce lower val-MAE than a stock, default-parameter Prophet baseline.**

The dataset is purpose-built to expose Prophet's default blind spots — the agent wins by
reasoning about *why* the defaults fail and adjusting the specific levers that address each
failure mode.

---

## Clarifications

- Q: Should the agent be LLM-driven (tool calls + free reasoning) or a deterministic rule
  loop? → A: LLM-driven with a bounded tool/action menu; the agent invokes Prophet via a
  typed tool, not by emitting raw config.
- Q: Val vs test split? → A: Three-way split — train / val / test. Agent selects config on
  **val** MAE only; final reported headline is **test** MAE for both naive and agent.
  Selecting and reporting on the same partition would constitute leakage.
- Q: Seed? → A: Fixed global seed (default `SEED=42`) for dataset generation, Prophet
  fitting, and all stochastic steps. Must be recorded in run artifacts for reproducibility.
- Q: How many complex changepoints must the dataset contain? → A: Minimum **four** distinct
  changepoints, each of a different structural type (see FR-003), so every failure mode the
  agent can address is represented at least once.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Agent beats naive Prophet on val MAE (Priority: P1)

A researcher runs the POC end-to-end and observes, per run, that the agent-selected Prophet
configuration achieves strictly lower val MAE than the naive (default-parameter) Prophet
trained on the same training split.

**Why this priority**: This is the core thesis. Without this comparison the POC has no
deliverable.

**Independent Test**: Run the POC once on the supplied synthetic dataset. Confirm the printed
decision matrix reports agent val MAE < naive val MAE, and that test MAE is computed only
after val-based config selection is complete.

**Acceptance Scenarios**:

1. **Given** the synthetic dataset and its train/val/test split, **When** the POC runs,
   **Then** the decision matrix artifact reports naive val MAE and agent val MAE, and agent
   val MAE is strictly less than naive val MAE.
2. **Given** the same run configuration and seed, **When** the POC is re-run, **Then**
   deterministic components (naive baseline, extracted stats, val scoring) produce identical
   numbers.
3. **Given** the completed val phase, **When** final test MAE is computed, **Then** neither
   the agent nor the dataset has seen test-period values during config selection.

---

### User Story 2 — Interactive Plotly visualisation reveals changepoints (Priority: P1)

A researcher opens the interactive Plotly chart and can visually inspect the dataset,
annotate each injected changepoint, and understand the structural complexity the agent must
reason about.

**Why this priority**: The visualisation is the primary tool for validating dataset design and
for human interpretation of agent reasoning.

**Independent Test**: Run the viz script independently. Confirm it opens without Prophet or
agent code, shows the full series, and renders all injected changepoint markers correctly.

**Acceptance Scenarios**:

1. **Given** the synthetic dataset, **When** the Plotly visualisation script runs, **Then**
   it renders an interactive figure showing: the full time series, a rolling mean overlay,
   rolling std band, and a vertical marker for each injected changepoint labelled with its
   structural type.
2. **Given** the figure, **When** the user hovers over any changepoint marker, **Then** the
   tooltip shows the date and the changepoint type (e.g., "Level shift — 2021-03-01").
3. **Given** the train/val/test split, **When** the figure is produced, **Then** the val and
   test regions are shaded differently from the training region so leakage is visually obvious.

---

### User Story 3 — Extracted stats drive agent hypothesis (Priority: P1)

A researcher inspects the extracted stats bundle and confirms it captures all structural
signals the agent needs to form a hypothesis about which Prophet levers to tune.

**Why this priority**: If the stats are uninformative or wrong, the agent's reasoning is
groundless regardless of its output.

**Independent Test**: Call `extract_stats(series, train_end)` on the dataset and assert the
returned bundle contains all required fields with non-trivial values.

**Acceptance Scenarios**:

1. **Given** the training portion of the dataset, **When** `extract_stats` is called, **Then**
   the returned bundle contains: detected changepoints (count ≥ 4), each changepoint's date and
   structural type hint, segment-level mean and std per inter-changepoint interval, a
   seasonality-mode signal (additive vs multiplicative), a trend-slope estimate per segment,
   a noise-level estimate, a post-last-changepoint history length, and a flag indicating
   whether that length is shorter than one seasonal period.
2. **Given** the stats bundle, **When** it is serialised, **Then** it is a valid JSON object
   with no NaN or Inf values (Prophet's requirements propagate upstream).

---

### User Story 4 — Agent pipeline trace is captured and human-readable (Priority: P1)

A reviewer reads the pipeline trace and can reconstruct, step-by-step, how the agent arrived
at its chosen Prophet configuration: which stats it read, the hypothesis it formed, which
Prophet parameters it set, the val MAE it received, and whether it accepted or iterated.

**Why this priority**: Without a trace the result is unauditable; the pipeline cannot be
evaluated as an agent system.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the trace JSON is opened, **Then** it contains, in
   order: extracted stats, agent hypothesis text, proposed Prophet config (typed fields only),
   val MAE for the proposal, decision (accept / iterate), final accepted config, val MAE of
   accepted config, and test MAE of accepted config.
2. **Given** the trace, **When** it is read, **Then** every proposed config falls within the
   bounded parameter grid — no free-form or out-of-bounds values.
3. **Given** the trace, **When** the agent iterated more than once, **Then** rejected configs
   and their val MAEs are recorded in order, and the accepted config is distinct from all
   rejected ones.

---

### User Story 5 — Comparative visualisation shows both forecasts with metrics (Priority: P2)

An analyst opens the results plot and can immediately see both the naive Prophet forecast and
the agent-selected forecast over the test horizon, with MAE annotations, on a single Plotly
figure with proper labelling.

**Why this priority**: The visual comparison is the primary artefact for reporting and
grading; it complements the numeric decision matrix.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the results plot is opened, **Then** it shows: the
   training history, the val region, test actuals, the naive Prophet forecast over the test
   horizon, the agent Prophet forecast over the test horizon, all labelled with legend entries
   and colour-coded.
2. **Given** the plot, **When** it is inspected, **Then** it includes annotations for naive
   test MAE and agent test MAE positioned so they do not overlap the forecast lines.
3. **Given** the plot, **When** each injected changepoint date falls within the visible
   x-axis range, **Then** a vertical dashed marker with label appears at that date.

---

### User Story 6 — Run results are captured for final reporting (Priority: P2)

A researcher returns to a completed run and can load all artefacts without re-running the
pipeline.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the run directory is opened, **Then** it contains:
   `dataset.csv`, `stats.json`, `trace.json`, `decision_matrix.json`, `viz_dataset.html`,
   `viz_results.html`, and `run_summary.json`.
2. **Given** `run_summary.json`, **When** it is read, **Then** it contains: seed, dataset
   config hash, naive val MAE, agent val MAE, naive test MAE, agent test MAE, accepted
   Prophet config, and a boolean `agent_beats_naive_on_val`.

---

### Edge Cases

- **Agent exhausts iteration budget without beating naive on val**: carry the best-val
  proposal to test evaluation anyway; `agent_beats_naive_on_val` is `false` in summary.
- **Agent proposes a parameter outside the bounded grid**: reject the proposal before val
  scoring; re-prompt with the boundary violation message; count as one iteration.
- **Post-last-changepoint history shorter than one seasonal period**: stats must flag this;
  agent should prefer interventions that preserve seasonal context over a simple recent-window
  retrain.
- **Prophet fitting fails** (degenerate config): catch the exception, record the config as
  rejected with `val_mae = null`, continue iterating.
- **Trend and seasonality confounded by changepoint location**: stats extraction must
  attribute signal to the correct inter-changepoint segment, not the full history.
- **Dataset seed produces a series where naive accidentally achieves near-zero MAE**: the
  dataset design must make this impossible; see FR-005 for the complexity floor.

---

## Requirements *(mandatory)*

### Functional Requirements

#### Dataset generation

- **FR-001**: The dataset generator MUST produce a daily-frequency univariate time series of
  configurable length (default: 3 years × 365 days = 1 095 observations) seeded by a
  global `SEED` parameter.
- **FR-002**: The series MUST combine, additively or multiplicatively, at least: a piecewise
  linear trend (slope changes at changepoints), a seasonal component with configurable period
  and varying amplitude, a heteroscedastic noise component whose variance changes at
  designated changepoints, and an optional one-time spike event.
- **FR-003**: The dataset MUST contain **at minimum four** injected changepoints of distinct
  structural types, one per type:
  - **Type A — Permanent level shift**: abrupt step in mean, flat trend before and after.
  - **Type B — Trend kink**: slope changes direction or magnitude without a level jump.
  - **Type C — Variance change**: noise standard deviation doubles or halves; mean/trend
    unchanged. (This tests whether the agent recognises heteroscedasticity.)
  - **Type D — Seasonality mode shift**: seasonality transitions from additive to
    multiplicative (or vice versa). This is the blind spot most likely to defeat default
    Prophet `seasonality_mode='additive'`.
- **FR-004**: The ground-truth changepoint dates MUST be stored alongside the series so that
  visualisation and evaluation can annotate them exactly.
- **FR-005**: The dataset complexity floor MUST ensure that a default-parameter Prophet
  model trained on the full training split achieves val MAE that is non-trivially higher
  (≥ 10% relative) than a well-tuned model on at least one of the four changepoint types.
  This is validated empirically at POC-time and recorded in the run summary.
- **FR-006**: Dataset generation MUST be a standalone function `generate_dataset(seed, ...)
  → (pd.DataFrame, dict[changepoints])` — no Prophet, no agent dependency.

#### Data splits

- **FR-007**: The data MUST be split into train / val / test. Default: 70% train, 15% val,
  15% test, by time (no shuffling). Fractions are configurable.
- **FR-008**: The agent MUST have access to training data only during hypothesis formation
  and val scoring. Val and test target values MUST NOT appear in the agent context or stats
  bundle.
- **FR-009**: Final test MAE MUST be computed only after val-based config selection is
  complete and the accepted config is fixed.

#### Plotly visualisation utility

- **FR-010**: A standalone script `viz_dataset.py` MUST render the dataset figure (see US2)
  using Plotly and save it as an interactive HTML file. It MUST NOT import Prophet or agent
  code.
- **FR-011**: The figure MUST include: raw series trace, rolling mean (window = seasonal
  period), rolling std band (mean ± std, filled, low opacity), vertical dashed lines at
  each injected changepoint with type label, and shaded regions for val and test splits.
- **FR-012**: The figure MUST use descriptive axis labels, a legend, and a title that
  includes the seed value.

#### Stats extraction

- **FR-013**: A pure function `extract_stats(series: pd.Series, train_end: pd.Timestamp,
  changepoints: list[pd.Timestamp]) → StatsBundle` MUST be implemented with no LLM
  dependency.
- **FR-014**: `StatsBundle` MUST be a typed dataclass or Pydantic model containing at
  minimum: detected changepoints list, segment stats (mean, std, slope per inter-changepoint
  interval), estimated seasonality period, seasonality mode signal (additive vs
  multiplicative likelihood score), noise level estimate, post-last-changepoint history
  length in days, insufficient-seasonal-history flag (True if length < 1 seasonal period).
- **FR-015**: `extract_stats` MUST be deterministic: same inputs → same outputs, no
  random calls.
- **FR-016**: The stats bundle MUST serialise to valid JSON (no NaN/Inf).

#### Naive Prophet pipeline

- **FR-017**: A function `run_naive_prophet(train, val) → NaiveResult` MUST fit Prophet
  with all default parameters on the training split and evaluate on the val split, returning
  `NaiveResult(val_mae, forecast_df)`.
- **FR-018**: `run_naive_prophet` MUST also evaluate on test when called in final reporting
  mode, but MUST NOT receive test data during agent-loop execution.
- **FR-019**: The naive pipeline MUST be deterministic and seeded via Prophet's `stan_backend`
  seed where applicable.

#### Agent pipeline

- **FR-020**: The agent MUST be an LLM-driven loop (max **five** iterations) that:
  1. Receives the `StatsBundle` (training-only) as context.
  2. Forms a text hypothesis identifying the dominant failure mode.
  3. Proposes a Prophet config chosen from the bounded parameter grid (see FR-022).
  4. Receives val MAE back as feedback.
  5. Accepts if val MAE < naive val MAE; otherwise records the proposal as rejected and
     iterates.
- **FR-021**: The agent's hypothesis and Prophet invocation MUST use a typed tool call
  — the agent does NOT emit raw Python or arbitrary JSON; it calls `fit_prophet_with_config(
  changepoint_prior_scale, seasonality_prior_scale, seasonality_mode, changepoint_range,
  n_changepoints)`.
- **FR-022**: The bounded parameter grid MUST be:
  - `changepoint_prior_scale` ∈ {0.001, 0.01, 0.05, 0.1, 0.5}
  - `seasonality_prior_scale` ∈ {0.01, 0.1, 1.0, 10.0}
  - `seasonality_mode` ∈ {"additive", "multiplicative"}
  - `changepoint_range` ∈ {0.8, 0.9, 0.95}
  - `n_changepoints` ∈ {10, 15, 25}
  Any proposal outside this grid MUST be rejected before val scoring.
- **FR-023**: The agent context MUST NOT include val or test target values, ground-truth
  changepoint dates, or the naive val MAE score before the agent's first proposal.
- **FR-024**: After the first proposal, the agent MAY receive its own previous val MAEs
  as feedback (not the naive score), so it can self-improve; the naive val MAE MUST NOT
  be revealed until the decision matrix is emitted at run end.
- **FR-025**: The agent loop MUST capture a structured trace (see US4 / FR-026).
- **FR-026**: The trace MUST be a JSON array of iteration records, each containing:
  `iteration`, `hypothesis`, `proposed_config`, `val_mae`, `decision` (accepted / rejected /
  exhausted), and `rejection_reason` (null if accepted).

#### Decision matrix

- **FR-027**: After the agent loop completes, a decision matrix MUST be computed containing:
  naive val MAE, agent val MAE (best accepted or best proposed), naive test MAE, agent
  test MAE, delta val MAE (naive − agent), delta test MAE (naive − agent), and
  `agent_beats_naive_on_val` boolean.
- **FR-028**: The decision matrix MUST be printed to stdout and saved as
  `decision_matrix.json` in the run directory.

#### Results visualisation

- **FR-029**: A function `plot_results(train, val, test, naive_forecast, agent_forecast,
  changepoints, naive_test_mae, agent_test_mae) → plotly.Figure` MUST produce the
  comparative figure described in US5.
- **FR-030**: The results figure MUST be saved as `viz_results.html` and MUST NOT be passed
  to the agent at any point.

#### Run artefacts

- **FR-031**: All artefacts MUST be written to a run directory named
  `runs/<YYYYMMDD-HHMMSS>-seed<SEED>/`. Runs MUST NOT overwrite each other.
- **FR-032**: The artefact set MUST include: `dataset.csv`, `stats.json`, `trace.json`,
  `decision_matrix.json`, `viz_dataset.html`, `viz_results.html`, `run_summary.json`.
- **FR-033**: `run_summary.json` MUST include all fields listed in US6 AC2.

#### Model configuration

- **FR-034**: The LLM model identifier and provider MUST be read from environment /
  configuration, not hardcoded. Default: Claude Sonnet 4.5 via AWS Bedrock (overridable).
- **FR-035**: If the configured model is unavailable, the pipeline MUST fail with an explicit
  error rather than silently substituting a different model.

### Key Entities

- **Dataset**: a `pd.DataFrame` with columns `ds` (datetime) and `y` (float), plus a
  companion `changepoints` dict mapping structural type → `pd.Timestamp`.
- **StatsBundle**: typed aggregate of per-segment statistics computed from training data only.
- **NaiveResult**: `{val_mae: float, test_mae: float | None, forecast_df: pd.DataFrame}`.
- **ProphetConfig**: typed dataclass of the five bounded parameters in FR-022.
- **AgentProposal**: `{hypothesis: str, config: ProphetConfig, val_mae: float | None,
  decision: str, rejection_reason: str | None}`.
- **DecisionMatrix**: `{naive_val_mae, agent_val_mae, naive_test_mae, agent_test_mae,
  delta_val_mae, delta_test_mae, agent_beats_naive_on_val}`.
- **RunSummary**: all fields from FR-033, serialisable to JSON.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The POC runs end-to-end (dataset → naive → agent → results) without errors
  when all env vars are set.
- **SC-002**: `agent_beats_naive_on_val = true` in `run_summary.json` for the reference run
  (seed=42, default dataset config).
- **SC-003**: The dataset contains exactly the four injected changepoint types (A–D); this is
  asserted by a smoke test in `test_dataset.py`.
- **SC-004**: `extract_stats` returns a non-null, JSON-serialisable `StatsBundle` with all
  required fields for the reference dataset; this is asserted by a unit test.
- **SC-005**: Re-running with the same seed produces identical naive val MAE and identical
  stats bundle.
- **SC-006**: Every proposed config in the trace falls within the bounded grid (FR-022);
  no run produces an out-of-bounds value.
- **SC-007**: The agent's test MAE is computed only after val-based selection; the trace
  shows `decision = "accepted"` before `test_mae` is non-null.
- **SC-008**: All seven artefacts (FR-032) are present after a completed run.
- **SC-009**: `viz_dataset.html` contains four distinct vertical markers (one per
  changepoint type).
- **SC-010**: The results plot (`viz_results.html`) contains labelled legend entries for
  "Naive Prophet" and "Agent Prophet" and MAE annotations for both.

---

## File Layout

```
pocs/changepoint/seasonalityV2/
├── datasets.py          # generate_dataset() — FR-001–FR-006
├── stats.py             # extract_stats(), StatsBundle — FR-013–FR-016
├── naive.py             # run_naive_prophet() — FR-017–FR-019
├── agent.py             # agent loop + tool call + trace — FR-020–FR-026
├── decision.py          # build_decision_matrix() — FR-027–FR-028
├── viz.py               # viz_dataset(), plot_results() — FR-010–FR-012, FR-029–FR-030
├── pipeline.py          # end-to-end orchestration + artefact writing — FR-031–FR-033
├── config.py            # bounded grid constants, env-var loading — FR-022, FR-034–FR-035
└── test_dataset.py      # smoke tests: injected changepoints, stats, reproducibility
```

All files are self-contained within `pocs/changepoint/seasonalityV2/`.  No dependencies on
`src/ailf/` or other POC directories are permitted (POC isolation principle).

---

## Reference Work

The following files from `pocs/changepoint/seasonality/` serve as direct reference
implementations and are co-located here for convenience:

| File | Origin | Role |
|---|---|---|
| `ref_datasets_seasonal.py` | `seasonality/datasets_seasonal.py` | Generator pattern to extend |
| `ref_tools_seasonal.py` | `seasonality/tools_seasonal.py` | PELT wrapper to reuse/adapt |
| `ref_viz_seasonal.py` | `seasonality/viz_seasonal.py` | Plotly figure pattern |
| `ref_test_seasonal.py` | `seasonality/test_seasonal.py` | Proof-test structure |
| `ref_SPEC.md` | `seasonality/SPEC.md` | Prior scope (amplitude shift only) |
| `ref_plan.md` | `seasonality/plan.md` | Prior decisions (C1–C4) |

The `ref_` prefix marks these as read-only reference — do not edit them.

---

## Assumptions

- This work lives in `pocs/changepoint/seasonalityV2/` and is exempt from quality gates
  per the constitution's POC exemption.
- "Beats naive on val" means strictly lower val MAE; ties do not count as a win.
- The primary metric is MAE on the val/test horizon. RMSE and MAPE may be reported
  additionally in the decision matrix but are not the acceptance criterion.
- One seasonal period = 365 days (annual) for a daily series, or 30 days if weekly
  seasonality is configured. The flag in StatsBundle uses the dominant detected period.
- The agent is given a single LLM call per iteration (hypothesis + config proposal in one
  turn); multi-turn sub-conversations within a single iteration are out of scope.
- LangSmith / observability tracing is used when env vars are present; its absence does not
  block a run.
- Dataset length and split fractions are configurable but the reference run uses defaults
  (1 095 days, 70/15/15).
- The four changepoint types are injected at roughly equal intervals (≈ every 200 days) so
  each structural type has sufficient post-changepoint history for both seasonality and
  trend signals to be visible.
- The "10% relative MAE improvement" floor in FR-005 is verified empirically on the
  reference run; if not met, the dataset parameters (noise scale, amplitude) must be
  adjusted before the POC is considered done.
- YOLO mode is required to execute the pipeline (Prophet fitting, agent LLM calls, file
  writes); WRITE mode suffices only for authoring the code.
- Prior decisions from `seasonality/plan.md` (C1–C4) carry forward: min_size = seasonal
  period, tolerance = ±1 period, penalty sweep over {0.5, 1.0, 2.0, 3.0, 5.0, 10.0}.

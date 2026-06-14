# Feature Specification: Agent-in-the-Loop Changepoint Forecasting POC

**Feature Branch**: `003-changepoint-agent-poc`

**Created**: 2026-06-14

**Status**: Draft

**Input**: User description: "Build a rigorous POC that tests whether an LLM agent can outperform a deterministic changepoint-window workflow on difficult forecasting scenarios where naive retraining-window selection fails."

## Clarifications

### Session 2026-06-14

- Q: Validation protocol for naive-window selection and agent acceptance — single holdout vs. rolling-origin backtest? → A: Single holdout — score on the last `validation_horizon` block of training data only; the same protocol applies to both the naive baseline and the agent acceptance gate.
- Q: Which changepoint-detection method backs the shared detector? → A: Implementation detail deferred to planning; the spec only requires the detector be deterministic and honor each scenario's `n_changepoints_to_detect`.
- Q: When no proposal beats the naive baseline on validation, what is the agent's final forecast? → A: Carry the best-validation-scoring proposal the agent generated (even if it did not beat naive); the trace records that no proposal beat the baseline.
- Q: Which event intervals may `full_history_clean_event` clean, given leakage concerns at the forecast origin? → A: Only intervals lying entirely within training history that also end strictly before the forecast origin; open/ongoing events at the origin are not cleanable.
- Q: Is the `forecast_comparison.png` (which shows hidden-test actuals) ever an agent input? → A: No — it is produced only at/after final evaluation as a human-only artifact and is never passed to any agent node.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent beats the naive changepoint baseline on hard scenarios (Priority: P1)

A forecasting researcher runs the POC over a fixed set of difficult changepoint
scenarios and observes, for each scenario, how a visual-first LLM agent's chosen
intervention compares against both a full-history default Prophet model and a naive
"pick the best changepoint window" workflow. The researcher wants empirical evidence
that the agent, by reasoning about *why* the series misbehaves (permanent shift vs.
gradual drift vs. temporary event vs. recurring calendar event), selects interventions
that produce lower hidden-test error than blindly retraining on the most recent
changepoint window.

**Why this priority**: This is the core thesis of the POC — without an end-to-end
comparison producing honest metrics, there is no deliverable. Everything else exists to
make this comparison trustworthy.

**Independent Test**: Run the POC over all supplied scenario CSVs and confirm that for
each scenario a metrics artifact reports comparable hidden-test errors for all three
methods, and that the agent method is defined and evaluated. Delivers the headline
result on its own.

**Acceptance Scenarios**:

1. **Given** a scenario CSV and its metadata (train end, horizons), **When** the POC is
   run for that scenario, **Then** hidden-test metrics are produced for full-history
   Prophet, the naive changepoint workflow, and the agent, in a single comparable table.
2. **Given** the full set of supplied scenarios, **When** the POC completes, **Then** a
   cross-scenario human-readable summary reports which method won each scenario and by
   how much.
3. **Given** the same scenario run twice with the same configuration, **When** the
   deterministic baselines are compared, **Then** their metrics are identical (seeded /
   deterministic), and the agent run is fully traced for audit.

---

### User Story 2 - Visual-first, leakage-free agent reasoning is provable (Priority: P1)

A reviewer (or grader) needs to confirm that the agent reasoned about a chart of the
training history *before* it looked at numeric diagnostics, and that it never had access
to test-period values, ground-truth boundaries, or audit-only labels. The reviewer
inspects the per-scenario trace and the exact image shown to the agent and verifies the
ordering and the absence of leaked information.

**Why this priority**: The credibility of the entire result depends on the agent being
honestly bounded. A leak invalidates the comparison. This is co-equal with US1.

**Independent Test**: Inspect the agent trace for any scenario and confirm visual
observations are recorded before the intervention decision, and confirm the agent-visible
image contains only training-period data. Delivers an auditable integrity guarantee.

**Acceptance Scenarios**:

1. **Given** a completed agent run, **When** the trace is inspected, **Then** the visual
   inspection output (observations, pattern summary, hypotheses, uncertainties) is present
   and recorded before any intervention decision — regardless of whether visual inspection
   and diagnostics were computed concurrently, the decision must consume a completed visual
   result.
2. **Given** the agent-visible image artifact, **When** it is examined, **Then** it shows
   only observations up to the forecast origin and no test-period actuals, boundaries, or
   labels.
3. **Given** the intervention decision record, **When** it is read, **Then** it contains a
   `visual_first_rationale` that references visual observations ahead of numeric
   diagnostics.
4. **Given** the diagnostics and visual inputs, **When** they are computed, **Then** both
   are derived solely from training history and contain no test-period data.

---

### User Story 3 - Bounded interventions validated before they count (Priority: P1)

A researcher wants assurance that the agent cannot apply an arbitrary or unbounded model
configuration, and that any intervention it proposes is accepted only if it beats the
naive baseline on historical validation data — never on the hidden test. The agent
iterates up to a fixed budget, and rejected proposals are recorded so the loop does not
repeat itself.

**Why this priority**: This is the safety gate that makes "agent in the loop" trustworthy
rather than dangerous. Without it, the agent could overfit to the test set or propose
unsafe configurations.

**Independent Test**: Inspect the trace to confirm each proposed intervention came from
the fixed menu within declared bounds, was scored only on validation/backtest folds, and
that acceptance required beating the naive baseline; confirm hidden-test scoring happened
only after the loop ended. Delivers the guardrail guarantee independently.

**Acceptance Scenarios**:

1. **Given** the intervention menu, **When** the agent proposes an action, **Then** the
   action and its parameters fall within the declared bounded menu and grids.
2. **Given** a proposed intervention, **When** it is validated, **Then** the score is
   computed only from historical validation/backtest folds and the hidden test is not
   touched.
3. **Given** a proposal that does not beat the naive workflow on validation, **When** the
   loop continues, **Then** that exact action signature is recorded as rejected and is not
   proposed again.
4. **Given** the loop reaches acceptance or exhausts its iteration budget, **When** final
   evaluation runs, **Then** and only then is the hidden test scored.

---

### User Story 4 - Each intervention family is demonstrated (Priority: P2)

A researcher wants the scenario suite to exercise the agent's full reasoning vocabulary so
that the POC demonstrates the agent distinguishing between failure modes: permanent level
shift, gradual drift, temporary events, recurring calendar events, and insufficient
post-changepoint history. Across the scenario suite, every intervention family should be the
accepted choice or best-validation proposal in at least one scenario.

**Why this priority**: Demonstrating breadth proves the agent is doing real
mode-discrimination rather than always reaching for one tool. Valuable but secondary to
the core comparison being correct.

**Independent Test**: Inspect the proposed/accepted interventions across all scenarios and
confirm ramp regressors, event cleaning, and holiday/prior tuning each appear as the
accepted/best-validation choice in at least one scenario, and that holiday tuning appears only
on the calendar-recurring scenario.

**Acceptance Scenarios**:

1. **Given** the five scenarios, **When** all agent runs complete, **Then** ramp regressors,
   event cleaning, and holiday/prior tuning are each demonstrated at least once as the accepted
   choice or best-validation proposal, and the summary reports honest per-family coverage
   (winner / best-val / proposed / not-exercised) for all five tools.
2. **Given** a scenario whose diagnostics indicate no calendar-recurring pattern, **When**
   the agent decides, **Then** it does not select the holiday-tuning intervention.

---

### User Story 5 - Reproducible, human-readable artifacts per run (Priority: P2)

An analyst returns to a completed run and needs to understand what happened without
re-running anything: which image the agent saw, how the forecasts compared, what metrics
each method achieved, the full agent reasoning trace, and a readable narrative summary.

**Why this priority**: The deliverable must be inspectable and gradable after the fact.
Important for usability and grading, but depends on US1–US3 being correct first.

**Independent Test**: After a run, open the run directory and confirm the agent-context
image, forecast comparison plot, metrics file, trace file, and summary report all exist
and are internally consistent.

**Acceptance Scenarios**:

1. **Given** a completed scenario run, **When** the run directory is opened, **Then** it
   contains the agent-context image, a forecast comparison plot, a metrics file, a
   structured agent trace, and the run contributes to a cross-scenario summary.
2. **Given** the forecast comparison plot, **When** it is viewed, **Then** it shows train
   history, hidden-test actuals, full-history Prophet, the naive workflow forecast, and
   the agent forecast together.
3. **Given** the agent trace, **When** it is read, **Then** it records the visual output,
   diagnostics, naive-workflow validation summary, each hypothesis iteration, rejected
   signatures, the accepted intervention, validation metrics, final hidden-test metrics,
   and the model identifiers used for the visual and decision nodes.

---

### Edge Cases

- **No changepoints detected**: the naive workflow still trains and evaluates the
  full-history candidate; the agent still receives diagnostics indicating no detected
  changepoint and reasons accordingly.
- **Post-changepoint history shorter than one seasonal period**: diagnostics must flag
  this, and the agent should prefer interventions that preserve full seasonal history
  rather than a recent-window retrain.
- **Agent exhausts its iteration budget without beating the naive baseline**: the loop
  ends and the agent's best-validation-scoring proposal (among those it generated) is carried
  to final hidden-test evaluation, even though it did not beat the naive baseline; the trace
  records that no proposal beat the baseline. The agent always produces at least one valid
  proposal across its iterations (the bounded menu plus re-prompting on rejection guarantees
  this), so there is always an agent forecast to evaluate.
- **Required model identifiers unavailable**: the run fails clearly with an explicit
  configuration error rather than silently substituting a different model.
- **Agent proposes a parameter outside the bounded grid**: the proposal is rejected before
  validation and the agent is asked to choose again within bounds.
- **Recurring-event diagnostic says the pattern is not calendar-recurring**: the holiday
  intervention is unavailable/disallowed for that decision.
- **Validation and test horizons overlap or exceed available data**: the run fails clearly
  with a configuration error rather than leaking or truncating silently.
- **All proposals tie or marginally differ from the naive baseline on validation**:
  acceptance requires strictly beating the baseline by the configured criterion; ties do
  not trigger acceptance.

## Requirements *(mandatory)*

### Functional Requirements

#### Data and scenario intake

- **FR-001**: The POC MUST read each scenario from a supplied CSV containing a timestamp
  column and an observed-value column, without requiring any synthetic generation at
  runtime.
- **FR-002**: The POC MUST read a companion scenario metadata definition providing, per
  scenario: a scenario identifier, the data file location, the training cutoff, the test
  horizon, the validation horizon, the number of changepoints to detect, and optional
  audit-only notes/labels.
- **FR-003**: The POC MUST treat audit-only notes/labels and ground-truth boundaries as
  never exposed to the agent at any stage.
- **FR-004**: The POC MAY include a separate, optional fixture-generation script to produce
  scenario CSVs, but the main runtime MUST NOT depend on it.
- **FR-005**: The supplied scenario suite MUST include the five required scenarios:
  multiple permanent level shifts that cost the recent window its seasonal history; a long
  gradual drift misrepresented by abrupt changepoints; a temporary event mistaken for a
  regime change; six irregular non-calendar temporary events over a long history; and a
  recurring calendar-like event combined with trend kinks.

#### Data leakage controls

- **FR-006**: The agent MUST only ever see historical observations up to the forecast
  origin.
- **FR-007**: The POC MUST ensure the agent never sees test-period target values,
  ground-truth boundaries, scenario notes, audit-only labels, or final test metrics during
  hypothesis generation.
- **FR-008**: The agent MAY use validation/backtest scores, but those scores MUST be
  computed only from historical training data.
- **FR-009**: Final hidden-test evaluation MUST occur only after the agent accepts an
  intervention or exhausts its iteration budget.

#### Baselines

- **FR-010**: The POC MUST produce a full-history default-Prophet baseline trained on all
  history up to the training cutoff, evaluated only in final reporting.
- **FR-011**: The POC MUST produce a naive changepoint baseline that detects changepoints,
  forms candidate windows consisting of the full history plus every detected
  changepoint-start window, trains a default Prophet on each candidate, selects the
  candidate with the best validation error on historical validation data, and evaluates the
  selected candidate on the hidden test.
- **FR-012**: The naive changepoint baseline MUST be the primary deterministic comparison
  point that the agent's accepted intervention is measured against on validation.

#### Deterministic diagnostics

- **FR-013**: The POC MUST compute deterministic diagnostics from training history only,
  exposed as reusable, typed functions.
- **FR-014**: The diagnostics MUST include, at minimum: detected changepoints, the latest
  changepoint, a primary changepoint, post-changepoint history length, whether
  post-changepoint history is shorter than one seasonal period, segment means and standard
  deviations, candidate event blocks, a recurring-event pattern summary, local boundary
  jumps, candidate drift/ramp intervals, a transient-event score, and a permanent-shift
  magnitude.

#### Agent architecture and flow

- **FR-015**: The agent MUST be orchestrated as an explicit multi-stage graph with separate
  stages for visual inspection, deterministic diagnostics, intervention decision,
  validation, and final evaluation. The visual-inspection and deterministic-diagnostics
  stages have no data dependency on each other and MAY run concurrently; both MUST complete
  before the decision stage runs, which consumes both their outputs.
- **FR-016**: The visual-inspection stage MUST receive only a training-only image (no
  numeric diagnostics, no test data), MUST produce concise visual observations, a visual
  pattern summary, visual hypotheses, and visual uncertainties, and MUST NOT choose an
  intervention.
- **FR-017**: The diagnostics stage MUST be deterministic and MUST NOT call a model.
- **FR-018**: The decision stage MUST receive the visual-inspection output, the
  deterministic diagnostics, a naive-workflow summary, and the list of previously rejected
  interventions; MUST choose exactly one bounded intervention; and MUST include a
  `visual_first_rationale` that cites visual observations before numeric diagnostics.
- **FR-019**: The validation stage MUST deterministically evaluate the proposed
  intervention on a single historical holdout — the last `validation_horizon` block of
  training data, immediately preceding the forecast origin — and MUST NOT expose final test
  data. The same holdout protocol MUST be used for naive-window selection and agent
  acceptance.
- **FR-020**: The loop MUST run up to five iterations; it MUST accept a candidate when that
  candidate beats the naive workflow on validation; otherwise it MUST record the exact
  action signature as rejected and let the decision stage propose another intervention.
- **FR-021**: The final-evaluation stage MUST run the agent's final candidate on the hidden
  test and produce final metrics and plots. The final candidate is the accepted intervention
  if one beat the naive baseline on validation; otherwise it is the agent's
  best-validation-scoring proposal (even though it did not beat the baseline). The trace MUST
  record which of these two cases applied.

#### Model configuration

- **FR-022**: The POC MUST read the visual-node model identifier and the decision-node model
  identifier from configuration/environment and MUST NOT hardcode provider model
  identifiers.
- **FR-023**: The POC MUST read provider/access configuration and enable observability
  tracing from configuration/environment rather than code constants.
- **FR-024**: If the configured/intended model identifiers are unavailable, the POC MUST
  fail clearly or require explicit configuration rather than silently falling back to a
  different model.
- **FR-025**: The intended defaults MUST be the stronger vision-capable model for the visual
  node and the faster reasoning model for the decision node, both via the configured
  provider, overridable by configuration.

#### Intervention menu and bounds

- **FR-026**: The decision stage MUST only choose from the fixed five-tool intervention menu:
  recent-window retrain; full-history with one or more post-changepoint step regressors;
  full-history with one or more clipped ramp regressors; full-history with selected
  temporary-event intervals cleaned/interpolated; and full-history with inferred calendar-like
  holiday windows plus bounded Prophet hyperparameter tuning.
- **FR-026a**: The event-cleaning intervention MAY only clean intervals that lie entirely
  within training history and end strictly before the forecast origin; open or ongoing events
  at the forecast origin are not cleanable, and interpolation MUST use only training points.
- **FR-028**: Holiday-based tuning MUST infer recurring calendar-like event windows from
  training history, encode them as holidays, and tune bounded values for changepoint prior
  scale, seasonality prior scale, holidays prior scale, seasonality mode, and changepoint
  range.
- **FR-029**: All tuning MUST use bounded parameter grids; free-form arbitrary model
  configuration MUST NOT be possible.

#### Agent decision rules

- **FR-030**: The agent's reasoning MUST distinguish: permanent level shift → step
  regressors; gradual transition → ramp regressors; irregular temporary events → event
  cleaning; recurring calendar-like events → holidays plus prior tuning; insufficient
  post-changepoint history → preserve full seasonal history where possible.
- **FR-031**: The holiday-tuning intervention MUST NOT be selected when the recurring-event
  diagnostic indicates the pattern is not calendar-recurring.

#### Outputs and reporting

- **FR-033**: For each scenario, the POC MUST write artifacts under a per-run directory.
- **FR-034**: The POC MUST emit the exact training-only image shown to the visual node as an
  artifact.
- **FR-035**: The POC MUST emit a forecast comparison plot showing train history,
  hidden-test actuals, full-history Prophet, the naive workflow forecast, and the agent
  forecast. This plot MUST be produced only at or after final evaluation, is a human-only
  artifact, and MUST NEVER be passed to any agent node (distinct from the training-only
  `agent_context.png`, which is the sole image the agent sees).
- **FR-036**: The POC MUST emit a human-readable metrics artifact covering all methods.
- **FR-037**: The POC MUST emit a structured agent trace containing the visual-node output,
  deterministic diagnostics, the naive-workflow validation summary, each hypothesis
  iteration, rejected action signatures, the accepted intervention, validation metrics,
  final hidden-test metrics, and the model identifiers used for the visual and decision
  nodes.
- **FR-038**: The POC MUST emit a human-readable report summarizing results across all
  scenarios.
- **FR-039**: The POC MUST NOT produce a diagnostics image as a required artifact; any
  debug-only plot MUST be behind an explicit developer flag and MUST never be passed to the
  agent.

#### Reproducibility

- **FR-040**: Deterministic components (baselines, diagnostics, validation scoring) MUST be
  reproducible: re-running a scenario with the same configuration MUST yield identical
  deterministic metrics, with any stochastic step seeded and recorded.

### Key Entities *(include if feature involves data)*

- **Scenario**: A single difficult forecasting case — its identifier, source data
  reference, training cutoff, validation horizon, test horizon, expected changepoint count,
  and audit-only notes (never shown to the agent).
- **Time Series Observation Set**: The ordered (timestamp, value) pairs; partitioned into a
  training portion (visible to the agent), a validation portion (used only for historical
  scoring), and a hidden-test portion (used only in final evaluation).
- **Diagnostics Bundle**: The deterministic, training-only set of computed signals about
  changepoints, segments, events, drift, and shift magnitudes consumed by the decision
  stage.
- **Visual Inspection Result**: The agent's concise observations, pattern summary,
  hypotheses, and uncertainties derived solely from the training-only chart.
- **Intervention Proposal**: A single choice from the bounded menu plus its bounded
  parameters and a visual-first rationale; carries an action signature used to detect and
  reject repeats.
- **Validation Result**: The historical-fold score for a proposal and whether it beat the
  naive baseline.
- **Naive Workflow Result**: The set of candidate windows, their validation scores, the
  selected window, and its score — the primary baseline the agent competes against.
- **Run Artifacts**: The per-scenario directory of outputs — agent-context image, forecast
  comparison plot, metrics, structured trace — plus the cross-scenario summary report.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five required scenarios run end-to-end from supplied CSVs and produce a
  complete set of artifacts each.
- **SC-002**: For every scenario, the image presented to the agent contains only
  training-period data, verifiable by inspection (0 test-period points visible).
- **SC-003**: For every agent run, the trace demonstrates that visual inspection was
  recorded before the intervention decision, and the decision's rationale references visual
  observations before numeric diagnostics.
- **SC-004**: The naive workflow demonstrably trains a default model on the full history and
  on every detected changepoint window, selecting among them by historical validation score.
- **SC-005**: For every agent run, every validated proposal is scored only on historical
  validation/backtest data, with no access to hidden-test values during the loop.
- **SC-006**: For every scenario, hidden-test metrics are computed only after the loop
  accepts a candidate or exhausts its budget.
- **SC-007**: Re-running any scenario with the same configuration reproduces identical
  deterministic baseline and validation metrics.
- **SC-008**: Across the five scenarios, the agent demonstrates mode-appropriate
  discrimination: ramp regressors, event cleaning, and holiday/prior tuning each appear as the
  accepted/best-validation choice in at least one scenario, and the holiday tool is selected
  ONLY on the calendar-recurring scenario (never elsewhere — FR-031). The remaining tools
  (recent-window retrain, step regressors) remain available and bounded but are not required to
  win, because with the forecast origin placed so validation coincides with the forecast window,
  some scenarios whose injected cause is a level shift are in fact better fit on that window by a
  ramp (the post-shift history has itself become a gradual climb). The summary reports, per
  family, whether it was an accepted winner, a best-validation proposal, merely proposed, or not
  exercised — this coverage is observed honestly at run time, never engineered.
- **SC-009**: Every proposed intervention falls within the fixed menu and declared
  parameter bounds; no run produces an out-of-bounds or free-form configuration.
- **SC-010**: When required model identifiers are unavailable, the run fails with an
  explicit, actionable error and never substitutes a different model silently.
- **SC-011**: A reader unfamiliar with the run can, from the cross-scenario summary alone,
  determine which method won each scenario and the relative error differences.

## Assumptions

- This work lives in the throwaway POC area (`pocs/changepoint/`) and is therefore exempt
  from the repository's test-first and quality gates per the constitution's POC exemption;
  it is fail-fast exploration, not promoted pipeline or core code.
- "Beats the naive workflow on validation" means strictly lower validation error by the
  configured primary metric (default MAE); ties do not trigger acceptance.
- The intervention menu has five tools (recent-window, step, ramp, event-cleaning,
  holiday-tuning). A generic Prophet-tuning tool was deliberately removed: it acted as an
  escape hatch that let the agent obtain a good validation score without committing to a
  structural diagnosis, and no fixture targets it.
- The forecast origin is placed so the validation window coincides with the forecast horizon.
  A side effect: the `level_shift_loses_seasonality` fixture's post-shift history has itself
  become a gradual climb on this window, so the agent legitimately fits it best with a ramp, and
  `step` is not the winning tool on any fixture. SC-008 therefore does not require `step` (or
  `recent_window`) to win; it requires honest mode-discrimination on the families the fixtures do
  elicit (ramp, event-cleaning, holidays) plus the holiday gate (FR-031). Forcing a step win by
  distorting bounds/prompts/data is disallowed (constitution honest-evaluation).
- The agent loop exits on the first proposal that strictly beats naive, so a scenario's trace may
  contain only one tool; family coverage is therefore measured across scenarios, not within one.
- The primary selection and comparison metric is MAE on the relevant horizon unless
  configuration specifies otherwise; the metrics artifact may additionally report other
  standard error metrics for context.
- "One seasonal period" is interpreted using the dominant seasonality inferred from the
  series' timestamp frequency (e.g., weekly or yearly) for the purpose of the
  insufficient-history flag.
- Scenario metadata is supplied as a single companion file alongside the CSVs under the
  POC data directory; the exact file format is an implementation detail not constrained by
  this spec.
- The intended default models are Claude Opus 4.8 (visual node) and Claude Sonnet 4.6
  (decision node) accessed via AWS Bedrock, but all model identifiers and access settings
  are read from configuration/environment and are overridable.
- Observability tracing (LangSmith) is enabled when its environment configuration is
  present; its absence does not block a run.
- The iteration budget is fixed at five decision iterations per scenario.
- Changepoint detection for both the naive baseline and diagnostics uses a single shared
  detector so that the agent and the baseline reason about the same changepoints. The
  detection method is an implementation detail deferred to planning; the only spec-level
  requirements are that the detector be deterministic and honor each scenario's
  `n_changepoints_to_detect`.
- Validation scoring uses a single holdout — the last `validation_horizon` block of training
  data immediately preceding the forecast origin — never overlapping the hidden test. This
  diverges from the constitution's default rolling-origin backtest (Principle V) as a
  deliberate POC simplification, permitted under the POC exemption.
- "Run directory" is uniquely named per execution (e.g., per scenario and timestamp) so runs
  do not overwrite one another.

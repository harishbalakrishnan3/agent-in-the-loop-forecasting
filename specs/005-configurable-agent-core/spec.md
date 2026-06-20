# Feature Specification: Configurable Agent Core (POC → Core Promotion)

**Feature Branch**: `005-configurable-agent-core`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "Convert the changepoint POC (`pocs/changepoint/`) into the full
agent core. Modularize so (1) the agent's intervention tools can be lifted-and-shifted to an MCP
server, (2) every stage of the agent analysis emits JSON payloads to a UI app for visualization,
and (3) a `config.yaml` drives model IDs, a visual-analysis on/off switch, per-diagnostic and
per-tool enable/disable toggles, and train/validation/test split knobs. The UI reads the config to
render checkboxes; triggering a run with specific toggles must make the backend behave accordingly."

## Clarifications

### Session 2026-06-20

- Q: How should the agent interact with the intervention "tools" intended for later MCP
  relocation? → A: Keep menu-select + relocatable tools. The agent proposes exactly one
  intervention via structured output; a separate deterministic backtest gate scores it; the agent
  never sees validation scores mid-loop (only that an action signature was rejected). Each tool is
  refactored behind a serializable registry contract (plain-data in, plain-data out) so it can later
  be served over MCP without changing the agent. No free-form tool-calling.
- Q: When the UI triggers a run with specific checked/unchecked toggles, how does that
  configuration reach the backend? → A: Per-run override merged with defaults. `config.yaml` holds
  defaults; each run receives an explicit (possibly partial) override that is merged, validated, and
  recorded alongside that run's artifacts.
- Q: The golden train/validation/test split lives in scenario metadata as absolute row counts, but
  the config requirement calls for "ratios" — and the changepoint scenarios' forecast-origin
  placement is load-bearing (SC-008 of the prior POC spec). How do split knobs interact with the
  golden split? → A: The golden absolute split stays in metadata as the per-scenario default. A run
  MAY override it for experimentation. The override / config knobs MAY be expressed as EITHER
  ratios (fractions of the series length, converted to rows at run start) OR absolute row counts
  (matching the golden metadata units). When no override is supplied, the golden split is used
  verbatim, so the golden result reproduces exactly.
- Q: When a diagnostic or a tool is unchecked in the config for a run, what happens? → A: Hidden
  from the agent, still computed. Disabled diagnostics are still COMPUTED (so dependent diagnostics
  do not break) but are excluded from what the agent sees; disabled tools are removed from the
  agent's menu (and from the deterministic gate's allowed set). The trace records exactly what was
  hidden and what was removed.
- Q: What is the scope of the UI event transport (SSE / WebSocket / file / queue)? → A: Deferred.
  This feature fixes the stage-event INTERFACE and the per-stage payload SHAPE (typed, serializable,
  ordered, run-scoped). The concrete transport is a later feature; a default sink that records every
  emitted event to the run directory is in scope so the contract is testable without a UI.
- Q: Where do secrets vs. operational settings live? → A: Secrets (provider API key, cloud access
  credentials) stay in `.env`. Non-secret operational settings (model IDs, region, observability
  toggle, `visual_analysis_enabled`, per-diagnostic toggles, per-tool toggles, split knobs) move to
  `config.yaml`. Model IDs that were in `.env` in the POC move to `config.yaml` with the same
  intended defaults.
- Q: What is the unit of execution — a single series or a batch over all scenarios? → A: A run is a
  single series/scenario only. The UI and the core entrypoint trigger single-series runs; the per-run
  effective configuration, the event stream, and all artifacts scope to that one series. The POC's
  cross-scenario batch summary is DROPPED entirely (not retained as a wrapper). Promoting additional
  datasets from the POC area into the core is explicitly a later concern, out of scope here.
- Q: When a stage fails, does the run terminate or degrade? → A: Fail-fast — a stage error is
  terminal. Any stage that raises emits a terminal error event and the run stops; no partial or
  degraded agent forecast is produced (consistent with the POC's no-silent-fallback behavior). Normal
  in-loop control flow — a proposal rejected for being out of bounds or failing to beat the naive
  baseline, or the iteration budget being exhausted and the best-validation proposal carried forward —
  is NOT a stage failure and is unaffected.
- Q: Must the feature support concurrent runs? → A: No. The UI triggers exactly one run at a time;
  the feature assumes single-run-at-a-time execution and makes no concurrency or in-process isolation
  guarantees (the POC's process-global seeding/logging patterns are acceptable). Per-run
  reproducibility (seed recorded per run) is still guaranteed. Fanning out parallel runs is a later
  concern for the UI/transport feature, not designed for here.
- Q: Which run steps emit events — only the agent-graph stages, or the deterministic steps too? → A:
  All run steps emit events, deterministic ones included. Changepoint detection and the two baseline
  fits (full-history Prophet and the naive changepoint-window workflow) each emit start/complete
  events with their results, alongside the agent stages, so the event contract covers the whole run
  and the UI can render detected changepoints and the baseline comparison live (matching the UI
  reference). The same leakage controls (FR-029) apply to these events.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Promote the changepoint agent into a reusable, serializable core (Priority: P1)

A forecasting researcher runs the changepoint analysis through the promoted code path — now living
in a shared, review-gated core plus a thin changepoint pipeline — and gets the same end-to-end
result the POC produced (visual ∥ diagnostics → decision ↔ validation → final evaluation; the
agent's chosen bounded intervention compared against full-history Prophet and the naive
changepoint-window workflow on hidden test). The difference is structural: the agent engine, the
tool-registry mechanism, the backtest gate, metrics, the model wrapper, configuration, stage-event
emission, and reporting now live in the core with a plain-serializable public API, while the
changepoint detector, the diagnostics bundle, the intervention set, and the prompts live in the
changepoint pipeline.

**Why this priority**: This is the deliverable. Everything else (config, UI events, MCP-readiness)
hangs off a clean core/pipeline boundary. Without the promotion, there is nothing to configure or
visualize.

**Independent Test**: Run the changepoint pipeline end-to-end through the core entrypoint with the
golden config for a single scenario and confirm it produces the same per-run artifact set the POC
produced for that scenario (agent-context image, forecast comparison plot, metrics, structured trace)
with the same deterministic baseline/validation metrics. Confirm the core package contains no
changepoint-specific logic and no UI/front-end types.

**Acceptance Scenarios**:

1. **Given** the golden configuration and a committed changepoint fixture, **When** a researcher
   runs that single scenario through the core entrypoint, **Then** the deterministic baseline and
   validation metrics are identical to the POC's for that fixture and seed.
2. **Given** the promoted code, **When** the core package is inspected, **Then** it contains the
   generic agent loop, tool-registry contract, backtest gate, metrics, model wrapper, config loader,
   stage-event emitter, and reporting — and contains no changepoint-specific detector, diagnostics,
   interventions, or prompts.
3. **Given** the promoted code, **When** the core's public API surface is inspected, **Then** every
   public function/stage consumes and returns plain serializable data (no front-end types, no live
   model handles in the serialized boundary), satisfying the importable-core principle.
4. **Given** the changepoint pipeline, **When** it is inspected, **Then** it depends only on the core
   (not on any other pipeline) and supplies its detector, diagnostics, interventions, prompts, and
   wiring.

---

### User Story 2 - Drive agent behavior from a configuration file (Priority: P1)

A researcher opens `config.yaml`, sees the model IDs, a visual-analysis on/off switch, a
`diagnostics` section listing every field of the diagnostics bundle (all defaulting to enabled), an
`agent_tools` section listing every intervention tool (all defaulting to enabled), and the
train/validation/test split knobs. They flip toggles to probe which statistical signals actually
help the agent versus pollute its context, and which tools matter — then run, and the system behaves
exactly as configured. They can also pass a per-run override (the same shape as the file) so a single
run can deviate from the defaults without editing the file.

**Why this priority**: This is the core knob the user asked for and the mechanism the UI depends on.
It is what turns the static POC into an experimentation platform.

**Independent Test**: Run the pipeline twice — once with all toggles on, once with a specific
diagnostic and a specific tool disabled — and confirm from the trace that the disabled diagnostic was
absent from the agent's decision input (while still computed) and the disabled tool was absent from
the agent's menu and the gate's allowed set, with both runs recording their resolved configuration.

**Acceptance Scenarios**:

1. **Given** `config.yaml` with default values, **When** the system loads it, **Then** every
   diagnostics-bundle field is present in the `diagnostics` section defaulting to enabled, every
   intervention tool is present in `agent_tools` defaulting to enabled, the visual-analysis switch
   defaults to on, and the two model IDs carry the POC's intended defaults.
2. **Given** a run with a diagnostic disabled, **When** the agent's decision stage runs, **Then** the
   disabled diagnostic is still computed but excluded from the data shown to the agent, and the trace
   records it as hidden.
3. **Given** a run with a tool disabled, **When** the agent decides, **Then** that tool is not
   offered in the menu and the deterministic gate rejects it if somehow proposed, and the trace
   records it as removed.
4. **Given** a per-run override that sets only a subset of fields, **When** the run starts, **Then**
   the override is merged onto the file defaults, validated, and the fully-resolved effective
   configuration is recorded with that run's artifacts.
5. **Given** an invalid configuration (unknown diagnostic/tool name, malformed value, or a split that
   leaves a non-positive or overlapping partition), **When** the system loads it, **Then** the run
   fails with an explicit, actionable error rather than silently ignoring or defaulting the bad value.

---

### User Story 3 - Toggle the visual-analysis node (Priority: P1)

A researcher disables visual analysis to measure the visual node's contribution. With the switch
off, the agent skips the visual-inspection stage entirely, the decision stage runs on a
diagnostics-only versioned prompt, no agent-context image is produced or sent to any model, and the
run still completes with a valid agent forecast. With the switch on (default), behavior is the POC's
visual-first flow, including the visual-before-decision ordering guarantee.

**Why this priority**: The visual node is the most expensive and most novel part of the agent; being
able to ablate it cleanly is essential to the research question and is an explicit config requirement.

**Independent Test**: Run the same scenario with the visual switch on and off; confirm the on-run's
trace contains a visual-inspection result recorded before the decision and the off-run's trace
contains no visual result, uses the diagnostics-only decision prompt, and still yields an agent
forecast and full metrics.

**Acceptance Scenarios**:

1. **Given** the visual switch on, **When** the agent runs, **Then** a training-only image is
   produced and shown to the visual node, a visual-inspection result is recorded before the decision,
   and the decision's rationale references visual observations first (POC visual-first invariant).
2. **Given** the visual switch off, **When** the agent runs, **Then** no agent-context image is
   produced or sent to any model, the visual stage is skipped, the decision stage uses a
   diagnostics-only versioned prompt, and the trace records that visual analysis was disabled.
3. **Given** either setting, **When** the run completes, **Then** a valid agent intervention is
   evaluated on the hidden test and the full artifact set is produced.

---

### User Story 4 - Relocatable intervention tools (MCP-ready) (Priority: P2)

A developer wants to later move the bounded intervention tools out of the in-process pipeline and
behind an MCP server without touching the agent loop or the gate. Each tool is registered with a
declared, serializable contract: a stable name, a human description, a bounded parameter schema, and
a pure mapping from (plain proposal + plain training-derived context) to (plain forecast/score
result). The agent selects a tool by name with bounded params; the registry resolves and invokes it;
nothing in the contract assumes the tool runs in-process.

**Why this priority**: Lift-and-shift readiness is an explicit design goal, but the relocation itself
is a later feature; what must be true now is that the contract is clean enough to relocate.

**Independent Test**: Inspect the tool registry and confirm each tool exposes name + description +
bounded parameter schema + a plain-data invocation contract, that the agent references tools only by
name and bounded params, and that swapping a tool's implementation for an equivalent out-of-process
stub (same contract) requires no change to the agent loop, the gate, or the prompts.

**Acceptance Scenarios**:

1. **Given** the tool registry, **When** it is inspected, **Then** every intervention tool declares a
   stable name, a description, and a bounded parameter schema, and accepts/returns only serializable
   data.
2. **Given** the agent's decision, **When** it proposes an intervention, **Then** the proposal is a
   tool name plus bounded parameters (no executable code, no free-form model configuration), and
   out-of-bounds parameters are rejected before any scoring.
3. **Given** a tool whose in-process implementation is replaced by a contract-equivalent stub,
   **When** the pipeline runs, **Then** the agent loop, the gate, the prompts, and the trace format
   are unchanged.
4. **Given** a tool disabled in configuration, **When** the registry is built for that run, **Then**
   the tool is excluded from the menu advertised to the agent and from the gate's allowed set.

---

### User Story 5 - Every stage emits a structured event for the UI (Priority: P2)

A UI developer wants to visualize the agent's analysis as it happens. Each step of the run —
deterministic and agent alike (configuration resolved, split built, changepoint detection, the two
baseline fits, diagnostics computed, visual inspection, each decision iteration, each validation
outcome, final evaluation, run complete) — emits a typed, serializable event carrying a stage
identifier, a lifecycle status (start/complete, or error), a run identifier, an ordering marker, and
a stage-appropriate payload. The events are emitted in causal order through
an emitter abstraction the core calls; a default sink records every event to the run directory so the
contract is exercisable without a UI. The concrete network transport is out of scope for this
feature.

**Why this priority**: The UI is being developed in parallel; the backend's obligation now is a
stable, documented event contract, not the transport. It depends on the stages existing (US1), so it
is P2.

**Independent Test**: Run a scenario with the default event sink and confirm the recorded event
stream contains one well-formed event per stage lifecycle in causal order, each conforming to the
documented per-stage payload shape, and that no event payload contains hidden-test values or
audit-only fields before final evaluation.

**Acceptance Scenarios**:

1. **Given** a run, **When** it executes, **Then** each stage emits at least a start and a
   complete event (or an error event on failure), each carrying the run identifier, stage identifier,
   ordering marker, and a payload matching that stage's documented shape.
2. **Given** the recorded event stream, **When** it is read in order, **Then** the stage order
   reflects the actual causal flow (configuration → split → changepoint detection → baseline fits →
   diagnostics/visual → decision/validation iterations → final evaluation → complete), with concurrent
   stages marked as such.
3. **Given** any event emitted before final evaluation, **When** its payload is inspected, **Then**
   it contains no hidden-test target values, ground-truth boundaries, or audit-only labels (the
   leakage controls extend to emitted events).
4. **Given** a stage that raises an error, **When** the run handles it, **Then** a terminal error
   event for that stage is emitted with a human-readable reason and the run stops (fail-fast) without
   producing a partial agent forecast, rather than emitting a malformed success event.

---

### User Story 6 - Reproducible, configuration-stamped artifacts per run (Priority: P2)

An analyst returns to a completed run and can reconstruct exactly what happened and under what
configuration: the resolved effective config (file defaults + per-run override), the split actually
used (and whether it came from golden metadata or an override), which diagnostics were hidden, which
tools were removed, whether visual analysis was on, the model IDs used, the full agent trace, the
metrics, the plots, and the recorded event stream.

**Why this priority**: Honest, reproducible evaluation is non-negotiable in this project; once
behavior is configurable, the configuration becomes part of the result and MUST be recoverable.

**Independent Test**: Open a completed run directory and confirm it contains the resolved effective
configuration, the split provenance, the agent trace (including hidden-diagnostics / removed-tools /
visual-enabled records), metrics, plots, and the event stream — and that re-running with the recorded
config reproduces identical deterministic metrics.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** its directory is opened, **Then** it contains the resolved
   effective configuration, the split provenance (golden vs. override, and the resolved row counts),
   the structured trace, metrics, plots, and the recorded event stream.
2. **Given** the recorded effective configuration from a prior run, **When** it is supplied as the
   override for a new run on the same fixtures and seed, **Then** the deterministic baseline and
   validation metrics reproduce identically.
3. **Given** the trace, **When** it is read, **Then** it records the visual-enabled flag, the list of
   hidden diagnostics, the list of removed tools, the split provenance, and the model IDs for the
   visual and decision stages.

---

### Edge Cases

- **All structural tools disabled**: if configuration disables every structural intervention, a
  guaranteed-valid fallback (full-history default forecast) MUST remain available so the run still
  produces an agent forecast; the trace records that the menu was reduced to the fallback.
- **Visual analysis disabled but a visual-only diagnostic is referenced**: the decision stage MUST
  use the diagnostics-only prompt and MUST NOT reference a visual result that does not exist.
- **Per-run override names an unknown diagnostic or tool**: the run fails with an explicit error
  naming the unknown key rather than silently ignoring it.
- **Split override (ratio or absolute) yields a non-positive, zero-length, or overlapping
  partition, or a test horizon exceeding available rows**: the run fails clearly with a configuration
  error rather than leaking or truncating silently.
- **Ratio split does not divide evenly into whole rows**: the conversion MUST be deterministic and
  documented (e.g., fixed rounding rule) so the same ratios always yield the same row counts for the
  same series length.
- **Both a ratio and an absolute split are supplied for the same run**: the run fails with an
  explicit "ambiguous split specification" error rather than guessing precedence.
- **No per-run override supplied**: the golden metadata split and the `config.yaml` defaults are used
  verbatim, reproducing the golden result.
- **Required model identifiers missing or unavailable**: the run fails clearly (no silent fallback to
  a different model), consistent with the POC behavior.
- **Disabling a diagnostic that another diagnostic depends on**: the dependency is still computed
  (diagnostics are always computed); only the agent-facing visibility is suppressed, so no dependent
  computation breaks.
- **An emitted event would exceed a reasonable size (e.g., a large payload)**: the event contract
  MUST define how large payloads are handled (e.g., reference an artifact rather than inline it)
  rather than emitting unbounded data.

## Requirements *(mandatory)*

### Core / pipeline boundary (promotion)

- **FR-001**: The system MUST relocate the generic, reusable agent machinery from the changepoint POC
  into a shared, review-gated core: the multi-stage agent loop and its orchestration, the tool
  registry mechanism, the deterministic backtest/validation gate, forecast metric computation, the
  model-provider wrapper, the configuration loader, the stage-event emitter, and the run/reporting
  artifact writers.
- **FR-002**: The system MUST keep all changepoint-specific logic in a thin changepoint pipeline: the
  changepoint detector, the diagnostics bundle, the intervention tool set, the versioned prompts, the
  scenario/fixture loading, and the wiring that registers them into the core loop.
- **FR-003**: The core's public API MUST consume and return plain serializable data across its
  boundary (no front-end/UI types, and no non-serializable live handles in the serialized state),
  honoring the importable-core principle.
- **FR-004**: The changepoint pipeline MUST depend only on the core and MUST NOT import or depend on
  any other pipeline.
- **FR-005**: The promoted deterministic components (baselines, diagnostics, validation scoring,
  metrics) MUST preserve the POC's behavior such that, for the committed fixtures and the recorded
  seed and the golden configuration, the deterministic baseline and validation metrics are identical
  to the POC's.
- **FR-006**: Promoted core deterministic logic MUST be covered test-first (failing-then-passing
  tests) per the constitution, including the configuration resolver, the split resolver, the tool
  registry/gate, the metrics, and the event emitter; the non-deterministic agent layer remains
  governed by the golden-set evaluation approach rather than exact-output unit tests.

### Configuration

- **FR-007**: The system MUST read a `config.yaml` providing at minimum: the visual-node model
  identifier and the decision-node model identifier; a `visual_analysis_enabled` boolean (default
  true); a `diagnostics` section enumerating every field of the diagnostics bundle, each a boolean
  defaulting to true; an `agent_tools` section enumerating every intervention tool, each a boolean
  defaulting to true; and the train/validation/test split knobs.
- **FR-008**: The model identifiers that were environment variables in the POC MUST move into
  `config.yaml`, retaining the POC's intended defaults (the stronger vision-capable model for the
  visual node, the faster reasoning model for the decision node). Secrets (provider API key, cloud
  access credentials) MUST remain outside `config.yaml` (in the environment), never committed.
- **FR-009**: The system MUST accept a per-run configuration override of the same shape as
  `config.yaml` (possibly partial), MUST merge it onto the file defaults, MUST validate the merged
  result, and MUST record the fully-resolved effective configuration with that run's artifacts.
- **FR-010**: Configuration loading MUST fail with an explicit, actionable error when it encounters an
  unknown diagnostic name, an unknown tool name, a malformed value, a missing required model
  identifier, or an invalid split specification — never silently ignoring or defaulting a bad value.
- **FR-011**: The `diagnostics` section MUST list exactly the fields present in the diagnostics
  bundle, so the configuration surface stays in lockstep with the bundle; adding a bundle field
  without exposing a toggle (or vice versa) MUST be detectable.
- **FR-012**: The `agent_tools` section MUST list exactly the registered intervention tools, so the
  configuration surface stays in lockstep with the tool registry.

### Toggle semantics

- **FR-013**: When a diagnostic is disabled, the system MUST still compute it (so dependent
  diagnostics are unaffected) but MUST exclude it from the data presented to the agent's decision
  stage; the trace MUST record the diagnostic as hidden.
- **FR-014**: When an intervention tool is disabled, the system MUST exclude it from the menu
  advertised to the agent and from the deterministic gate's allowed set; if such a tool is somehow
  proposed it MUST be rejected; the trace MUST record the tool as removed.
- **FR-015**: When `visual_analysis_enabled` is false, the system MUST skip the visual-inspection
  stage, MUST NOT produce or send any agent-context image to a model, MUST run the decision stage on
  a diagnostics-only versioned prompt, and MUST record in the trace that visual analysis was disabled;
  the visual-first ordering invariant applies only when visual analysis is enabled.
- **FR-016**: When configuration disables every structural intervention, the system MUST retain a
  guaranteed-valid fallback intervention (a full-history default forecast) so a run still yields an
  agent forecast; the trace MUST record the menu reduction.

### Split configuration

- **FR-017**: The golden train/validation/test split MUST remain in scenario metadata as the
  per-scenario default and MUST be used verbatim when no override is supplied, so the golden result
  reproduces exactly.
- **FR-018**: A run MUST be able to override the split for experimentation, expressed as EITHER
  ratios (fractions of the series length) OR absolute row counts (matching the golden metadata
  units); supplying both for the same run MUST fail with an explicit ambiguity error.
- **FR-019**: Ratio-to-row conversion MUST be deterministic and documented (a fixed rounding rule) so
  the same ratios always produce the same row counts for the same series length.
- **FR-020**: Split resolution MUST validate that the resulting partitions are positive, non-empty,
  non-overlapping, and fit within the available rows, failing clearly otherwise.
- **FR-021**: The system MUST record, per run, the split provenance: whether the split came from
  golden metadata or an override, the override units used, and the resolved absolute row counts.

### Tool registry (MCP-readiness)

- **FR-022**: Each intervention tool MUST be registered with a declared, serializable contract: a
  stable name, a human-readable description, and a bounded parameter schema; the registry MUST be the
  single place the agent's available tools and their bounds are defined.
- **FR-023**: The agent MUST select an intervention by tool name plus bounded parameters only; no
  free-form model configuration and no executable payload may be proposed; out-of-bounds parameters
  MUST be rejected before any scoring (preserving the POC's bounds enforcement).
- **FR-024**: A tool's invocation contract MUST be a pure mapping from plain, training-derived input
  to a plain result, with no assumption that the tool executes in-process, so an equivalent
  out-of-process (e.g., MCP-served) implementation can replace it without changing the agent loop,
  the gate, or the prompts.
- **FR-025**: The deterministic gate MUST remain the sole authority that accepts or rejects a
  proposal by scoring it on historical validation data only; the agent MUST NOT observe validation
  scores during the decision loop (it observes only that an action signature was rejected), preserving
  the proposer/guardrail separation.

### Stage events for the UI

- **FR-026**: Every stage of a run MUST emit, through an emitter abstraction the core invokes, a
  typed, serializable event carrying at minimum: a run identifier, a stage identifier, a lifecycle
  status (start / complete / error), an ordering marker, and a stage-appropriate payload.
- **FR-027**: The per-stage event payload shapes MUST be documented as part of the event contract,
  covering at least: configuration resolved, split built, changepoint detection, full-history Prophet
  baseline fit, naive changepoint-window baseline workflow, diagnostics computed, visual inspection
  (if enabled), each decision iteration, each validation outcome, final evaluation, and run complete.
  Events MUST be emitted for the deterministic run steps (changepoint detection and the two baseline
  fits), not only the agent-graph stages.
- **FR-028**: Events MUST be emitted in causal order; stages that run concurrently MUST be
  identifiable as concurrent in the stream.
- **FR-029**: Event payloads emitted before final evaluation MUST NOT contain hidden-test target
  values, ground-truth boundaries, or audit-only labels — the POC's leakage controls extend to
  emitted events.
- **FR-030**: A default event sink MUST record every emitted event to the run directory so the event
  contract is exercisable and testable without a UI; the concrete network transport is out of scope
  for this feature.
- **FR-031**: The event contract MUST define how oversized payloads are handled (e.g., emitting a
  reference to an artifact rather than inlining large data) so the stream does not carry unbounded
  data.
- **FR-032**: A stage failure MUST emit a terminal error event for that stage with a human-readable
  reason rather than a malformed success event, and the run MUST then stop (fail-fast) without
  producing a partial or degraded agent forecast. In-loop control flow that is part of normal
  operation — a proposal rejected as out-of-bounds or for not beating the naive baseline, or the
  iteration budget being exhausted (after which the best-validation proposal is carried forward) — is
  NOT a stage failure and MUST NOT emit a terminal error event.

### Preserved POC guarantees (carried into core)

- **FR-033**: The promoted system MUST preserve the POC's data-leakage controls: the agent only ever
  sees training-period observations up to the forecast origin; it never sees test-period values,
  ground-truth boundaries, scenario notes, audit-only labels, or final test metrics during hypothesis
  generation; validation scores are computed only from historical training data; and hidden-test
  evaluation occurs only after the agent accepts an intervention or exhausts its iteration budget.
- **FR-034**: The promoted system MUST preserve the POC's baselines (full-history default forecast and
  the naive changepoint-window workflow) and the bounded-intervention, backtest-gated acceptance rule
  (strictly beat the naive baseline on validation to accept; otherwise carry the best-validation
  proposal; record which case applied).
- **FR-035**: The promoted system MUST preserve the POC's per-run artifact set (the training-only
  agent-context image when visual analysis is enabled, the human-only forecast comparison plot, the
  metrics artifact, and the structured agent trace) and MUST NOT pass any human-only artifact to an
  agent stage. The POC's cross-scenario batch summary is NOT carried over (a run is a single
  scenario).
- **FR-036**: The promoted system MUST preserve the POC's explicit-failure behavior for unavailable
  model identifiers (no silent substitution).

### Key Entities *(include if feature involves data)*

- **Effective Configuration**: The validated, fully-resolved settings for a run — model IDs,
  visual-analysis switch, per-diagnostic toggles, per-tool toggles, and the split specification —
  produced by merging a per-run override onto the `config.yaml` defaults, and recorded with the run.
- **Split Specification & Provenance**: The chosen train/validation/test partition, its source
  (golden metadata vs. override), its units (ratios vs. absolute rows), and the resolved absolute row
  counts actually used.
- **Diagnostics Bundle (with visibility)**: The deterministic, training-only diagnostic signals (the
  POC's bundle), each field always computed, each carrying an agent-visible / hidden status derived
  from configuration.
- **Tool Registry Entry**: A registered intervention's stable name, description, bounded parameter
  schema, enabled/disabled status, and serializable invocation contract.
- **Intervention Proposal**: The agent's single choice — a tool name plus bounded parameters and a
  rationale — carrying an action signature used to detect and reject repeats (the POC's proposal).
- **Stage Event**: A typed, serializable record of a stage lifecycle — run id, stage id, status,
  ordering marker, and a stage-appropriate payload — emitted through the emitter abstraction.
- **Run Artifacts**: The per-run (single-scenario) outputs — resolved effective configuration, split
  provenance, agent-context image (when visual enabled), forecast comparison plot, metrics, structured
  trace, and the recorded event stream.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running a single changepoint scenario through the core entrypoint with the golden
  configuration reproduces the POC's deterministic baseline and validation metrics identically for
  that committed fixture and recorded seed.
- **SC-002**: The core package contains zero changepoint-specific symbols (detector, diagnostics,
  interventions, prompts) and zero front-end/UI types, verifiable by inspection; the changepoint
  pipeline imports only the core and standard libraries, not any other pipeline.
- **SC-003**: `config.yaml`'s `diagnostics` section enumerates exactly the diagnostics-bundle fields
  and its `agent_tools` section enumerates exactly the registered tools — a mismatch in either
  direction is detectable by an automated check.
- **SC-004**: Disabling a diagnostic results in a run whose trace shows that diagnostic as hidden and
  whose agent decision input omits it, while the diagnostic is still computed (confirmable from the
  recorded bundle).
- **SC-005**: Disabling a tool results in a run whose advertised menu and gate allowed-set both
  exclude it, whose trace records it as removed, and in which it is never the accepted intervention.
- **SC-006**: With `visual_analysis_enabled` false, no agent-context image is produced or sent to any
  model, the decision uses the diagnostics-only prompt, and the run still produces a valid agent
  forecast and the full metrics set; with it true, the visual result is recorded before the decision.
- **SC-007**: A per-run override of a subset of fields produces a run whose recorded effective
  configuration equals the file defaults with exactly that subset changed, and re-running with that
  recorded effective configuration reproduces identical deterministic metrics.
- **SC-008**: An invalid configuration (unknown diagnostic/tool, malformed value, ambiguous or
  out-of-range split, missing model id) causes an explicit, actionable failure with a message naming
  the offending field — never a silent default.
- **SC-009**: The golden split reproduces exactly when no override is supplied; a ratio override and
  an equivalent absolute-rows override on the same series produce the same resolved row counts.
- **SC-010**: Every run emits one well-formed event per step lifecycle — covering the deterministic
  steps (changepoint detection, both baseline fits) as well as the agent stages — in causal order
  through the emitter, recorded by the default sink, each conforming to its documented payload shape;
  no pre-final-evaluation event payload contains hidden-test values, boundaries, or audit-only fields.
- **SC-011**: An intervention tool's in-process implementation can be replaced by a contract-equivalent
  stub with no change to the agent loop, the gate, the prompts, or the trace/event format —
  demonstrating lift-and-shift readiness.
- **SC-012**: A completed run directory lets a reader determine, without re-running, the effective
  configuration, the split provenance, which diagnostics were hidden, which tools were removed,
  whether visual analysis was on, and the model IDs used.

## Assumptions

- This feature promotes throwaway POC code (`pocs/changepoint/`) into the review-gated core and a
  thin pipeline; per the constitution, the promoted code is now held to the full test-first and
  quality gates (the POC exemption no longer applies once code leaves the POC area). The original POC
  remains as-is for provenance.
- The changepoint use-case is the reference pipeline for this promotion. The drift and anomaly tracks
  plug their own detector, diagnostics, tools, and prompts into the same core later; this feature does
  not implement them, but the core boundary is designed so they can.
- "Same result as the POC" is asserted on the deterministic components (baselines, diagnostics,
  validation scoring, metrics) for the committed fixtures and seed. The LLM-driven stages remain
  non-deterministic and are governed by golden-set evaluation, not exact-output assertions.
- The intended default models are the POC's: the stronger vision-capable model for the visual node
  and the faster reasoning model for the decision node, via the configured provider, all overridable
  through `config.yaml` and the per-run override.
- The concrete UI transport (SSE / WebSocket / queue / network protocol) is a separate, later feature
  owned alongside the UI work; this feature delivers only the event interface, the documented
  per-stage payload shapes, and a default file sink. The attached UI screenshot is reference context
  for what the events ultimately feed, not a deliverable here.
- The deterministic ratio-to-row rounding rule and the canonical ordering of `diagnostics` /
  `agent_tools` keys are implementation details to be fixed in planning, constrained here only to be
  deterministic and documented.
- The primary selection/comparison metric remains MAE on the relevant horizon unless configuration
  specifies otherwise, consistent with the POC.
- The feature assumes single-run-at-a-time execution (the UI triggers one run at a time); it makes no
  concurrency or in-process isolation guarantees, and the POC's process-global seeding/logging
  patterns are acceptable. Each run still resolves its own effective configuration and writes to its
  own per-run artifact directory, and the shared `config.yaml` provides defaults only and is not
  mutated by a run; parallel execution is a later concern for the UI/transport feature.
- Observability tracing (e.g., LangSmith) remains environment-driven and optional; its absence does
  not block a run.

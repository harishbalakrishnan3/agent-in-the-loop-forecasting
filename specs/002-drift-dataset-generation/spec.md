# Feature Specification: Drift Dataset Generation & Procurement

**Feature Branch**: `002-drift-dataset-generation`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Drift Dataset Generation & Procurement — the drift team's data layer: a seeded, parameterized synthetic generator producing univariate series with injected, ground-truth-labeled gradual drift (four flavors), plus ~2 curated real univariate series for demo only, with a standard visual-confirmation overlay."

## Overview

The agent-in-the-loop system is graded on **diagnostic correctness** — precision, recall,
and false-positive rate — for detecting drift. Those metrics are only measurable when each
test case carries a **known, injected drift onset**, which no real-world series provides.
This feature delivers the drift track's *data layer*: the foundation every downstream drift
deliverable (the detection tool's unit tests, the agent evals, the LLM judge) depends on.

The **primary** deliverable is a seeded, parameterized synthetic generator that produces
univariate series with machine-readable ground-truth drift labels, across four drift flavors
that each map to a distinct Prophet decomposition component (`y = g(t) + s(t) + h(t) + ε`).
The **secondary** deliverable is a small set of curated real univariate series, loadable
through the same interface, used only for qualitative demonstration and forecast-degradation
reproduction.

This feature is **dataset generation and procurement only**. It is explicitly NOT the drift
detection tool, the agent, the forecasting models, or backtesting.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a single-flavor labeled drift case (Priority: P1)

A drift-team developer writing unit tests for the (future) drift-detection tool needs a
univariate series that provably contains exactly one kind of gradual drift, starting at a
known location, so the test can assert "the tool found the drift the generator injected."

**Why this priority**: This is the foundational capability. Without seeded single-flavor
cases carrying ground-truth labels, no precision/recall measurement of any downstream drift
diagnostic is possible — the whole drift track's evaluation rests on it.

**Independent Test**: Request a case for a chosen flavor with a fixed seed; confirm the
returned object contains a univariate series plus ground-truth labels (flavor, onset, transition
width, affected component), and that regenerating with the same seed and parameters yields an
identical series and identical labels.

**Acceptance Scenarios**:

1. **Given** a chosen drift flavor, a seed, and default knobs, **When** a case is generated,
   **Then** the result contains one univariate time series and a ground-truth label record
   naming the injected flavor, the onset location, the transition width, and the affected
   Prophet component.
2. **Given** the same flavor, seed, and knobs, **When** generation is repeated, **Then** the
   produced series values and labels are identical (reproducibility).
3. **Given** two different seeds with otherwise identical knobs, **When** cases are generated,
   **Then** the series differ in their noise realization but both carry the same flavor and
   onset semantics.
4. **Given** a request for each of the four flavors (trend-slope drift, mean-level ramp,
   variance inflation, seasonal-amplitude drift), **When** each case is generated, **Then**
   each is produced successfully and its label records the correct affected component.

---

### User Story 2 - Produce the reproducible eval corpus (Priority: P1)

A developer preparing the drift agent evals needs a single command that materializes the
canonical, versioned corpus of labeled cases to disk, so that tool tests, agent evals, and
the LLM judge all consume the *same* reproducible dataset and can report precision/recall over
a meaningful number of cases.

**Why this priority**: Diagnostic-correctness metrics are only meaningful and comparable across
runs and contributors if everyone evaluates against one fixed, regenerable corpus. This is the
artifact the constitution's "results must be recoverable from the repository" rule attaches to.

**Independent Test**: Run the corpus-generation step; confirm it writes the agreed number of
single-flavor and combined-flavor cases (each with its series and label sidecar) under a
versioned location, and that deleting and re-running reproduces an identical corpus.

**Acceptance Scenarios**:

1. **Given** the corpus generation step, **When** it is run, **Then** it produces the core set
   of single-flavor cases (≈25 per flavor across the four flavors) plus a smaller set
   (≈10) of combined-flavor stretch cases, each persisted with its series and a
   machine-readable ground-truth label record.
2. **Given** an already-generated corpus, **When** generation is re-run with the same
   configuration, **Then** the regenerated corpus is identical (same cases, series, labels).
3. **Given** the generated corpus, **When** a consumer enumerates it, **Then** every case is
   discoverable together with its labels without bespoke per-case parsing.
4. **Given** the corpus configuration (seed and knob sweep), **When** it is inspected, **Then**
   it is committed/recorded such that the exact corpus can be reproduced from the repository.

---

### User Story 3 - Generate ambiguous (mid-transition-width) cases on demand (Priority: P2)

A developer stress-testing the drift detector — and the eventual agent's drift-vs-changepoint
judgment — needs to generate deliberately ambiguous cases where the transition width sits
between "clearly gradual drift" and "abrupt changepoint," to verify graceful handling of the
boundary.

**Why this priority**: The drift/changepoint boundary is a spectrum, not a binary; the agent
is evaluated partly on handling ambiguity. The generator must make this controllable, but it is
a stretch beyond the clean single-flavor cases needed for the core metric.

**Independent Test**: Request a case with a transition width in the ambiguous band; confirm the
case is produced, its label records the (wide-ish) transition width, and the series visibly
transitions over an extended interval rather than at a single index.

**Acceptance Scenarios**:

1. **Given** a transition-width value in the ambiguous middle band, **When** a case is
   generated, **Then** the case is produced and its label records that transition width.
2. **Given** a very small transition width versus a large one with otherwise identical knobs,
   **When** both are generated, **Then** the small-width case concentrates its change in a
   narrow window and the large-width case spreads it across many points.

---

### User Story 4 - Load a real demo series through the same interface (Priority: P2)

Someone preparing the demo / "reproduce the issue" step needs to load a real univariate series
that genuinely exhibits gradual drift, through the same access pattern used for synthetic cases,
so demo code does not branch on synthetic-vs-real.

**Why this priority**: Real series anchor the demo in recognizable data and support the
forecast-degradation reproduction step, but they cannot contribute to precision/recall (no
labeled onset), so they rank below the labeled-corpus work.

**Independent Test**: Load each curated real series; confirm it returns a univariate series via
the same interface as synthetic cases, and that it is clearly marked as having no ground-truth
drift-onset label (i.e., excluded from precision/recall).

**Acceptance Scenarios**:

1. **Given** a curated real drift series (e.g. the growing-seasonal-amplitude air-passengers
   series, or a slow-rising-level-with-seasonality CO₂ series), **When** it is loaded, **Then**
   it returns a univariate time series through the same interface shape as synthetic cases.
2. **Given** a real series, **When** its labels are inspected, **Then** it is explicitly marked
   as having no ground-truth drift onset and therefore excluded from precision/recall evals.
3. **Given** the set of curated real series, **When** enumerated, **Then** approximately two
   series are available, each documented as to which drift behavior it qualitatively exhibits.

---

### User Story 5 - Visually confirm a case actually contains drift (Priority: P3)

A reviewer accepting a generated or curated dataset needs a standard visual overlay — the
series plus its rolling mean and rolling standard deviation, with the injected onset marked —
to eyeball-confirm the case genuinely contains drift (reproducing Figure 3 of the proposal).

**Why this priority**: This is the human acceptance aid ("is this dataset good?"). It is
valuable for trust and review but is not itself consumed by the automated metrics, so it is the
lowest priority of the set.

**Independent Test**: Produce the overlay for a synthetic case and confirm it shows the series,
a rolling mean, a rolling spread band, and a marker at the injected onset; produce it for a real
series and confirm the same overlay renders without an onset marker.

**Acceptance Scenarios**:

1. **Given** a synthetic case, **When** the visual confirmation is produced, **Then** it shows
   the observations, a rolling mean, a rolling standard-deviation indication, and a marker at
   the injected drift onset.
2. **Given** a real demo series (no onset label), **When** the visual confirmation is produced,
   **Then** it renders the same series + rolling-mean + rolling-spread overlay without an onset
   marker.

---

### Edge Cases

- **Onset near series boundaries**: What happens when the requested drift onset leaves too few
  points before it (no stable reference regime) or too few after it (drift cannot develop)? The
  generator MUST reject or clearly constrain such requests rather than emit a mislabeled case.
- **Transition width exceeding remaining length**: What happens when transition width + onset
  runs past the end of the series? The generator MUST **reject** such a request with a clear
  validation error rather than silently clamping — a clamp would make the label's realized width
  disagree with the requested `transition_width`, exactly the label/config contradiction FR-009
  exists to prevent.
- **Zero / negative magnitude**: A drift magnitude of zero would yield a series with no actual
  drift but a label claiming drift. The generator MUST prevent a label that contradicts the
  produced series.
- **Variance-inflation with a non-positive base noise level**: Growth of noise spread is
  undefined without a positive base; the generator MUST require a valid base noise level for
  that flavor.
- **Seasonal-amplitude drift with no seasonality configured**: This flavor is meaningless
  without a seasonal component; the generator MUST require seasonality to be present for it.
- **Combined-flavor conflicts**: When multiple flavors are injected into one case, overlapping
  onsets/components MUST still produce a coherent, fully-labeled case (each injected flavor
  represented in the labels).
- **Real series with missing timestamps / gaps**: Curated real series MUST be presented in a
  consistent, regular form (or their irregularities documented) so downstream consumers are not
  surprised.

## Requirements *(mandatory)*

### Functional Requirements

**Synthetic generation — core**

- **FR-001**: The system MUST generate univariate time series with deterministically injected
  gradual drift.
- **FR-002**: The system MUST support four distinct drift flavors, each tied to a Prophet
  decomposition component: (a) **trend-slope drift** — gradual change in trend slope (`g(t)`);
  (b) **mean-level ramp** — gradual shift in level (`g(t)`); (c) **variance inflation** —
  gradual growth in noise spread (`ε`); (d) **seasonal-amplitude drift** — seasonal swings grow
  or shrink over time, i.e. additive→multiplicative (`s(t)`).
- **FR-003**: The system MUST expose the following knobs, each with a reasonable default:
  drift **onset** (start location), drift **magnitude**, **transition width** (Δt), drift
  **duration**, **base noise level**, **seasonality** (period and base amplitude), and a
  **random seed**.
- **FR-004**: Generation MUST be fully reproducible: identical seed + knobs MUST yield an
  identical series and identical labels.
- **FR-005**: Each generated case MUST carry a machine-readable ground-truth label record
  containing at minimum: the **drift flavor**, the **onset** location, the **transition width**,
  and the **affected component** — sufficient to compute detection precision/recall.
- **FR-006**: The system MUST support generating a case with **exactly one** injected flavor
  (clean ground truth for metrics).
- **FR-007**: The system MUST support generating **combined-flavor** cases (more than one
  injected flavor in a single series) as harder stretch cases, with every injected flavor
  represented in the labels.
- **FR-008**: The transition width (Δt) MUST be an explicit, controllable parameter spanning
  from narrow (changepoint-like) to wide (clearly gradual), so deliberately **ambiguous
  middle-ground** cases can be generated on demand.
- **FR-009**: The system MUST validate knob combinations and refuse to emit a case whose labels
  would contradict the produced series (see Edge Cases), failing clearly rather than silently
  mislabeling.

**Eval corpus**

- **FR-010**: The system MUST provide a step that materializes a canonical eval corpus to disk:
  approximately **25 single-flavor cases per flavor** (≈100 total across the four flavors) plus
  approximately **10 combined-flavor** stretch cases, each persisted with its series and its
  ground-truth label record.
- **FR-011**: The on-disk corpus MUST be regenerable to an identical state from a committed
  seed/knob configuration (reproducibility of the whole corpus, not just individual cases).
- **FR-012**: The corpus MUST be enumerable by consumers such that each case's series and its
  labels are retrievable together without bespoke per-case handling.
- **FR-013**: The generator MUST also be usable to return cases as **in-memory typed objects**
  (series + labels) without requiring disk persistence, for direct use in unit tests.

**Real datasets**

- **FR-014**: The system MUST provide approximately **two** curated real univariate series that
  genuinely exhibit gradual drift, loadable through the **same interface shape** as synthetic
  cases.
- **FR-015**: Real series MUST be explicitly marked as having **no ground-truth drift onset**,
  and therefore excluded from precision/recall evaluation; they exist for qualitative demo and
  forecast-degradation reproduction only.
- **FR-016**: Each curated real series MUST be documented as to which drift behavior it
  qualitatively exhibits (e.g. growing seasonal amplitude; slow rising level with seasonality).

**Visualization**

- **FR-017**: The system MUST be able to produce a standard visual-confirmation overlay for any
  case — the series, a rolling mean, and a rolling standard-deviation indication — reproducing
  the proposal's drift illustration.
- **FR-018**: For synthetic cases, the overlay MUST mark the injected drift onset; for real
  series (no onset label), the overlay MUST render without an onset marker.

### Key Entities

- **Drift Case**: A single generated or curated unit of data. Holds one univariate time series
  plus its ground-truth label record (which may be empty/marked-unlabeled for real series).
- **Ground-Truth Label Record**: The machine-readable description of what was injected — drift
  flavor(s), onset location(s), transition width(s), affected Prophet component(s) — that
  downstream detection metrics are scored against.
- **Drift Flavor**: One of the four supported injected drift types, each bound to a Prophet
  component (trend-slope `g(t)`, mean-level `g(t)`, variance `ε`, seasonal-amplitude `s(t)`).
- **Generator Configuration / Knobs**: The reproducible parameter set (onset, magnitude,
  transition width, duration, base noise, seasonality, seed) that determines a case.
- **Eval Corpus**: The named, versioned, on-disk collection of cases (single-flavor +
  combined-flavor) consumed by tool tests, agent evals, and the LLM judge.
- **Real Demo Series**: A curated real univariate series exhibiting gradual drift, with no
  onset label, loadable through the same interface as synthetic cases.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All four drift flavors can be generated, each fully parameterized by the required
  knobs and reproducible from seed + knobs (identical output on repeat).
- **SC-002**: 100% of synthetic cases carry a machine-readable ground-truth label record
  sufficient to compute detection precision, recall, and false-positive rate.
- **SC-003**: The canonical eval corpus contains the agreed composition — roughly 25
  single-flavor cases per flavor (≈100 total) plus ≈10 combined-flavor cases — and can be
  regenerated to an identical state from committed configuration.
- **SC-004**: Ambiguous (mid-transition-width) cases can be generated on demand, and a small
  transition width versus a large one demonstrably differ in how concentrated the change is.
- **SC-005**: Approximately two real demo series load through the same interface as synthetic
  cases and are clearly flagged as unlabeled (excluded from precision/recall).
- **SC-006**: For any case, the standard visual overlay (series + rolling mean + rolling spread,
  with onset marked for synthetic cases) can be produced and visually confirms drift presence.
- **SC-007**: A reviewer can reproduce any reported corpus or case from the repository alone,
  using the committed seed and configuration, with no external state.

## Assumptions

- **Univariate, gradual only**: All series are single-variable; only *gradual* drift is in
  scope. Abrupt/localized breaks (changepoints) and isolated outliers are explicitly other
  teams' domains and out of scope here.
- **Drift framing**: "Drift" follows the proposal's univariate, forecasting-flavored definition
  (a gradual shift in the target's level/slope/spread/seasonal-amplitude with no single obvious
  break date), not the streaming-ML `P(y|X)` concept-drift sense.
- **Corpus composition default**: Absent a stricter mandate, the eval corpus targets ≈25
  single-flavor cases per flavor plus ≈10 combined-flavor cases; exact counts may be tuned as
  long as they remain sufficient for meaningful precision/recall and stay reproducible.
- **Delivery model**: Cases are available both as in-memory typed objects (for unit tests) and
  as a materialized on-disk corpus (for shared, reproducible evals).
- **Δt threshold deferred**: The transition width is exposed as an explicit knob with sensible
  defaults per regime (narrow / gradual / ambiguous), but the exact numeric threshold that
  *demarcates* drift from a changepoint is NOT fixed in this feature — it is a cross-team
  agreement to be ratified separately (see Dependencies).
- **Real series candidates**: The growing-seasonal-amplitude air-passengers series and a
  slow-rising-level CO₂ series are the leading candidates for the ≈2 real demo series; the final
  pick may change as long as each genuinely exhibits gradual drift.
- **Tooling context**: Synthetic generation builds on the project's time-series tooling (Darts)
  and lives in the drift pipeline directory; generic, reusable plumbing belongs in the shared
  core datasets module, consistent with the shared-core/independent-pipelines structure.
- **No detection here**: This feature does not implement or assume any particular drift
  *detection* method; it only guarantees the data and its ground truth.

## Dependencies

- **Cross-team Δt convention**: The drift and changepoint teams MUST agree on the
  transition-width convention (where gradual drift ends and an abrupt changepoint begins) so
  generated cases do not ambiguously overlap and the agent has a consistent labeling rule. This
  feature makes Δt explicit so the boundary is controllable, but the ratified threshold value is
  an external decision this feature depends on, not one it sets.
- **Shared interface shape**: The same case/loader interface is intended to serve synthetic and
  real series and to feed the downstream drift-detection tool tests and agent evals; its shape
  should be coordinated with the shared core datasets module.

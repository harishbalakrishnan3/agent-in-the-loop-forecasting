# Feature Specification: Changepoint Dataset Generation & Procurement

**Feature Branch**: `003-changepoint-dataset-generation`

**Created**: 2026-06-15

**Status**: Draft

**Input**: User description: "Changepoint dataset generation — seeded, parameterized synthetic generator producing univariate series with injected, ground-truth-labeled abrupt changepoints (four flavors: level shift, slope change, variance jump, seasonality shift), plus ~2 curated real univariate series for demo only, with a standard visual-confirmation overlay. Mirrors the structure of the drift dataset feature (002) for the changepoint track."

## Overview

The agent-in-the-loop system is graded on **diagnostic correctness** — precision, recall,
and false-positive rate — for detecting changepoints. Those metrics are only measurable when
each test case carries a **known, injected changepoint location**, which no real-world series
provides reliably. This feature delivers the changepoint track's *data layer*: the foundation
every downstream changepoint deliverable (the detection tool's unit tests, the agent evals,
the LLM judge) depends on.

The **primary** deliverable is a seeded, parameterized synthetic generator that produces
univariate series with machine-readable ground-truth changepoint labels, across four changepoint
flavors that each map to a distinct Prophet decomposition component (`y = g(t) + s(t) + h(t) + ε`).
The **secondary** deliverable is a small set of curated real univariate series, loadable through
the same interface, used only for qualitative demonstration and forecast-degradation reproduction.

A changepoint is an **abrupt structural break** — unlike gradual drift, the break is localized
to a narrow window (ideally a single index). This is the defining contrast with the drift track's
ramp-based transition.

This feature is **dataset generation and procurement only**. It is explicitly NOT the changepoint
detection tool, the agent, the forecasting models, or backtesting.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a single-flavor labeled changepoint case (Priority: P1)

A changepoint-team developer writing unit tests for the (future) changepoint-detection tool needs
a univariate series that provably contains exactly one abrupt structural break of a known flavor,
at a known location, so the test can assert "the tool found the changepoint the generator injected."

**Why this priority**: This is the foundational capability. Without seeded single-flavor cases
carrying ground-truth labels, no precision/recall measurement of any downstream changepoint
diagnostic is possible — the whole changepoint track's evaluation rests on it.

**Independent Test**: Request a case for a chosen flavor with a fixed seed; confirm the returned
object contains a univariate series plus ground-truth labels (flavor, break index, break time,
affected component, magnitude), and that regenerating with the same seed and parameters yields
an identical series and identical labels.

**Acceptance Scenarios**:

1. **Given** a chosen changepoint flavor, a seed, and default knobs, **When** a case is generated,
   **Then** the result contains one univariate time series and a ground-truth label record naming
   the injected flavor, the break index, the break timestamp, the affected Prophet component, and
   the magnitude.
2. **Given** the same flavor, seed, and knobs, **When** generation is repeated, **Then** the
   produced series values and labels are identical (reproducibility).
3. **Given** two different seeds with otherwise identical knobs, **When** cases are generated,
   **Then** the series differ in their noise realization but both carry the same flavor and break
   semantics.
4. **Given** a request for each of the four flavors (level shift, slope change, variance jump,
   seasonality shift), **When** each case is generated, **Then** each is produced successfully
   and its label records the correct affected Prophet component.

---

### User Story 2 - Produce the reproducible eval corpus (Priority: P1)

A developer preparing the changepoint agent evals needs a single command that materializes the
canonical, versioned corpus of labeled cases to disk, so that tool tests, agent evals, and the
LLM judge all consume the *same* reproducible dataset and can report precision/recall over a
meaningful number of cases.

**Why this priority**: Diagnostic-correctness metrics are only meaningful and comparable across
runs and contributors if everyone evaluates against one fixed, regenerable corpus. This is the
artifact the constitution's "results must be recoverable from the repository" rule attaches to.

**Independent Test**: Run the corpus-generation step; confirm it writes the agreed number of
single-flavor and combined-flavor cases (each with its series and label sidecar) under a
versioned location, and that deleting and re-running reproduces an identical corpus.

**Acceptance Scenarios**:

1. **Given** the corpus generation step, **When** it is run, **Then** it produces the core set
   of single-flavor cases (≈25 per flavor across the four flavors) plus a smaller set (≈10) of
   combined-flavor stretch cases, each persisted with its series and a machine-readable
   ground-truth label record.
2. **Given** an already-generated corpus, **When** generation is re-run with the same
   configuration, **Then** the regenerated corpus is identical (same cases, series, labels).
3. **Given** the generated corpus, **When** a consumer enumerates it, **Then** every case is
   discoverable together with its labels without bespoke per-case parsing.
4. **Given** the corpus configuration (seed and knob sweep), **When** it is inspected, **Then**
   it is committed/recorded such that the exact corpus can be reproduced from the repository.

---

### User Story 3 - Generate multiple changepoints in one series (Priority: P2)

A developer stress-testing the changepoint detector needs to generate series with more than one
injected break — either multiple breaks of the same flavor or mixed flavors — to verify the
detector handles multi-break series and the agent can reason about them.

**Why this priority**: Real-world series often contain more than one structural break. Testing
multi-break detection is important but is a stretch beyond the clean single-break cases needed
for the core metric.

**Independent Test**: Request a case with two or more injected breaks; confirm every break is
represented in the label list, and that each label records its own break index and flavor.

**Acceptance Scenarios**:

1. **Given** a list of two or more (flavor, break_index) pairs, **When** a case is generated,
   **Then** the case is produced and its labels list contains one entry per injected break.
2. **Given** two breaks of different flavors at non-overlapping locations, **When** a case is
   generated, **Then** each break is visually distinguishable in the series and its label is
   correct.

---

### User Story 4 - Load a real demo series through the same interface (Priority: P2)

Someone preparing the demo / "reproduce the issue" step needs to load a real univariate series
that genuinely exhibits an abrupt structural break, through the same access pattern used for
synthetic cases, so demo code does not branch on synthetic-vs-real.

**Why this priority**: Real series anchor the demo in recognizable data and support the
forecast-degradation reproduction step, but they cannot contribute to precision/recall (no
labeled break location), so they rank below the labeled-corpus work.

**Independent Test**: Load each curated real series; confirm it returns a univariate series via
the same interface as synthetic cases, and that it is clearly marked as having no ground-truth
changepoint label (i.e., excluded from precision/recall).

**Acceptance Scenarios**:

1. **Given** a curated real changepoint series (e.g. the Nile river annual flow with its ~1898
   break, or UK coal mining disasters), **When** it is loaded, **Then** it returns a univariate
   time series through the same interface shape as synthetic cases.
2. **Given** a real series, **When** its labels are inspected, **Then** it is explicitly marked
   as having no ground-truth changepoint location and therefore excluded from precision/recall evals.
3. **Given** the set of curated real series, **When** enumerated, **Then** approximately two
   series are available, each documented as to which changepoint behavior it qualitatively exhibits.

---

### User Story 5 - Visually confirm a case contains a changepoint (Priority: P3)

A reviewer accepting a generated or curated dataset needs a standard visual overlay — the series
plus its rolling mean and rolling standard deviation, with the injected break location marked —
to eyeball-confirm the case genuinely contains an abrupt structural break.

**Why this priority**: This is the human acceptance aid ("is this dataset good?"). It is valuable
for trust and review but is not itself consumed by the automated metrics, so it is the lowest
priority of the set.

**Independent Test**: Produce the overlay for a synthetic case and confirm it shows the series,
a rolling mean, a rolling spread band, and a vertical marker at the injected break; produce it
for a real series and confirm the same overlay renders without a break marker.

**Acceptance Scenarios**:

1. **Given** a synthetic case, **When** the visual confirmation is produced, **Then** it shows
   the observations, a rolling mean, a rolling standard-deviation indication, and a vertical
   marker at the injected changepoint location.
2. **Given** a real demo series (no break label), **When** the visual confirmation is produced,
   **Then** it renders the same overlay without a break marker.

---

### Edge Cases

- **Break too near series boundaries**: What happens when the requested break location leaves too
  few points before it (no stable pre-break regime) or too few after it (break effect cannot be
  observed)? The generator MUST reject or clearly constrain such requests rather than emit a
  mislabeled case.
- **Zero / negative magnitude**: A changepoint magnitude of zero would yield a series with no
  actual break but a label claiming one. The generator MUST prevent a label that contradicts the
  produced series.
- **Variance jump with non-positive base noise**: Growth in noise spread is undefined without a
  positive base; the generator MUST require a valid base noise level for that flavor.
- **Seasonality shift with no seasonality configured**: This flavor is meaningless without a
  seasonal component; the generator MUST require seasonality to be present.
- **Overlapping multi-break locations**: Two breaks injected at the same or adjacent indices may
  produce a coherent but ambiguous series; the generator MUST validate that break indices are
  sufficiently separated (at least `_MIN_REGIME` points apart).
- **Real series with missing timestamps / gaps**: Curated real series MUST be presented in a
  consistent, regular form (or their irregularities documented) so downstream consumers are not
  surprised.

## Requirements *(mandatory)*

### Functional Requirements

**Synthetic generation — core**

- **FR-001**: The system MUST generate univariate time series with deterministically injected
  abrupt changepoints.
- **FR-002**: The system MUST support four distinct changepoint flavors, each tied to a Prophet
  decomposition component: (a) **level shift** — abrupt jump in the series mean (`g(t)`);
  (b) **slope change** — abrupt change in trend slope (`g(t)`); (c) **variance jump** — sudden
  increase in noise spread (`ε`); (d) **seasonality shift** — sudden change in seasonal amplitude
  (`s(t)`).
- **FR-003**: The system MUST expose the following knobs, each with a reasonable default:
  changepoint **break index** (location), changepoint **magnitude**, **base noise level**,
  **seasonality** (period and base amplitude), series **length**, **start timestamp**, **frequency**,
  and a **random seed**.
- **FR-004**: Generation MUST be fully reproducible: identical seed + knobs MUST yield an
  identical series and identical labels.
- **FR-005**: Each generated case MUST carry a machine-readable ground-truth label record
  containing at minimum: the **changepoint flavor**, the **break index**, the **break timestamp**,
  the **affected Prophet component**, and the **magnitude** — sufficient to compute detection
  precision/recall.
- **FR-006**: The system MUST support generating a case with **exactly one** injected changepoint
  (clean ground truth for metrics).
- **FR-007**: The system MUST support generating **multi-break** cases (more than one injected
  changepoint in a single series) as harder stretch cases, with every injected break represented
  in the labels.
- **FR-008**: The generator MUST validate knob combinations and refuse to emit a case whose labels
  would contradict the produced series (see Edge Cases), failing clearly rather than silently
  mislabeling.
- **FR-009**: The break MUST be abrupt — the structural change happens at a single index, not
  across a ramp window. This is the defining contrast with the drift track's transition-width knob.

**Eval corpus**

- **FR-010**: The system MUST provide a step that materializes a canonical eval corpus to disk:
  approximately **25 single-flavor cases per flavor** (≈100 total across the four flavors) plus
  approximately **10 multi-break** stretch cases, each persisted with its series and its
  ground-truth label record.
- **FR-011**: The on-disk corpus MUST be regenerable to an identical state from a committed
  seed/knob configuration.
- **FR-012**: The corpus MUST be enumerable by consumers such that each case's series and its
  labels are retrievable together without bespoke per-case handling.
- **FR-013**: The generator MUST also be usable to return cases as **in-memory typed objects**
  (series + labels) without requiring disk persistence, for direct use in unit tests.

**Real datasets**

- **FR-014**: The system MUST provide approximately **two** curated real univariate series that
  genuinely exhibit abrupt structural breaks, loadable through the **same interface shape** as
  synthetic cases.
- **FR-015**: Real series MUST be explicitly marked as having **no ground-truth changepoint
  location**, and therefore excluded from precision/recall evaluation.
- **FR-016**: Each curated real series MUST be documented as to which changepoint behavior it
  qualitatively exhibits.

**Visualization**

- **FR-017**: The system MUST be able to produce a standard visual-confirmation overlay for any
  case — the series, a rolling mean, and a rolling standard-deviation band.
- **FR-018**: For synthetic cases, the overlay MUST mark the injected break location(s) with a
  vertical line; for real series (no break label), the overlay MUST render without break markers.

### Key Entities

- **Changepoint Case**: A single generated or curated unit of data. Holds one univariate time
  series plus its ground-truth label record (which may be empty/marked-unlabeled for real series).
- **Ground-Truth Label Record**: The machine-readable description of what was injected —
  changepoint flavor(s), break index/timestamp(s), affected Prophet component(s), magnitude(s) —
  that downstream detection metrics are scored against.
- **Changepoint Flavor**: One of the four supported injected break types, each bound to a Prophet
  component (level shift `g(t)`, slope change `g(t)`, variance jump `ε`, seasonality shift `s(t)`).
- **Generator Configuration / Knobs**: The reproducible parameter set (break_index, magnitude,
  base noise, seasonality, length, seed) that determines a case.
- **Eval Corpus**: The named, versioned, on-disk collection of cases consumed by tool tests,
  agent evals, and the LLM judge.
- **Real Demo Series**: A curated real univariate series exhibiting an abrupt break, with no
  break label, loadable through the same interface as synthetic cases.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All four changepoint flavors can be generated, each fully parameterized and
  reproducible from seed + knobs (identical output on repeat).
- **SC-002**: 100% of synthetic cases carry a machine-readable ground-truth label record
  sufficient to compute detection precision, recall, and false-positive rate.
- **SC-003**: The canonical eval corpus contains ≈25 single-flavor cases per flavor (≈100 total)
  plus ≈10 multi-break cases and can be regenerated to an identical state from committed
  configuration.
- **SC-004**: Multi-break cases can be generated on demand, with each break represented in the
  label list.
- **SC-005**: Approximately two real demo series load through the same interface as synthetic
  cases and are clearly flagged as unlabeled (excluded from precision/recall).
- **SC-006**: For any case, the standard visual overlay (series + rolling mean + rolling spread,
  with break marker(s) for synthetic cases) can be produced and visually confirms the changepoint.
- **SC-007**: A reviewer can reproduce any reported corpus or case from the repository alone,
  using the committed seed and configuration, with no external state.

## Assumptions

- **Univariate, abrupt only**: All series are single-variable; only *abrupt* structural breaks
  are in scope. Gradual drift is the drift track's domain; isolated outliers are the anomaly
  track's domain.
- **Abrupt framing**: "Changepoint" means a break localized to a single index — `transition_width`
  is effectively 1 (a step function), in contrast to the drift track's ramp.
- **Corpus composition default**: ≈25 single-flavor cases per flavor plus ≈10 multi-break cases;
  exact counts may be tuned as long as they remain sufficient for meaningful precision/recall and
  stay reproducible.
- **Delivery model**: Cases are available both as in-memory typed objects (for unit tests) and as
  a materialized on-disk corpus (for shared, reproducible evals).
- **Real series candidates**: The Nile river annual flow (`statsmodels.datasets.nile`) and UK coal
  mining disasters are the leading candidates; the final pick may change as long as each genuinely
  exhibits an abrupt structural break.
- **Shared infrastructure**: The `Case` container, `write_case`, `load_corpus`, and
  `write_manifest` from `ailf.core.datasets` are reused directly. The viz overlay may reuse or
  extend `ailf.core.datasets.viz`. Changepoint-specific logic (flavors, labels, generator) lives
  in `src/ailf/pipelines/changepoint/datasets.py`.
- **No detection here**: This feature does not implement or assume any particular changepoint
  *detection* method; it only guarantees the data and its ground truth.

## Dependencies

- **Shared interface shape**: Reuses `Case`, `write_case`, `load_corpus`, `write_manifest` from
  `ailf.core.datasets` — no changes to core required (Principle VII).
- **Cross-team Δt convention**: The drift and changepoint teams MUST agree on the transition-width
  threshold distinguishing gradual drift from an abrupt changepoint, so generated cases do not
  ambiguously overlap. This feature hard-codes `transition_width = 1` (step), which is the
  changepoint extreme of the spectrum.
- **Visualization**: The overlay may extend or parallel `plot_drift_overlay` from
  `ailf.core.datasets.viz`; if a generic `plot_overlay` helper is extracted to core, that touches
  shared core and requires Harish's review.

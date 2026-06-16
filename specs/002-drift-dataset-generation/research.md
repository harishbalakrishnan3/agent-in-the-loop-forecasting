# Phase 0 Research: Drift Dataset Generation & Procurement

The spec carried no `[NEEDS CLARIFICATION]` markers — three scope decisions (corpus size,
dual delivery, deferred Δt threshold) were resolved before drafting. This document records the
remaining *technical* decisions needed to design the generator, corpus, loaders, and overlay.

## R1. Base-series construction with Darts

- **Decision**: Compose each base series from `darts.utils.timeseries_generation` primitives —
  `linear_timeseries` (trend `g(t)`), `sine_timeseries` (seasonal `s(t)`), and
  `gaussian_timeseries` (noise `ε`) — summed into `y = g(t) + s(t) + ε`, then inject the chosen
  drift flavor by modulating the relevant component over the transition window. Verified
  available in Darts 0.44.1.
- **Rationale**: These map 1:1 onto the Prophet decomposition the four flavors target, keep
  generation transparent and unit-testable, and require no extra dependency.
- **Alternatives considered**: `random_walk_timeseries` as the base — rejected because a
  stochastic-trend base makes "the injected drift is *the* trend change" harder to assert
  against ground truth. Hand-rolling numpy arrays — rejected; Darts `TimeSeries` is the project's
  house type and gives us a `DatetimeIndex` for free.

## R2. Seeding & reproducibility

- **Decision**: Each case takes an explicit integer `seed` (**default `42`**); the generator
  constructs a `numpy.random.Generator` (`np.random.default_rng(seed)`) used for *all* stochastic
  steps (noise, and any randomized knob draws in corpus sweeps). No reliance on global RNG state.
  Corpus cases derive per-case seeds deterministically from a single base seed + case index.
- **Rationale**: Satisfies Principle V and FR-004 — identical seed + knobs ⇒ identical series
  and labels. `default_rng` is the modern, isolated, reproducible numpy RNG.
- **Alternatives considered**: Global `np.random.seed()` — rejected; not isolated, leaks across
  cases and other code. Python `random` — rejected; numpy is already the numeric substrate.

## R3. Transition-shape model (the Δt knob)

- **Decision**: Model the drift as a smooth ramp from the reference regime to the drifted regime
  over a transition window of width `transition_width` (Δt, in number of steps) starting at
  `onset`. Use a clamped linear (or smoothstep) ramp: 0 before onset, rising to full `magnitude`
  across Δt, held for the remaining `duration`. Δt is the single shared knob distinguishing
  gradual drift (large Δt) from changepoint-like (Δt→1).
- **Rationale**: Directly realizes FR-008 and the spec's ambiguity story; a single width
  parameter makes "narrow vs gradual" measurable and lets us generate the ambiguous middle band.
- **Alternatives considered**: Sigmoid/`tanh` transition — viable and slightly smoother;
  recorded as an acceptable variant but linear/smoothstep keeps the onset and end of transition
  unambiguous for labeling. Instantaneous step — that is the changepoint team's domain, out of
  scope.
- **Deferred**: The exact numeric Δt threshold demarcating "drift" vs "changepoint" is a
  cross-team agreement (spec Dependencies); we expose named default bands (e.g.
  narrow / gradual / ambiguous) without hard-committing the boundary value.

## R4. Per-flavor injection semantics

- **Decision**:
  - **Trend-slope drift** (`g(t)`): add an extra linear term whose slope ramps in over Δt — the
    series bends to a steeper/shallower trajectory.
  - **Mean-level ramp** (`g(t)`): add a level offset that ramps from 0 to `magnitude` over Δt —
    the series shifts to a new range.
  - **Variance inflation** (`ε`): scale the noise std by a factor ramping from 1 to
    `1+magnitude` over Δt — spread grows. Requires `base_noise > 0`.
  - **Seasonal-amplitude drift** (`s(t)`): multiply the seasonal component by an amplitude factor
    ramping over Δt (additive→multiplicative behavior). Requires seasonality configured.
- **Rationale**: One distinct, Prophet-aligned mechanism per flavor (FR-002), each giving the
  downstream agent a distinct intervention; affected component is unambiguous for the label.
- **Alternatives considered**: Folding mean-ramp and trend-slope into one "trend drift" knob —
  rejected; the spec and proposal want them distinct because they map to different interventions.

## R5. Label schema sufficiency for precision/recall

- **Decision**: `DriftLabel` records per injected drift: `flavor`, `onset` (index + timestamp),
  `transition_width`, `affected_component`, and `magnitude`. A case holds a list of labels
  (length 1 for single-flavor, >1 for combined). Real series carry an empty label list plus an
  explicit `labeled = False` / `is_synthetic = False` flag.
- **Rationale**: FR-005/FR-007/FR-015. Onset + width define the ground-truth interval a detector
  is scored against (a detection within the labeled window = true positive); flavor/component
  enable per-flavor breakdowns; the unlabeled flag keeps real series out of precision/recall.
- **Alternatives considered**: Single onset index only — insufficient, can't score a gradual
  detection fairly without the width/interval. Per-point boolean mask — heavier than needed; the
  (onset, width) interval is reconstructable and lighter to serialize.

## R6. Corpus persistence format

- **Decision**: Materialize each case as two files under `data/synthetic/drift/<case_id>/`:
  the series as CSV (timestamp,value) and the label record as `labels.json`. A top-level
  `corpus.json` (or manifest) lists all case ids + their config for enumeration, and the
  generating seed/knob-sweep config is committed under the feature/source (not the bulk dir).
- **Rationale**: FR-010/FR-011/FR-012. CSV + JSON are plain, diffable, language-agnostic, and
  trivially serializable (Principle I). Manifest gives O(1) enumeration without per-case parsing.
  `data/synthetic/*` is gitignored, so bulk output never bloats the repo; reproducibility rests
  on the committed config (Principle V).
- **Alternatives considered**: Pickle — rejected; not plain/serializable-friendly, version-brittle.
  Single combined parquet — heavier dependency surface and less human-diffable for review.

## R7. Real demo series selection & loading

- **Decision**: Ship two loaders: **Air Passengers** via `darts.datasets.AirPassengersDataset`
  (growing seasonal amplitude — the multiplicative-seasonal-drift twin) and **Mauna Loa CO₂** via
  `statsmodels.datasets.co2` (slow rising level + seasonality). Both return the same `Case`
  container as synthetic, with `labeled=False`. CO₂ has weekly gaps/missing values → resample to
  a regular monthly frequency and document it (Edge Case: real series gaps).
- **Rationale**: FR-014/FR-015/FR-016; both are recognizable, genuinely drifting, and already
  installed (Darts + statsmodels in `uv.lock`). Same-interface loading satisfies the
  "demo code doesn't branch on synthetic-vs-real" goal.
- **Alternatives considered**: ELEC2 — noted in research but rejected as lead (framed for
  streaming classification, awkward univariate-forecasting fit). M3/M4 series — large pools, no
  single canonical "drift" series, heavier to curate for a 2-series demo.

## R8. Visual-confirmation overlay

- **Decision**: A **plotly** function plotting observations + rolling mean + rolling-std band,
  with a vertical marker at the injected onset when the case is labeled (omitted for real
  series). Returns the plotly `Figure` (no forced display) and offers a helper that writes paired
  artifacts for manual inspection: an **interactive `.html`** (native `fig.write_html`) and a
  **static `.png`** (`fig.write_image`, requires `kaleido`), under `reports/` (gitignored). Lives
  in `core/datasets/viz.py` (domain-agnostic).
- **Rationale**: FR-017/FR-018, reproduces proposal Figure 3, and is the human eyeball gate. The
  user wants plotly with both PNG (quick glance / paste into docs) and HTML (zoom/hover for real
  inspection). Returning the figure keeps it testable headlessly (assert on traces/shapes without
  rendering).
- **Dependency impact**: adds `plotly` (HTML export native) and `kaleido` (PNG/static export) —
  neither is currently in `uv.lock`; both added via `uv add` during implementation.
- **Alternatives considered**: matplotlib — rejected per user preference for plotly's interactive
  HTML. HTML-only (drop kaleido) — rejected; user explicitly wants PNG too.

## R9. Test strategy (Principle II)

- **Decision**: Test-first in `tests/pipelines/drift/` (flavor correctness, label correctness,
  reproducibility, knob-validation rejections, combined-flavor labeling, loader shape/flag) and
  `tests/core/datasets/` (case round-trip serialization, corpus write/read/enumerate identity,
  overlay structure). Drift assertions inject known ground truth and check the realized series
  actually exhibits the change (e.g. rolling-mean step for mean-ramp, rolling-std growth for
  variance inflation) — i.e. tests verify the data, not a detector.
- **Rationale**: NON-NEGOTIABLE Principle II; these are deterministic components. Verifying the
  *generated data matches its own labels* is the foundation everything downstream trusts.
- **Alternatives considered**: Deferring tests until the detection tool exists — rejected;
  violates test-first and would let a mislabeled generator silently corrupt all drift evals.
